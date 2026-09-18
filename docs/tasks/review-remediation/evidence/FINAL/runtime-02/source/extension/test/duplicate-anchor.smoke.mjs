// Focused regression check: identical sentence text repeated in two places on
// the page (e.g. githubstatus.com's "latest update" summary + timeline entry)
// must get the blue era-page-anchor-block highlight applied to BOTH blocks,
// not just the first match.
import { createRequire } from 'node:module';
import { createServer } from 'node:http';
import { mkdtempSync, readdirSync, existsSync } from 'node:fs';
import { tmpdir, homedir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright-core');

const EXT_DIR = join(dirname(fileURLToPath(import.meta.url)), '..');
const PORT = 18199;

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

const DUPLICATE_SENTENCE =
  'We are continuing to monitor the situation and will provide updates as more information becomes available.';

const PAGE_HTML = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Status Test</title></head>
<body>
<main>
  <section>
    <p id="latest">${DUPLICATE_SENTENCE}</p>
  </section>
  <section>
    <p id="timeline-entry">${DUPLICATE_SENTENCE}</p>
  </section>
</main>
</body></html>`;

const server = createServer((req, res) => {
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
  res.end(PAGE_HTML);
});
await new Promise((resolve) => server.listen(PORT, resolve));

const userDataDir = mkdtempSync(join(tmpdir(), 'era-dup-anchor-'));
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

// publishReadingSession lives in the content script's isolated world, which
// Playwright's page.evaluate cannot reach (it runs in the page's main
// world). Reach it the same way the extension's own background worker does:
// chrome.scripting.executeScript defaults to the isolated world.
const [result] = await worker.evaluate(async (pattern) => {
  const [tab] = await chrome.tabs.query({ url: pattern });
  const [scriptResult] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: async () => {
      const preload = {
        id: 'dup-1',
        page_url: location.href,
        summary: '',
        topics: [],
        sentences: [
          {
            id: 's1',
            index: 0,
            text: 'We are continuing to monitor the situation and will provide updates as more information becomes available.',
            analysis: { translation: 't', grammar: 'g', vocabulary: [] },
          },
        ],
        study_items: [],
      };
      await window.publishReadingSession(preload, { openPanel: false });
      await new Promise((resolve) => setTimeout(resolve, 200));

      const latest = document.getElementById('latest');
      const entry = document.getElementById('timeline-entry');
      return {
        anchorBlockCount: document.querySelectorAll('.era-page-anchor-block').length,
        latestAnchored: latest.classList.contains('era-page-anchor-block'),
        entryAnchored: entry.classList.contains('era-page-anchor-block'),
        latestSentenceId: latest.dataset.eraSentenceId || null,
        entrySentenceId: entry.dataset.eraSentenceId || null,
      };
    },
  });
  return [scriptResult.result];
}, `http://localhost:${PORT}/*`);
console.log('duplicate anchor result:', JSON.stringify(result, null, 2));

if (!result.latestAnchored) errors.push('first occurrence did not get era-page-anchor-block');
if (!result.entryAnchored)
  errors.push('duplicate occurrence did not get era-page-anchor-block (the "not blue" bug)');
if (result.anchorBlockCount !== 2)
  errors.push(`expected 2 anchored blocks, got ${result.anchorBlockCount}`);
if (result.latestSentenceId !== 's1' || result.entrySentenceId !== 's1') {
  errors.push(`expected both blocks linked to sentence s1, got ${JSON.stringify(result)}`);
}

await context.close();
server.close();

if (errors.length) {
  console.error('\nDUPLICATE ANCHOR TEST FAILURES:');
  for (const entry of errors) console.error(' -', entry);
  process.exit(1);
}
console.log('\nDUPLICATE ANCHOR TEST PASSED');
