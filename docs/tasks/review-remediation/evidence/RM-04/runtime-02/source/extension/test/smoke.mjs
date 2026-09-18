// Browser smoke test: loads the extension in Chromium, opens a test article
// page and the side panel document, and fails on any console or page error.
//
// Requirements:
//   npm ci --ignore-scripts
//   extension/node_modules/.bin/playwright install chromium
//
// Usage: npm run test:smoke
/* global activePageUrl:writable, cachedActivePreload, clearCachedActivePreload, refreshPreloadStatus, setSidePanelView, startPreload, syncReadingViewUi, waitForReadingPanelApi:writable */
import { createServer } from 'node:http';
import {
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmdirSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const SOURCE_EXTENSION_DIR = join(dirname(fileURLToPath(import.meta.url)), '..');
const EXT_DIR = process.env.SMOKE_EXTENSION_DIR
  ? resolve(process.env.SMOKE_EXTENSION_DIR)
  : SOURCE_EXTENSION_DIR;
const REPOSITORY_ROOT = join(SOURCE_EXTENSION_DIR, '..');
const ARTIFACT_ROOT = join(REPOSITORY_ROOT, 'output', 'playwright');
mkdirSync(ARTIFACT_ROOT, { recursive: true });
const ARTIFACT_DIR = mkdtempSync(join(ARTIFACT_ROOT, 'smoke-'));
let fixtureBaseUrl;
let preloadEndpointController = null;

function normalizeFixturePageUrl(pageUrl) {
  const normalized = new URL(pageUrl);
  normalized.hash = '';
  return normalized.toString().replace(/\/$/, '');
}

function fixtureUrlPattern(pageUrl) {
  const normalized = new URL(normalizeFixturePageUrl(pageUrl));
  return `${normalized.origin}${normalized.pathname === '/' ? '/*' : `${normalized.pathname}*`}`;
}

function createPreloadRequestGate(matches = () => true) {
  let releaseRequest;
  let signalRequestStarted;
  const released = new Promise((resolve) => {
    releaseRequest = resolve;
  });
  return {
    matches,
    matchCount: 0,
    used: false,
    started: new Promise((resolve) => {
      signalRequestStarted = resolve;
    }),
    async wait() {
      signalRequestStarted();
      await released;
    },
    release() {
      releaseRequest();
    },
  };
}

async function waitForPreloadRequestGate(gate, description, timeoutMs = 5000) {
  let timeout;
  try {
    await Promise.race([
      gate.started,
      new Promise((_, reject) => {
        timeout = setTimeout(
          () => reject(new Error(`Timed out waiting for ${description}`)),
          timeoutMs,
        );
      }),
    ]);
  } finally {
    clearTimeout(timeout);
  }
}

async function getContentPing(worker, pageUrl) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const ping = await worker.evaluate(async (url) => {
      const [tab] = await chrome.tabs.query({ url });
      if (!tab?.id) return null;
      try {
        return { tabId: tab.id, response: await chrome.tabs.sendMessage(tab.id, { type: 'PING' }) };
      } catch {
        return null;
      }
    }, fixtureUrlPattern(pageUrl));
    if (ping?.response?.ok) return ping;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(`Content script did not answer PING for ${pageUrl}`);
}

async function respondToPreloadRequest(req, res) {
  const method = req.method === 'POST' ? 'post' : 'get';
  const controller = preloadEndpointController;
  const countKey = `${method}RequestCount`;
  const count = (controller?.[countKey] || 0) + 1;
  if (controller) controller[countKey] = count;

  const gate = controller?.[`${method}Gate`];
  const matchesGate = Boolean(gate?.matches(req));
  if (matchesGate) gate.matchCount += 1;
  if (gate && !gate.used && matchesGate) {
    gate.used = true;
    await gate.wait();
  }

  const response = controller?.[`${method}Response`];
  const body = typeof response === 'function' ? response(req, count) : response || { ready: false };
  res.writeHead(method === 'post' ? 202 : 200, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(body));
}

function hasForcedColorsFocusFallback(cssFile, selector) {
  const css = readFileSync(join(EXT_DIR, cssFile), 'utf8');
  const forcedColorsBlocks = css.match(/@media \(forced-colors: active\) \{[\s\S]*?\n\}/g) || [];
  return forcedColorsBlocks.some(
    (block) =>
      block.includes(selector) &&
      block.includes('box-shadow: none') &&
      block.includes('outline: 2px solid Highlight') &&
      block.includes('outline-offset: 2px'),
  );
}

const forcedColorsFocusFallbacks = [
  ['panel-ui.css', '.era-select-trigger:focus-visible'],
  ['reading-panel.css', '.era-audio-playback .era-select-trigger:focus-visible'],
].map(([cssFile, selector]) => ({
  cssFile,
  present: hasForcedColorsFocusFallback(cssFile, selector),
}));

const PAGE_HTML = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Test Article</title></head>
<body>
<main><article>
<h1>Extension Smoke Test</h1>
<p>The quick brown fox jumps over the lazy dog. It happens every day.</p>
<p>Reading assistants should not break simple pages like this one.</p>
</article></main>
</body></html>`;

let billingScenario = 'downgrade';
const server = createServer(async (req, res) => {
  if (req.url === '/auth/config') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ provider: 'mock' }));
    return;
  }
  if (req.url === '/auth/login' && req.method === 'POST') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(
      JSON.stringify({
        access_token: 'smoke-access-token',
        user: { id: 'smoke-user', email: 'smoke@example.com', display_name: 'Smoke User' },
      }),
    );
    return;
  }
  if (req.url?.startsWith('/pages/preload')) {
    await respondToPreloadRequest(req, res);
    return;
  }
  if (req.url === '/billing/me') {
    const mismatch =
      billingScenario === 'upgrade'
        ? { plan: 'pro', quota_plan: 'basic' }
        : { plan: 'basic', quota_plan: 'pro' };
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(
      JSON.stringify({
        ...mismatch,
        month: '2026-07',
        articles_used: 7,
        articles_pending: 1,
        articles_limit: 10,
        articles_remaining: 2,
        chats_used: 3,
        chats_pending: 2,
        chats_limit: 10,
        chats_remaining: 5,
        reset_at: '2026-08-01T00:00:00+00:00',
        warning_codes: ['article_quota_approaching'],
        tokens: 987654,
        cost_micro_usd: 123456,
        model: 'hidden-model',
        rate_card_version: 'hidden-rate',
        tokenizer_encoding: 'hidden-tokenizer',
      }),
    );
    return;
  }
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
  res.end(PAGE_HTML);
});
let context;
let userDataDir;
let traceStarted = false;
let interruption;
let artifactPromise;
let cleanupPromise;
const errors = [];
const browserEvents = [];
const artifactErrors = [];

function errorMessage(error) {
  return error instanceof Error ? error.stack || error.message : String(error);
}

function throwIfInterrupted() {
  if (interruption) throw interruption;
}

async function saveFailureArtifacts(failure) {
  try {
    if (process.env.SMOKE_TEST_FORCE_ARTIFACT_WRITE_FAILURE === '1') {
      try {
        writeFileSync(join(ARTIFACT_DIR, 'missing-directory', 'forced.txt'), 'forced failure');
      } catch (error) {
        artifactErrors.push(`forced artifact write: ${errorMessage(error)}`);
      }
    }

    if (context) {
      const pages = context.pages().filter((page) => !page.isClosed());
      for (let index = 0; index < pages.length; index += 1) {
        try {
          await pages[index].screenshot({
            path: join(ARTIFACT_DIR, `page-${index + 1}.png`),
            fullPage: true,
          });
        } catch (error) {
          const message = errorMessage(error);
          if (!interruption || !/Target page, context or browser has been closed/.test(message)) {
            artifactErrors.push(`page-${index + 1} screenshot: ${message}`);
          }
        }
      }
      if (traceStarted) {
        try {
          await context.tracing.stop({ path: join(ARTIFACT_DIR, 'trace.zip') });
          traceStarted = false;
        } catch (error) {
          artifactErrors.push(`trace: ${errorMessage(error)}`);
        }
      }
    }
  } catch (error) {
    artifactErrors.push(`artifact capture: ${errorMessage(error)}`);
  }

  const report = {
    failure: errorMessage(failure),
    assertions: errors,
    browserEvents,
    artifactErrors,
  };
  try {
    writeFileSync(join(ARTIFACT_DIR, 'errors.json'), `${JSON.stringify(report, null, 2)}\n`);
  } catch (error) {
    artifactErrors.push(`error report: ${errorMessage(error)}`);
    console.error(JSON.stringify(report, null, 2));
  }
  for (const artifactError of artifactErrors) {
    console.error(`Artifact diagnostic: ${artifactError}`);
  }
}

async function cleanup() {
  const cleanupErrors = [];
  if (context) {
    if (traceStarted) {
      try {
        await context.tracing.stop();
      } catch (error) {
        cleanupErrors.push(`stop trace: ${errorMessage(error)}`);
      }
      traceStarted = false;
    }
    try {
      await context.close();
    } catch (error) {
      cleanupErrors.push(`close browser context: ${errorMessage(error)}`);
    }
    context = undefined;
  }
  if (server.listening) {
    try {
      await new Promise((resolve, reject) => {
        server.close((error) => (error ? reject(error) : resolve()));
      });
    } catch (error) {
      cleanupErrors.push(`close fixture server: ${errorMessage(error)}`);
    }
  }
  if (userDataDir) {
    try {
      rmSync(userDataDir, { recursive: true, force: true });
    } catch (error) {
      cleanupErrors.push(`remove temporary profile: ${errorMessage(error)}`);
    }
    userDataDir = undefined;
  }
  return cleanupErrors;
}

function saveFailureArtifactsOnce(failure) {
  artifactPromise ??= saveFailureArtifacts(failure);
  return artifactPromise;
}

function cleanupOnce() {
  cleanupPromise ??= cleanup();
  return cleanupPromise;
}

function removeSuccessfulRunArtifacts() {
  rmSync(ARTIFACT_DIR, { recursive: true, force: true });
  try {
    if (readdirSync(ARTIFACT_ROOT).length === 0) rmdirSync(ARTIFACT_ROOT);
  } catch (error) {
    if (!['ENOENT', 'ENOTEMPTY'].includes(error?.code)) {
      console.error(`Artifact directory cleanup diagnostic: ${errorMessage(error)}`);
    }
  }
}

class InterruptionError extends Error {
  constructor(signal, exitCode) {
    super(`Smoke test interrupted by ${signal}`);
    this.name = 'InterruptionError';
    this.signal = signal;
    this.exitCode = exitCode;
  }
}

let resolveSignal;
const signalPromise = new Promise((resolve) => {
  resolveSignal = resolve;
});
const signalHandlers = new Map();
for (const [signal, exitCode] of [
  ['SIGHUP', 129],
  ['SIGINT', 130],
  ['SIGTERM', 143],
]) {
  const handler = () => {
    if (interruption) return;
    interruption = new InterruptionError(signal, exitCode);
    resolveSignal(interruption);
  };
  signalHandlers.set(signal, handler);
  process.on(signal, handler);
}

async function runSmokeTest() {
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      server.off('error', reject);
      resolve();
    });
  });
  const address = server.address();
  if (!address || typeof address === 'string') {
    throw new Error('Fixture server did not expose an assigned TCP port');
  }
  fixtureBaseUrl = `http://127.0.0.1:${address.port}`;
  throwIfInterrupted();

  userDataDir = mkdtempSync(join(tmpdir(), 'era-smoke-'));
  for (const fallback of forcedColorsFocusFallbacks) {
    if (!fallback.present) {
      errors.push(`forced-colors focus fallback missing in ${fallback.cssFile}`);
    }
  }

  context = await chromium.launchPersistentContext(userDataDir, {
    channel: 'chromium',
    headless: true,
    handleSIGHUP: false,
    handleSIGINT: false,
    handleSIGTERM: false,
    args: [
      `--disable-extensions-except=${EXT_DIR}`,
      `--load-extension=${EXT_DIR}`,
      '--no-first-run',
    ],
  });
  throwIfInterrupted();
  await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
  traceStarted = true;
  throwIfInterrupted();

  function watch(page, label) {
    page.on('console', (message) => {
      if (message.type() === 'error') {
        browserEvents.push({ page: label, type: 'console', message: message.text() });
        errors.push(`[${label}] console.error: ${message.text()}`);
      }
    });
    page.on('pageerror', (error) => {
      browserEvents.push({ page: label, type: 'pageerror', message: error.message });
      errors.push(`[${label}] pageerror: ${error.message}`);
    });
  }

  throwIfInterrupted();
  // 1. Background service worker must start cleanly.
  let [worker] = context.serviceWorkers();
  if (!worker) {
    worker = await context.waitForEvent('serviceworker', { timeout: 10000 });
  }
  const extensionId = new URL(worker.url()).host;
  console.log('service worker:', worker.url());
  const contractState = await worker.evaluate(() => ({
    operationIds: Object.keys(globalThis.UntangleApiContract?.operations || {}),
    namespaceFrozen: Object.isFrozen(globalThis.UntangleApiContract),
    operationsFrozen: Object.isFrozen(globalThis.UntangleApiContract?.operations),
    runtimeLoaded: typeof globalThis.UntangleApiContractRuntime?.inspectResponse === 'function',
  }));
  console.log('API contract state:', JSON.stringify(contractState));
  if (contractState.operationIds.length !== 11) {
    errors.push(
      `expected 11 generated consumer operations, got ${contractState.operationIds.length}`,
    );
  }
  if (
    !contractState.namespaceFrozen ||
    !contractState.operationsFrozen ||
    !contractState.runtimeLoaded
  ) {
    errors.push(`classic API contract did not load immutably: ${JSON.stringify(contractState)}`);
  }

  await worker.evaluate((apiBaseUrl) => chrome.storage.local.set({ apiBaseUrl }), fixtureBaseUrl);

  throwIfInterrupted();
  // 2. Article page: content scripts (settings.js, shared.js, content.js) load.
  const page = await context.newPage();
  watch(page, 'article');
  await page.goto(`${fixtureBaseUrl}/`);
  await page.waitForTimeout(1500);

  const probe = await worker.evaluate(async (pattern) => {
    const [tab] = await chrome.tabs.query({ url: pattern });
    if (!tab?.id) return { error: 'tab not found' };
    try {
      const response = await chrome.tabs.sendMessage(tab.id, { type: 'PING' });
      return { ping: Boolean(response?.ok) };
    } catch (error) {
      return { error: String(error) };
    }
  }, `${fixtureBaseUrl}/*`);
  console.log('content script PING:', JSON.stringify(probe));
  if (!probe.ping) errors.push(`content script did not answer PING: ${JSON.stringify(probe)}`);

  // Re-injection safety: the manifest and the background programmatic path can
  // both inject the bundle into the same page. Force a second injection and
  // confirm it does not throw "already declared" (captured as a pageerror in
  // `errors`) and the content script still answers PING.
  // Release host permissions rely on activeTab for programmatic injection.
  // Startup-only ZIP validation has no real user action granting that access.
  if (process.env.SMOKE_STARTUP_ONLY !== '1') {
    const reinjectProbe = await worker.evaluate(async (pattern) => {
      const [tab] = await chrome.tabs.query({ url: pattern });
      if (!tab?.id) return { error: 'tab not found' };
      try {
        await chrome.scripting.executeScript({
          target: { tabId: tab.id },
          files: ['settings.js', 'i18n.js', 'shared.js', 'content.js'],
        });
        const response = await chrome.tabs.sendMessage(tab.id, { type: 'PING' });
        return { ping: Boolean(response?.ok) };
      } catch (error) {
        return { error: String(error) };
      }
    }, `${fixtureBaseUrl}/*`);
    console.log('content script re-injection PING:', JSON.stringify(reinjectProbe));
    if (!reinjectProbe.ping) {
      errors.push(`content script did not survive re-injection: ${JSON.stringify(reinjectProbe)}`);
    }
  }
  await page.waitForTimeout(200);

  // Selecting page text must not throw (analysis mode is off -> early return).
  await page.evaluate(() => {
    const paragraph = document.querySelector('article p');
    const range = document.createRange();
    range.selectNodeContents(paragraph);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  });
  await page.mouse.click(200, 200, { clickCount: 1 });
  await page.waitForTimeout(600);

  throwIfInterrupted();
  // 3. Side panel document: settings.js, shared.js, reading-panel.js, panel-ui.js.
  const panel = await context.newPage();
  watch(panel, 'sidepanel');
  await panel.goto(`chrome-extension://${extensionId}/sidepanel.html`);
  await panel.waitForTimeout(1500);

  const panelState = await panel.evaluate(() => ({
    hasSettingsButton: Boolean(document.getElementById('settingsViewButton')),
    hasReadingRoot: Boolean(document.getElementById('readingPanelRoot')),
    readingPanelApi: typeof window.ReadingPanel?.mountReadingPanel === 'function',
    sharedLoaded: typeof window.renderContextChat === 'function',
    presetsPopulated: document.getElementById('learnerLevelPreset')?.options.length > 0,
    languagesPopulated:
      document.getElementById('targetLanguageSelect')?.options.length > 1 &&
      document.getElementById('nativeLanguageSelect')?.options.length > 0,
    settingsSelects: ['targetLanguageSelect', 'nativeLanguageSelect', 'learnerLevelPreset'].map(
      (id) => {
        const select = document.getElementById(id);
        return {
          id,
          eraSelect: select?.classList.contains('era-select') === true,
          labelText: select?.closest('label')?.querySelector('span')?.textContent.trim() || '',
          optionValues: [...(select?.options || [])].map((option) => option.value),
        };
      },
    ),
    mockSignInAvailable: [...document.querySelectorAll('#signInRoot button')].some(
      (button) => button.textContent.includes('Sign in with an account') && !button.disabled,
    ),
    featuresLocked: document.getElementById('targetLanguageSelect')?.disabled === true,
    // The word-book tab exists and is gated behind sign-in.
    vocabBookTabDisabled: document.getElementById('vocabBookViewButton')?.disabled === true,
    // Billing section renders but exposes no actions while logged out.
    billingSectionPresent: Boolean(document.getElementById('billingSummary')),
    billingActionsHidden:
      document.getElementById('billingUpgradeProButton')?.hidden === true &&
      document.getElementById('billingPortalButton')?.hidden === true,
  }));
  console.log('side panel state:', JSON.stringify(panelState, null, 2));
  for (const [key, value] of Object.entries(panelState)) {
    if (!value) errors.push(`side panel check failed: ${key}`);
  }
  for (const select of panelState.settingsSelects) {
    if (!select.eraSelect) errors.push(`settings select is missing era-select: ${select.id}`);
    if (!select.labelText) errors.push(`settings select lost its label: ${select.id}`);
  }
  const settingsOptions = Object.fromEntries(
    panelState.settingsSelects.map((select) => [select.id, select.optionValues]),
  );
  if (
    !settingsOptions.targetLanguageSelect?.includes('auto') ||
    !settingsOptions.targetLanguageSelect?.includes('en')
  ) {
    errors.push('target language select is missing expected auto/en options');
  }
  if (
    !settingsOptions.nativeLanguageSelect?.includes('ja') ||
    !settingsOptions.nativeLanguageSelect?.includes('en')
  ) {
    errors.push('native language select is missing expected ja/en options');
  }
  if (!settingsOptions.learnerLevelPreset?.length) {
    errors.push('learner level select is missing expected options');
  }

  if (process.env.SMOKE_STARTUP_ONLY === '1') {
    const fatalErrors = errors.filter(
      (error) => !/net::|favicon|ERR_CONNECTION|Failed to load resource/.test(error),
    );
    if (fatalErrors.length) throw new Error(fatalErrors.join('\n'));
    return;
  }

  throwIfInterrupted();
  // 3. Fully custom static dropdowns retain their native source select for
  // existing listeners, while the visible trigger and listbox own interaction.
  await panel.evaluate(
    (apiBaseUrl) => chrome.storage.local.set({ apiBaseUrl }),
    `${fixtureBaseUrl}`,
  );
  await panel.getByRole('button', { name: 'Sign in with an account' }).click();
  await panel.getByRole('button', { name: 'Use another account' }).click();
  await panel.getByRole('textbox', { name: 'Email', exact: true }).fill('smoke@example.com');
  await panel.getByRole('button', { name: 'Continue', exact: true }).click();
  await panel.waitForFunction(
    () => document.getElementById('targetLanguageSelect')?.disabled === false,
  );
  await panel.waitForFunction(() =>
    document.getElementById('billingSummary')?.textContent.includes('2'),
  );

  const quotaState = await panel.evaluate(() => {
    const summary = document.getElementById('billingSummary')?.textContent || '';
    const warning = document.getElementById('billingWarning');
    const completeText = document.querySelector('.billing-panel')?.textContent || '';
    return {
      summary,
      warningText: warning?.textContent || '',
      warningRole: warning?.getAttribute('role'),
      warningLive: warning?.getAttribute('aria-live'),
      articlesExact: summary.includes('記事: 使用 7 + 処理中 1・残り 2'),
      chatsExact: summary.includes('チャット: 使用 3 + 処理中 2・残り 5'),
      resetExact: summary.includes('2026年8月1日 にリセット'),
      hiddenFieldsAbsent: !/987654|123456|hidden-model|hidden-rate|hidden-tokenizer/.test(
        completeText,
      ),
      currentPlanLabelExact: summary.includes('現在の契約: basic プラン'),
      quotaPlanLabelExact: summary.includes('今月の利用枠: pro プラン'),
      deferredDowngradeExact: summary.includes('リセットまで維持'),
      summaryLive: document.getElementById('billingSummary')?.getAttribute('aria-live'),
      summaryAtomic: document.getElementById('billingSummary')?.getAttribute('aria-atomic'),
    };
  });
  console.log('quota state:', JSON.stringify(quotaState, null, 2));
  for (const key of [
    'articlesExact',
    'chatsExact',
    'resetExact',
    'hiddenFieldsAbsent',
    'currentPlanLabelExact',
    'quotaPlanLabelExact',
    'deferredDowngradeExact',
  ]) {
    if (!quotaState[key])
      errors.push(`quota UI check failed: ${key}: ${JSON.stringify(quotaState)}`);
  }
  if (quotaState.summaryLive !== 'polite' || quotaState.summaryAtomic !== 'true') {
    errors.push(`quota summary accessibility contract failed: ${JSON.stringify(quotaState)}`);
  }

  billingScenario = 'upgrade';
  await panel.evaluate(() => refreshBillingInfo());
  const upgradeQuotaState = await panel.evaluate(() => {
    const summary = document.getElementById('billingSummary')?.textContent || '';
    return {
      summary,
      currentPlanLabelExact: summary.includes('現在の契約: pro プラン'),
      quotaPlanLabelExact: summary.includes('現在の利用枠: basic プラン'),
      pendingRatchetExact: summary.includes('次回の従量処理時に反映'),
      noRefreshPromise: !summary.includes('または更新'),
      noDowngradeCopy: !summary.includes('リセットまで維持'),
    };
  });
  console.log('upgrade quota state:', JSON.stringify(upgradeQuotaState, null, 2));
  for (const key of [
    'currentPlanLabelExact',
    'quotaPlanLabelExact',
    'pendingRatchetExact',
    'noRefreshPromise',
    'noDowngradeCopy',
  ]) {
    if (!upgradeQuotaState[key]) {
      errors.push(`upgrade quota UI check failed: ${key}: ${JSON.stringify(upgradeQuotaState)}`);
    }
  }
  if (!quotaState.warningText) errors.push('quota warning was not visible');
  if (quotaState.warningRole !== 'status' || quotaState.warningLive !== 'polite') {
    errors.push(`quota warning accessibility contract failed: ${JSON.stringify(quotaState)}`);
  }

  // RM-03: a stale worker envelope must not mutate a live content document,
  // and a panel must not mount account A data after account B replaces it.
  const rm03Isolation = await worker.evaluate(async (pattern) => {
    const [tab] = await chrome.tabs.query({ url: pattern });
    const scope = await chrome.storage.local.get('authSession');
    const authScope = {
      userId: scope.authSession.user.id,
      loginId: scope.authSession.loginId,
    };
    const preload = {
      id: 'rm03-private-preload',
      page_url: tab.url.replace(/\/$/, ''),
      sentences: [
        { id: 'rm03-sentence', index: 0, text: 'Private reading sentence.', analysis: {} },
      ],
    };
    const staleResponse = await chrome.tabs.sendMessage(tab.id, {
      type: 'SHOW_SENTENCE_PANEL',
      payload: {
        preload,
        pageUrl: preload.page_url,
        authScope,
        documentNonce: 'stale-smoke-document',
      },
    });
    const [contentState] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => Boolean(globalThis.activePreload),
    });
    return { staleResponse, contentMutated: contentState.result };
  }, `${fixtureBaseUrl}/*`);
  if (rm03Isolation.staleResponse?.ok || rm03Isolation.contentMutated) {
    errors.push(`RM03 stale-document delivery mutated content: ${JSON.stringify(rm03Isolation)}`);
  }

  const rm03PanelSwitch = await panel.evaluate(async (pageUrl) => {
    const accountA = {
      accessToken: 'account-a-token',
      user: { id: 'account-a' },
      loginId: 'account-a-login',
    };
    const preload = {
      id: 'rm03-panel-preload',
      page_url: pageUrl,
      sentences: [
        { id: 'rm03-panel-sentence', index: 0, text: 'Account A sentence.', analysis: {} },
      ],
    };
    await chrome.storage.local.set({ authSession: accountA });
    const scopeA = await getAuthScope();
    await setReadingSession(
      {
        pageUrl,
        pageTitle: 'Account A article',
        preload,
        domLinkStatus: {},
        ui: {},
        updatedAt: Date.now(),
      },
      scopeA,
    );
    await chrome.storage.local.set({
      authSession: {
        accessToken: 'account-b-token',
        user: { id: 'account-b' },
        loginId: 'account-b-login',
      },
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    const mounted = await syncReadingViewUi({
      preload,
      pageTitle: 'Account A article',
      authScope: scopeA,
    });
    return {
      mounted,
      cached: Boolean(cachedActivePreload),
      visible: document.getElementById('readingPanelRoot')?.hidden === false,
    };
  }, `${fixtureBaseUrl}`);
  if (rm03PanelSwitch.mounted || rm03PanelSwitch.cached || rm03PanelSwitch.visible) {
    errors.push(`RM03 account switch mounted stale panel data: ${JSON.stringify(rm03PanelSwitch)}`);
  }
  await worker.evaluate(async () => {
    const storage = await chrome.storage.local.get(null);
    const privateSessionKeys = Object.keys(storage).filter((key) =>
      key.startsWith('eraReadingSession:'),
    );
    if (privateSessionKeys.length) await chrome.storage.local.remove(privateSessionKeys);
  });

  const readyPreload = (id, pageUrl) => ({
    ready: true,
    preload: {
      id,
      page_url: pageUrl,
      sentences: [
        { id: `${id}-sentence`, index: 0, text: 'Private reading sentence.', analysis: {} },
      ],
    },
  });

  // RM-03: hold the real worker POST and poll requests. A navigation to a
  // different origin must prevent the captured document from receiving data.
  const originalArticleUrl = normalizeFixturePageUrl(page.url());
  const crossOriginArticleUrl = normalizeFixturePageUrl(
    originalArticleUrl.replace('127.0.0.1', 'localhost'),
  );
  const originalContent = await getContentPing(worker, originalArticleUrl);
  const navigationPostGate = createPreloadRequestGate();
  const navigationPollGate = createPreloadRequestGate(
    (request) =>
      normalizeFixturePageUrl(new URL(request.url, fixtureBaseUrl).searchParams.get('page_url')) ===
      originalArticleUrl,
  );
  preloadEndpointController = {
    postGate: navigationPostGate,
    getGate: navigationPollGate,
    postResponse: { status: 'processing' },
    getResponse: readyPreload('rm03-navigation-preload', originalArticleUrl),
  };
  let navigationCompletion;
  let navigationState;
  try {
    navigationCompletion = panel.evaluate(
      (tabId) => chrome.runtime.sendMessage({ type: 'START_PRELOAD', payload: { tabId } }),
      originalContent.tabId,
    );
    await waitForPreloadRequestGate(navigationPostGate, 'RM03 worker submission');
    await page.goto(crossOriginArticleUrl);
    const crossOriginContent = await getContentPing(worker, crossOriginArticleUrl);
    navigationPostGate.release();
    await waitForPreloadRequestGate(navigationPollGate, 'RM03 worker poll');
    navigationPollGate.release();
    await navigationCompletion;
    navigationState = await worker.evaluate(async () => {
      const storage = await chrome.storage.local.get(null);
      return {
        privateSessions: Object.keys(storage).filter((key) => key.startsWith('eraReadingSession:')),
      };
    });
    navigationState.documentReplaced =
      crossOriginContent.response.documentNonce !== originalContent.response.documentNonce;
    navigationState.postRequests = preloadEndpointController.postRequestCount || 0;
    navigationState.pollRequests = navigationPollGate.matchCount;
  } finally {
    navigationPostGate.release();
    navigationPollGate.release();
    preloadEndpointController = null;
    await navigationCompletion?.catch(() => {});
  }
  if (
    !navigationState.documentReplaced ||
    navigationState.privateSessions.length ||
    navigationState.postRequests !== 1 ||
    navigationState.pollRequests < 1
  ) {
    errors.push(
      `RM03 cross-origin completion leaked private data: ${JSON.stringify(navigationState)}`,
    );
  }

  // RM-03: account replacement during a real worker poll must prevent both
  // delivery and scoped persistence of the original account's response.
  const accountA = {
    accessToken: 'rm03-account-a-token',
    user: { id: 'rm03-account-a' },
    loginId: 'rm03-account-a-login',
  };
  const accountB = {
    accessToken: 'rm03-account-b-token',
    user: { id: 'rm03-account-b' },
    loginId: 'rm03-account-b-login',
  };
  await worker.evaluate((session) => chrome.storage.local.set({ authSession: session }), accountA);
  await panel.waitForTimeout(0);
  const logoutPostGate = createPreloadRequestGate();
  const logoutPollGate = createPreloadRequestGate(
    (request) =>
      normalizeFixturePageUrl(new URL(request.url, fixtureBaseUrl).searchParams.get('page_url')) ===
      crossOriginArticleUrl,
  );
  preloadEndpointController = {
    postGate: logoutPostGate,
    getGate: logoutPollGate,
    postResponse: { status: 'processing' },
    getResponse: readyPreload('rm03-logout-preload', crossOriginArticleUrl),
  };
  let logoutCompletion;
  let logoutState;
  try {
    const crossOriginContent = await getContentPing(worker, crossOriginArticleUrl);
    logoutCompletion = panel.evaluate(
      (tabId) => chrome.runtime.sendMessage({ type: 'START_PRELOAD', payload: { tabId } }),
      crossOriginContent.tabId,
    );
    await waitForPreloadRequestGate(logoutPostGate, 'RM03 logout submission');
    logoutPostGate.release();
    await waitForPreloadRequestGate(logoutPollGate, 'RM03 logout poll');
    await worker.evaluate(() => chrome.storage.local.remove('authSession'));
    await worker.evaluate(
      (session) => chrome.storage.local.set({ authSession: session }),
      accountB,
    );
    logoutPollGate.release();
    await logoutCompletion;
    logoutState = await worker.evaluate(async () => {
      const storage = await chrome.storage.local.get(null);
      return {
        accountASessions: Object.keys(storage).filter((key) => key.includes('rm03-account-a')),
      };
    });
    logoutState.postRequests = preloadEndpointController.postRequestCount || 0;
    logoutState.pollRequests = logoutPollGate.matchCount;
  } finally {
    logoutPostGate.release();
    logoutPollGate.release();
    preloadEndpointController = null;
    await logoutCompletion?.catch(() => {});
  }
  if (
    logoutState.accountASessions.length ||
    logoutState.postRequests !== 1 ||
    logoutState.pollRequests < 1
  ) {
    errors.push(`RM03 account switch completed account A work: ${JSON.stringify(logoutState)}`);
  }

  // RM-03: a replacement document at the same URL must reject the real
  // worker restore response that began against the older document nonce.
  const restoreGate = createPreloadRequestGate(
    (request) =>
      normalizeFixturePageUrl(new URL(request.url, fixtureBaseUrl).searchParams.get('page_url')) ===
      crossOriginArticleUrl,
  );
  preloadEndpointController = {
    getGate: restoreGate,
    getResponse: (_request, count) =>
      count === 1 ? readyPreload('rm03-reload-preload', crossOriginArticleUrl) : { ready: false },
  };
  let restoreCompletion;
  let restoreResult;
  let documentReplaced;
  try {
    const originalContent = await getContentPing(worker, crossOriginArticleUrl);
    restoreCompletion = panel.evaluate(
      ({ tabId, pageUrl }) =>
        chrome.runtime.sendMessage({
          type: 'RESTORE_PAGE_READING_SESSION',
          payload: { tabId, pageUrl },
        }),
      { tabId: originalContent.tabId, pageUrl: crossOriginArticleUrl },
    );
    await waitForPreloadRequestGate(restoreGate, 'RM03 restore status');
    await page.reload();
    const replacementContent = await getContentPing(worker, crossOriginArticleUrl);
    documentReplaced =
      replacementContent.response.documentNonce !== originalContent.response.documentNonce;
    restoreGate.release();
    restoreResult = await restoreCompletion;
  } finally {
    restoreGate.release();
    preloadEndpointController = null;
    await restoreCompletion?.catch(() => {});
  }
  if (!documentReplaced || restoreResult?.restored) {
    errors.push(
      `RM03 same-URL document reload accepted stale restore data: ${JSON.stringify({ restoreResult, documentReplaced })}`,
    );
  }

  // RM-03: hold GET_PRELOAD_STATUS while panel hydration is in progress, then
  // replace its account. No original-account record or panel may be mounted.
  await worker.evaluate((session) => chrome.storage.local.set({ authSession: session }), accountA);
  await panel.waitForTimeout(0);
  const panelStatusGate = createPreloadRequestGate(
    (request) =>
      normalizeFixturePageUrl(new URL(request.url, fixtureBaseUrl).searchParams.get('page_url')) ===
      crossOriginArticleUrl,
  );
  preloadEndpointController = {
    getGate: panelStatusGate,
    getResponse: readyPreload('rm03-panel-status-preload', crossOriginArticleUrl),
  };
  let panelHydration;
  let panelMounted;
  let panelRaceState;
  try {
    panelHydration = panel.evaluate(async (pageUrl) => {
      clearCachedActivePreload();
      if (activePageUrl !== pageUrl) activePageUrl = pageUrl;
      window.ReadingPanel?.clearReadingPanel();
      return syncReadingViewUi({ switchToReading: true, pageTitle: 'Account A article' });
    }, crossOriginArticleUrl);
    await waitForPreloadRequestGate(panelStatusGate, 'RM03 panel status');
    await worker.evaluate(
      (session) => chrome.storage.local.set({ authSession: session }),
      accountB,
    );
    panelStatusGate.release();
    panelMounted = await panelHydration;
    panelRaceState = await panel.evaluate(() => ({
      cached: Boolean(cachedActivePreload),
      visible: document.getElementById('readingPanelRoot')?.hidden === false,
    }));
  } finally {
    panelStatusGate.release();
    preloadEndpointController = null;
    await panelHydration?.catch(() => {});
  }
  if (panelMounted || panelRaceState.cached || panelRaceState.visible) {
    errors.push(
      `RM03 delayed panel status mounted account A data for account B: ${JSON.stringify({ panelMounted, panelRaceState })}`,
    );
  }

  await worker.evaluate((session) => chrome.storage.local.set({ authSession: session }), accountA);
  let panelApiCompletion;
  let panelApiResult;
  try {
    panelApiCompletion = panel.evaluate(async (pageUrl) => {
      const authScope = await getAuthScope();
      const originalWait = waitForReadingPanelApi;
      const originalMount = window.ReadingPanel.mountReadingPanel;
      let releaseApi;
      let mountCalls = 0;
      const apiBlocked = new Promise((resolve) => {
        releaseApi = resolve;
      });
      window.__rm03ReleaseApi = () => releaseApi();
      window.__rm03ApiBlocked = false;
      waitForReadingPanelApi = async (...args) => {
        window.__rm03ApiBlocked = true;
        await apiBlocked;
        return originalWait(...args);
      };
      window.ReadingPanel.mountReadingPanel = (...args) => {
        mountCalls += 1;
        return originalMount(...args);
      };
      try {
        const mounted = await syncReadingViewUi({
          preload: {
            id: 'rm03-api-readiness-preload',
            page_url: pageUrl,
            sentences: [
              { id: 'rm03-api-sentence', index: 0, text: 'Private sentence.', analysis: {} },
            ],
          },
          authScope,
        });
        const stored = await chrome.storage.local.get(null);
        return {
          mounted,
          mountCalls,
          staleRecord: Object.values(stored).some(
            (value) => value?.preload?.id === 'rm03-api-readiness-preload',
          ),
        };
      } finally {
        waitForReadingPanelApi = originalWait;
        window.ReadingPanel.mountReadingPanel = originalMount;
        delete window.__rm03ReleaseApi;
        delete window.__rm03ApiBlocked;
      }
    }, crossOriginArticleUrl);
    await panel.waitForFunction(() => window.__rm03ApiBlocked === true, null, { timeout: 5000 });
    await worker.evaluate(
      (session) => chrome.storage.local.set({ authSession: session }),
      accountB,
    );
    await panel.evaluate(() => window.__rm03ReleaseApi?.());
    panelApiResult = await panelApiCompletion;
  } finally {
    await panel.evaluate(() => window.__rm03ReleaseApi?.()).catch(() => {});
    await panelApiCompletion?.catch(() => {});
  }
  if (panelApiResult.mounted || panelApiResult.mountCalls !== 0 || panelApiResult.staleRecord) {
    errors.push(
      `RM03 panel API readiness accepted stale account data: ${JSON.stringify(panelApiResult)}`,
    );
  }

  const runPanelLearnerProfileRace = async (flow) => {
    await worker.evaluate(
      (session) => chrome.storage.local.set({ authSession: session }),
      accountA,
    );
    await panel.waitForTimeout(0);
    let completion;
    try {
      completion = panel.evaluate(
        async ({ pageUrl, flowName }) => {
          const originalGet = chrome.storage.local.get.bind(chrome.storage.local);
          const originalSendMessage = chrome.runtime.sendMessage.bind(chrome.runtime);
          let releaseProfileRead;
          const profileReadBlocked = new Promise((resolve) => {
            releaseProfileRead = resolve;
          });
          let profileReadStarted = false;
          window.__rm03ReleaseProfileRead = () => releaseProfileRead();
          window.__rm03ProfileReadBlocked = false;
          chrome.storage.local.get = async (keys) => {
            const requestsLearnerProfile =
              keys === 'learnerProfile' || (Array.isArray(keys) && keys.includes('learnerProfile'));
            if (requestsLearnerProfile && !profileReadStarted) {
              profileReadStarted = true;
              window.__rm03ProfileReadBlocked = true;
              await profileReadBlocked;
            }
            return originalGet(keys);
          };
          chrome.runtime.sendMessage = async (message, ...args) => {
            if (message?.type === 'GET_PRELOAD_STATUS') {
              return {
                ok: true,
                status: {
                  ready: true,
                  preload: {
                    id: `rm03-${flowName}-preload`,
                    page_url: pageUrl,
                    sentences: [
                      {
                        id: `rm03-${flowName}-sentence`,
                        index: 0,
                        text: 'Private reading sentence.',
                        analysis: {},
                      },
                    ],
                  },
                },
              };
            }
            return originalSendMessage(message, ...args);
          };

          try {
            const result =
              flowName === 'existing'
                ? await startPreload({ tab: { id: 1, url: pageUrl, title: 'Account A article' } })
                : await refreshPreloadStatus();
            return {
              result,
              cached: Boolean(cachedActivePreload),
              visible: document.getElementById('readingPanelRoot')?.hidden === false,
              confirmVisible: document.getElementById('preloadConfirm')?.hidden === false,
            };
          } finally {
            chrome.storage.local.get = originalGet;
            chrome.runtime.sendMessage = originalSendMessage;
            delete window.__rm03ReleaseProfileRead;
            delete window.__rm03ProfileReadBlocked;
          }
        },
        { pageUrl: crossOriginArticleUrl, flowName: flow },
      );
      await panel.waitForFunction(() => window.__rm03ProfileReadBlocked === true, null, {
        timeout: 5000,
      });
      await worker.evaluate(
        (session) => chrome.storage.local.set({ authSession: session }),
        accountB,
      );
      await panel.evaluate(() => window.__rm03ReleaseProfileRead?.());
      return await completion;
    } finally {
      await panel.evaluate(() => window.__rm03ReleaseProfileRead?.()).catch(() => {});
      await completion?.catch(() => {});
    }
  };

  const existingPreloadRace = await runPanelLearnerProfileRace('existing');
  const refreshPreloadRace = await runPanelLearnerProfileRace('refresh');
  await worker.evaluate((session) => chrome.storage.local.set({ authSession: session }), accountA);
  await panel.waitForTimeout(0);
  let panelMountCompletion;
  let replacementSessionStored;
  try {
    panelMountCompletion = panel.evaluate(async (pageUrl) => {
      const authScope = await getAuthScope();
      const originalMount = window.ReadingPanel.mountReadingPanel;
      let releaseMount;
      const mountBlocked = new Promise((resolve) => {
        releaseMount = resolve;
      });
      window.__rm03ReleaseMount = () => releaseMount();
      window.__rm03MountBlocked = false;
      window.ReadingPanel.mountReadingPanel = async (session) => {
        window.__rm03MountBlocked = true;
        await mountBlocked;
        return originalMount(session);
      };
      try {
        return await syncReadingViewUi({
          preload: {
            id: 'rm03-delayed-mount-preload',
            page_url: pageUrl,
            sentences: [
              {
                id: 'rm03-delayed-mount-sentence',
                index: 0,
                text: 'Private reading sentence.',
                analysis: {},
              },
            ],
          },
          pageTitle: 'Account A article',
          authScope,
        });
      } finally {
        window.ReadingPanel.mountReadingPanel = originalMount;
        delete window.__rm03ReleaseMount;
        delete window.__rm03MountBlocked;
      }
    }, crossOriginArticleUrl);
    await panel.waitForFunction(() => window.__rm03MountBlocked === true, null, { timeout: 5000 });
    await worker.evaluate(
      (session) => chrome.storage.local.set({ authSession: session }),
      accountB,
    );
    replacementSessionStored = await panel.evaluate(async (pageUrl) => {
      const authScope = await getAuthScope();
      return setReadingSession(
        {
          pageUrl,
          pageTitle: 'Account B article',
          preload: {
            id: 'rm03-replacement-account-preload',
            page_url: pageUrl,
            sentences: [
              {
                id: 'rm03-replacement-account-sentence',
                index: 0,
                text: 'Replacement account sentence.',
                analysis: {},
              },
            ],
          },
          domLinkStatus: {},
          ui: {},
          updatedAt: Date.now(),
        },
        authScope,
      );
    }, crossOriginArticleUrl);
    await panel.evaluate(() => window.__rm03ReleaseMount?.());
    const mounted = await panelMountCompletion;
    if (mounted)
      errors.push('RM03 delayed mount rendered account A data after account B signed in');
  } finally {
    await panel.evaluate(() => window.__rm03ReleaseMount?.()).catch(() => {});
    await panelMountCompletion?.catch(() => {});
  }
  const mountRaceStorage = await worker.evaluate(() => chrome.storage.local.get(null));
  if (
    !replacementSessionStored ||
    !Object.values(mountRaceStorage).some(
      (value) => value?.preload?.id === 'rm03-replacement-account-preload',
    )
  ) {
    errors.push('RM03 account-switch cleanup removed the replacement account session');
  }
  const learnerProfileRaceStorage = await worker.evaluate(() => chrome.storage.local.get(null));
  if (
    existingPreloadRace.cached ||
    existingPreloadRace.visible ||
    existingPreloadRace.confirmVisible ||
    refreshPreloadRace.cached ||
    refreshPreloadRace.visible ||
    Object.keys(learnerProfileRaceStorage).some((key) => key.includes('rm03-account-a'))
  ) {
    errors.push(
      `RM03 learner-profile race relabeled account A data: ${JSON.stringify({ existingPreloadRace, refreshPreloadRace })}`,
    );
  }
  await page.goto(originalArticleUrl);
  await getContentPing(worker, originalArticleUrl);

  // RM-04: independent article contexts receive their own scoped state. An
  // update for article B must not reset article A's anchors or selection, and
  // the panel focused on A must not write back B's change.
  const secondArticle = await context.newPage();
  watch(secondArticle, 'rm04-second-article');
  const secondArticleUrl = `${fixtureBaseUrl}/rm04-independent`;
  let firstPanel;
  let secondPanel;
  let rm04SessionKeys = [];
  try {
    await secondArticle.goto(secondArticleUrl);
    const [firstContent, secondContent] = await Promise.all([
      getContentPing(worker, originalArticleUrl),
      getContentPing(worker, secondArticleUrl),
    ]);
    const rm04Sessions = await worker.evaluate(
      async ({ firstUrl, secondUrl }) => {
        const authScope = await getAuthScope();
        const createSession = (pageUrl, id, sentenceId, text) => ({
          schemaVersion: 1,
          owner: authScope,
          pageUrl,
          pageTitle: id,
          preload: {
            id,
            page_url: pageUrl,
            sentences: [{ id: sentenceId, index: 0, text, analysis: {} }],
          },
          domLinkStatus: { [sentenceId]: true },
          ui: {
            activeSentenceId: sentenceId,
            hoveredSentenceId: null,
            activeStudyItemId: null,
            activeSentenceScreen: 'detail',
          },
          updatedAt: Date.now(),
        });
        const firstSession = createSession(
          firstUrl,
          'rm04-first-preload',
          'rm04-first-sentence',
          'The quick brown fox jumps over the lazy dog.',
        );
        firstSession.preload.sentences.push({
          id: 'rm04-first-sentence-selected',
          index: 1,
          text: 'It happens every day.',
          analysis: {},
        });
        firstSession.domLinkStatus['rm04-first-sentence-selected'] = true;
        const secondSession = createSession(
          secondUrl,
          'rm04-second-preload',
          'rm04-second-sentence',
          'Reading assistants should not break simple pages like this one.',
        );
        const firstKey = readingSessionStorageKey(firstUrl, authScope);
        const secondKey = readingSessionStorageKey(secondUrl, authScope);
        await chrome.storage.local.set({ [firstKey]: firstSession, [secondKey]: secondSession });
        return { firstKey, firstSession, secondKey, secondSession };
      },
      { firstUrl: originalArticleUrl, secondUrl: secondArticleUrl },
    );
    rm04SessionKeys = [rm04Sessions.firstKey, rm04Sessions.secondKey];
    const readContentState = async (tabId) =>
      worker.evaluate(async (id) => {
        const [result] = await chrome.scripting.executeScript({
          target: { tabId: id },
          func: () => ({
            preloadId: globalThis.activePreload?.id || null,
            activeSentenceId: globalThis.activeSentenceId || null,
            anchorCount: document.querySelectorAll('.era-page-anchor').length,
          }),
        });
        return result.result;
      }, tabId);

    const waitForContentState = (tabId, preloadId, sentenceId) =>
      worker.evaluate(
        async ({ id, expectedPreloadId, expectedSentenceId }) => {
          for (let attempt = 0; attempt < 100; attempt += 1) {
            const [result] = await chrome.scripting.executeScript({
              target: { tabId: id },
              func: () => ({
                preloadId: globalThis.activePreload?.id || null,
                activeSentenceId: globalThis.activeSentenceId || null,
                anchorCount: document.querySelectorAll('.era-page-anchor').length,
              }),
            });
            const state = result.result;
            if (
              state.preloadId === expectedPreloadId &&
              state.activeSentenceId === expectedSentenceId &&
              state.anchorCount > 0
            ) {
              return state;
            }
            await new Promise((resolve) => setTimeout(resolve, 50));
          }
          throw new Error(`RM04 content did not become ready for ${expectedPreloadId}`);
        },
        { id: tabId, expectedPreloadId: preloadId, expectedSentenceId: sentenceId },
      );

    await Promise.all([
      waitForContentState(firstContent.tabId, 'rm04-first-preload', 'rm04-first-sentence'),
      waitForContentState(secondContent.tabId, 'rm04-second-preload', 'rm04-second-sentence'),
    ]);

    let rm04SecondSession = rm04Sessions.secondSession;
    preloadEndpointController = {
      getResponse: (request) => {
        const requestedPageUrl = new URL(request.url, fixtureBaseUrl).searchParams.get('page_url');
        const normalizedPageUrl = requestedPageUrl ? normalizeFixturePageUrl(requestedPageUrl) : '';
        if (normalizedPageUrl === originalArticleUrl) {
          return { ready: true, preload: rm04Sessions.firstSession.preload };
        }
        if (normalizedPageUrl === secondArticleUrl) {
          return { ready: true, preload: rm04SecondSession.preload };
        }
        return { ready: false };
      },
    };
    firstPanel = await context.newPage();
    secondPanel = await context.newPage();
    watch(firstPanel, 'rm04-first-panel');
    watch(secondPanel, 'rm04-second-panel');
    await Promise.all([
      firstPanel.goto(
        `chrome-extension://${extensionId}/sidepanel.html?pageUrl=${encodeURIComponent(originalArticleUrl)}`,
      ),
      secondPanel.goto(
        `chrome-extension://${extensionId}/sidepanel.html?pageUrl=${encodeURIComponent(secondArticleUrl)}`,
      ),
    ]);
    await Promise.all([
      firstPanel.waitForFunction(
        () => document.getElementById('targetLanguageSelect')?.disabled === false,
      ),
      secondPanel.waitForFunction(
        () => document.getElementById('targetLanguageSelect')?.disabled === false,
      ),
    ]);
    const mountBoundPanel = (boundPanel, session) =>
      boundPanel.evaluate(async (readingSession) => {
        const authScope = await getAuthScope();
        return syncReadingViewUi({
          preload: readingSession.preload,
          pageTitle: readingSession.pageTitle,
          sentenceCount: readingSession.preload.sentences.length,
          switchToReading: true,
          authScope,
        });
      }, session);
    const [firstMounted, secondMounted] = await Promise.all([
      mountBoundPanel(firstPanel, rm04Sessions.firstSession),
      mountBoundPanel(secondPanel, rm04Sessions.secondSession),
    ]);
    const waitForPanelState = (boundPanel, pageUrl, preloadId, sentenceText) =>
      boundPanel.waitForFunction(
        ({ expectedPageUrl, expectedPreloadId, expectedSentenceText }) => {
          const root = document.getElementById('readingPanelRoot');
          return (
            activePageUrl === expectedPageUrl &&
            cachedActivePreload?.id === expectedPreloadId &&
            root?.hidden === false &&
            root.textContent.includes(expectedSentenceText)
          );
        },
        {
          expectedPageUrl: pageUrl,
          expectedPreloadId: preloadId,
          expectedSentenceText: sentenceText,
        },
      );
    await Promise.all([
      waitForPanelState(
        firstPanel,
        originalArticleUrl,
        'rm04-first-preload',
        'The quick brown fox jumps over the lazy dog.',
      ),
      waitForPanelState(
        secondPanel,
        secondArticleUrl,
        'rm04-second-preload',
        'Reading assistants should not break simple pages like this one.',
      ),
    ]);

    const [firstBefore, secondBefore] = await Promise.all([
      readContentState(firstContent.tabId),
      readContentState(secondContent.tabId),
    ]);
    const readPanelState = (boundPanel) =>
      boundPanel.evaluate(() => ({
        cachedPreloadId: cachedActivePreload?.id || null,
        pageUrl: activePageUrl,
        detailText:
          document.querySelector('#readingPanelRoot .era-section-original')?.textContent || '',
      }));
    const [firstPanelBefore, secondPanelBefore] = await Promise.all([
      readPanelState(firstPanel),
      readPanelState(secondPanel),
    ]);

    await firstPanel.locator('.era-panel-nav-button[data-nav="next"]').click();
    const firstSelectionStored = await worker.evaluate(
      async ({ key, sentenceId }) => {
        for (let attempt = 0; attempt < 100; attempt += 1) {
          const session = (await chrome.storage.local.get(key))[key];
          if (session?.ui?.activeSentenceId === sentenceId) return true;
          await new Promise((resolve) => setTimeout(resolve, 50));
        }
        return false;
      },
      { key: rm04Sessions.firstKey, sentenceId: 'rm04-first-sentence-selected' },
    );
    const firstRestored = await firstPanel.evaluate(async (pageUrl) => {
      window.ReadingPanel.clearReadingPanel();
      return window.ReadingPanel.mountFromStorage(pageUrl);
    }, originalArticleUrl);
    await Promise.all([
      waitForContentState(firstContent.tabId, 'rm04-first-preload', 'rm04-first-sentence-selected'),
      waitForPanelState(
        firstPanel,
        originalArticleUrl,
        'rm04-first-preload',
        'It happens every day.',
      ),
    ]);
    const [firstPanelSelected, secondPanelSelected] = await Promise.all([
      readPanelState(firstPanel),
      readPanelState(secondPanel),
    ]);

    rm04SecondSession = {
      ...rm04Sessions.secondSession,
      ui: {
        ...rm04Sessions.secondSession.ui,
        activeSentenceId: 'rm04-second-sentence-updated',
      },
      preload: {
        ...rm04Sessions.secondSession.preload,
        id: 'rm04-second-preload-updated',
        sentences: [
          {
            id: 'rm04-second-sentence-updated',
            index: 0,
            text: 'It happens every day.',
            analysis: {},
          },
        ],
      },
      domLinkStatus: { 'rm04-second-sentence-updated': true },
      updatedAt: Date.now(),
    };
    await worker.evaluate(
      async ({ secondKey, updatedSecondSession }) => {
        const events = [];
        const listener = (changes, area) => {
          if (area === 'local') events.push(Object.keys(changes));
        };
        chrome.storage.onChanged.addListener(listener);
        globalThis.__rm04WriteEvents = events;
        globalThis.__rm04StopWriteEvents = () => {
          chrome.storage.onChanged.removeListener(listener);
        };
        await chrome.storage.local.set({ [secondKey]: updatedSecondSession });
      },
      { secondKey: rm04Sessions.secondKey, updatedSecondSession: rm04SecondSession },
    );

    await Promise.all([
      waitForContentState(
        secondContent.tabId,
        'rm04-second-preload-updated',
        'rm04-second-sentence-updated',
      ),
      waitForPanelState(
        secondPanel,
        secondArticleUrl,
        'rm04-second-preload-updated',
        'It happens every day.',
      ),
    ]);

    const [firstAfter, secondAfter] = await Promise.all([
      readContentState(firstContent.tabId),
      readContentState(secondContent.tabId),
    ]);
    const [firstPanelAfter, secondPanelAfter] = await Promise.all([
      readPanelState(firstPanel),
      readPanelState(secondPanel),
    ]);
    const rm04WriteEvents = await worker.evaluate(() => {
      const events = globalThis.__rm04WriteEvents || [];
      globalThis.__rm04StopWriteEvents?.();
      delete globalThis.__rm04WriteEvents;
      delete globalThis.__rm04StopWriteEvents;
      return events;
    });
    const onlySecondWrite =
      rm04WriteEvents.length === 1 &&
      rm04WriteEvents[0].length === 1 &&
      rm04WriteEvents[0][0] === rm04Sessions.secondKey;
    if (
      firstBefore.preloadId !== 'rm04-first-preload' ||
      firstBefore.activeSentenceId !== 'rm04-first-sentence' ||
      firstBefore.anchorCount === 0 ||
      secondBefore.preloadId !== 'rm04-second-preload' ||
      secondBefore.activeSentenceId !== 'rm04-second-sentence' ||
      secondBefore.anchorCount === 0 ||
      firstAfter.preloadId !== 'rm04-first-preload' ||
      firstAfter.activeSentenceId !== 'rm04-first-sentence-selected' ||
      firstAfter.anchorCount === 0 ||
      secondAfter.preloadId !== 'rm04-second-preload-updated' ||
      secondAfter.activeSentenceId !== 'rm04-second-sentence-updated' ||
      secondAfter.anchorCount === 0 ||
      !firstMounted ||
      !secondMounted ||
      firstPanelBefore.cachedPreloadId !== 'rm04-first-preload' ||
      firstPanelBefore.pageUrl !== originalArticleUrl ||
      !firstPanelBefore.detailText.includes('The quick brown fox jumps over the lazy dog.') ||
      !firstSelectionStored ||
      !firstRestored ||
      firstPanelSelected.cachedPreloadId !== 'rm04-first-preload' ||
      firstPanelSelected.pageUrl !== originalArticleUrl ||
      !firstPanelSelected.detailText.includes('It happens every day.') ||
      secondPanelSelected.cachedPreloadId !== 'rm04-second-preload' ||
      secondPanelSelected.pageUrl !== secondArticleUrl ||
      !secondPanelSelected.detailText.includes(
        'Reading assistants should not break simple pages like this one.',
      ) ||
      secondPanelBefore.cachedPreloadId !== 'rm04-second-preload' ||
      secondPanelBefore.pageUrl !== secondArticleUrl ||
      !secondPanelBefore.detailText.includes(
        'Reading assistants should not break simple pages like this one.',
      ) ||
      firstPanelAfter.cachedPreloadId !== 'rm04-first-preload' ||
      firstPanelAfter.pageUrl !== originalArticleUrl ||
      !firstPanelAfter.detailText.includes('It happens every day.') ||
      secondPanelAfter.cachedPreloadId !== 'rm04-second-preload-updated' ||
      secondPanelAfter.pageUrl !== secondArticleUrl ||
      !secondPanelAfter.detailText.includes('It happens every day.') ||
      !onlySecondWrite
    ) {
      errors.push(
        `RM04 interleaved article state crossed contexts: ${JSON.stringify({ firstBefore, secondBefore, firstAfter, secondAfter, firstMounted, secondMounted, firstPanelBefore, secondPanelBefore, firstSelectionStored, firstRestored, firstPanelSelected, secondPanelSelected, firstPanelAfter, secondPanelAfter, rm04WriteEvents })}`,
      );
    }
    await worker.evaluate(
      ({ firstKey, secondKey }) => chrome.storage.local.remove([firstKey, secondKey]),
      rm04Sessions,
    );
    rm04SessionKeys = [];
  } finally {
    preloadEndpointController = null;
    await worker
      .evaluate(() => {
        globalThis.__rm04StopWriteEvents?.();
        delete globalThis.__rm04WriteEvents;
        delete globalThis.__rm04StopWriteEvents;
      })
      .catch(() => {});
    if (rm04SessionKeys.length) {
      await worker
        .evaluate((keys) => chrome.storage.local.remove(keys), rm04SessionKeys)
        .catch(() => {});
    }
    await Promise.all([firstPanel?.close().catch(() => {}), secondPanel?.close().catch(() => {})]);
    await secondArticle.close();
    await page.bringToFront();
  }

  // A fresh preload carries the stable-preset-derived coverage to the backend.
  // Changing that profile clears only the local page session; it must not start
  // another request until the learner explicitly confirms a reload.
  const learnerCoverageResult = await worker.evaluate(async (pattern) => {
    const [tab] = await chrome.tabs.query({ url: pattern });
    const [result] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: async () => {
        const originalSendMessage = chrome.runtime.sendMessage.bind(chrome.runtime);
        const capturedPreloads = [];
        window.__smokeOriginalSendMessage = originalSendMessage;
        window.__smokePreloadPayloads = capturedPreloads;
        chrome.runtime.sendMessage = async (message, ...args) => {
          if (message?.type === 'CREATE_PAGE_PRELOAD') {
            capturedPreloads.push(message.payload);
            return {
              ok: true,
              preload: {
                id: 'coverage-fixture',
                page_url: location.href.replace(/\/$/, ''),
                summary: '',
                topics: [],
                sentences: [
                  {
                    id: 'coverage-fixture-sentence',
                    index: 0,
                    text: 'Coverage fixture sentence.',
                    analysis: {},
                  },
                ],
                study_items: [],
              },
            };
          }
          return originalSendMessage(message, ...args);
        };
        await chrome.storage.local.set({
          authSession: {
            accessToken: 'smoke-token',
            user: { id: 'smoke', email: 'smoke@example.com' },
            loginId: 'smoke-login-1',
          },
          learnerProfile: { preset: 'cefr-a1', notes: '' },
        });
        await window.runPagePreload();
        return { capturedPreloads };
      },
    });
    return result.result;
  }, `${fixtureBaseUrl}/*`);
  if (learnerCoverageResult.capturedPreloads.length !== 1) {
    errors.push(
      `expected one fresh preload payload, got ${learnerCoverageResult.capturedPreloads.length}`,
    );
  }
  const learnerCoveragePayload = learnerCoverageResult.capturedPreloads[0] || {};
  if (learnerCoveragePayload.vocabulary_coverage_percent !== 18) {
    errors.push(
      `beginner preset coverage was ${learnerCoveragePayload.vocabulary_coverage_percent}, expected 18`,
    );
  }
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(
      learnerCoveragePayload.operation_id || '',
    )
  ) {
    errors.push(
      `preload operation_id was not UUID v7: ${learnerCoveragePayload.operation_id || ''}`,
    );
  }

  const learnerInvalidationResult = await panel.evaluate(async (pageUrl) => {
    await chrome.storage.local.set({
      eraReadingSession: {
        pageUrl,
        preload: {
          id: 'stale-profile-preload',
          page_url: pageUrl,
          sentences: [{ id: 's1', index: 0, text: 'Cached sentence.', analysis: {} }],
        },
      },
    });
    const preset = document.getElementById('learnerLevelPreset');
    const notes = document.getElementById('learnerLevelNotes');
    preset.value = 'toeic-700';
    notes.value = '';
    await window.saveLearnerProfile();
    const stored = await chrome.storage.local.get('eraReadingSession');
    const originalSendMessage = chrome.runtime.sendMessage.bind(chrome.runtime);
    const messages = [];
    chrome.runtime.sendMessage = async (message, ...args) => {
      messages.push(message);
      if (message?.type === 'GET_PRELOAD_STATUS') {
        return {
          ok: true,
          status: {
            ready: true,
            preload: {
              id: 'server-preload',
              page_url: pageUrl,
              summary: '',
              topics: [],
              sentences: [{ id: 's1', index: 0, text: 'Existing sentence.', analysis: {} }],
              study_items: [],
              learner_level: 'TOEIC 500点程度',
              vocabulary_coverage_percent: 18,
            },
          },
        };
      }
      return originalSendMessage(message, ...args);
    };
    try {
      await window.startPreload({ tab: { id: 1, url: pageUrl, title: 'Existing article' } });
    } finally {
      chrome.runtime.sendMessage = originalSendMessage;
    }
    const afterReloadAttempt = await chrome.storage.local.get('eraReadingSession');
    return {
      sessionRetained: Boolean(stored.eraReadingSession),
      reloadRequiredMessage: document
        .getElementById('preloadStatus')
        ?.textContent.includes(
          document.querySelector('[data-i18n="learnerSectionDesc"]')?.textContent || '',
        ),
      existingServerPreloadRetained: messages.some(
        (message) => message?.type === 'GET_PRELOAD_STATUS',
      ),
      overwriteConfirmationShown: document.getElementById('preloadConfirm')?.hidden === false,
      automaticPreloadRequests: messages.filter((message) => message?.type === 'START_PRELOAD')
        .length,
      localSessionKeptAfterConfirm: Boolean(afterReloadAttempt.eraReadingSession),
      // Overwrite is explicit — confirming the dialog is required before a new
      // START_PRELOAD. Until then the existing reading content may stay visible.
      noAutomaticStartPreload: messages.every((message) => message?.type !== 'START_PRELOAD'),
    };
  }, `${fixtureBaseUrl}`);
  if (!learnerInvalidationResult.sessionRetained) {
    errors.push('learner profile change cleared the local reading session');
  }
  if (!learnerInvalidationResult.reloadRequiredMessage) {
    errors.push('learner profile change did not show the reload-required guidance');
  }
  if (!learnerInvalidationResult.existingServerPreloadRetained) {
    errors.push('existing ready server preload was not retained for overwrite confirmation');
  }
  if (!learnerInvalidationResult.overwriteConfirmationShown) {
    errors.push('existing ready server preload did not require explicit overwrite confirmation');
  }
  if (learnerInvalidationResult.automaticPreloadRequests !== 0) {
    errors.push('existing ready server preload triggered an automatic preload request');
  }
  if (!learnerInvalidationResult.localSessionKeptAfterConfirm) {
    errors.push('overwrite confirmation cleared the local reading session before confirm');
  }
  if (!learnerInvalidationResult.noAutomaticStartPreload) {
    errors.push('profile-mismatched ready preload started a preload without confirmation');
  }
  const automaticPreloadCount = await worker.evaluate(async (pattern) => {
    const [tab] = await chrome.tabs.query({ url: pattern });
    const [result] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        const count = window.__smokePreloadPayloads?.length || 0;
        chrome.runtime.sendMessage = window.__smokeOriginalSendMessage;
        delete window.__smokeOriginalSendMessage;
        delete window.__smokePreloadPayloads;
        return count;
      },
    });
    return result.result;
  }, `${fixtureBaseUrl}/*`);
  if (automaticPreloadCount !== 1) {
    errors.push(
      `learner profile change triggered ${automaticPreloadCount - 1} automatic preload requests`,
    );
  }

  await panel.evaluate(() => {
    setSidePanelView('settings');
    const select = document.getElementById('targetLanguageSelect');
    select.value = 'auto';
    window.__eraStaticSelectChangeCount = 0;
    document.addEventListener(
      'change',
      (event) => {
        if (event.target?.id === 'targetLanguageSelect') window.__eraStaticSelectChangeCount += 1;
      },
      true,
    );
  });
  const staticTrigger = panel.locator(
    '#targetLanguageSelect + .era-select-control .era-select-trigger',
  );
  await staticTrigger.waitFor({ state: 'visible' });
  await staticTrigger.press('Enter');
  const enterOpens = (await staticTrigger.getAttribute('aria-expanded')) === 'true';
  await panel.keyboard.press('Escape');
  const escapeRestoresFocus = await panel.evaluate(
    () =>
      document.activeElement ===
      document.querySelector('#targetLanguageSelect + .era-select-control .era-select-trigger'),
  );
  await staticTrigger.press(' ');
  const spaceOpens = (await staticTrigger.getAttribute('aria-expanded')) === 'true';
  await panel.keyboard.press('ArrowDown');
  await panel.keyboard.press('Enter');
  await panel.waitForFunction(async () => {
    const select = document.getElementById('targetLanguageSelect');
    const trigger = select.nextElementSibling?.querySelector('.era-select-trigger');
    const { languageProfile } = await chrome.storage.local.get('languageProfile');
    return (
      select.value === 'en' &&
      languageProfile?.target === 'en' &&
      window.__eraStaticSelectChangeCount === 1 &&
      trigger?.getAttribute('aria-expanded') === 'false'
    );
  });
  await panel.evaluate(() => setSidePanelView('settings'));
  await staticTrigger.waitFor({ state: 'visible' });
  const staticDropdownResult = await panel.evaluate(() => {
    const select = document.getElementById('targetLanguageSelect');
    const trigger = select.nextElementSibling?.querySelector('.era-select-trigger');
    return {
      nativeSourceHidden:
        select.classList.contains('era-select-source') &&
        select.getAttribute('aria-hidden') === 'true',
      selectedValue: select.value,
      selectedText: trigger?.querySelector('.era-select-trigger-text')?.textContent || '',
      changeCount: window.__eraStaticSelectChangeCount,
      closedAfterSelect: trigger?.getAttribute('aria-expanded') === 'false',
    };
  });
  await staticTrigger.press('Enter');
  await panel.keyboard.press('Tab');
  const tabCloses = (await staticTrigger.getAttribute('aria-expanded')) === 'false';
  await staticTrigger.click();
  await panel.locator('h1').click();
  const outsideClickCloses = (await staticTrigger.getAttribute('aria-expanded')) === 'false';
  await panel.waitForFunction(
    () =>
      document.activeElement ===
      document.querySelector('#targetLanguageSelect + .era-select-control .era-select-trigger'),
  );
  const outsideClickRestoresFocus = await panel.evaluate(
    () =>
      document.activeElement ===
      document.querySelector('#targetLanguageSelect + .era-select-control .era-select-trigger'),
  );
  await staticTrigger.press('Enter');
  await panel.locator('#darkModeToggle').click();
  const interactiveOutsideKeepsFocus = await panel.evaluate(
    () => document.activeElement === document.getElementById('darkModeToggle'),
  );

  // The observer must rebuild a newly added select after option text, values,
  // selected state, and disabled state change inside it.
  const dynamicDropdownReady = await panel.evaluate(async () => {
    const fixture = document.createElement('label');
    fixture.id = 'dynamicSelectFixture';
    fixture.innerHTML = `
    <span>Dynamic fixture</span>
    <select id="dynamicSelectSource" class="era-select">
      <option value="one">One</option>
      <option value="two" selected>Two</option>
      <option value="three">Three</option>
      <option value="duplicate">Duplicate first</option>
      <option value="duplicate">Duplicate second</option>
    </select>
  `;
    document.body.append(fixture);
    await new Promise((resolve) => setTimeout(resolve, 0));

    const select = document.getElementById('dynamicSelectSource');
    const trigger = select.nextElementSibling?.querySelector('.era-select-trigger');
    return {
      upgraded: Boolean(trigger && document.getElementById(trigger.getAttribute('aria-controls'))),
    };
  });
  const dynamicTrigger = panel.locator(
    '#dynamicSelectSource + .era-select-control .era-select-trigger',
  );
  await dynamicTrigger.press('Enter');
  const dynamicListboxId = await dynamicTrigger.getAttribute('aria-controls');
  const dynamicOptions = panel.locator(`#${dynamicListboxId} [role="option"]`);
  await dynamicOptions.first().press('ArrowUp');
  const arrowUpWrapsLast = await panel.evaluate((id) => {
    const options = document.querySelectorAll(`#${id} [role="option"]`);
    return document.activeElement === options[options.length - 1];
  }, dynamicListboxId);
  await dynamicOptions.last().press('Home');
  const homeFocusesFirst = await panel.evaluate((id) => {
    const options = document.querySelectorAll(`#${id} [role="option"]`);
    return document.activeElement === options[0];
  }, dynamicListboxId);
  await dynamicOptions.first().press('End');
  const endFocusesLast = await panel.evaluate((id) => {
    const options = document.querySelectorAll(`#${id} [role="option"]`);
    return document.activeElement === options[options.length - 1];
  }, dynamicListboxId);
  await dynamicOptions.last().press('Enter');
  const duplicateValueResult = await panel.evaluate(
    () => document.getElementById('dynamicSelectSource')?.selectedIndex === 4,
  );
  const dynamicSyncResult = await panel.evaluate(async () => {
    const select = document.getElementById('dynamicSelectSource');
    select.value = 'three';
    window.SelectUI.refresh(select);
    await new Promise((resolve) => setTimeout(resolve, 0));

    let trigger = select.nextElementSibling?.querySelector('.era-select-trigger');
    let listbox = document.getElementById(trigger?.getAttribute('aria-controls'));
    const programmaticValueSynced =
      trigger?.querySelector('.era-select-trigger-text')?.textContent === 'Three' &&
      listbox?.querySelector('[aria-selected="true"]')?.textContent === 'Three';

    select.setAttribute('aria-label', 'Dynamic source label');
    await new Promise((resolve) => setTimeout(resolve, 0));
    trigger = select.nextElementSibling?.querySelector('.era-select-trigger');
    listbox = document.getElementById(trigger?.getAttribute('aria-controls'));
    const ariaLabelSynced =
      trigger?.getAttribute('aria-label') === 'Dynamic source label' &&
      listbox?.getAttribute('aria-label') === 'Dynamic source label';

    select.removeAttribute('aria-label');
    document.querySelector('#dynamicSelectFixture span').textContent = 'Dynamic fixture updated';
    await new Promise((resolve) => setTimeout(resolve, 0));
    trigger = select.nextElementSibling?.querySelector('.era-select-trigger');
    listbox = document.getElementById(trigger?.getAttribute('aria-controls'));
    const associatedLabelSynced =
      trigger?.getAttribute('aria-label') === 'Dynamic fixture updated' &&
      listbox?.getAttribute('aria-label') === 'Dynamic fixture updated';

    return { programmaticValueSynced, ariaLabelSynced, associatedLabelSynced };
  });
  const dynamicDropdownResult = await panel.evaluate(async () => {
    const select = document.getElementById('dynamicSelectSource');
    select.options[0].textContent = 'One updated';
    select.options[0].value = 'one-updated';
    select.options[0].disabled = true;
    select.options[2].selected = true;
    select.options[2].setAttribute('selected', '');
    await new Promise((resolve) => setTimeout(resolve, 0));

    const trigger = select.nextElementSibling?.querySelector('.era-select-trigger');
    const listbox = document.getElementById(trigger?.getAttribute('aria-controls'));
    const firstOption = listbox?.querySelector('[role="option"]');
    firstOption?.click();
    const disabledOptionNonSelectable = select.value === 'three';
    return {
      selectedDisplay: trigger?.querySelector('.era-select-trigger-text')?.textContent || '',
      firstText: firstOption?.textContent || '',
      firstDisabled: firstOption?.disabled === true,
      firstAriaDisabled: firstOption?.getAttribute('aria-disabled') === 'true',
      disabledOptionNonSelectable,
      selectedMarked: listbox?.querySelector('[aria-selected="true"]')?.textContent || '',
      sourceValue: select.value,
    };
  });
  await dynamicTrigger.press('Enter');
  const disabledOpenResult = await panel.evaluate(async () => {
    const select = document.getElementById('dynamicSelectSource');
    const trigger = select.nextElementSibling?.querySelector('.era-select-trigger');
    const valueBeforeDisable = select.value;
    select.disabled = true;
    await new Promise((resolve) => setTimeout(resolve, 0));
    const listbox = document.getElementById(trigger?.getAttribute('aria-controls'));
    const firstOption = listbox?.querySelector('[role="option"]');
    firstOption?.click();
    const result = {
      triggerDisabled:
        trigger?.disabled === true && trigger?.getAttribute('aria-disabled') === 'true',
      closed: trigger?.getAttribute('aria-expanded') === 'false' && listbox?.hidden === true,
      selectionPrevented: select.value === valueBeforeDisable,
    };
    select.disabled = false;
    await new Promise((resolve) => setTimeout(resolve, 0));
    return result;
  });
  const cleanupResult = await panel.evaluate(async () => {
    const fixture = document.createElement('label');
    fixture.id = 'cleanupSelectFixture';
    fixture.innerHTML =
      '<span>Cleanup fixture</span><select class="era-select"><option>First</option></select>';
    document.body.append(fixture);
    await new Promise((resolve) => setTimeout(resolve, 0));
    const originalSource = fixture.querySelector('select');
    fixture.innerHTML =
      '<span>Cleanup fixture</span><select class="era-select"><option>Second</option></select>';
    await new Promise((resolve) => setTimeout(resolve, 0));
    return {
      oldWrapperRemoved:
        !originalSource.nextElementSibling?.classList.contains('era-select-control'),
      oneCurrentWrapper: fixture.querySelectorAll('.era-select-control').length === 1,
    };
  });
  await panel.emulateMedia({ reducedMotion: 'reduce' });
  await dynamicTrigger.press('Enter');
  const reducedDynamicListboxId = await dynamicTrigger.getAttribute('aria-controls');
  await panel.locator(`#${reducedDynamicListboxId} [role="option"]`).last().press('Enter');
  const reducedMotionResult = await panel.evaluate(() => {
    const trigger = document.querySelector(
      '#dynamicSelectSource + .era-select-control .era-select-trigger',
    );
    return {
      closed: trigger?.getAttribute('aria-expanded') === 'false',
      reducedMotionActive: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    };
  });
  await panel.emulateMedia({ reducedMotion: 'no-preference' });
  console.log(
    'static custom dropdown:',
    JSON.stringify(
      {
        enterOpens,
        spaceOpens,
        homeFocusesFirst,
        endFocusesLast,
        arrowUpWrapsLast,
        duplicateValueResult,
        ...staticDropdownResult,
        escapeRestoresFocus,
        tabCloses,
        outsideClickCloses,
        outsideClickRestoresFocus,
        interactiveOutsideKeepsFocus,
        dynamicDropdownReady,
        dynamicSyncResult,
        dynamicDropdownResult,
        disabledOpenResult,
        cleanupResult,
        reducedMotionResult,
      },
      null,
      2,
    ),
  );
  for (const key of ['nativeSourceHidden', 'selectedText', 'closedAfterSelect']) {
    if (!staticDropdownResult[key]) errors.push(`static dropdown check failed: ${key}`);
  }
  for (const [key, value] of Object.entries({
    enterOpens,
    spaceOpens,
    arrowUpWrapsLast,
    duplicateValueResult,
    homeFocusesFirst,
    endFocusesLast,
    escapeRestoresFocus,
    tabCloses,
    outsideClickCloses,
    outsideClickRestoresFocus,
    interactiveOutsideKeepsFocus,
    reducedMotionClosed: reducedMotionResult.closed,
    reducedMotionActive: reducedMotionResult.reducedMotionActive,
  })) {
    if (!value) errors.push(`static dropdown check failed: ${key}`);
  }
  if (staticDropdownResult.selectedValue === 'auto') {
    errors.push(
      `keyboard selection did not update native source: ${staticDropdownResult.selectedValue}`,
    );
  }
  if (staticDropdownResult.changeCount !== 1) {
    errors.push(
      `native change listener fired ${staticDropdownResult.changeCount} times, expected once`,
    );
  }
  for (const [key, value] of Object.entries({
    ...dynamicDropdownReady,
    ...dynamicSyncResult,
    ...dynamicDropdownResult,
    ...disabledOpenResult,
    ...cleanupResult,
  })) {
    if (key === 'sourceValue' ? value !== 'three' : !value) {
      errors.push(`dynamic dropdown check failed: ${key}`);
    }
  }

  // Mount the reading panel with fixture data to exercise reading-panel.js.
  const mountResult = await panel.evaluate(async (pageUrl) => {
    const preload = {
      id: 'pre-1',
      page_url: pageUrl,
      summary: 'A test article.',
      sentences: [
        {
          id: 's1',
          index: 0,
          text: 'The quick brown fox jumps over the lazy dog.',
          analysis: { translation: '訳1', grammar: '文法1', vocabulary: ['fox: きつね'] },
        },
        {
          id: 's2',
          index: 1,
          text: 'It happens every day.',
          analysis: { translation: '訳2', grammar: '文法2', vocabulary: [] },
        },
      ],
      study_items: [{ id: 'v1', text: 'lazy dog', meaning: '怠け者の犬', sentence_ids: ['s1'] }],
      // Plan cap truncated a longer article: 2 of 40 sentences analyzed.
      sentences_detected: 40,
      sentence_limit: 2,
    };
    const mounted = await window.ReadingPanel.mountFromPreload(preload, preload.page_url, 'Test');
    const root = document.getElementById('readingPanelRoot');
    root.hidden = false;
    const sentenceButtons = root.querySelectorAll('.era-sentence-button').length;
    root.querySelector('.era-sentence-button')?.click();
    await new Promise((resolve) => setTimeout(resolve, 300));
    const result = {
      mounted,
      sentenceButtons,
      detailShown: Boolean(root.querySelector('.era-panel-detail-view')),
      speakButton: Boolean(root.querySelector('.era-sentence-speak-button')),
      chatForm: Boolean(root.querySelector('.era-context-chat-form')),
      analysisShown: root.textContent.includes('訳1'),
      // Each vocabulary line in the explanation gets a read-aloud button in
      // place of the bullet (s1 has one vocabulary entry, "fox").
      vocabLineSpeakButton: Boolean(
        root.querySelector('.era-vocab-line .era-vocab-speak[data-speak-key^="vocab:"]'),
      ),
    };

    // The reading panel is sentences-only: the inner vocabulary switch is
    // gone (vocabulary lives in the word-book tab).
    result.noInnerVocabTab = !root.querySelector('.era-panel-view-button');
    // Plan-cap truncation is surfaced in the meta line.
    result.truncationShown = (root.querySelector('.era-panel-meta')?.textContent || '').includes(
      '40',
    );
    return result;
  }, `${fixtureBaseUrl}/`);
  console.log('reading panel mount:', JSON.stringify(mountResult, null, 2));
  if (!mountResult.mounted) errors.push('reading panel did not mount');
  if (mountResult.sentenceButtons !== 2)
    errors.push(`expected 2 sentence buttons, got ${mountResult.sentenceButtons}`);
  for (const key of [
    'detailShown',
    'speakButton',
    'chatForm',
    'analysisShown',
    'vocabLineSpeakButton',
    'noInnerVocabTab',
    'truncationShown',
  ]) {
    if (!mountResult[key]) errors.push(`reading panel check failed: ${key}`);
  }

  await panel.evaluate(() => {
    setSidePanelView('reading');
    const root = document.getElementById('readingPanelRoot');
    root.tabIndex = -1;
    root.focus();
  });

  // 3a. Audio reading bar: continuous read-aloud controls in the reading view.
  // Isolate control behavior from OS voices. Headless Chromium may emit an
  // immediate TTS error, otherwise advancing to the end before the pause click.
  const audioResult = await panel.evaluate(async () => {
    const synthesis = window.speechSynthesis;
    synthesis.cancel();
    synthesis.speak = (utterance) => {
      window.smokeUtterance = utterance;
    };
    synthesis.cancel = () => {};
    const root = document.getElementById('readingPanelRoot');
    // Return to the list screen (the bar is hidden in detail mode).
    root.querySelector('.era-panel-back-button')?.click();

    const bar = root.querySelector('.era-audio-bar');
    const play = bar?.querySelector('.era-audio-play');
    const rate = bar?.querySelector('.era-audio-rate');
    const result = {
      barShown: Boolean(bar) && getComputedStyle(bar).display !== 'none',
      rateOptions: rate ? rate.options.length : 0,
      rateEraSelect: rate?.classList.contains('era-select') === true,
      rateCustomUpgraded: Boolean(bar?.querySelector('.era-audio-rate + .era-select-control')),
      rateAccessibleLabel: rate?.getAttribute('aria-label') || '',
      rateValues: [...(rate?.options || [])].map((option) => option.value),
      positionText: bar?.querySelector('.era-audio-position')?.textContent || '',
    };

    play?.click();
    result.playingAfterClick = Boolean(play?.classList.contains('era-audio-playing'));

    // No on-screen step buttons on the list view; stepping is via arrow keys.
    result.noStepButtons = !bar?.querySelector('.era-audio-step');
    return result;
  });
  await panel.keyboard.press('ArrowRight');
  await panel.waitForTimeout(100);
  Object.assign(
    audioResult,
    await panel.evaluate(() => {
      const bar = document.querySelector('#readingPanelRoot .era-audio-bar');
      const play = bar?.querySelector('.era-audio-play');
      const result = {
        positionAfterStep: bar?.querySelector('.era-audio-position')?.textContent || '',
      };

      play?.click();
      result.pausedAfterClick = !play?.classList.contains('era-audio-playing');

      // The controlled engine also exercises the real completion callback.
      play?.click();
      window.smokeUtterance.onend();
      result.stoppedAtEnd = !play?.classList.contains('era-audio-playing');
      return result;
    }),
  );
  await panel.evaluate(() => {
    document.getElementById('readingPanelRoot')?.classList.remove('era-panel-sentence-detail-mode');
  });
  const audioRateTrigger = panel.locator(
    '.era-audio-rate + .era-select-control .era-select-trigger',
  );
  await audioRateTrigger.click();
  await panel
    .locator('.era-audio-rate + .era-select-control [role="option"]', { hasText: '1.25' })
    .click();
  await panel.waitForTimeout(200);
  audioResult.rateStored = await panel.evaluate(async () => {
    const stored = await chrome.storage.local.get('audioReadingRate');
    return stored.audioReadingRate === 1.25;
  });
  audioResult.rateRefreshedThroughAudioUpdate = await panel.evaluate(async () => {
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    const trigger = document.querySelector(
      '.era-audio-rate + .era-select-control .era-select-trigger',
    );
    return trigger?.querySelector('.era-select-trigger-text')?.textContent === '1.25x';
  });
  console.log('audio reading bar:', JSON.stringify(audioResult, null, 2));
  if (!audioResult.barShown) errors.push('audio bar not shown in list view');
  if (audioResult.rateOptions !== 5)
    errors.push(`expected 5 rate options, got ${audioResult.rateOptions}`);
  if (!audioResult.rateEraSelect) errors.push('audio rate select is missing era-select');
  if (!audioResult.rateCustomUpgraded) errors.push('audio rate select was not upgraded');
  if (!audioResult.rateAccessibleLabel) errors.push('audio rate select lost its accessible label');
  if (audioResult.rateValues.join(',') !== '0.75,0.9,1,1.1,1.25') {
    errors.push(`unexpected audio rate options: ${audioResult.rateValues.join(',')}`);
  }
  if (audioResult.positionText !== '1 / 2')
    errors.push(`unexpected audio position: ${audioResult.positionText}`);
  if (!audioResult.playingAfterClick) errors.push('audio play button did not enter playing state');
  if (!audioResult.noStepButtons)
    errors.push('audio bar should not render on-screen step buttons on the list view');
  if (audioResult.positionAfterStep !== '2 / 2')
    errors.push(`arrow-key step did not advance: ${audioResult.positionAfterStep}`);
  if (!audioResult.pausedAfterClick) errors.push('audio play button did not pause');
  if (!audioResult.stoppedAtEnd) errors.push('audio playback did not stop at the final sentence');
  if (!audioResult.rateStored) errors.push('audio rate change was not persisted');
  if (!audioResult.rateRefreshedThroughAudioUpdate) {
    errors.push('audio update did not refresh the custom rate trigger');
  }

  // 3b. Reading summary: preserve native details activation while measuring the
  // content through each transition. A second activation during close must
  // restore the latest requested (open) state.
  const summaryAccordionResult = await panel.evaluate(async () => {
    const root = document.getElementById('readingPanelRoot');
    const accordion = root.querySelector('.era-panel-summary-accordion');
    const summary = accordion?.querySelector('.era-panel-summary-toggle');
    const content = accordion?.querySelector('.era-panel-summary');
    const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

    summary?.click();
    await wait(20);
    const openingMeasuresHeight = Boolean(content?.style.height);
    await wait(260);
    const openedAfterTransition = accordion?.open === true && content?.style.height === '';

    let closeRequestPrevented = false;
    const recordCloseRequest = (event) => {
      closeRequestPrevented = event.defaultPrevented;
    };
    summary?.addEventListener('click', recordCloseRequest, { once: true });
    summary?.click();
    await wait(20);
    const remainsOpenDuringClose = accordion?.open === true && Boolean(content?.style.height);
    summary?.click();
    await wait(260);
    const reopenedAfterInterrupt = accordion?.open === true && content?.style.height === '';

    const originalMatchMedia = window.matchMedia;
    window.matchMedia = (query) => ({
      matches: query === '(prefers-reduced-motion: reduce)',
      media: query,
      addEventListener() {},
      removeEventListener() {},
    });
    summary?.click();
    await wait(20);
    const closesImmediatelyWithReducedMotion =
      accordion?.open === false && content?.style.height === '';
    summary?.click();
    await wait(20);
    const opensImmediatelyWithReducedMotion =
      accordion?.open === true && content?.style.height === '';
    window.matchMedia = originalMatchMedia;

    summary?.click();
    await wait(260);
    summary?.click();
    summary?.click();
    await wait(260);
    const closesAfterRapidDoubleActivation =
      accordion?.open === false && content?.style.height === '';

    return {
      openingMeasuresHeight,
      openedAfterTransition,
      closeRequestPrevented,
      remainsOpenDuringClose,
      reopenedAfterInterrupt,
      closesImmediatelyWithReducedMotion,
      opensImmediatelyWithReducedMotion,
      closesAfterRapidDoubleActivation,
    };
  });
  console.log('summary accordion:', JSON.stringify(summaryAccordionResult, null, 2));
  for (const key of [
    'openingMeasuresHeight',
    'openedAfterTransition',
    'closeRequestPrevented',
    'remainsOpenDuringClose',
    'reopenedAfterInterrupt',
    'closesImmediatelyWithReducedMotion',
    'opensImmediatelyWithReducedMotion',
    'closesAfterRapidDoubleActivation',
  ]) {
    if (!summaryAccordionResult[key]) errors.push(`summary accordion check failed: ${key}`);
  }

  // 3c. Vocabulary book: renderVocabularyBook is a pure renderer — a flat,
  // title-less list of the words it is given (current-article scoping lives in
  // loadVocabularyBook and is not exercised here). Confirms rows, speak
  // buttons, no per-article title, and the expandable detail with follow-up
  // chat.
  const vocabBookResult = await panel.evaluate(async () => {
    window.renderVocabularyBook({
      preload_count: 1,
      items: [
        {
          id: 'b1',
          text: 'resilient',
          meaning: '回復力のある',
          part_of_speech: 'adjective',
          preload_id: 'p2',
          page_url: 'https://example.com/current',
          page_title: 'Current Article',
          target_language: 'en',
        },
        {
          id: 'b2',
          text: 'phase out',
          meaning: '段階的に廃止する',
          part_of_speech: 'phrasal verb',
          preload_id: 'p2',
          page_url: 'https://example.com/current',
          page_title: 'Current Article',
          target_language: 'en',
        },
      ],
    });
    const list = document.getElementById('vocabBookList');
    const entryButton = list.querySelector('.vocab-book-entry[data-book-item-id="b1"]');
    const detail = list.querySelector(
      '.vocab-book-item[data-book-item-id="b1"] .vocab-book-detail',
    );
    const controlsDetail = Boolean(
      detail?.id && entryButton?.getAttribute('aria-controls') === detail.id,
    );
    const startsCollapsed = entryButton?.getAttribute('aria-expanded') === 'false';
    entryButton?.click();
    await new Promise((resolve) => setTimeout(resolve, 260));
    const detailExpanded = Boolean(detail && !detail.hidden);
    const expandedAfterOpen = entryButton?.getAttribute('aria-expanded') === 'true';
    list.querySelector('.vocab-book-entry[data-book-item-id="b1"]')?.click();
    await new Promise((resolve) => setTimeout(resolve, 20));
    const remainsMountedDuringClose = detail?.hidden === false && Boolean(detail?.style.height);
    const collapsedDuringClose = entryButton?.getAttribute('aria-expanded') === 'false';
    list.querySelector('.vocab-book-entry[data-book-item-id="b1"]')?.click();
    const expandedAfterCloseInterrupt = entryButton?.getAttribute('aria-expanded') === 'true';
    await new Promise((resolve) => setTimeout(resolve, 260));
    const reopenedAfterCloseInterrupt = detail?.hidden === false && detail?.style.height === '';

    list.querySelector('.vocab-book-entry[data-book-item-id="b1"]')?.click();
    await new Promise((resolve) => setTimeout(resolve, 260));
    const hiddenAfterClose = detail?.hidden === true;

    list.querySelector('.vocab-book-entry[data-book-item-id="b1"]')?.click();
    await new Promise((resolve) => setTimeout(resolve, 20));
    const expandedDuringOpen = entryButton?.getAttribute('aria-expanded') === 'true';
    list.querySelector('.vocab-book-entry[data-book-item-id="b1"]')?.click();
    const collapsedAfterOpenInterrupt = entryButton?.getAttribute('aria-expanded') === 'false';
    await new Promise((resolve) => setTimeout(resolve, 260));
    const closedAfterOpenInterrupt = detail?.hidden === true && detail?.style.height === '';

    const originalMatchMedia = window.matchMedia;
    window.matchMedia = (query) => ({
      matches: query === '(prefers-reduced-motion: reduce)',
      media: query,
      addEventListener() {},
      removeEventListener() {},
    });
    list.querySelector('.vocab-book-entry[data-book-item-id="b1"]')?.click();
    await new Promise((resolve) => setTimeout(resolve, 20));
    const opensImmediatelyWithReducedMotion =
      detail?.hidden === false && detail?.style.height === '';
    list.querySelector('.vocab-book-entry[data-book-item-id="b1"]')?.click();
    await new Promise((resolve) => setTimeout(resolve, 20));
    const closesImmediatelyWithReducedMotion =
      detail?.hidden === true && detail?.style.height === '';
    window.matchMedia = originalMatchMedia;

    return {
      rows: list.querySelectorAll('.vocab-book-item').length,
      speakButtons: list.querySelectorAll('[data-speak-key^="book:"]').length,
      noTitle: !list.querySelector('.vocab-book-group-title, .vocab-book-group'),
      controlsDetail,
      startsCollapsed,
      detailExpanded,
      expandedAfterOpen,
      detailChatForm: Boolean(detail?.querySelector('.era-context-chat-form')),
      remainsMountedDuringClose,
      collapsedDuringClose,
      expandedAfterCloseInterrupt,
      reopenedAfterCloseInterrupt,
      hiddenAfterClose,
      expandedDuringOpen,
      collapsedAfterOpenInterrupt,
      closedAfterOpenInterrupt,
      opensImmediatelyWithReducedMotion,
      closesImmediatelyWithReducedMotion,
      statusText: document.getElementById('vocabBookStatus')?.textContent || '',
    };
  });
  console.log('vocab book render:', JSON.stringify(vocabBookResult, null, 2));
  if (vocabBookResult.rows !== 2)
    errors.push(`expected 2 vocab book rows, got ${vocabBookResult.rows}`);
  if (vocabBookResult.speakButtons !== 2)
    errors.push(`expected 2 speak buttons, got ${vocabBookResult.speakButtons}`);
  for (const key of [
    'noTitle',
    'controlsDetail',
    'startsCollapsed',
    'detailExpanded',
    'expandedAfterOpen',
    'detailChatForm',
    'remainsMountedDuringClose',
    'collapsedDuringClose',
    'expandedAfterCloseInterrupt',
    'reopenedAfterCloseInterrupt',
    'hiddenAfterClose',
    'expandedDuringOpen',
    'collapsedAfterOpenInterrupt',
    'closedAfterOpenInterrupt',
    'opensImmediatelyWithReducedMotion',
    'closesImmediatelyWithReducedMotion',
  ]) {
    if (!vocabBookResult[key]) errors.push(`vocab book check failed: ${key}`);
  }

  throwIfInterrupted();
  // 4. Changing the native language must relocalize the whole UI (settings
  // DOM, selects, and a re-mounted reading panel).
  const localeResult = await panel.evaluate(async (pageUrl) => {
    await chrome.storage.local.set({ languageProfile: { target: 'en', native: 'en' } });
    await new Promise((resolve) => setTimeout(resolve, 900));

    const settingsTab = document.getElementById('settingsViewButton')?.textContent.trim();
    const presetHasCefr = [...document.getElementById('learnerLevelPreset').options].some(
      (option) => option.value === 'cefr-b1',
    );
    const autoOption =
      document.getElementById('targetLanguageSelect')?.options[0]?.textContent || '';

    const preload = {
      id: 'pre-2',
      page_url: pageUrl,
      target_language: 'en',
      native_language: 'en',
      summary: 'summary',
      sentences: [
        {
          id: 'x1',
          index: 0,
          text: 'Hello world.',
          analysis: { translation: 't', grammar: 'g', vocabulary: [] },
        },
      ],
      study_items: [],
    };
    await window.ReadingPanel.mountFromPreload(preload, preload.page_url, 'T2');
    const root = document.getElementById('readingPanelRoot');
    root.hidden = false;

    return {
      settingsTab,
      presetHasCefr,
      autoOption,
      panelTitle: root.querySelector('.era-panel-title')?.textContent.trim(),
      readingTab: document.getElementById('readingViewButton')?.textContent.trim(),
    };
  }, `${fixtureBaseUrl}/`);
  console.log('locale switch:', JSON.stringify(localeResult, null, 2));
  if (localeResult.settingsTab !== 'Settings') {
    errors.push(`expected English settings tab, got "${localeResult.settingsTab}"`);
  }
  if (!localeResult.presetHasCefr) errors.push('expected CEFR presets for non-ja locale');
  if (!/Auto-detect/.test(localeResult.autoOption)) {
    errors.push(`expected English auto-detect option, got "${localeResult.autoOption}"`);
  }
  if (localeResult.panelTitle !== 'Explanations') {
    errors.push(`expected English panel title, got "${localeResult.panelTitle}"`);
  }
  if (localeResult.readingTab !== 'Reading') {
    errors.push(`expected English reading tab, got "${localeResult.readingTab}"`);
  }

  throwIfInterrupted();
  // 5. Dark mode: writing panelTheme to storage must theme the whole side
  // panel document through the storage.onChanged path (document root
  // attribute, shell background, and the mounted reading panel root).
  const themeResult = await panel.evaluate(async () => {
    await chrome.storage.local.set({ panelTheme: 'dark' });
    await new Promise((resolve) => setTimeout(resolve, 400));
    return {
      documentTheme: document.documentElement.dataset.theme || '',
      readingRootTheme: document.getElementById('readingPanelRoot')?.dataset.eraTheme || '',
      bodyBg: getComputedStyle(document.body).backgroundColor,
      // The settings-tab toggle mirrors the stored theme; the reading panel
      // header no longer hosts a toggle of its own.
      settingsToggleChecked:
        document.getElementById('darkModeToggle')?.getAttribute('aria-pressed') === 'true',
      headerToggleGone: !document.querySelector('.era-panel-theme-toggle'),
    };
  });
  console.log('dark theme:', JSON.stringify(themeResult, null, 2));
  if (themeResult.documentTheme !== 'dark') {
    errors.push(`document data-theme did not become dark: "${themeResult.documentTheme}"`);
  }
  if (themeResult.readingRootTheme !== 'dark') {
    errors.push(
      `reading root data-era-theme did not become dark: "${themeResult.readingRootTheme}"`,
    );
  }
  // --shell-bg in dark is #0c0a09.
  if (themeResult.bodyBg !== 'rgb(12, 10, 9)') {
    errors.push(`body background did not turn dark: ${themeResult.bodyBg}`);
  }
  if (!themeResult.settingsToggleChecked) errors.push('settings dark-mode toggle did not sync');
  if (!themeResult.headerToggleGone) errors.push('reading panel header still has a theme toggle');

  throwIfInterrupted();
  if (process.env.SMOKE_TEST_FORCE_FAILURE === '1') {
    errors.push('forced failure for artifact verification');
  }

  const fatal = errors.filter(
    (entry) => !/net::|favicon|ERR_CONNECTION|Failed to load resource/.test(entry),
  );
  if (fatal.length) {
    throw new Error(`SMOKE TEST FAILURES:\n${fatal.map((entry) => ` - ${entry}`).join('\n')}`);
  }
}

const smokeOutcomePromise = runSmokeTest().then(
  () => ({ kind: 'success' }),
  (error) => ({ kind: 'failure', error }),
);
const outcome = await Promise.race([
  smokeOutcomePromise,
  signalPromise.then((error) => ({ kind: 'interrupted', error })),
]);

let finalFailure;
let cleanupErrors;
try {
  if (outcome.kind === 'interrupted') {
    // Let the main flow reach an interruption checkpoint before touching shared
    // browser state. Its result is secondary to the original signal reason.
    await smokeOutcomePromise;
    await saveFailureArtifactsOnce(outcome.error);
  } else if (outcome.kind === 'failure') {
    finalFailure = outcome.error;
    await saveFailureArtifactsOnce(outcome.error);
  }
} catch (error) {
  const primary = outcome.kind === 'interrupted' ? outcome.error : finalFailure;
  console.error(`Failure-handling diagnostic: ${errorMessage(error)}`);
  if (!primary) finalFailure = error;
} finally {
  for (const [signal, handler] of signalHandlers) {
    process.off(signal, handler);
  }
  try {
    cleanupErrors = await cleanupOnce();
  } catch (error) {
    cleanupErrors = [`unexpected cleanup failure: ${errorMessage(error)}`];
  }
}

if (cleanupErrors.length) {
  console.error(`Smoke test cleanup failed:\n${cleanupErrors.join('\n')}`);
  if (outcome.kind !== 'interrupted' && !finalFailure) {
    finalFailure = new Error(`Smoke test cleanup failed:\n${cleanupErrors.join('\n')}`);
    try {
      await saveFailureArtifactsOnce(finalFailure);
    } catch (error) {
      console.error(`Artifact diagnostic: ${errorMessage(error)}`);
    }
  }
}

if (outcome.kind === 'interrupted') {
  console.error(outcome.error.message);
  process.exitCode = outcome.error.exitCode;
}

if (finalFailure) throw finalFailure;

if (!interruption) {
  removeSuccessfulRunArtifacts();
  console.log('\nSMOKE TEST PASSED');
}
