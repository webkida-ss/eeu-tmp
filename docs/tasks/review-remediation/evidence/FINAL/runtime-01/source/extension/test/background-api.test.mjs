import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import vm from 'node:vm';

const extensionDir = join(dirname(fileURLToPath(import.meta.url)), '..');

function event() {
  const listeners = [];
  return {
    listeners,
    addListener(listener) {
      listeners.push(listener);
    },
  };
}

function createWorker({
  initialStorage = {},
  responseBodies: responseBodyOverrides = {},
  statuses: statusOverrides = {},
  tab = null,
  extraction = null,
  onFetch = null,
} = {}) {
  const state = Object.assign(Object.create(null), initialStorage);
  const calls = [];
  const consoleErrors = [];
  const tabMessages = [];
  const runtimeMessages = event();
  const storageChanged = event();

  const responseBodies = {
    'GET /auth/config': { provider: 'mock' },
    'POST /auth/login': {
      access_token: 'test-access-token',
      user: { id: 'test-user', email: 'test@example.com' },
    },
    'GET /pages/preload': { ready: false },
    'POST /pages/preload': {
      status: 'ready',
      preload: {
        id: 'preload-id',
        status: 'ready',
        page_url: '__request_page_url__',
        sentences: [{ id: 'sentence-id', text: 'Article text.' }],
      },
    },
    'POST /analyze': { translation: 'translated' },
    'POST /chat': { reply: 'reply' },
    'GET /billing/me': { plan: 'basic' },
    'POST /billing/checkout': { url: 'https://billing.example/checkout' },
    'POST /billing/portal': { url: 'https://billing.example/portal' },
    'GET /vocabulary': { items: [] },
    'POST /auth/logout': {},
    ...responseBodyOverrides,
  };
  const statuses = { 'POST /pages/preload': 202, ...statusOverrides };

  const sandbox = {
    ArrayBuffer,
    Headers,
    ReadableStream,
    Response,
    TextEncoder,
    URL,
    URLSearchParams,
    clearTimeout,
    crypto: webcrypto,
    setTimeout,
    console: {
      ...console,
      error(...args) {
        consoleErrors.push(args);
      },
    },
    fetch: async (url, options = {}) => {
      const parsed = new URL(url);
      const method = options.method || 'GET';
      calls.push({ url, method, options });
      const key = `${method} ${parsed.pathname}`;
      assert.ok(key in responseBodies, `unexpected fetch ${key}`);
      if (onFetch) await onFetch({ url, method, options, key });
      const responseBody = structuredClone(responseBodies[key]);
      if (
        key === 'POST /pages/preload' &&
        responseBody?.preload?.page_url === '__request_page_url__'
      ) {
        responseBody.preload.page_url = JSON.parse(options.body).page_url;
      }
      return new Response(JSON.stringify(responseBody), {
        status: statuses[key] || 200,
        headers: { 'Content-Type': 'application/json; charset=utf-8' },
      });
    },
    chrome: {
      action: {
        onClicked: event(),
        setBadgeText: async () => {},
      },
      management: {
        async getSelf() {
          return { installType: 'normal' };
        },
      },
      runtime: {
        id: 'test-extension',
        onInstalled: event(),
        onMessage: runtimeMessages,
        getPlatformInfo() {},
        reload() {},
      },
      scripting: { executeScript: async () => [] },
      storage: {
        local: {
          async get(keys) {
            if (typeof keys === 'string') return { [keys]: state[keys] };
            if (Array.isArray(keys)) {
              return Object.fromEntries(keys.map((key) => [key, state[key]]));
            }
            if (keys && typeof keys === 'object') return { ...keys, ...state };
            return { ...state };
          },
          async set(values) {
            const changes = Object.fromEntries(
              Object.entries(values).map(([key, newValue]) => [
                key,
                { oldValue: state[key], newValue },
              ]),
            );
            Object.assign(state, values);
            for (const listener of storageChanged.listeners) listener(changes, 'local');
          },
          async remove(keys) {
            const changes = {};
            for (const key of Array.isArray(keys) ? keys : [keys]) {
              if (Object.hasOwn(state, key)) {
                changes[key] = { oldValue: state[key] };
                delete state[key];
              }
            }
            if (Object.keys(changes).length) {
              for (const listener of storageChanged.listeners) listener(changes, 'local');
            }
          },
        },
        onChanged: storageChanged,
      },
      tabs: {
        onActivated: event(),
        onUpdated: event(),
        onRemoved: event(),
        async query() {
          return [];
        },
        async get(tabId) {
          if (tab?.id === tabId) return tab;
          throw new Error('tab unavailable');
        },
        async sendMessage(tabId, message) {
          tabMessages.push({ tabId, message });
          if (message.type === 'PING') {
            return {
              ok: true,
              documentNonce: tab?.documentNonce || 'document-23',
              pageUrl: tab?.url,
            };
          }
          if (message.type === 'EXTRACT_PAGE_HTML') return extraction || { ok: false };
          return { ok: true };
        },
      },
    },
  };
  vm.createContext(sandbox);
  sandbox.importScripts = (...files) => {
    for (const file of files) {
      const sourcePath = join(extensionDir, file);
      vm.runInContext(readFileSync(sourcePath, 'utf8'), sandbox, {
        filename: sourcePath,
      });
    }
  };
  const backgroundPath = join(extensionDir, 'background.js');
  vm.runInContext(readFileSync(backgroundPath, 'utf8'), sandbox, {
    filename: backgroundPath,
  });
  return { calls, consoleErrors, runtimeMessages, sandbox, state, tabMessages };
}

async function sendWorkerMessage(worker, type, payload = undefined) {
  const listener = worker.runtimeMessages.listeners[0];
  return new Promise((resolve) => {
    listener({ type, payload }, {}, resolve);
  });
}

test('background executes all consumed operations with generated URL and method', async () => {
  const worker = createWorker();
  const { sandbox } = worker;
  await vm.runInContext(
    `chrome.storage.local.set({ apiBaseUrl: "https://api.example.test" })`,
    sandbox,
  );

  await vm.runInContext('getAuthConfig()', sandbox);
  await vm.runInContext('login({ credential: "mock:test@example.com" })', sandbox);
  await vm.runInContext(`getPreloadStatus("https://article.example/a path/?x=1&y=two")`, sandbox);
  await vm.runInContext(
    `createPagePreload({ page_url: "https://article.example", html: "<p>Public</p>" })`,
    sandbox,
  );
  await vm.runInContext(
    `analyzeSelection({ text: "Public sentence", page_preload_id: "preload-id" })`,
    sandbox,
  );
  await vm.runInContext(
    `chatFollowUp({ message: "Explain", page_preload_id: "preload-id" })`,
    sandbox,
  );
  await vm.runInContext('getBillingMe()', sandbox);
  await vm.runInContext('startBillingCheckout("pro")', sandbox);
  await vm.runInContext('openBillingPortal()', sandbox);
  await vm.runInContext('getVocabularyBook()', sandbox);
  await vm.runInContext('logout()', sandbox);

  assert.deepEqual(
    worker.calls.map(({ url, method }) => {
      const parsed = new URL(url);
      return [method, `${parsed.pathname}${parsed.search}`];
    }),
    [
      ['GET', '/auth/config'],
      ['POST', '/auth/login'],
      [
        'GET',
        '/pages/preload?page_url=https%3A%2F%2Farticle.example%2Fa+path%2F%3Fx%3D1%26y%3Dtwo',
      ],
      ['POST', '/pages/preload'],
      ['POST', '/analyze'],
      ['POST', '/chat'],
      ['GET', '/billing/me'],
      ['POST', '/billing/checkout'],
      ['POST', '/billing/portal'],
      ['GET', '/vocabulary'],
      ['POST', '/auth/logout'],
    ],
  );
});

test('fetch rejection becomes ApiNetworkError without leaking its cause', async () => {
  const { sandbox } = createWorker();
  sandbox.fetch = async () => {
    throw new TypeError('token=private-value');
  };
  await assert.rejects(
    vm.runInContext('apiFetch(API_OPERATIONS.getAuthConfig, { authenticated: false })', sandbox),
    (error) => {
      assert.equal(error.name, 'ApiNetworkError');
      assert.doesNotMatch(error.message, /private-value/);
      return true;
    },
  );
});

test('query contract errors at fetch boundary are not classified as network failures', async () => {
  const { sandbox } = createWorker();
  await assert.rejects(
    vm.runInContext('apiFetch(API_OPERATIONS.getPagePreload)', sandbox),
    (error) => {
      assert.equal(error.name, 'ApiContractViolationError');
      assert.equal(error.reason, 'missing-required-query-parameter');
      return true;
    },
  );
});

test('message boundary localizes contract failures and logs safe diagnostics only', async () => {
  const worker = createWorker();
  worker.sandbox.fetch = async () =>
    new Response('{}', {
      status: 299,
      headers: { 'Content-Type': 'application/json' },
    });
  const response = await sendWorkerMessage(worker, 'GET_AUTH_CONFIG');
  assert.equal(response.ok, false);
  assert.equal(response.error, vm.runInContext(`t("apiContractError")`, worker.sandbox));
  assert.equal(worker.consoleErrors.length, 1);
  const serialized = JSON.stringify(worker.consoleErrors);
  assert.match(serialized, /getAuthConfig/);
  assert.match(serialized, /undeclared-status-299/);
  assert.doesNotMatch(serialized, /token|credential|response body|private/i);
});

test('Japanese API boundary sanitizes every failure class and preserves quota messages', async () => {
  const cases = [
    {
      name: 'network',
      type: 'GET_AUTH_CONFIG',
      fetch: async () => {
        throw new TypeError('token=network-secret');
      },
      expectedKey: 'apiFailure',
    },
    {
      name: 'unknown HTTP',
      type: 'GET_BILLING_ME',
      fetch: async () =>
        new Response(
          JSON.stringify({
            detail: 'private@example.com database-secret',
          }),
          {
            status: 401,
            headers: { 'Content-Type': 'application/json' },
          },
        ),
      expectedKey: 'apiFailure',
    },
    {
      name: 'malformed success JSON',
      type: 'GET_AUTH_CONFIG',
      fetch: async () =>
        new Response('token=malformed-secret', {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      expectedKey: 'apiFailure',
    },
    {
      name: 'contract',
      type: 'GET_AUTH_CONFIG',
      fetch: async () =>
        new Response('{}', {
          status: 299,
          headers: { 'Content-Type': 'application/json' },
        }),
      expectedKey: 'apiContractError',
    },
    {
      name: 'validation detail',
      type: 'LOGIN',
      payload: { credential: 'private-credential' },
      fetch: async () =>
        new Response(
          JSON.stringify({
            detail: [{ msg: 'credential private-credential is invalid' }],
          }),
          {
            status: 422,
            headers: { 'Content-Type': 'application/json' },
          },
        ),
      expectedKey: 'apiFailure',
    },
    {
      name: 'programming failure',
      type: 'LOGIN',
      payload: null,
      fetch: async () => {
        throw new Error('fetch must not run');
      },
      expectedKey: 'apiFailure',
    },
    {
      name: 'allowlisted quota',
      type: 'GET_BILLING_ME',
      fetch: async () =>
        new Response(
          JSON.stringify({
            code: 'article_quota_exceeded',
            detail: 'private quota detail',
          }),
          {
            status: 401,
            headers: { 'Content-Type': 'application/json' },
          },
        ),
      expectedKey: 'quotaArticleExceeded',
    },
  ];

  for (const failureCase of cases) {
    const worker = createWorker();
    vm.runInContext(`setUiLocale("ja")`, worker.sandbox);
    worker.sandbox.fetch = failureCase.fetch;
    const result = await sendWorkerMessage(worker, failureCase.type, failureCase.payload);
    assert.equal(result.ok, false, failureCase.name);
    assert.equal(
      result.error,
      vm.runInContext(`t(${JSON.stringify(failureCase.expectedKey)})`, worker.sandbox),
      failureCase.name,
    );
    assert.doesNotMatch(
      result.error,
      /private|secret|credential|token|@|getAuthConfig|billing|LOGIN/i,
      failureCase.name,
    );
    const logs = JSON.stringify(worker.consoleErrors);
    assert.doesNotMatch(
      logs,
      /network-secret|database-secret|malformed-secret|private-credential|private quota detail/i,
      failureCase.name,
    );
  }
});

test('non-API message failures retain their existing localized behavior', async () => {
  const worker = createWorker();
  vm.runInContext(`setUiLocale("ja")`, worker.sandbox);
  const result = await sendWorkerMessage(worker, 'GET_ACTIVE_TAB');
  assert.equal(result.ok, false);
  assert.equal(result.error, vm.runInContext(`t("errNeedWebPage")`, worker.sandbox));
});

test('START_PRELOAD worker handler extracts, submits, and publishes a preload', async () => {
  const pageUrl = 'https://article.example/reading';
  const worker = createWorker({
    initialStorage: {
      apiBaseUrl: 'https://api.example.test',
      authSession: {
        accessToken: 'worker-access-token',
        user: { id: 'worker-user' },
        loginId: 'worker-login-1',
      },
    },
    tab: { id: 23, url: pageUrl },
    extraction: {
      ok: true,
      payload: {
        page_url: pageUrl,
        page_title: 'Article title',
        html: '<main>Article text.</main>',
        detected_language: 'en',
        document_nonce: 'document-23',
      },
    },
  });

  const response = await sendWorkerMessage(worker, 'START_PRELOAD', { tabId: 23 });

  assert.equal(response.ok, true);
  assert.equal(response.preload.id, 'preload-id');
  assert.equal(worker.state.preloadJob.state, 'ready');
  assert.equal(worker.state.preloadJob.pageUrl, pageUrl);
  assert.equal(worker.state.preloadJob.sentenceCount, 1);
  assert.deepEqual(
    worker.tabMessages.map(({ message }) => message.type),
    ['PING', 'EXTRACT_PAGE_HTML', 'PING', 'PING', 'SHOW_SENTENCE_PANEL'],
  );

  const submission = worker.calls.find(
    ({ method, url }) => method === 'POST' && new URL(url).pathname === '/pages/preload',
  );
  assert.ok(submission);
  assert.equal(submission.options.headers.Authorization, 'Bearer worker-access-token');
  assert.equal(JSON.parse(submission.options.body).page_url, pageUrl);
});

test('START_PRELOAD worker handler records submission failures without a missing binding', async () => {
  const pageUrl = 'https://article.example/submission-failure';
  const worker = createWorker({
    initialStorage: {
      apiBaseUrl: 'https://api.example.test',
      authSession: {
        accessToken: 'worker-access-token',
        user: { id: 'worker-user' },
        loginId: 'worker-login-1',
      },
    },
    responseBodies: {
      'POST /pages/preload': { detail: 'submission failed' },
    },
    statuses: { 'POST /pages/preload': 422 },
    tab: { id: 29, url: pageUrl },
    extraction: {
      ok: true,
      payload: {
        page_url: pageUrl,
        page_title: 'Article title',
        html: '<main>Article text.</main>',
        detected_language: 'en',
        document_nonce: 'document-23',
      },
    },
  });

  const response = await sendWorkerMessage(worker, 'START_PRELOAD', { tabId: 29 });

  assert.equal(response.ok, false);
  assert.equal(response.error, vm.runInContext(`t("apiFailure")`, worker.sandbox));
  assert.equal(worker.state.preloadJob.state, 'error');
  assert.equal(worker.state.preloadJob.pageUrl, pageUrl);
  assert.equal(
    worker.tabMessages.some(({ message }) => message.type === 'SHOW_SENTENCE_PANEL'),
    false,
  );
  assert.ok(
    worker.calls.some(
      ({ method, url }) => method === 'POST' && new URL(url).pathname === '/pages/preload',
    ),
  );
});

test('START_PRELOAD never delivers an article after the tab navigates to another origin', async () => {
  const pageUrl = 'https://article.example/private-reading';
  const tab = { id: 31, url: pageUrl };
  let releaseSubmission;
  const submissionBlocked = new Promise((resolve) => {
    releaseSubmission = resolve;
  });
  const worker = createWorker({
    initialStorage: {
      apiBaseUrl: 'https://api.example.test',
      authSession: {
        accessToken: 'worker-access-token',
        user: { id: 'account-a' },
        loginId: 'account-a-login-1',
      },
    },
    tab,
    extraction: {
      ok: true,
      payload: {
        page_url: pageUrl,
        page_title: 'Private article',
        html: '<main>Private article text.</main>',
        detected_language: 'en',
        document_nonce: 'document-23',
      },
    },
    onFetch: async ({ key }) => {
      if (key === 'POST /pages/preload') await submissionBlocked;
    },
  });

  const completion = sendWorkerMessage(worker, 'START_PRELOAD', { tabId: 31 });
  while (
    !worker.calls.some(
      ({ method, url }) => method === 'POST' && new URL(url).pathname === '/pages/preload',
    )
  ) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  tab.url = 'https://other.example/unrelated';
  releaseSubmission();

  const response = await completion;
  assert.equal(response.ok, false);
  assert.equal(
    worker.tabMessages.some(({ message }) => message.type === 'SHOW_SENTENCE_PANEL'),
    false,
  );
  assert.equal(worker.state.eraReadingSession, undefined);
});

test('START_PRELOAD rejects a completion after the same user receives a replacement login scope', async () => {
  const pageUrl = 'https://article.example/account-a';
  const tab = { id: 37, url: pageUrl };
  let releaseSubmission;
  const submissionBlocked = new Promise((resolve) => {
    releaseSubmission = resolve;
  });
  const worker = createWorker({
    initialStorage: {
      apiBaseUrl: 'https://api.example.test',
      authSession: {
        accessToken: 'account-a-token',
        user: { id: 'account-a' },
        loginId: 'account-a-login-4',
      },
    },
    tab,
    extraction: {
      ok: true,
      payload: {
        page_url: pageUrl,
        page_title: 'Account A article',
        html: '<main>Account A article text.</main>',
        detected_language: 'en',
        document_nonce: 'document-23',
      },
    },
    onFetch: async ({ key }) => {
      if (key === 'POST /pages/preload') await submissionBlocked;
    },
  });

  const completion = sendWorkerMessage(worker, 'START_PRELOAD', { tabId: 37 });
  while (
    !worker.calls.some(
      ({ method, url }) => method === 'POST' && new URL(url).pathname === '/pages/preload',
    )
  ) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  const replacementSession = await vm.runInContext(
    `setAuthSession({ accessToken: 'replacement-token', user: { id: 'account-a' } })`,
    worker.sandbox,
  );
  assert.notEqual(replacementSession.loginId, 'account-a-login-4');
  releaseSubmission();

  const response = await completion;
  assert.equal(response.ok, false);
  assert.equal(
    worker.tabMessages.some(({ message }) => message.type === 'SHOW_SENTENCE_PANEL'),
    false,
  );
});

test('RESTORE_PAGE_READING_SESSION rejects a same-URL document replacement', async () => {
  const pageUrl = 'https://article.example/reloaded';
  const tab = { id: 41, url: pageUrl, documentNonce: 'document-before-reload' };
  let releaseStatus;
  const statusBlocked = new Promise((resolve) => {
    releaseStatus = resolve;
  });
  const worker = createWorker({
    initialStorage: {
      apiBaseUrl: 'https://api.example.test',
      authSession: {
        accessToken: 'account-a-token',
        user: { id: 'account-a' },
        loginId: 'account-a-login-1',
      },
    },
    responseBodies: {
      'GET /pages/preload': {
        ready: true,
        preload: {
          id: 'preload-reloaded',
          page_url: pageUrl,
          sentences: [{ id: 'sentence-reloaded', text: 'Private article sentence.' }],
        },
      },
    },
    tab,
    onFetch: async ({ key }) => {
      if (key === 'GET /pages/preload') await statusBlocked;
    },
  });

  const completion = sendWorkerMessage(worker, 'RESTORE_PAGE_READING_SESSION', {
    tabId: 41,
    pageUrl,
  });
  while (
    !worker.calls.some(
      ({ method, url }) => method === 'GET' && new URL(url).pathname === '/pages/preload',
    )
  ) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  tab.documentNonce = 'document-after-reload';
  releaseStatus();

  const response = await completion;
  assert.equal(response.ok, true);
  assert.equal(response.restored, false);
  assert.equal(
    worker.tabMessages.some(({ message }) => message.type === 'RESTORE_READING_SESSION'),
    false,
  );
});

test('concurrent logins receive distinct atomic login scopes', async () => {
  const worker = createWorker();
  const sessions = await Promise.all([
    vm.runInContext(
      `setAuthSession({ accessToken: 'first-token', user: { id: 'same-user' } })`,
      worker.sandbox,
    ),
    vm.runInContext(
      `setAuthSession({ accessToken: 'second-token', user: { id: 'same-user' } })`,
      worker.sandbox,
    ),
  ]);

  assert.notEqual(sessions[0].loginId, sessions[1].loginId);
  const currentScope = await vm.runInContext(`getAuthScope()`, worker.sandbox);
  assert.ok([sessions[0].loginId, sessions[1].loginId].includes(currentScope.loginId));
});
