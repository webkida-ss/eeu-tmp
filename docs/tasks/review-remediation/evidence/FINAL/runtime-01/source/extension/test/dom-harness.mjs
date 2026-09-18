// Loads the real extension content script against a jsdom page so the DOM
// analysis in content.js can be unit-tested against many page shapes.
//
// Why this exists: getContentRoot / getContentBlocks / linkSentencesToDom /
// extractPageHtml decide what Untangle reads on an arbitrary website. They had
// no unit coverage — only one hand-written page inside the Playwright smoke
// test — so a selector tweak could silently break whole classes of sites.
//
// The scripts are executed verbatim (no copies, no re-implementation) inside
// jsdom's own VM context, so `document`, `Element`, `Node` and `NodeFilter`
// are the same objects content.js sees at runtime and `instanceof` holds.
//
// Fidelity note: jsdom has no layout engine and does not implement innerText,
// which isTextBlockElement and getFallbackContentBlocks rely on. We install an
// approximation (see installInnerTextShim). Everything content.js does with
// innerText is fed through normalizeText(), which collapses all whitespace, so
// the approximation only has to agree with Chrome about *which text is
// visible* — not about exact line breaks. Layout-dependent invisibility
// (zero-height clipping, off-screen positioning, CSS that jsdom cannot
// cascade) is NOT modelled; keep such cases in the Playwright smoke test.

import { JSDOM, VirtualConsole } from 'jsdom';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const extensionDir = join(dirname(fileURLToPath(import.meta.url)), '..');

// Load order matches manifest.json: content.js depends on the helpers defined
// by settings.js, i18n.js and shared.js.
const EXTENSION_SCRIPTS = ['settings.js', 'i18n.js', 'shared.js', 'content.js'];

const SCRIPT_SOURCE = new Map(
  EXTENSION_SCRIPTS.map((file) => [file, readFileSync(join(extensionDir, file), 'utf8')]),
);

// Tags whose text content is never rendered, so innerText skips them.
const NON_RENDERED_TAGS = new Set([
  'SCRIPT',
  'STYLE',
  'NOSCRIPT',
  'TEMPLATE',
  'HEAD',
  'TITLE',
  'META',
  'LINK',
]);

// Block-level tags force a line break in innerText. Only the break matters
// here, not the exact count, because normalizeText() collapses whitespace.
const BLOCK_TAGS = new Set([
  'ADDRESS',
  'ARTICLE',
  'ASIDE',
  'BLOCKQUOTE',
  'DD',
  'DETAILS',
  'DIALOG',
  'DIV',
  'DL',
  'DT',
  'FIELDSET',
  'FIGCAPTION',
  'FIGURE',
  'FOOTER',
  'FORM',
  'H1',
  'H2',
  'H3',
  'H4',
  'H5',
  'H6',
  'HEADER',
  'HGROUP',
  'HR',
  'LI',
  'MAIN',
  'NAV',
  'OL',
  'P',
  'PRE',
  'SECTION',
  'TABLE',
  'TBODY',
  'TD',
  'TFOOT',
  'TH',
  'THEAD',
  'TR',
  'UL',
]);

function computedStyleOf(element, window) {
  // jsdom cascades <style> rules for simple selectors, but throws on some
  // real-world CSS. Treat an unresolvable style as "no opinion".
  try {
    return window.getComputedStyle(element);
  } catch {
    return null;
  }
}

// "display: none" — the element generates no box at all. Verified against
// Chrome 145: such an element contributes nothing to an ancestor's innerText.
function isDisplayNone(element, window) {
  if (NON_RENDERED_TAGS.has(element.tagName)) return true;
  if (element.hasAttribute('hidden')) return true;

  const inline = element.getAttribute('style') || '';
  if (/display\s*:\s*none/i.test(inline)) return true;

  return computedStyleOf(element, window)?.display === 'none';
}

// "visibility: hidden" — the element still generates a box, so it is "being
// rendered", but its text is invisible and drops out of innerText.
// Approximation: a descendant re-declaring `visibility: visible` is not
// modelled, which is vanishingly rare in article markup.
function isVisibilityHidden(element, window) {
  const inline = element.getAttribute('style') || '';
  if (/visibility\s*:\s*(hidden|collapse)/i.test(inline)) return true;

  const visibility = computedStyleOf(element, window)?.visibility;
  return visibility === 'hidden' || visibility === 'collapse';
}

// The rendered-text collection walk, for an element that IS being rendered.
function collectRenderedText(element, window) {
  let text = '';

  for (const node of element.childNodes) {
    if (node.nodeType === window.Node.TEXT_NODE) {
      text += node.textContent;
      continue;
    }
    if (node.nodeType !== window.Node.ELEMENT_NODE) continue;

    if (isDisplayNone(node, window)) continue;

    if (node.tagName === 'BR') {
      text += '\n';
      continue;
    }

    if (isVisibilityHidden(node, window)) continue;

    const childText = collectRenderedText(node, window);
    if (!childText) continue;

    text += BLOCK_TAGS.has(node.tagName) ? `\n${childText}\n` : childText;
  }

  return text;
}

// Matches the HTML spec's innerText getter, and was checked against Chrome 145
// (see test/chrome-fidelity.mjs):
//   - an element that is NOT being rendered returns its raw textContent,
//     so `<p hidden>` and `<p style="display:none">` still report their text;
//   - an element that IS being rendered returns only its visible text.
// This distinction is load-bearing: content.js keys isTextBlockElement() off
// innerText, so getting it backwards would silently change which blocks the
// extension reads.
function installInnerTextShim(window) {
  Object.defineProperty(window.HTMLElement.prototype, 'innerText', {
    configurable: true,
    get() {
      if (isDisplayNone(this, window)) return this.textContent;
      if (isVisibilityHidden(this, window)) return '';
      return collectRenderedText(this, window);
    },
  });
}

// jsdom has no layout tree, so it omits document.elementFromPoint(). The
// extension samples the page surface beneath its launcher; document.body is
// the only layout-neutral fallback the harness can represent.
function installElementFromPointShim(window) {
  if (typeof window.document.elementFromPoint === 'function') return;
  window.document.elementFromPoint = () => window.document.body;
}

// Minimal chrome.* surface. content.js touches it at load time (runtime.id
// gates the whole script body, plus two listener registrations and a preload
// status lookup) and the stub keeps those paths inert.
function createChromeStub({ extensionId, storage }) {
  const local = { ...storage };
  const runtimeMessageListeners = [];
  const storageChangedListeners = [];

  function notifyStorageChanges(changes) {
    for (const listener of storageChangedListeners) {
      listener(changes, 'local');
    }
  }

  const area = {
    get: (keys) => {
      if (typeof keys === 'string') return Promise.resolve({ [keys]: local[keys] });
      if (Array.isArray(keys)) {
        return Promise.resolve(Object.fromEntries(keys.map((key) => [key, local[key]])));
      }
      return Promise.resolve({ ...local });
    },
    set: (items) => {
      const changes = Object.fromEntries(
        Object.entries(items).map(([key, newValue]) => [key, { oldValue: local[key], newValue }]),
      );
      Object.assign(local, items);
      notifyStorageChanges(changes);
      return Promise.resolve();
    },
    remove: (keys) => {
      const changes = {};
      for (const key of Array.isArray(keys) ? keys : [keys]) {
        if (Object.hasOwn(local, key)) {
          changes[key] = { oldValue: local[key] };
          delete local[key];
        }
      }
      if (Object.keys(changes).length) notifyStorageChanges(changes);
      return Promise.resolve();
    },
  };

  return {
    runtime: {
      id: extensionId,
      lastError: null,
      // No preload is registered, so refreshPanelLauncher() removes the
      // launcher instead of injecting a button into the fixture page.
      sendMessage: () => Promise.resolve({ ok: false }),
      onMessage: {
        addListener(listener) {
          runtimeMessageListeners.push(listener);
        },
        removeListener(listener) {
          const index = runtimeMessageListeners.indexOf(listener);
          if (index >= 0) runtimeMessageListeners.splice(index, 1);
        },
      },
      getURL: (path) => `chrome-extension://${extensionId}/${path}`,
    },
    storage: {
      local: area,
      sync: area,
      onChanged: {
        addListener(listener) {
          storageChangedListeners.push(listener);
        },
        removeListener(listener) {
          const index = storageChangedListeners.indexOf(listener);
          if (index >= 0) storageChangedListeners.splice(index, 1);
        },
      },
    },
    __storage: local,
    __runtimeMessageListeners: runtimeMessageListeners,
    __dispose() {
      runtimeMessageListeners.length = 0;
      storageChangedListeners.length = 0;
    },
  };
}

/**
 * Load the extension's content script against `html` and return handles to it.
 *
 * @param {string} html Full document markup for the fixture page.
 * @param {{url?: string, extensionId?: string, storage?: object}} [options]
 */
export function createPage(html, options = {}) {
  const {
    url = 'https://example.test/article',
    extensionId = 'untangle-test-extension',
    storage = {},
  } = options;

  // Swallow jsdom's "could not parse CSS" noise from real-world fixtures;
  // surface everything else so genuine script errors stay visible.
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', (error) => {
    if (error?.type === 'css parsing') return;
    console.error(error);
  });
  virtualConsole.on('error', (...args) => console.error(...args));

  const dom = new JSDOM(html, { url, runScripts: 'dangerously', virtualConsole });
  const { window } = dom;

  installInnerTextShim(window);
  installElementFromPointShim(window);
  window.chrome = createChromeStub({ extensionId, storage });

  const context = dom.getInternalVMContext();
  for (const file of EXTENSION_SCRIPTS) {
    vm.runInContext(SCRIPT_SOURCE.get(file), context, { filename: file });
  }

  // content.js guards its whole body on being the top frame with a live
  // runtime id. If that guard ever stops matching, every function below would
  // be undefined and the suite would pass vacuously — so fail loudly instead.
  if (typeof window.getContentRoot !== 'function') {
    throw new Error('content.js did not initialize: its runtime guard rejected the harness page');
  }

  return {
    dom,
    window,
    document: window.document,

    /** Call a top-level content.js function by name. */
    call(name, ...args) {
      if (typeof window[name] !== 'function') {
        throw new Error(`content.js has no function named ${name}`);
      }
      return window[name](...args);
    },

    /** Evaluate an expression inside the page context (for var/const reads). */
    evaluate(expression) {
      return vm.runInContext(expression, context);
    },

    /** Deliver a message through the real content-script receiver. */
    sendRuntimeMessage(message) {
      const [listener] = window.chrome.__runtimeMessageListeners;
      if (!listener) throw new Error('content.js did not register a runtime message receiver');
      return new Promise((resolve) => {
        const keepChannelOpen = listener(message, {}, resolve);
        if (!keepChannelOpen) resolve(undefined);
      });
    },

    storage: window.chrome.__storage,

    /**
     * content.js kicks off async work at load time (a preload-status lookup
     * that ends in removePanelLauncher). Let those continuations run against a
     * live document before tearing the window down, otherwise they reject
     * against an undefined `document` and crash the test process.
     */
    async close() {
      await new Promise((resolve) => setTimeout(resolve, 0));
      window.chrome.__dispose();
      window.close();
    },
  };
}

/**
 * Run `body` against a freshly loaded page and always tear the page down.
 *
 * @param {string} html Full document markup.
 * @param {(page: ReturnType<typeof createPage>) => unknown} body
 * @param {Parameters<typeof createPage>[1]} [options]
 */
export async function withPage(html, body, options) {
  const page = createPage(html, options);
  try {
    return await body(page);
  } finally {
    await page.close();
  }
}

/** Tag names of the elements a parsing pass returned, in document order. */
export function tagsOf(elements) {
  return [...elements].map((element) => element.tagName);
}

/** Stable identifiers for matched elements: prefers id, falls back to tag. */
export function idsOf(elements) {
  return [...elements].map((element) => element.id || element.tagName.toLowerCase());
}
