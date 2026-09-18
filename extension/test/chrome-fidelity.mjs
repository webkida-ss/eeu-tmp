// Checks that the jsdom harness agrees with real Chrome.
//
// test/content-parsing.test.mjs runs content.js under jsdom, which has no
// layout engine and needs an innerText shim (see dom-harness.mjs). That shim is
// the one place where the unit tests could quietly stop describing reality.
// This script runs the *same* scripts against the *same* fixtures in a real
// Chrome and reports any fixture where the two disagree.
//
// It is deliberately not part of `node --test`: it needs a browser binary.
// Run it after changing the harness, the innerText shim, or the DOM analysis
// in content.js:
//
//   cd extension && node test/chrome-fidelity.mjs
//
// Set CHROME_BIN to point at a Chrome/Chromium binary, or let it fall back to
// the Chrome for Testing builds Playwright and Puppeteer download.

import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { homedir } from 'node:os';
import { createPage, idsOf } from './dom-harness.mjs';

const testDir = dirname(fileURLToPath(import.meta.url));
const extensionDir = join(testDir, '..');
const fixturesDir = join(testDir, 'fixtures');

const EXTENSION_SCRIPTS = ['settings.js', 'i18n.js', 'shared.js', 'content.js'];

function findChromeBinary() {
  if (process.env.CHROME_BIN) return process.env.CHROME_BIN;

  const roots = [
    join(homedir(), 'Library/Caches/ms-playwright'),
    join(homedir(), '.cache/ms-playwright'),
    join(homedir(), '.cache/puppeteer/chrome'),
  ];

  const relatives = [
    'chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
    'chrome-mac/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
    'chrome-mac-arm64/Chromium.app/Contents/MacOS/Chromium',
    'chrome-mac/Chromium.app/Contents/MacOS/Chromium',
    'chrome-linux/chrome',
    'chrome-linux64/chrome',
  ];

  for (const root of roots) {
    if (!existsSync(root)) continue;
    for (const entry of readdirSync(root)) {
      for (const relative of relatives) {
        const candidate = join(root, entry, relative);
        if (existsSync(candidate)) return candidate;
      }
    }
  }

  return null;
}

async function importPlaywright() {
  try {
    return await import('playwright');
  } catch {
    return null;
  }
}

// Serialised view of one fixture's parse, comparable across the two engines.
function describeInPage() {
  const ids = (elements) =>
    [...elements].map((element) => element.id || element.tagName.toLowerCase());

  const root = getContentRoot();
  return {
    root: root.id ? `#${root.id}` : root.tagName,
    blocks: ids(getContentBlocks()),
    fallbackBlocks: ids(getFallbackContentBlocks()),
  };
}

function describeWithHarness(html) {
  const page = createPage(html);
  const root = page.call('getContentRoot');
  const result = {
    root: root.id ? `#${root.id}` : root.tagName,
    blocks: idsOf(page.call('getContentBlocks')),
    fallbackBlocks: idsOf(page.call('getFallbackContentBlocks')),
  };
  return { result, page };
}

const chromeBinary = findChromeBinary();
const playwright = await importPlaywright();

if (!playwright) {
  console.error(
    'playwright is not installed. Install it (npm i -D playwright) or run\n' +
      '`npx playwright@latest install chromium`, then re-run this script.',
  );
  process.exit(2);
}
if (!chromeBinary) {
  console.error('No Chrome binary found. Set CHROME_BIN to a Chrome/Chromium executable.');
  process.exit(2);
}

console.log(`Chrome: ${chromeBinary}\n`);

const bundle = EXTENSION_SCRIPTS.map((file) => readFileSync(join(extensionDir, file), 'utf8')).join(
  '\n;\n',
);

const browser = await playwright.chromium.launch({ executablePath: chromeBinary });
const context = await browser.newContext();

// content.js gates its entire body on a live chrome.runtime.id, and registers
// listeners at load. Provide the same inert stub the jsdom harness uses.
await context.addInitScript(() => {
  const noop = () => {};
  const area = {
    get: () => Promise.resolve({}),
    set: () => Promise.resolve(),
    remove: () => Promise.resolve(),
  };
  window.chrome = {
    runtime: {
      id: 'untangle-test-extension',
      lastError: null,
      sendMessage: () => Promise.resolve({ ok: false }),
      onMessage: { addListener: noop, removeListener: noop },
      getURL: (path) => `chrome-extension://untangle-test-extension/${path}`,
    },
    storage: { local: area, sync: area, onChanged: { addListener: noop, removeListener: noop } },
  };
});

const fixtures = readdirSync(fixturesDir)
  .filter((file) => file.endsWith('.html'))
  .sort();

let mismatches = 0;

for (const file of fixtures) {
  const html = readFileSync(join(fixturesDir, file), 'utf8');

  const page = await context.newPage();
  await page.setContent(html, { waitUntil: 'load' });
  await page.evaluate(bundle);
  const chromeResult = await page.evaluate(describeInPage);
  await page.close();

  const { result: jsdomResult, page: harnessPage } = describeWithHarness(html);
  await harnessPage.close();

  const differences = [];
  for (const key of ['root', 'blocks', 'fallbackBlocks']) {
    const inChrome = JSON.stringify(chromeResult[key]);
    const inJsdom = JSON.stringify(jsdomResult[key]);
    if (inChrome !== inJsdom) {
      differences.push(`    ${key}:\n      chrome: ${inChrome}\n      jsdom : ${inJsdom}`);
    }
  }

  if (differences.length === 0) {
    console.log(`  ok    ${file}`);
  } else {
    mismatches += 1;
    console.log(`  DIFF  ${file}`);
    console.log(differences.join('\n'));
  }
}

await browser.close();

console.log(`\n${fixtures.length - mismatches}/${fixtures.length} fixtures match real Chrome.`);

if (mismatches > 0) {
  console.error(
    "\nThe jsdom harness no longer describes Chrome's behaviour. Fix the shim\n" +
      'in test/dom-harness.mjs before trusting test/content-parsing.test.mjs.',
  );
  process.exit(1);
}
