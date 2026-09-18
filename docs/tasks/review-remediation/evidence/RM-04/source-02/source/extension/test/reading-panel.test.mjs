// Exercises the real reading-panel persistence producer against scoped storage.

import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import vm from 'node:vm';
import { JSDOM } from 'jsdom';

const extensionDir = join(dirname(fileURLToPath(import.meta.url)), '..');

function createPanel({ storage }) {
  const dom = new JSDOM('<!doctype html><body><div id="readingPanelRoot"></div></body>', {
    url: 'chrome-extension://test-extension/sidepanel.html',
    runScripts: 'outside-only',
  });
  const context = dom.getInternalVMContext();
  const changedListeners = [];
  const local = structuredClone(storage);
  context.crypto = webcrypto;
  context.CSS = { escape: (value) => String(value) };
  context.matchMedia = () => ({ matches: true });
  context.HTMLElement.prototype.scrollIntoView = () => {};
  context.chrome = {
    runtime: {
      id: 'test-extension',
      sendMessage: async () => ({ ok: true }),
    },
    storage: {
      local: {
        async get(keys) {
          if (typeof keys === 'string') return { [keys]: local[keys] };
          if (Array.isArray(keys)) {
            return Object.fromEntries(keys.map((key) => [key, local[key]]));
          }
          return { ...local };
        },
        async set(values) {
          const changes = Object.fromEntries(
            Object.entries(values).map(([key, newValue]) => [
              key,
              { oldValue: local[key], newValue },
            ]),
          );
          Object.assign(local, values);
          for (const listener of changedListeners) listener(changes, 'local');
        },
      },
      onChanged: {
        addListener(listener) {
          changedListeners.push(listener);
        },
      },
    },
  };
  for (const file of ['settings.js', 'i18n.js', 'shared.js', 'reading-panel.js']) {
    vm.runInContext(readFileSync(join(extensionDir, file), 'utf8'), context, { filename: file });
  }
  return { context, dom, local };
}

function session({ owner, pageUrl, preload, activeSentenceId = null }) {
  return {
    schemaVersion: 1,
    owner,
    pageUrl,
    pageTitle: 'Article',
    preload,
    domLinkStatus: Object.fromEntries(preload.sentences.map((sentence) => [sentence.id, true])),
    ui: {
      activeSentenceId,
      hoveredSentenceId: null,
      activeStudyItemId: null,
      activeSentenceScreen: activeSentenceId ? 'detail' : 'list',
    },
    updatedAt: Date.now(),
  };
}

async function settle() {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
}

test('panel selection persists and restores only its mounted scoped session', async () => {
  const accountA = { userId: 'account-a', loginId: 'login-a' };
  const accountB = { userId: 'account-b', loginId: 'login-b' };
  const pageA = 'https://example.test/article-a';
  const pageB = 'https://example.test/article-b';
  const preloadA = {
    id: 'preload-a',
    page_url: pageA,
    sentences: [
      { id: 'sentence-a-first', index: 0, text: 'First article sentence.', analysis: {} },
      { id: 'sentence-a-second', index: 1, text: 'Second article sentence.', analysis: {} },
    ],
  };
  const preloadB = {
    id: 'preload-b',
    page_url: pageB,
    sentences: [{ id: 'sentence-b', index: 0, text: 'Other article sentence.', analysis: {} }],
  };
  const initialStorage = {
    authSession: {
      accessToken: 'account-a-token',
      user: { id: accountA.userId },
      loginId: accountA.loginId,
    },
  };
  const { context, dom, local } = createPanel({ storage: initialStorage });
  const keyA = context.readingSessionStorageKey(pageA, accountA);
  const keyB = context.readingSessionStorageKey(pageB, accountB);
  const sessionA = session({ owner: accountA, pageUrl: pageA, preload: preloadA });
  const sessionB = session({ owner: accountB, pageUrl: pageB, preload: preloadB });
  await context.chrome.storage.local.set({ [keyA]: sessionA, [keyB]: sessionB });

  try {
    assert.equal(
      await context.window.ReadingPanel.mountFromPreload(preloadA, pageA, 'Article A', accountA),
      true,
    );
    context.document
      .querySelector('.era-sentence-button[data-sentence-id="sentence-a-second"]')
      .click();
    await settle();

    assert.equal(local[keyA].ui.activeSentenceId, 'sentence-a-second');
    assert.equal(local[keyB].ui.activeSentenceId, null);
    assert.equal(local[keyB].preload.id, 'preload-b');

    context.window.ReadingPanel.clearReadingPanel();
    assert.equal(await context.window.ReadingPanel.mountFromStorage(pageA), true);
    assert.match(
      context.document.getElementById('readingPanelRoot').textContent,
      /Second article sentence/,
    );
    assert.equal(local[keyA].ui.activeSentenceId, 'sentence-a-second');
    assert.equal(local[keyB].preload.id, 'preload-b');
  } finally {
    dom.window.close();
  }
});
