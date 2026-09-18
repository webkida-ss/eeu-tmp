importScripts(
  'generated/api-contract.js',
  'api-contract-runtime.js',
  'settings.js',
  'i18n.js',
  'shared.js',
);

const API_OPERATIONS = UntangleApiContract.operations;
const BACKGROUND_HAS_OWN = Function.call.bind(Object.prototype.hasOwnProperty);
const BACKGROUND_REGEXP_TEST = Function.call.bind(RegExp.prototype.test);
const PUBLIC_QUOTA_MESSAGE_KEYS = Object.freeze([
  'quotaArticleExceeded',
  'quotaChatExceeded',
  'quotaTokenExceeded',
]);

const DEFAULT_SETTINGS = {
  selectionAnalysisEnabled: false,
};

let lastContentTabId = null;

// Keep the worker's UI locale in sync with the native-language setting so
// error messages surface in the learner's language.
getLanguageProfile()
  .then((profile) => setUiLocale(profile.native))
  .catch(() => {});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== 'local') return;
  if (changes.languageProfile) {
    setUiLocale(normalizeLanguageProfile(changes.languageProfile.newValue).native);
  }
  if (changes.authSession || changes.authSessionGeneration) {
    cancelPreload();
    clearPreloadBadge().catch(() => {});
  }
});

function isInjectableUrl(url) {
  return typeof url === 'string' && (url.startsWith('http://') || url.startsWith('https://'));
}

async function rememberContentTab(tabId, tabMaybe) {
  try {
    const tab = tabMaybe || (await chrome.tabs.get(tabId));
    if (isInjectableUrl(tab.url)) {
      lastContentTabId = tab.id;
    }
  } catch {
    if (lastContentTabId === tabId) {
      lastContentTabId = null;
    }
  }
}

chrome.tabs.onActivated.addListener(({ tabId }) => {
  rememberContentTab(tabId).catch(() => {});
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.url || changeInfo.status === 'complete') {
    rememberContentTab(tabId, tab).catch(() => {});
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (lastContentTabId === tabId) {
    lastContentTabId = null;
  }
});

chrome.action.onClicked.addListener((tab) => {
  openOrPreloadInPage(tab).catch((error) => {
    // A newer click/start intentionally supersedes in-flight work — not a failure.
    if (isPreloadCancelledError(error)) return;
    if (!reportContractViolation(error)) {
      console.error('[Untangle] action click failed.');
    }
  });
});

chrome.runtime.onInstalled.addListener(async () => {
  const current = await chrome.storage.local.get(Object.keys(DEFAULT_SETTINGS));
  await chrome.storage.local.set({ ...DEFAULT_SETTINGS, ...current });
});

// Each handler receives the message payload and sender, and returns the
// extra fields merged into the `{ ok: true }` response. Rejections become
// `{ ok: false, error }`.
const messageHandlers = Object.freeze(
  Object.assign(Object.create(null), {
    ANALYZE_SELECTION: async (payload) => ({ analysis: await analyzeSelection(payload) }),
    CHAT_FOLLOW_UP: async (payload) => ({ reply: (await chatFollowUp(payload)).reply }),
    GET_PRELOAD_STATUS: async (payload) => ({ status: await getPreloadStatus(payload?.page_url) }),
    CREATE_PAGE_PRELOAD: async (payload) => ({ preload: await createPagePreload(payload) }),
    START_PRELOAD: async (payload) => ({ preload: await startPreload(payload) }),
    CANCEL_PRELOAD: async () => {
      cancelPreload();
    },
    SET_PRELOAD_BADGE: async (payload) => {
      const text = payload?.text || '';
      await (text ? setPreloadBadge(text) : clearPreloadBadge());
    },
    GET_AUTH_CONFIG: async () => ({ config: await getAuthConfig() }),
    GET_VOCABULARY_BOOK: async () => ({ book: await getVocabularyBook() }),
    GET_BILLING_ME: async () => ({ billing: await getBillingMe() }),
    BILLING_CHECKOUT: async (payload) => ({ checkout: await startBillingCheckout(payload.plan) }),
    BILLING_PORTAL: async () => ({ portal: await openBillingPortal() }),
    LOGIN: async (payload) => ({ session: await login(payload) }),
    LOGOUT: async () => {
      await logout();
    },
    GET_AUTH_SESSION: async () => ({ session: await getAuthSession() }),
    GET_ACTIVE_TAB: async (payload) => ({ tab: await getActiveContentTab(payload) }),
    OPEN_SENTENCE_PANEL: async (payload) => {
      await openSentencePanel(payload);
    },
    RESTORE_PAGE_READING_SESSION: async (payload) => restorePageReadingSession(payload),
    READING_SESSION_READY: async () => {},
    PAGE_FOCUS_REQUEST: async (payload, sender) => {
      await forwardPageFocusRequest(payload, sender.tab?.id);
    },
    PAGE_HIGHLIGHT_STATE: async (payload) => {
      await broadcastPageHighlightState(payload).catch(() => {});
    },
  }),
);

const API_MESSAGE_TYPES = Object.create(null);
for (const type of [
  'ANALYZE_SELECTION',
  'CHAT_FOLLOW_UP',
  'GET_PRELOAD_STATUS',
  'CREATE_PAGE_PRELOAD',
  'START_PRELOAD',
  'GET_AUTH_CONFIG',
  'GET_VOCABULARY_BOOK',
  'GET_BILLING_ME',
  'BILLING_CHECKOUT',
  'BILLING_PORTAL',
  'LOGIN',
  'LOGOUT',
  'OPEN_SENTENCE_PANEL',
  'RESTORE_PAGE_READING_SESSION',
]) {
  API_MESSAGE_TYPES[type] = true;
}
Object.freeze(API_MESSAGE_TYPES);

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const messageType = typeof message?.type === 'string' ? message.type : '';
  const handler = BACKGROUND_HAS_OWN(messageHandlers, messageType)
    ? messageHandlers[messageType]
    : null;
  if (!handler) {
    return false;
  }

  handler(message.payload, sender)
    .then((result) => sendResponse({ ok: true, ...(result || {}) }))
    .catch((error) => {
      if (BACKGROUND_HAS_OWN(API_MESSAGE_TYPES, messageType)) {
        reportApiFailure(error);
        sendResponse({ ok: false, error: publicApiErrorMessage(error) });
        return;
      }
      sendResponse({
        ok: false,
        error: toUserFacingErrorMessage(error, error.message || t('preloadFailed')),
      });
    });
  return true;
});

function safeApiOperationId(error) {
  return BACKGROUND_HAS_OWN(API_OPERATIONS, error?.operationId)
    ? error.operationId
    : 'unknownOperation';
}

function reportContractViolation(error) {
  if (error?.name !== 'ApiContractViolationError') return false;
  const operationId = safeApiOperationId(error);
  const reason =
    typeof error.reason === 'string' && BACKGROUND_REGEXP_TEST(/^[a-z0-9-]+$/, error.reason)
      ? error.reason
      : 'unknown-reason';
  console.error('[Untangle] API contract violation', { operationId, reason });
  return true;
}

function reportApiFailure(error) {
  if (reportContractViolation(error)) return;
  let kind = 'internal';
  if (error?.name === 'ApiNetworkError') kind = 'network';
  if (error?.name === 'ApiDeclaredError') kind = 'http';
  if (error?.name === 'ApiBodyError') kind = 'body';
  console.error('[Untangle] API request failed', {
    operationId: safeApiOperationId(error),
    kind,
  });
}

function publicApiErrorMessage(error) {
  if (error?.name === 'ApiContractViolationError') return t('apiContractError');
  if (error?.name === 'ApiDeclaredError') {
    for (let index = 0; index < PUBLIC_QUOTA_MESSAGE_KEYS.length; index += 1) {
      const message = t(PUBLIC_QUOTA_MESSAGE_KEYS[index]);
      if (error.message === message) return message;
    }
  }
  return t('apiFailure');
}

async function apiFetch(operation, options = {}) {
  const apiBaseUrl = await getApiBaseUrl();
  const { authenticated = true, query, ...fetchOptions } = options;
  const authHeaders = authenticated ? await getAuthHeaders() : {};
  const headers = {
    'Content-Type': 'application/json',
    ...authHeaders,
    ...(fetchOptions.headers || {}),
  };
  const requestUrl = `${apiBaseUrl}${UntangleApiContractRuntime.buildPath(operation, query)}`;
  const requestOptions = {
    ...fetchOptions,
    method: UntangleApiContractRuntime.methodFor(operation),
    headers,
  };

  let response;
  try {
    response = await fetch(requestUrl, requestOptions);
  } catch {
    throw new UntangleApiContractRuntime.ApiNetworkError(operation);
  }
  UntangleApiContractRuntime.inspectResponse(operation, response);
  // Stale tokens linger in storage after backend/session resets (common in
  // local DynamoDB). Clear them so the next click can open the login UI.
  if (response.status === 401 && authHeaders.Authorization) {
    await clearAuthSession();
  }
  return response;
}

async function consumeApiResponse(operation, response, fallback) {
  return UntangleApiContractRuntime.consumeResponse(
    operation,
    response,
    readApiErrorMessage,
    fallback,
  );
}

function isAuthError(error) {
  return isAuthErrorMessage(error?.message || error);
}

function isPreloadCancelledError(error) {
  return String(error?.message || '') === t('preloadCancelled');
}

async function openInPagePanelShell(tabId) {
  await chrome.tabs.sendMessage(tabId, { type: 'OPEN_READING_PANEL' }).catch(() => {});
}

async function getPreloadStatus(pageUrl, expectedScope = null) {
  if (!pageUrl) {
    return { ready: false };
  }
  const authScope = expectedScope || (await getAuthScope());
  if (!authScope || !(await authScopeMatches(authScope))) {
    throw new Error(t('preloadCancelled'));
  }

  const operation = API_OPERATIONS.getPagePreload;
  const response = await apiFetch(operation, { query: { page_url: pageUrl } });
  const status = await consumeApiResponse(operation, response, 'Failed to fetch preload status.');
  if (!(await authScopeMatches(authScope))) throw new Error(t('preloadCancelled'));
  return status;
}

// Preload is asynchronous server-side: POST submits the job (fast: text
// extraction only, so it never hits API Gateway's 30-second cap) and the
// analysis runs on a worker. We then poll GET until the record is ready or
// failed. A record with no `status` is a legacy synchronous response and is
// already complete.
const PRELOAD_POLL_INTERVAL_MS = 3000;
const PRELOAD_POLL_TIMEOUT_MS = 5 * 60 * 1000;

// Cancellation is cooperative: CANCEL_PRELOAD bumps this generation so the
// active poll loop stops. The job keeps running server-side (there is no
// cancel endpoint); that is acceptable — the next status poll or resubmit
// picks up the finished record.
let preloadPollGeneration = 0;

async function createPagePreload(payload, authScope = null) {
  const operation = API_OPERATIONS.createPagePreload;
  const response = await runIdempotentRequest(payload, (requestPayload) =>
    apiFetch(operation, {
      body: JSON.stringify(requestPayload),
    }),
  );

  const submitted = await consumeApiResponse(operation, response, 'Failed to preload page.');
  const record = submitted?.preload || submitted;

  // Legacy synchronous backend (no status): the record is already the result.
  const status = submitted?.status ?? record?.status ?? null;
  if (status === null || status === 'ready') {
    return record;
  }

  return pollPreloadUntilReady(payload.page_url, authScope);
}

async function pollPreloadUntilReady(pageUrl, authScope = null) {
  // Adopt the current generation. Only cancelPreload() bumps it — starting a
  // poll must not cancel a sibling wait on the same in-flight server job.
  const generation = preloadPollGeneration;
  const deadline = Date.now() + PRELOAD_POLL_TIMEOUT_MS;

  while (Date.now() < deadline) {
    if (generation !== preloadPollGeneration) {
      throw new Error(t('preloadCancelled'));
    }

    const statusResponse = await getPreloadStatus(pageUrl, authScope);
    const recordStatus = statusResponse?.status ?? statusResponse?.preload?.status ?? null;

    if (statusResponse?.ready && statusResponse.preload) {
      return statusResponse.preload;
    }
    if (recordStatus === 'failed') {
      const detail = statusResponse?.error || statusResponse?.preload?.error;
      throw new Error(detail || t('preloadFailedStatus'));
    }

    await sleep(PRELOAD_POLL_INTERVAL_MS);

    if (generation !== preloadPollGeneration) {
      throw new Error(t('preloadCancelled'));
    }
  }

  throw new Error(t('preloadFailedStatus'));
}

async function openSentencePanel({ tabId, pageUrl }) {
  const authScope = await getAuthScope();
  if (!authScope) throw new Error(t('preloadNeedLogin'));
  const documentContext = await getContentDocumentContext(tabId, pageUrl);
  if (!documentContext) throw new Error(t('errNoPreloadData'));
  const status = await getPreloadStatus(pageUrl, authScope);
  if (!status?.ready || !status.preload || !(await authScopeMatches(authScope))) {
    throw new Error(t('errNoPreloadData'));
  }

  if (
    !(await deliverPreloadToDocument({
      tabId,
      pageUrl,
      preload: status.preload,
      authScope,
      documentContext,
    }))
  ) {
    throw new Error(t('errNoPreloadData'));
  }
}

let openOrPreloadInFlight = null;

async function openOrPreloadInPage(tab) {
  if (!tab?.id || !isInjectableUrl(tab.url)) {
    return;
  }

  // Collapse overlapping action handlers onto one preload run, but always
  // re-show the panel so a second click is never a no-op while waiting.
  if (openOrPreloadInFlight) {
    await ensureContentScript(tab.id).catch(() => {});
    await openInPagePanelShell(tab.id);
    return openOrPreloadInFlight;
  }

  openOrPreloadInFlight = openOrPreloadInPageImpl(tab).finally(() => {
    openOrPreloadInFlight = null;
  });
  return openOrPreloadInFlight;
}

async function openOrPreloadInPageImpl(tab) {
  await rememberContentTab(tab.id, tab);
  await ensureContentScript(tab.id);

  const pageUrl = normalizePageUrl(tab.url);

  // Open the panel immediately. Network / preload can take minutes; the click
  // must never feel like a no-op while we wait on the API.
  await openInPagePanelShell(tab.id);

  const restoreResponse = await chrome.tabs
    .sendMessage(tab.id, {
      type: 'RESTORE_READING_SESSION',
      payload: { localOnly: true },
    })
    .catch(() => null);

  if (restoreResponse?.ok && restoreResponse.preload?.sentences?.length) {
    return;
  }

  const authScope = await getAuthScope();
  const documentContext = await getContentDocumentContext(tab.id, pageUrl);
  if (!authScope || !documentContext) {
    return;
  }

  let status;
  try {
    status = await getPreloadStatus(pageUrl, authScope);
  } catch (error) {
    if (isAuthError(error) || !(await authScopeMatches(authScope))) {
      return;
    }
    // Panel is already open; fall through and try a fresh preload.
  }

  if (status?.ready && status.preload?.sentences?.length) {
    await deliverPreloadToDocument({
      tabId: tab.id,
      pageUrl,
      preload: status.preload,
      authScope,
      documentContext,
    });
    return;
  }

  const recordStatus = status?.status ?? status?.preload?.status ?? null;
  if (recordStatus === 'processing') {
    // Join the server job already running — do not POST/cancel again.
    await globalThis.updatePreloadJob(pageUrl, {
      state: 'loading',
      message: t('preloadSplitting'),
    });
    await setPreloadBadge('…');
    try {
      const preload = await pollPreloadUntilReady(pageUrl, authScope);
      const sentenceCount = preload?.sentences?.length || 0;
      await globalThis.updatePreloadJob(pageUrl, {
        state: 'ready',
        message: t('preloadDonePanel', { count: sentenceCount }),
        sentenceCount,
      });
      await clearPreloadBadge();
      await deliverPreloadToDocument({
        tabId: tab.id,
        pageUrl,
        preload,
        authScope,
        documentContext,
      });
    } catch (error) {
      await clearPreloadBadge();
      if (isAuthError(error) || isPreloadCancelledError(error)) {
        return;
      }
      throw error;
    }
    return;
  }

  if (!(await authScopeMatches(authScope))) {
    return;
  }

  try {
    await startPreload({ tabId: tab.id });
  } catch (error) {
    if (isAuthError(error) || isPreloadCancelledError(error)) {
      return;
    }
    throw error;
  }
}

async function restorePageReadingSession({ tabId, pageUrl } = {}) {
  const resolvedTabId = tabId || lastContentTabId || (await getActiveTabId());
  if (!resolvedTabId) {
    return { restored: false };
  }

  await rememberContentTab(resolvedTabId);
  const authScope = await getAuthScope();
  if (!authScope || !pageUrl) return { restored: false };
  await ensureContentScript(resolvedTabId);
  const originatingDocument = await getContentDocumentContext(resolvedTabId, pageUrl);
  if (!originatingDocument || !(await authScopeMatches(authScope))) {
    return { restored: false };
  }

  let status;
  try {
    status = await getPreloadStatus(pageUrl, authScope);
  } catch {
    status = null;
  }

  const currentDocument = await getContentDocumentContext(resolvedTabId, pageUrl);
  if (
    !currentDocument ||
    currentDocument.documentNonce !== originatingDocument.documentNonce ||
    !(await authScopeMatches(authScope))
  ) {
    return { restored: false };
  }

  try {
    const response = await chrome.tabs.sendMessage(resolvedTabId, {
      type: 'RESTORE_READING_SESSION',
      payload: {
        localOnly: true,
        preload: status?.ready ? status.preload : null,
        pageUrl: originatingDocument.pageUrl,
        authScope,
        documentNonce: originatingDocument.documentNonce,
      },
    });
    return {
      restored: Boolean(response?.ok),
      preload: response?.preload || status?.preload || null,
    };
  } catch {
    return { restored: false, needsPageRefresh: true, preload: status?.preload || null };
  }
}

async function restoreReadingSessionsOnOpenTabs() {
  const session = await getAuthSession();
  if (!session?.accessToken) {
    return;
  }

  const tabs = await chrome.tabs.query({});
  await Promise.all(
    tabs.map(async (tab) => {
      if (!tab.id || !isInjectableUrl(tab.url)) return;
      try {
        await restorePageReadingSession({
          tabId: tab.id,
          pageUrl: normalizePageUrl(tab.url),
        });
      } catch {
        // Ignore tabs that still run an invalidated content script until refresh.
      }
    }),
  );
}

async function getActiveTabId() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  return tab?.id || null;
}

async function findContentTabByPageUrl(pageUrl) {
  if (!pageUrl) return null;
  const normalizedPageUrl = normalizePageUrl(pageUrl);

  if (lastContentTabId) {
    try {
      const tab = await chrome.tabs.get(lastContentTabId);
      if (tab?.id && isInjectableUrl(tab.url) && normalizePageUrl(tab.url) === normalizedPageUrl) {
        return tab;
      }
    } catch {
      lastContentTabId = null;
    }
  }

  const tabs = await chrome.tabs.query({});
  return (
    tabs.find(
      (tab) =>
        tab.id && isInjectableUrl(tab.url) && normalizePageUrl(tab.url) === normalizedPageUrl,
    ) || null
  );
}

async function forwardPageFocusRequest(payload, tabId) {
  if (!payload?.pageUrl) return;

  let resolvedTabId = tabId || payload.tabId || null;
  if (!resolvedTabId) {
    const tab = await findContentTabByPageUrl(payload.pageUrl);
    resolvedTabId = tab?.id || null;
  }
  if (!resolvedTabId) return;

  await rememberContentTab(resolvedTabId);
  await chrome.tabs.sendMessage(resolvedTabId, {
    type: 'PAGE_FOCUS_REQUEST',
    payload,
  });
}

async function broadcastPageHighlightState(payload) {
  if (!payload?.pageUrl) return;

  const tabs = await chrome.tabs.query({});
  await Promise.all(
    tabs.map(async (tab) => {
      if (!tab.id || !tab.url || tab.url.startsWith('chrome://')) return;
      if (normalizePageUrl(tab.url) !== normalizePageUrl(payload.pageUrl)) return;
      try {
        await chrome.tabs.sendMessage(tab.id, {
          type: 'PAGE_HIGHLIGHT_STATE',
          payload,
        });
      } catch {
        // Ignore tabs without the content script.
      }
    }),
  );
}

let currentPreload = null; // { tabId, aborted, promise }

async function clearPreloadBadge() {
  try {
    await chrome.action.setBadgeText({ text: '' });
  } catch {
    // Ignore when the action badge is unavailable.
  }
}

async function setPreloadBadge(text) {
  try {
    await chrome.action.setBadgeText({ text });
  } catch {
    // Ignore when the action badge is unavailable.
  }
}

function cancelPreload() {
  // Stop any active status polling (the server-side job keeps running).
  preloadPollGeneration += 1;

  if (!currentPreload) return;

  currentPreload.aborted = true;
  if (currentPreload.tabId) {
    chrome.tabs.sendMessage(currentPreload.tabId, { type: 'CANCEL_PAGE_PRELOAD' }).catch(() => {});
  }
  currentPreload = null;
}

function isCurrentPreloadActive(tabId) {
  return Boolean(
    currentPreload &&
    !currentPreload.aborted &&
    currentPreload.tabId === tabId &&
    currentPreload.promise,
  );
}

async function getActiveContentTab({ pageUrl } = {}) {
  if (pageUrl) {
    const tab = await findContentTabByPageUrl(pageUrl);
    if (tab?.id) {
      lastContentTabId = tab.id;
      return tab;
    }
  }

  if (lastContentTabId) {
    try {
      const tab = await chrome.tabs.get(lastContentTabId);
      if (isInjectableUrl(tab.url)) {
        return tab;
      }
    } catch {
      lastContentTabId = null;
    }
  }

  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!tab?.id || !isInjectableUrl(tab.url)) {
    throw new Error(t('errNeedWebPage'));
  }

  lastContentTabId = tab.id;
  return tab;
}

async function pingContentScript(tabId) {
  try {
    const response = await chrome.tabs.sendMessage(tabId, { type: 'PING' });
    return Boolean(response?.ok);
  } catch {
    return false;
  }
}

async function getContentDocumentContext(tabId, expectedPageUrl) {
  if (!tabId || !expectedPageUrl) return null;
  try {
    const [tab, response] = await Promise.all([
      chrome.tabs.get(tabId),
      chrome.tabs.sendMessage(tabId, { type: 'PING' }),
    ]);
    if (
      !isInjectableUrl(tab?.url) ||
      !response?.ok ||
      typeof response.documentNonce !== 'string' ||
      !response.documentNonce ||
      !pageUrlsMatch(tab.url, expectedPageUrl) ||
      !pageUrlsMatch(response.pageUrl, expectedPageUrl)
    ) {
      return null;
    }
    return { documentNonce: response.documentNonce, pageUrl: normalizePageUrl(expectedPageUrl) };
  } catch {
    return null;
  }
}

async function deliverPreloadToDocument({ tabId, pageUrl, preload, authScope, documentContext }) {
  if (!authScope || !(await authScopeMatches(authScope))) return false;
  if (!isValidStoredPreload(preload, pageUrl)) return false;
  const currentDocument = await getContentDocumentContext(tabId, pageUrl);
  if (
    !currentDocument ||
    currentDocument.documentNonce !== documentContext?.documentNonce ||
    !pageUrlsMatch(currentDocument.pageUrl, pageUrl) ||
    !(await authScopeMatches(authScope))
  ) {
    return false;
  }
  const response = await chrome.tabs.sendMessage(tabId, {
    type: 'SHOW_SENTENCE_PANEL',
    payload: {
      preload,
      pageUrl: currentDocument.pageUrl,
      authScope,
      documentNonce: currentDocument.documentNonce,
    },
  });
  return Boolean(response?.ok);
}

async function waitForContentScript(tabId, { attempts = 8, delayMs = 150 } = {}) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    if (await pingContentScript(tabId)) {
      return true;
    }
    if (attempt < attempts - 1) {
      await sleep(delayMs);
    }
  }
  return false;
}

async function injectReadingAssistantScripts(tabId) {
  let baseReady;
  let contentReady;
  try {
    const [result] = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => {
        try {
          const runtimeId = chrome.runtime.id || '';
          return {
            baseReady:
              typeof globalThis.getSelectionAnalysisEnabled === 'function' &&
              typeof globalThis.t === 'function' &&
              typeof globalThis.renderContextChat === 'function',
            contentReady:
              Boolean(runtimeId) && globalThis.__ERA_READING_ASSISTANT_RUNTIME__ === runtimeId,
          };
        } catch {
          return { baseReady: false, contentReady: false };
        }
      },
    });
    baseReady = Boolean(result?.result?.baseReady);
    contentReady = Boolean(result?.result?.contentReady);
  } catch {
    baseReady = false;
    contentReady = false;
  }

  if (contentReady) {
    return;
  }

  await chrome.scripting.executeScript({
    target: { tabId },
    files: baseReady ? ['content.js'] : ['settings.js', 'i18n.js', 'shared.js', 'content.js'],
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function ensureContentScript(tabId) {
  if (await waitForContentScript(tabId)) {
    return;
  }

  const tab = await chrome.tabs.get(tabId);
  if (!isInjectableUrl(tab.url)) {
    throw new Error(t('errPageNotPreloadable'));
  }

  await injectReadingAssistantScripts(tabId);

  if (!(await waitForContentScript(tabId, { attempts: 10, delayMs: 200 }))) {
    throw new Error(t('errInjectFailed'));
  }
}

async function startPreload({ tabId }) {
  // Same-tab overlaps should join the existing run instead of cancelling it
  // (action double-clicks and panel+icon races were surfacing as cancelled).
  if (isCurrentPreloadActive(tabId)) {
    return currentPreload.promise;
  }

  cancelPreload();

  const preloadSession = { tabId, aborted: false, promise: null };
  currentPreload = preloadSession;

  const promise = runStartPreload(preloadSession);
  preloadSession.promise = promise;
  return promise;
}

async function runStartPreload(preloadSession) {
  const { tabId } = preloadSession;
  let pageUrl = null;
  let authScope;
  let documentContext;

  try {
    await rememberContentTab(tabId);
    await ensureContentScript(tabId);

    authScope = await getAuthScope();
    if (!authScope) {
      throw new Error(t('preloadNeedLogin'));
    }

    // Keep the tabs channel short-lived: only extract HTML from the page.
    // Long-running create/poll stays in the background service worker so we
    // never nest chrome.runtime.sendMessage under an open tabs.sendMessage.
    const extracted = await chrome.tabs.sendMessage(tabId, { type: 'EXTRACT_PAGE_HTML' });
    if (preloadSession.aborted) {
      throw new Error(t('preloadCancelled'));
    }
    if (!extracted?.ok || !extracted.payload) {
      throw new Error(extracted?.error || t('preloadFailed'));
    }

    pageUrl = normalizePageUrl(extracted.payload.page_url);
    documentContext = {
      documentNonce: extracted.payload.document_nonce,
      pageUrl,
    };
    if (
      !documentContext.documentNonce ||
      !(await authScopeMatches(authScope)) ||
      !(await getContentDocumentContext(tabId, pageUrl)) ||
      !pageUrlsMatch(extracted.payload.page_url, pageUrl)
    ) {
      throw new Error(t('preloadCancelled'));
    }
    await globalThis.updatePreloadJob(pageUrl, {
      state: 'loading',
      message: t('preloadSplitting'),
    });
    await setPreloadBadge('…');

    const learnerProfile = await getLearnerProfile();
    const languageProfile = await getLanguageProfile();
    const targetLanguage =
      languageProfile.target === AUTO_TARGET_LANGUAGE
        ? extracted.payload.detected_language || getDefaultLanguageProfile().target
        : languageProfile.target;

    const preload = await createPagePreload(
      withOperationId({
        page_url: extracted.payload.page_url,
        page_title: extracted.payload.page_title,
        html: extracted.payload.html,
        learner_level: formatLearnerLevelForApi(learnerProfile),
        vocabulary_coverage_percent: getVocabularyCoveragePercent(learnerProfile),
        target_language: targetLanguage,
        native_language: languageProfile.native,
      }),
      authScope,
    );

    if (preloadSession.aborted || !(await authScopeMatches(authScope))) {
      throw new Error(t('preloadCancelled'));
    }

    const currentLearnerProfile = await getLearnerProfile();
    if (!learnerProfileRevisionMatches(learnerProfile, currentLearnerProfile)) {
      throw new Error(t('preloadCancelled'));
    }

    const sentenceCount = preload?.sentences?.length || 0;
    await globalThis.updatePreloadJob(pageUrl, {
      state: 'ready',
      message: t('preloadDonePanel', { count: sentenceCount }),
      sentenceCount,
    });
    await clearPreloadBadge();

    if (
      !(await deliverPreloadToDocument({
        tabId,
        pageUrl,
        preload,
        authScope,
        documentContext,
      }))
    ) {
      throw new Error(t('preloadCancelled'));
    }

    return preload;
  } catch (error) {
    await clearPreloadBadge();
    if (pageUrl) {
      const cancelled = preloadSession.aborted || isPreloadCancelledError(error);
      await globalThis
        .updatePreloadJob(pageUrl, {
          state: cancelled ? 'idle' : 'error',
          message: cancelled
            ? t('preloadAborted')
            : toUserFacingErrorMessage(error, t('preloadFailed')),
        })
        .catch(() => {});
    }
    throw error;
  } finally {
    if (currentPreload === preloadSession) {
      currentPreload = null;
    }
  }
}

async function analyzeSelection(payload) {
  const authScope = await getAuthScope();
  if (!authScope) throw new Error(t('preloadNeedLogin'));
  if (!payload.page_preload_id && payload.page_url) {
    const status = await getPreloadStatus(payload.page_url);
    if (status?.ready && status.preload?.id) {
      payload.page_preload_id = status.preload.id;
    }
  }

  const operation = API_OPERATIONS.analyzeText;
  const response = await runIdempotentRequest(payload, (requestPayload) =>
    apiFetch(operation, {
      body: JSON.stringify(requestPayload),
    }),
  );

  const analysis = await consumeApiResponse(operation, response, 'Failed to analyze text.');
  if (!(await authScopeMatches(authScope))) throw new Error(t('preloadCancelled'));
  return analysis;
}

async function chatFollowUp(payload) {
  const authScope = await getAuthScope();
  if (!authScope) throw new Error(t('preloadNeedLogin'));
  const operation = API_OPERATIONS.createChatReply;
  const response = await runIdempotentRequest(payload, (requestPayload) =>
    apiFetch(operation, {
      body: JSON.stringify(requestPayload),
    }),
  );

  const reply = await consumeApiResponse(operation, response, 'Failed to send chat message.');
  if (!(await authScopeMatches(authScope))) throw new Error(t('preloadCancelled'));
  return reply;
}

// Reports which sign-in flow the server expects: the mock provider (local
// development) or Google SSO. The panel decides its login UI from this.
async function getAuthConfig() {
  const operation = API_OPERATIONS.getAuthConfig;
  const response = await apiFetch(operation, { authenticated: false });
  return consumeApiResponse(operation, response, 'Failed to fetch auth config.');
}

// Vocabulary aggregated across every preloaded article for the signed-in
// user, newest article first.
async function getBillingMe() {
  const operation = API_OPERATIONS.getBillingSummary;
  const response = await apiFetch(operation);
  return consumeApiResponse(operation, response, 'Failed to fetch plan info.');
}

async function startBillingCheckout(plan) {
  const operation = API_OPERATIONS.createBillingCheckout;
  const response = await apiFetch(operation, {
    body: JSON.stringify({ plan }),
  });
  return consumeApiResponse(operation, response, 'Failed to start checkout.');
}

async function openBillingPortal() {
  const operation = API_OPERATIONS.openBillingPortal;
  const response = await apiFetch(operation);
  return consumeApiResponse(operation, response, 'Failed to open the billing portal.');
}

async function getVocabularyBook() {
  const operation = API_OPERATIONS.getVocabularyBook;
  const response = await apiFetch(operation);
  return consumeApiResponse(operation, response, 'Failed to fetch the vocabulary book.');
}

// `credential` is provider-specific: a Google ID token, or "mock:<email>"
// with the local mock provider. The server verifies it and issues a session.
async function login(payload = {}) {
  const operation = API_OPERATIONS.createAuthSession;
  const response = await apiFetch(operation, {
    authenticated: false,
    body: JSON.stringify({ credential: payload.credential }),
  });

  const session = await consumeApiResponse(operation, response, 'Failed to sign in.');
  await setAuthSession({
    accessToken: session.access_token,
    user: session.user,
  });
  return session;
}

async function logout() {
  const session = await getAuthSession();
  if (session?.accessToken) {
    try {
      const operation = API_OPERATIONS.closeAuthSession;
      const response = await apiFetch(operation);
      await consumeApiResponse(operation, response, 'Failed to sign out.');
    } catch {
      // Clear local session even when the server is unavailable.
    }
  }
  await clearAuthSession();
}

restoreReadingSessionsOnOpenTabs().catch(() => {});

// --- Dev auto-reload (unpacked installs only) --------------------------------
// Connects to the local reload server (extension/dev/reload-server.mjs) and
// reloads the extension whenever it broadcasts a change. The server's
// periodic pings keep this service worker alive, so the connection persists.
// On store installs (installType !== 'development') this never runs, and
// when the server is down the retry loop stays silent.
const DEV_RELOAD_URL = 'ws://127.0.0.1:18766';

async function connectDevReload() {
  const self = await chrome.management.getSelf();
  if (self.installType !== 'development') return;

  const connect = () => {
    let socket;
    try {
      socket = new WebSocket(DEV_RELOAD_URL);
    } catch {
      setTimeout(connect, 10000);
      return;
    }
    socket.onmessage = (event) => {
      if (event.data === 'reload') {
        chrome.runtime.reload();
        return;
      }
      // Server pings arrive every 20s. WebSocket traffic alone does not
      // reset this service worker's 30s idle timer, but any extension API
      // call does — so each ping doubles as a keepalive and the connection
      // survives indefinitely.
      chrome.runtime.getPlatformInfo();
    };
    socket.onclose = () => setTimeout(connect, 10000);
  };
  connect();
}

connectDevReload().catch(() => {});
