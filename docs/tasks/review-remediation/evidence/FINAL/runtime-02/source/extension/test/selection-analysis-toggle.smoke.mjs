// Regression check for the "double-click reacts everywhere" complaint:
// selecting text (including a native double-click word selection) must NOT
// trigger the ad-hoc analyze-selection popup unless the learner opted in via
// the new global "selectionAnalysisEnabled" setting. Also verifies the
// settings-tab checkbox and the popup's quick "turn it off" control.
import { createRequire } from 'node:module';
import { createServer } from 'node:http';
import { mkdtempSync, readdirSync, existsSync } from 'node:fs';
import { tmpdir, homedir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright-core');

const EXT_DIR = join(dirname(fileURLToPath(import.meta.url)), '..');
const PORT = 18299;

function findChromiumExecutable() {
  const cacheDir = join(homedir(), 'Library/Caches/ms-playwright');
  const chromiumDir = readdirSync(cacheDir)
    .filter((name) => /^chromium-\d+$/.test(name))
    .sort()
    .pop();
  const candidates = [
    'chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
    'chrome-mac/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
    'chrome-mac/Chromium.app/Contents/MacOS/Chromium',
  ];
  for (const candidate of candidates) {
    const path = join(cacheDir, chromiumDir, candidate);
    if (existsSync(path)) return path;
  }
  throw new Error('No Chromium executable found');
}

const PAGE_HTML = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Toggle Test</title></head>
<body>
<main><article>
<p id="target">The quick brown fox jumps over the lazy dog every single morning.</p>
</article></main>
</body></html>`;

const server = createServer((req, res) => {
  if (req.url === '/auth/config') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ provider: 'mock' }));
    return;
  }
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
  res.end(PAGE_HTML);
});
await new Promise((resolve) => server.listen(PORT, resolve));

const userDataDir = mkdtempSync(join(tmpdir(), 'era-selection-toggle-'));
const errors = [];
const context = await chromium.launchPersistentContext(userDataDir, {
  executablePath: findChromiumExecutable(),
  headless: false,
  args: [
    '--headless=new',
    `--disable-extensions-except=${EXT_DIR}`,
    `--load-extension=${EXT_DIR}`,
    '--no-first-run',
  ],
});

let [worker] = context.serviceWorkers();
if (!worker) worker = await context.waitForEvent('serviceworker', { timeout: 10000 });

const page = await context.newPage();
page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`));
await page.goto(`http://localhost:${PORT}/`);
await page.waitForTimeout(1000);

// Selects the whole paragraph and fires a synthetic mouseup, mirroring what
// a real double-click word selection (or a click-drag selection) produces.
// A real page.mouse.click() at a coordinate would itself collapse the
// selection before content.js's mouseup handler ever sees it.
async function selectWordAndWaitForPopup(waitMs = 700) {
  await page.evaluate(() => {
    const p = document.getElementById('target');
    const range = document.createRange();
    range.selectNodeContents(p);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    document.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true }));
  });
  await page.waitForTimeout(waitMs);
  return page.evaluate(() => Boolean(document.getElementById('untangle-popup')));
}

// 1. Default OFF: selecting text must not show the popup.
const popupShownByDefault = await selectWordAndWaitForPopup();
if (popupShownByDefault) {
  errors.push('selection popup appeared even though selectionAnalysisEnabled defaults to off');
}

// 2. Turning the setting on (as the settings-tab checkbox would) makes the
// popup appear on the next selection. chrome.storage is only reachable from
// the service worker or a content script's isolated world, not the page's
// main world that Playwright's page.evaluate runs in.
await worker.evaluate(() => chrome.storage.local.set({ selectionAnalysisEnabled: true }));
await page.waitForTimeout(200);
const popupShownWhenEnabled = await selectWordAndWaitForPopup();
if (!popupShownWhenEnabled) {
  errors.push('selection popup did not appear once selectionAnalysisEnabled was turned on');
}

// 3. The popup's quick "turn it off" control disables the setting again and
// closes the popup, without requiring a trip to the settings tab. The click
// itself is dispatched on the page's DOM (shared across JS worlds, so it
// still reaches content.js's isolated-world listener); the resulting storage
// write can only be read back through the service worker.
await page.evaluate(async () => {
  document.querySelector('.era-selection-toggle-off')?.click();
  await new Promise((resolve) => setTimeout(resolve, 300));
});
const toggleOffResult = await worker.evaluate(async () => {
  const stored = await chrome.storage.local.get('selectionAnalysisEnabled');
  return { settingDisabled: stored.selectionAnalysisEnabled === false };
});
toggleOffResult.popupClosed = !(await page.evaluate(() =>
  Boolean(document.getElementById('untangle-popup')),
));
if (!toggleOffResult.popupClosed)
  errors.push('popup did not close after clicking the quick-disable control');
if (!toggleOffResult.settingDisabled)
  errors.push('quick-disable control did not persist selectionAnalysisEnabled=false');

// 4. After the quick-disable, selecting text again must not reopen the popup.
const popupShownAfterDisable = await selectWordAndWaitForPopup();
if (popupShownAfterDisable) {
  errors.push('selection popup reappeared after the quick-disable control turned the setting off');
}

console.log(
  'selection analysis toggle result:',
  JSON.stringify(
    {
      popupShownByDefault,
      popupShownWhenEnabled,
      toggleOffResult,
      popupShownAfterDisable,
    },
    null,
    2,
  ),
);

await context.close();
server.close();

if (errors.length) {
  console.error('\nSELECTION ANALYSIS TOGGLE TEST FAILURES:');
  for (const entry of errors) console.error(' -', entry);
  process.exit(1);
}
console.log('\nSELECTION ANALYSIS TOGGLE TEST PASSED');
