// Tests for the DOM analysis in extension/content.js — the code that decides
// what Untangle reads on an arbitrary web page.
//
// Run with: node --test test/content-parsing.test.mjs
//
// Each page shape lives in test/fixtures/ as a standalone HTML document, so the
// corpus doubles as a set of sample pages you can open in a browser. See
// test/fixtures/README.md for what each one stands for, and dom-harness.mjs for
// how the real content script is loaded against them.
//
// The harness runs under jsdom. test/chrome-fidelity.mjs verifies that every
// fixture parses identically in real Chrome; run it after touching the harness
// or the DOM analysis.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { idsOf, withPage as withHtml } from './dom-harness.mjs';

const fixturesDir = join(dirname(fileURLToPath(import.meta.url)), 'fixtures');

function fixture(name) {
  return readFileSync(join(fixturesDir, name), 'utf8');
}

/** Open a fixture page by file name, hand it to `body`, then tear it down. */
async function withFixture(name, body) {
  return withHtml(fixture(name), body);
}

function describeRoot(root) {
  return root.id ? `#${root.id}` : root.tagName;
}

// --- Content root detection -------------------------------------------------
//
// getContentRoot() picks the subtree Untangle treats as "the article". Getting
// it wrong on a site class means either reading the navigation or reading
// nothing, so every supported page shape is pinned here.

const ROOT_EXPECTATIONS = [
  [
    'wordpress-entry-content.html',
    'DIV',
    'the .entry-content inside <article>, not the whole post',
  ],
  ['news-article-noise.html', 'ARTICLE', 'the bare <article>, ignoring header/nav/aside/footer'],
  [
    'daily-dev-markdown.html',
    '#post-shell',
    'the parent of the hashed markdown_markdown container',
  ],
  ['role-main-article-body.html', '#main-region', 'the [role=main] region wrapping .article-body'],
  ['main-tag-plain.html', 'MAIN', 'the plain <main> when no content class exists'],
  ['div-soup.html', 'BODY', '<body> when the page has no landmarks at all'],
  ['nested-wrappers.html', 'MAIN', '<main>, however deeply the prose is wrapped'],
  ['list-and-quote.html', 'MAIN', '<main> for list-driven prose'],
  [
    'multiple-articles.html',
    '#post-content',
    'the .post-content of the one real post, not a teaser card',
  ],
  ['itemprop-article-body.html', '#article-body', 'the [itemprop=articleBody] subtree'],
  ['inline-markup.html', 'MAIN', '<main> regardless of inline markup'],
  ['repeated-sentences.html', 'MAIN', '<main> when sentences repeat'],
  ['hidden-content.html', 'MAIN', '<main> when parts of the page are hidden'],
  ['typographic-text.html', 'MAIN', '<main> for typographically rich text'],
  [
    'article-in-excluded-region.html',
    'MAIN',
    '<main>, never an <article> parked inside nav/footer',
  ],
  [
    'article-inside-main.html',
    '#article-landmark',
    'the inner <article>, not the <main> around it',
  ],
  ['table-layout.html', 'BODY', '<body> on a legacy table layout with no landmarks'],
  ['cjk-article.html', 'ARTICLE', 'the <article> of a Japanese page'],
];

for (const [name, expected, reason] of ROOT_EXPECTATIONS) {
  test(`getContentRoot: ${name} resolves to ${reason}`, async () => {
    await withFixture(name, (page) => {
      assert.equal(describeRoot(page.call('getContentRoot')), expected);
    });
  });
}

test('getContentRoot: every fixture is covered by a root expectation', () => {
  const files = readdirSync(fixturesDir)
    .filter((file) => file.endsWith('.html'))
    .sort();
  const covered = ROOT_EXPECTATIONS.map(([name]) => name).sort();
  assert.deepEqual(
    files,
    covered,
    'add the new fixture to ROOT_EXPECTATIONS (and to fixtures/README.md)',
  );
});

test('getContentRoot: falls back to <body> when the document has no landmarks', async () => {
  await withHtml(
    `<!DOCTYPE html><html lang="en"><body>
       <div>A page with nothing semantic to hold on to at all.</div>
     </body></html>`,
    (page) => {
      assert.equal(page.call('getContentRoot').tagName, 'BODY');
    },
  );
});

const PRIVATE_PRELOAD = {
  id: 'preload-private',
  page_url: 'https://article.example/private',
  sentences: [{ id: 'sentence-private', text: 'Private article sentence.' }],
};

function readingSession(preload, owner, activeSentenceId = null) {
  return {
    schemaVersion: 1,
    owner,
    pageUrl: preload.page_url,
    pageTitle: 'Private article',
    preload,
    domLinkStatus: {},
    ui: {
      activeSentenceId,
      hoveredSentenceId: null,
      activeStudyItemId: null,
      activeSentenceScreen: activeSentenceId ? 'detail' : 'list',
    },
    updatedAt: Date.now(),
  };
}

async function settleStorageListeners() {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
}

test('content applies only its own scoped session changes without writing back foreign article events', async () => {
  await withHtml(
    '<!doctype html><main><p>Private article sentence.</p></main>',
    async (page) => {
      // jsdom has no CSS.escape. This fixture uses only unescaped identifiers;
      // the real-browser scenario exercises Chrome's selector implementation.
      page.window.CSS = {
        escape(value) {
          assert.match(value, /^[a-z][a-z0-9-]*$/i);
          return value;
        },
      };
      const accountAScope = { userId: 'account-a', loginId: 'login-a-1' };
      const accountBScope = { userId: 'account-b', loginId: 'login-b-1' };
      const applyErrors = [];
      const originalApply = page.window.applyScopedReadingSessionChange;
      page.window.applyScopedReadingSessionChange = async (...args) => {
        try {
          return await originalApply(...args);
        } catch (error) {
          applyErrors.push(error.stack);
          throw error;
        }
      };
      const ownKey = page.evaluate(
        `readingSessionStorageKey(${JSON.stringify(PRIVATE_PRELOAD.page_url)}, ${JSON.stringify(accountAScope)})`,
      );
      const otherPreload = {
        ...PRIVATE_PRELOAD,
        id: 'preload-other-article',
        page_url: 'https://article.example/other',
        sentences: [{ id: 'sentence-other', text: 'Other article sentence.' }],
      };
      const otherKey = page.evaluate(
        `readingSessionStorageKey(${JSON.stringify(otherPreload.page_url)}, ${JSON.stringify(accountBScope)})`,
      );

      await page.window.chrome.storage.local.set({
        [ownKey]: readingSession(PRIVATE_PRELOAD, accountAScope, 'sentence-private'),
      });
      await settleStorageListeners();
      assert.deepEqual(applyErrors, [], 'scoped storage events must apply without hidden errors');
      assert.equal(page.evaluate('activePreload.id'), PRIVATE_PRELOAD.id);
      assert.equal(page.evaluate('activeSentenceId'), 'sentence-private');
      assert.ok(
        page.document.querySelector('[data-era-sentence-id="sentence-private"]'),
        'the scoped session must create its anchor before a foreign event arrives',
      );

      let writeCount = 0;
      const originalSet = page.window.chrome.storage.local.set;
      page.window.chrome.storage.local.set = async (items) => {
        writeCount += 1;
        return originalSet(items);
      };
      try {
        await page.window.chrome.storage.local.set({
          [otherKey]: readingSession(otherPreload, accountBScope, 'sentence-other'),
        });
        await settleStorageListeners();
      } finally {
        page.window.chrome.storage.local.set = originalSet;
      }

      assert.equal(writeCount, 1);
      assert.equal(page.evaluate('activePreload.id'), PRIVATE_PRELOAD.id);
      assert.equal(page.evaluate('activeSentenceId'), 'sentence-private');
      assert.equal(
        page.document.querySelector('[data-era-sentence-id="sentence-private"]') !== null,
        true,
      );
    },
    {
      url: PRIVATE_PRELOAD.page_url,
      storage: {
        authSession: {
          accessToken: 'account-a-token',
          user: { id: 'account-a' },
          loginId: 'login-a-1',
        },
      },
    },
  );
});

test('content receiver rejects a preload addressed to a replaced same-URL document', async () => {
  await withHtml(
    '<!doctype html><main>Private article sentence.</main>',
    async (page) => {
      const response = await page.sendRuntimeMessage({
        type: 'SHOW_SENTENCE_PANEL',
        payload: {
          preload: PRIVATE_PRELOAD,
          pageUrl: PRIVATE_PRELOAD.page_url,
          authScope: { userId: 'account-a', loginId: 'login-a-1' },
          documentNonce: 'nonce-from-the-replaced-document',
        },
      });

      assert.equal(response.ok, false);
      assert.deepEqual(Object.keys(page.storage).sort(), ['authSession']);
    },
    {
      url: PRIVATE_PRELOAD.page_url,
      storage: {
        authSession: {
          accessToken: 'account-a-token',
          user: { id: 'account-a' },
          loginId: 'login-a-1',
        },
      },
    },
  );
});

test('page sessionStorage cannot restore a forged preload into extension storage', async () => {
  await withHtml(
    '<!doctype html><main>Private article sentence.</main>',
    async (page) => {
      page.window.sessionStorage.setItem(
        `era_preload_data:${PRIVATE_PRELOAD.page_url}`,
        JSON.stringify(PRIVATE_PRELOAD),
      );

      const restored = await page.call('restoreReadingSessionFromServer', { localOnly: true });

      assert.equal(restored, null);
      assert.deepEqual(Object.keys(page.storage).sort(), ['authSession']);
    },
    {
      url: PRIVATE_PRELOAD.page_url,
      storage: {
        authSession: {
          accessToken: 'account-a-token',
          user: { id: 'account-a' },
          loginId: 'login-a-1',
        },
      },
    },
  );
});

test('schema-invalid extension reading data is ignored before it can be restored', async () => {
  await withHtml(
    '<!doctype html><main>Private article sentence.</main>',
    async (page) => {
      const storageKey = page.evaluate(
        `readingSessionStorageKey(${JSON.stringify(PRIVATE_PRELOAD.page_url)}, { userId: 'account-a', loginId: 'login-a-1' })`,
      );
      page.storage[storageKey] = {
        schemaVersion: 1,
        owner: { userId: 'account-a', loginId: 'login-a-1' },
        pageUrl: PRIVATE_PRELOAD.page_url,
        preload: { id: 'forged', sentences: [{ id: 'missing-text' }] },
        updatedAt: Date.now(),
      };

      const restored = await page.call('getReadingSession', PRIVATE_PRELOAD.page_url);

      assert.equal(restored, null);
    },
    {
      url: PRIVATE_PRELOAD.page_url,
      storage: {
        authSession: {
          accessToken: 'account-a-token',
          user: { id: 'account-a' },
          loginId: 'login-a-1',
        },
      },
    },
  );
});

test('account B cannot restore account A scoped reading data after a new login', async () => {
  await withHtml(
    '<!doctype html><main>Private article sentence.</main>',
    async (page) => {
      const accountAKey = page.evaluate(
        `readingSessionStorageKey(${JSON.stringify(PRIVATE_PRELOAD.page_url)}, { userId: 'account-a', loginId: 'login-a-4' })`,
      );
      page.storage[accountAKey] = {
        schemaVersion: 1,
        owner: { userId: 'account-a', loginId: 'login-a-4' },
        pageUrl: PRIVATE_PRELOAD.page_url,
        preload: PRIVATE_PRELOAD,
        updatedAt: Date.now(),
      };

      const restored = await page.call('getReadingSession', PRIVATE_PRELOAD.page_url);

      assert.equal(restored, null);
    },
    {
      url: PRIVATE_PRELOAD.page_url,
      storage: {
        authSession: {
          accessToken: 'account-b-token',
          user: { id: 'account-b' },
          loginId: 'login-b-6',
        },
      },
    },
  );
});

test('RESTORE receiver rejects a stale envelope before considering a valid local cache', async () => {
  await withHtml(
    '<!doctype html><main>Private article sentence.</main>',
    async (page) => {
      const storageKey = page.evaluate(
        `readingSessionStorageKey(${JSON.stringify(PRIVATE_PRELOAD.page_url)}, { userId: 'account-a', loginId: 'login-a-1' })`,
      );
      page.storage[storageKey] = {
        schemaVersion: 1,
        owner: { userId: 'account-a', loginId: 'login-a-1' },
        pageUrl: PRIVATE_PRELOAD.page_url,
        pageTitle: 'Private article',
        preload: PRIVATE_PRELOAD,
        domLinkStatus: {},
        ui: {},
        updatedAt: Date.now(),
      };

      const response = await page.sendRuntimeMessage({
        type: 'RESTORE_READING_SESSION',
        payload: {
          localOnly: true,
          preload: PRIVATE_PRELOAD,
          pageUrl: PRIVATE_PRELOAD.page_url,
          authScope: { userId: 'account-a', loginId: 'login-a-1' },
          documentNonce: 'stale-document-nonce',
        },
      });

      assert.equal(response.ok, false);
      assert.equal(page.evaluate('activePreload'), null);
    },
    {
      url: PRIVATE_PRELOAD.page_url,
      storage: {
        authSession: {
          accessToken: 'account-a-token',
          user: { id: 'account-a' },
          loginId: 'login-a-1',
        },
      },
    },
  );
});

test('RESTORE receiver ignores forged page sessionStorage through its message boundary', async () => {
  await withHtml(
    '<!doctype html><main>Private article sentence.</main>',
    async (page) => {
      page.window.sessionStorage.setItem(
        `era_preload_data:${PRIVATE_PRELOAD.page_url}`,
        JSON.stringify(PRIVATE_PRELOAD),
      );

      const response = await page.sendRuntimeMessage({
        type: 'RESTORE_READING_SESSION',
        payload: { localOnly: true },
      });

      assert.equal(response.ok, false);
      assert.equal(page.evaluate('activePreload'), null);
      assert.deepEqual(Object.keys(page.storage).sort(), ['authSession']);
    },
    {
      url: PRIVATE_PRELOAD.page_url,
      storage: {
        authSession: {
          accessToken: 'account-a-token',
          user: { id: 'account-a' },
          loginId: 'login-a-1',
        },
      },
    },
  );
});

test('SHOW receiver rejects an otherwise valid preload without page_url', async () => {
  await withHtml(
    '<!doctype html><main>Private article sentence.</main>',
    async (page) => {
      const response = await page.sendRuntimeMessage({
        type: 'SHOW_SENTENCE_PANEL',
        payload: {
          preload: { ...PRIVATE_PRELOAD, page_url: undefined },
          pageUrl: PRIVATE_PRELOAD.page_url,
          authScope: { userId: 'account-a', loginId: 'login-a-1' },
          documentNonce: page.evaluate('contentDocumentNonce'),
        },
      });

      assert.equal(response.ok, false);
      assert.equal(page.evaluate('activePreload'), null);
      assert.deepEqual(Object.keys(page.storage).sort(), ['authSession']);
    },
    {
      url: PRIVATE_PRELOAD.page_url,
      storage: {
        authSession: {
          accessToken: 'account-a-token',
          user: { id: 'account-a' },
          loginId: 'login-a-1',
        },
      },
    },
  );
});

test('RESTORE receiver rejects an otherwise valid preload for a different page_url', async () => {
  await withHtml(
    '<!doctype html><main>Private article sentence.</main>',
    async (page) => {
      const response = await page.sendRuntimeMessage({
        type: 'RESTORE_READING_SESSION',
        payload: {
          localOnly: true,
          preload: { ...PRIVATE_PRELOAD, page_url: 'https://article.example/other' },
          pageUrl: PRIVATE_PRELOAD.page_url,
          authScope: { userId: 'account-a', loginId: 'login-a-1' },
          documentNonce: page.evaluate('contentDocumentNonce'),
        },
      });

      assert.equal(response.ok, false);
      assert.equal(page.evaluate('activePreload'), null);
      assert.deepEqual(Object.keys(page.storage).sort(), ['authSession']);
    },
    {
      url: PRIVATE_PRELOAD.page_url,
      storage: {
        authSession: {
          accessToken: 'account-a-token',
          user: { id: 'account-a' },
          loginId: 'login-a-1',
        },
      },
    },
  );
});

test('RESTORE receiver keeps account A data unmounted when its scoped storage read finishes after account B signs in', async () => {
  await withHtml(
    '<!doctype html><main>Private article sentence.</main>',
    async (page) => {
      const accountAScope = { userId: 'account-a', loginId: 'login-a-1' };
      const storageKey = page.evaluate(
        `readingSessionStorageKey(${JSON.stringify(PRIVATE_PRELOAD.page_url)}, ${JSON.stringify(accountAScope)})`,
      );
      page.storage[storageKey] = {
        schemaVersion: 1,
        owner: accountAScope,
        pageUrl: PRIVATE_PRELOAD.page_url,
        pageTitle: 'Private article',
        preload: PRIVATE_PRELOAD,
        domLinkStatus: {},
        ui: {},
        updatedAt: Date.now(),
      };

      let releaseRead;
      const readBlocked = new Promise((resolve) => {
        releaseRead = resolve;
      });
      let signalReadStarted;
      const readStarted = new Promise((resolve) => {
        signalReadStarted = resolve;
      });
      const originalGet = page.window.chrome.storage.local.get;
      page.window.chrome.storage.local.get = async (key) => {
        if (key === storageKey) {
          signalReadStarted();
          await readBlocked;
        }
        return originalGet(key);
      };

      const completion = page.sendRuntimeMessage({
        type: 'RESTORE_READING_SESSION',
        payload: { localOnly: true },
      });
      await readStarted;
      await page.window.chrome.storage.local.set({
        authSession: {
          accessToken: 'account-b-token',
          user: { id: 'account-b' },
          loginId: 'login-b-2',
        },
      });
      releaseRead();

      const response = await completion;
      assert.equal(response.ok, false);
      assert.equal(page.evaluate('activePreload'), null);
    },
    {
      url: PRIVATE_PRELOAD.page_url,
      storage: {
        authSession: {
          accessToken: 'account-a-token',
          user: { id: 'account-a' },
          loginId: 'login-a-1',
        },
      },
    },
  );
});

test('SHOW receiver removes a delayed account A write and never renders it after account B signs in', async () => {
  await withHtml(
    '<!doctype html><main>Private article sentence.</main>',
    async (page) => {
      const accountAScope = { userId: 'account-a', loginId: 'login-a-1' };
      const accountAStorageKey = page.evaluate(
        `readingSessionStorageKey(${JSON.stringify(PRIVATE_PRELOAD.page_url)}, ${JSON.stringify(accountAScope)})`,
      );
      let releaseWrite;
      const writeBlocked = new Promise((resolve) => {
        releaseWrite = resolve;
      });
      let signalWriteStarted;
      const writeStarted = new Promise((resolve) => {
        signalWriteStarted = resolve;
      });
      const originalSet = page.window.chrome.storage.local.set;
      page.window.chrome.storage.local.set = async (items) => {
        if (Object.hasOwn(items, accountAStorageKey)) {
          signalWriteStarted();
          await writeBlocked;
        }
        return originalSet(items);
      };

      const completion = page.sendRuntimeMessage({
        type: 'SHOW_SENTENCE_PANEL',
        payload: {
          preload: PRIVATE_PRELOAD,
          pageUrl: PRIVATE_PRELOAD.page_url,
          authScope: accountAScope,
          documentNonce: page.evaluate('contentDocumentNonce'),
        },
      });
      await writeStarted;
      await page.window.chrome.storage.local.set({
        authSession: {
          accessToken: 'account-b-token',
          user: { id: 'account-b' },
          loginId: 'login-b-2',
        },
      });
      releaseWrite();

      const response = await completion;
      assert.equal(response.ok, false);
      assert.equal(page.evaluate('activePreload'), null);
      assert.equal(page.storage[accountAStorageKey], undefined);
    },
    {
      url: PRIVATE_PRELOAD.page_url,
      storage: {
        authSession: {
          accessToken: 'account-a-token',
          user: { id: 'account-a' },
          loginId: 'login-a-1',
        },
      },
    },
  );
});

// --- Content block selection ------------------------------------------------
//
// getContentBlocks() returns the individual text blocks offered for analysis.
// The ids below are the blocks a reader would consider part of the article.

const BLOCK_EXPECTATIONS = {
  'wordpress-entry-content.html': ['lede', 'body-1', 'heading-1', 'body-2', 'quote', 'body-3'],
  'news-article-noise.html': ['title', 'lede', 'body-1', 'body-2'],
  'main-tag-plain.html': ['title', 'body-1', 'body-2', 'body-3'],
  'itemprop-article-body.html': ['body-1', 'body-2', 'body-3'],
  'multiple-articles.html': ['body-1', 'body-2'],
  'inline-markup.html': ['title', 'body-1', 'body-2', 'body-3'],
  'article-in-excluded-region.html': ['title', 'body-1', 'body-2'],
  'repeated-sentences.html': ['title', 'summary', 'body-1', 'restated', 'body-2'],
  'typographic-text.html': ['title', 'curly-quotes', 'dashes', 'nbsp', 'zero-width'],
  'article-inside-main.html': ['title', 'body-1', 'body-2'],
  'cjk-article.html': ['title', 'body-1', 'body-2', 'body-3'],
  'list-and-quote.html': [
    'title',
    'heading-1',
    'item-1',
    'item-2',
    'item-3',
    'quote',
    'step-1',
    'step-2',
  ],
};

for (const [name, expected] of Object.entries(BLOCK_EXPECTATIONS)) {
  test(`getContentBlocks: ${name} yields the article's text blocks`, async () => {
    await withFixture(name, (page) => {
      assert.deepEqual(idsOf(page.call('getContentBlocks')), expected);
    });
  });
}

test('getContentBlocks: drops site chrome — nav, header, aside, footer, comments', async () => {
  await withFixture('wordpress-entry-content.html', (page) => {
    const text = page
      .call('getContentBlocks')
      .map((element) => element.textContent)
      .join(' ');

    for (const chrome of [
      'About the Example Journal team', // nav
      'Published on 4 March 2026', // .entry-meta
      'Share this article', // .sharedaddy
      'Related reading', // .jp-relatedposts
      'I worked on exactly this problem', // .comment
      'All rights reserved worldwide', // .site-footer
    ]) {
      assert.ok(!text.includes(chrome), `site chrome leaked into content blocks: ${chrome}`);
    }
  });
});

test('getContentBlocks: returns disjoint blocks, never a block and its ancestor', async () => {
  await withFixture('nested-wrappers.html', (page) => {
    const blocks = page.call('getContentBlocks');
    assert.deepEqual(idsOf(blocks), ['title', 'body-1', 'callout', 'body-2']);

    for (const block of blocks) {
      for (const other of blocks) {
        if (block === other) continue;
        assert.ok(
          !other.contains(block),
          `${other.id} contains ${block.id}; both were returned as blocks`,
        );
      }
    }
  });
});

test('getContentBlocks: when candidates nest, the outermost one wins', async () => {
  // A <blockquote> wrapping a <p> is a single quotation, so the blockquote is
  // offered and the inner paragraph is dropped. Layout <div>s never reach this
  // rule because isTextBlockElement() rejects a div that holds nested blocks.
  await withFixture('wordpress-entry-content.html', (page) => {
    const ids = idsOf(page.call('getContentBlocks'));
    assert.ok(ids.includes('quote'), 'the blockquote itself is the block');
    assert.ok(!ids.includes('quote-text'), 'its inner paragraph must not also be a block');
  });
});

test('getContentBlocks: a bare <div> counts as a block only when it holds no nested block', async () => {
  await withFixture('div-soup.html', (page) => {
    const ids = idsOf(page.call('getContentBlocks'));
    for (const id of ['title', 'body-1', 'body-2', 'body-3']) {
      assert.ok(ids.includes(id), `expected div-based block ${id}`);
    }
    assert.ok(!ids.includes('content'), 'the wrapping .content div must not be a block');
  });
});

test('getContentBlocks: list items and blockquotes carry prose too', async () => {
  await withFixture('list-and-quote.html', (page) => {
    const blocks = page.call('getContentBlocks');
    const tags = blocks.map((element) => element.tagName);
    assert.ok(tags.includes('LI'), 'list items must be offered for analysis');
    assert.ok(tags.includes('BLOCKQUOTE'), 'blockquotes must be offered for analysis');
    assert.ok(tags.includes('H1'), 'headings must be offered for analysis');
  });
});

test('getContentBlocks: ignores an <article> that only exists inside nav or footer', async () => {
  await withFixture('article-in-excluded-region.html', (page) => {
    const ids = idsOf(page.call('getContentBlocks'));
    assert.ok(!ids.includes('nav-promo-text'), 'nav promo must not be treated as article text');
    assert.ok(
      !ids.includes('footer-promo-text'),
      'footer promo must not be treated as article text',
    );
  });
});

test('getContentBlocks: an inner <article> beats the <main> wrapped around it', async () => {
  await withFixture('article-inside-main.html', (page) => {
    const text = page
      .call('getContentBlocks')
      .map((element) => element.textContent)
      .join(' ');
    assert.ok(!text.includes('Save this article for later'), 'toolbar must stay out');
    assert.ok(!text.includes('three more pieces'), 'related links must stay out');
  });
});

test('getContentBlocks: a landmark-free table layout also returns page furniture', async () => {
  // Documented limitation. A legacy table layout offers no <main>, no
  // <article> and none of the excluded class names, so the root falls back to
  // <body> and the masthead and sidebar come along with the article text.
  // Recorded here so that improving it is a visible, deliberate change.
  await withFixture('table-layout.html', (page) => {
    assert.deepEqual(idsOf(page.call('getContentBlocks')), [
      'masthead',
      'sidebar-links',
      'title',
      'body-1',
      'body-2',
    ]);
  });
});

test('getContentBlocks: skips blocks shorter than the minimum selection length', async () => {
  await withHtml(
    `<!DOCTYPE html><html lang="en"><body><main>
       <p id="keep">A sentence long enough to be worth analysing.</p>
       <p id="drop">.</p>
       <p id="empty"></p>
     </main></body></html>`,
    (page) => {
      assert.deepEqual(idsOf(page.call('getContentBlocks')), ['keep']);
    },
  );
});

test('getContentBlocks: never returns script, style or noscript text', async () => {
  await withHtml(
    `<!DOCTYPE html><html lang="en"><body><main>
       <p id="keep">Visible prose that should be analysed by the extension.</p>
       <script id="js">var leaked = "script contents must never be analysed";</script>
       <style id="css">.leaked { content: "style contents must never be analysed"; }</style>
       <noscript id="ns">Enable JavaScript to view this content properly.</noscript>
     </main></body></html>`,
    (page) => {
      const text = page
        .call('getContentBlocks')
        .map((element) => element.textContent)
        .join(' ');
      assert.ok(!text.includes('must never be analysed'));
      assert.ok(!text.includes('Enable JavaScript'));
    },
  );
});

// --- Hidden content ---------------------------------------------------------
//
// Documented CURRENT behaviour, matched against Chrome 145 rather than assumed.
// Per the HTML spec an element that is not being rendered reports its raw
// textContent from innerText, so `display: none` prose still reaches
// isTextBlockElement(). Only `visibility: hidden` text disappears.
//
// The practical consequence is that collapsed FAQ answers and hidden template
// fragments ARE offered for analysis. These tests exist so that stays a
// deliberate choice: if you decide to skip hidden prose, they will fail and
// tell you exactly which cases changed.

test('hidden content: display:none prose is still collected (Chrome innerText fallback)', async () => {
  await withFixture('hidden-content.html', (page) => {
    assert.deepEqual(idsOf(page.call('getContentBlocks')), [
      'title',
      'visible-1',
      'hidden-attribute',
      'hidden-inline',
      'hidden-class-child',
      'visible-2',
    ]);
  });
});

test('hidden content: visibility:hidden prose is dropped', async () => {
  await withHtml(
    `<!DOCTYPE html><html lang="en"><body><main>
       <p id="visible">This paragraph is plainly visible to the reader.</p>
       <p id="invisible" style="visibility: hidden">This paragraph occupies space but shows nothing.</p>
     </main></body></html>`,
    (page) => {
      assert.deepEqual(idsOf(page.call('getContentBlocks')), ['visible']);
    },
  );
});

// --- Sentence to DOM linking ------------------------------------------------
//
// linkSentencesToDom() maps backend sentences onto page elements so they can be
// highlighted. A regression here shows up as sentences that silently stop
// highlighting, which is the failure users notice first.

test('linkSentences: maps each sentence onto its own paragraph', async () => {
  await withFixture('main-tag-plain.html', (page) => {
    const links = page.call('linkSentencesToDom', [
      {
        id: 's1',
        text: 'Every outbound call in the client library retries twice by default.',
      },
      {
        id: 's2',
        text: 'Set the retry budget per client rather than per request.',
      },
    ]);

    assert.equal(links.get('s1').id, 'body-1');
    assert.equal(links.get('s2').id, 'body-2');
  });
});

test('linkSentences: matches across inline markup like <em>, <a> and <code>', async () => {
  await withFixture('inline-markup.html', (page) => {
    const links = page.call('linkSentencesToDom', [
      {
        id: 's1',
        text: 'The tokenizer runs before the parser, and a grammar rule decides where each clause ends.',
      },
      {
        id: 's2',
        text: 'Call parse(input) with the raw string; the function returns a tree even when the input is partially malformed.',
      },
    ]);

    assert.equal(links.get('s1').id, 'body-1');
    assert.equal(links.get('s2').id, 'body-2');
  });
});

test('linkSentences: an exactly repeated sentence claims two different blocks', async () => {
  await withFixture('repeated-sentences.html', (page) => {
    const links = page.call('linkSentencesToDom', [
      { id: 's1', text: 'Never deploy on a Friday afternoon.' },
      { id: 's2', text: 'Never deploy on a Friday afternoon.' },
    ]);

    assert.equal(links.get('s1').id, 'summary');
    assert.equal(
      links.get('s2').id,
      'restated',
      'the second occurrence must not collapse onto the first block',
    );
  });
});

test('linkSentences: returns null for text that is not on the page', async () => {
  await withFixture('main-tag-plain.html', (page) => {
    const links = page.call('linkSentencesToDom', [
      { id: 'missing', text: 'This sentence appears nowhere in the document at all.' },
    ]);

    assert.equal(links.get('missing'), null);
  });
});

test('linkSentences: never links a sentence to site chrome', async () => {
  await withFixture('wordpress-entry-content.html', (page) => {
    const links = page.call('linkSentencesToDom', [
      { id: 'article', text: 'Bearings fail first in almost every recorded case.' },
      { id: 'comment', text: 'Great piece, I worked on exactly this problem back in 2019.' },
      { id: 'footer', text: 'Copyright Example Journal. All rights reserved worldwide.' },
    ]);

    assert.equal(links.get('article').id, 'body-2');
    assert.equal(links.get('comment'), null, 'comment text must not be linkable');
    assert.equal(links.get('footer'), null, 'footer text must not be linkable');
  });
});

test('linkSentences: finds a sentence inside a blockquote', async () => {
  await withFixture('wordpress-entry-content.html', (page) => {
    const links = page.call('linkSentencesToDom', [
      {
        id: 's1',
        text: 'We stopped trying to keep the sea out and started designing for the day it gets in.',
      },
    ]);

    // The blockquote, not its inner <p> — see the nesting rule above.
    assert.equal(links.get('s1').id, 'quote');
  });
});

test('linkSentences: matches a list item', async () => {
  await withFixture('list-and-quote.html', (page) => {
    const links = page.call('linkSentencesToDom', [
      {
        id: 's1',
        text: 'Two pairs of gloves, because one pair will get wet on the first day.',
      },
    ]);

    assert.equal(links.get('s1').id, 'item-1');
  });
});

// --- Block selection internals ----------------------------------------------

test('isTextBlockElement: accepts prose blocks and rejects layout wrappers', async () => {
  await withHtml(
    `<!DOCTYPE html><html lang="en"><body><main>
       <p id="paragraph">A paragraph with enough text to be worth analysing.</p>
       <div id="wrapper"><p id="nested">A nested paragraph carrying the actual prose.</p></div>
     </main></body></html>`,
    (page) => {
      const at = (id) => page.document.getElementById(id);

      assert.equal(page.call('isTextBlockElement', at('paragraph')), true);
      assert.equal(
        page.call('isTextBlockElement', at('wrapper')),
        false,
        'a div holding another block is layout, not prose',
      );
      assert.equal(page.call('isTextBlockElement', at('nested')), true);
    },
  );
});

test('getFallbackContentBlocks: reaches section/article/main that the primary tier skips', async () => {
  await withHtml(
    `<!DOCTYPE html><html lang="en"><body><main>
       <section id="sect">Loose prose held directly by the section element.
         <p id="p">A separate paragraph of text.</p>
       </section>
     </main></body></html>`,
    (page) => {
      assert.deepEqual(idsOf(page.call('getContentBlocks')), ['p']);
      assert.deepEqual(idsOf(page.call('getFallbackContentBlocks')), ['sect', 'p']);
    },
  );
});

// --- Sentence matching tiers ------------------------------------------------
//
// findSentenceElement() tries three tiers in order: content blocks, then the
// broader fallback blocks, then a raw text-node walk. Each tier has its own
// test so a regression says which one broke.

test('findSentenceElement: falls back to a <section> when no content block matches', async () => {
  await withHtml(
    `<!DOCTYPE html><html lang="en"><body><main>
       <section id="sect">Loose prose held directly by the section element.
         <p id="p">A separate paragraph of text.</p>
       </section>
     </main></body></html>`,
    (page) => {
      const links = page.call('linkSentencesToDom', [
        { id: 's1', text: 'Loose prose held directly by the section element.' },
      ]);

      assert.equal(links.get('s1').id, 'sect');
    },
  );
});

test('findTextRangeElement: last resort finds text in an element no tier collects', async () => {
  await withHtml(
    `<!DOCTYPE html><html lang="en"><body><main>
       <span id="sp">A sentence living inside a bare span element only.</span>
     </main></body></html>`,
    (page) => {
      assert.deepEqual(idsOf(page.call('getContentBlocks')), [], 'no block tier candidate');

      const element = page.call(
        'findTextRangeElement',
        'A sentence living inside a bare span element only.',
      );
      assert.equal(element?.id, 'sp');
    },
  );
});

test('findBestSentenceBlock: the smallest matching block wins', async () => {
  await withHtml(
    `<!DOCTYPE html><html lang="en"><body><main>
       <div id="outer"><p id="inner">Target sentence here now.</p></div>
       <section id="sect">Target sentence here now. Plus extra trailing words.</section>
     </main></body></html>`,
    (page) => {
      const links = page.call('linkSentencesToDom', [
        { id: 's1', text: 'Target sentence here now.' },
      ]);

      assert.equal(
        links.get('s1').id,
        'inner',
        'an exact-length match beats a longer block that merely contains the sentence',
      );
    },
  );
});

test('linkSentences: a sentence split across two sibling blocks is not linked', async () => {
  // Documented limitation. The two paragraphs' text runs together without a
  // space, so neither the exact nor the whitespace-tolerant match applies.
  await withHtml(
    `<!DOCTYPE html><html lang="en"><body><main>
       <div id="wrap"><p id="a">First half of the idea</p><p id="b">and the second half of it.</p></div>
     </main></body></html>`,
    (page) => {
      const links = page.call('linkSentencesToDom', [
        { id: 's1', text: 'First half of the idea and the second half of it.' },
      ]);

      assert.equal(links.get('s1'), null);
    },
  );
});

test('linkSentences: a block already carrying vocabulary marks still matches', async () => {
  // Marking rewrites the paragraph's child nodes. Matching reads textContent
  // rather than the node structure precisely so re-linking keeps working after
  // vocabulary highlighting has run — the panel relinks on every update.
  await withHtml(
    `<!DOCTYPE html><html lang="en"><body><main>
       <p id="p">The cache warms up quickly on restart.</p>
     </main></body></html>`,
    (page) => {
      const element = page.document.getElementById('p');
      page.call('highlightTextInElement', element, 'cache', 'item-1');
      assert.ok(element.querySelector('mark.era-vocabulary-mark'), 'precondition: marked');

      const links = page.call('linkSentencesToDom', [
        { id: 's1', text: 'The cache warms up quickly on restart.' },
      ]);

      assert.equal(links.get('s1')?.id, 'p');
    },
  );
});

test('canHighlightSentenceInElement: true for contained text, false otherwise', async () => {
  await withHtml(
    `<!DOCTYPE html><html lang="en"><body><main>
       <p id="p">The council voted on Tuesday to rebuild the wall.</p>
     </main></body></html>`,
    (page) => {
      const element = page.document.getElementById('p');

      assert.equal(page.call('canHighlightSentenceInElement', element, 'voted on Tuesday'), true);
      assert.equal(
        page.call('canHighlightSentenceInElement', element, 'a sentence from elsewhere'),
        false,
      );
      assert.equal(page.call('canHighlightSentenceInElement', null, 'anything'), false);
      assert.equal(page.call('canHighlightSentenceInElement', element, ''), false);
    },
  );
});

// --- Typography normalization -----------------------------------------------
//
// The backend returns sentences with plain ASCII punctuation while pages use
// typographic characters. Matching has to survive the difference.

const TYPOGRAPHY_CASES = [
  [
    'curly-quotes',
    'The editor called it "a small change" and the author didn\'t argue with her about it.',
    'curly quotes and apostrophes',
  ],
  [
    'dashes',
    'The window - roughly 40-60 minutes - is when most readers give up entirely.',
    'em dashes and en dashes',
  ],
  ['nbsp', 'Print runs of 5 000 copies were normal until the late 1990s.', 'non-breaking spaces'],
  [
    'zero-width',
    'Invisiblecharacterssurvive copy and paste and quietly ruin every exact string comparison.',
    'zero-width characters',
  ],
];

for (const [blockId, sentenceText, description] of TYPOGRAPHY_CASES) {
  test(`linkSentences: ASCII text still matches a page using ${description}`, async () => {
    await withFixture('typographic-text.html', (page) => {
      const links = page.call('linkSentencesToDom', [{ id: 's1', text: sentenceText }]);
      assert.equal(links.get('s1')?.id, blockId);
    });
  });
}

// --- Non-Latin scripts ------------------------------------------------------
//
// Sentence matching leans on whitespace-separated words in places. Japanese
// prose has no inter-word spaces, so it exercises the exact-substring path
// rather than the word-overlap fallback.

test('cjk: sentences in a Japanese article link to their paragraphs', async () => {
  await withFixture('cjk-article.html', (page) => {
    const links = page.call('linkSentencesToDom', [
      { id: 's1', text: '潮流発電機は、技術者が設計しうるもっとも過酷な環境で稼働しつづける。' },
      {
        id: 's2',
        text: '最初に壊れるのはほぼ必ず軸受であり、海水を遮るシールこそが本当の設計課題である。',
      },
    ]);

    assert.equal(links.get('s1').id, 'body-1');
    assert.equal(links.get('s2').id, 'body-3');
  });
});

test('cjk: the page language is detected from the document', async () => {
  await withFixture('cjk-article.html', (page) => {
    assert.equal(page.call('detectPageLanguage'), 'ja');
  });
});

test('cjk: highlighting a Japanese phrase preserves the paragraph text', async () => {
  await withFixture('cjk-article.html', (page) => {
    const element = page.document.getElementById('body-2');
    const before = element.textContent;

    page.call('highlightTextInElement', element, '海底', 'item-1');

    const marks = [...element.querySelectorAll('mark.era-vocabulary-mark')];
    assert.equal(marks.length, 1);
    assert.equal(marks[0].textContent, '海底');
    assert.equal(element.textContent, before);
  });
});

// --- Page HTML extraction ---------------------------------------------------
//
// extractPageHtml() produces what the backend actually reads. Anything left in
// here costs tokens; anything wrongly stripped is lost article text.

test('extractPageHtml: keeps article prose and the doctype', async () => {
  await withFixture('news-article-noise.html', (page) => {
    const html = page.call('extractPageHtml');
    assert.match(html, /^<!DOCTYPE html>\n<html/);
    assert.ok(html.includes('The council voted on Tuesday'));
  });
});

test('extractPageHtml: strips script, style, noscript, iframe, svg and aria-hidden nodes', async () => {
  await withHtml(
    `<!DOCTYPE html><html lang="en"><head>
       <style>.a { color: red } /* STYLE_MARKER */</style>
     </head><body><main>
       <p>A long enough paragraph of article prose to clear the minimum length check comfortably.</p>
       <script>var x = "SCRIPT_MARKER";</script>
       <noscript>NOSCRIPT_MARKER</noscript>
       <iframe src="https://example.test/embed" title="IFRAME_MARKER"></iframe>
       <svg><title>SVG_MARKER</title></svg>
       <div aria-hidden="true">ARIA_HIDDEN_MARKER</div>
       <p>A second paragraph so the document stays comfortably above the minimum size.</p>
     </main></body></html>`,
    (page) => {
      const html = page.call('extractPageHtml');
      for (const marker of [
        'SCRIPT_MARKER',
        'STYLE_MARKER',
        'NOSCRIPT_MARKER',
        'IFRAME_MARKER',
        'SVG_MARKER',
        'ARIA_HIDDEN_MARKER',
      ]) {
        assert.ok(!html.includes(marker), `${marker} survived extraction`);
      }
      assert.ok(html.includes('A long enough paragraph of article prose'));
      assert.ok(html.includes('A second paragraph'));
    },
  );
});

test('extractPageHtml: does not mutate the live document', async () => {
  await withHtml(
    `<!DOCTYPE html><html lang="en"><body><main>
       <p>Article prose that is comfortably longer than the two hundred character floor
          so that extraction succeeds without any padding tricks being needed here.</p>
       <script id="js">var keep = 1;</script>
     </main></body></html>`,
    (page) => {
      page.call('extractPageHtml');
      assert.ok(
        page.document.getElementById('js'),
        'extraction must work on a clone, not strip nodes from the page',
      );
    },
  );
});

test('extractPageHtml: rejects a page too small to be an article', async () => {
  await withHtml(`<!DOCTYPE html><html lang="en"><body><p>Hi</p></body></html>`, (page) => {
    assert.throws(() => page.call('extractPageHtml'), /.+/);
  });
});

test('extractPageHtml: truncates at the maximum payload length', async () => {
  const filler = '<p>Sentences repeat here so the document grows past the cap.</p>'.repeat(12000);
  await withHtml(
    `<!DOCTYPE html><html lang="en"><body><main>${filler}</main></body></html>`,
    (page) => {
      const limit = page.evaluate('MAX_PAGE_HTML_LENGTH');
      const html = page.call('extractPageHtml');
      assert.ok(html.length > limit / 2, 'fixture must actually exceed the cap');
      assert.equal(html.length, limit);
    },
  );
});

// --- Page language ----------------------------------------------------------

test('detectPageLanguage: reads the document language', async () => {
  await withHtml(
    `<!DOCTYPE html><html lang="en-GB"><body><p>Some prose.</p></body></html>`,
    (page) => {
      assert.equal(page.call('detectPageLanguage'), 'en');
    },
  );
});

test('detectPageLanguage: returns empty string when the page declares nothing', async () => {
  await withHtml(`<!DOCTYPE html><html><body><p>Some prose.</p></body></html>`, (page) => {
    assert.equal(page.call('detectPageLanguage'), '');
  });
});
