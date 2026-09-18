var POPUP_ID = 'untangle-popup';
var IN_PAGE_PANEL_ID = 'untangle-panel';
var LAUNCHER_ID = 'untangle-launcher';
var SELECTED_CLASS = 'untangle-active';
var MIN_SELECTION_LENGTH = 2;
var MAX_SELECTION_LENGTH = 3000;
var MAX_PAGE_HTML_LENGTH = 500000;

var currentText = '';
var currentAnalysis = null;
var lastSelectionRect = null;
var debounceTimer = null;
var activePreload = null;
var sentenceDomLinks = new Map();
var activeSentenceId = null;
var hoveredSentenceId = null;
var activeStudyItemId = null;
var activeSentenceScreen = 'list';
var vocabularyHighlightMarks = [];
var sentenceHighlightMarks = [];
var pagePreloadController = null;
var pagePreloadGeneration = 0;
var pageAnchorSyncRetryTimer = null;
var pageAnchorPersistInProgress = false;
var launcherThemeListenersBound = false;
var launcherThemeRefreshTimer = null;
var inPagePanelResizeState = null;
var hoverPersistTimer = null;
var activeReadingScope = null;
var contentDocumentNonce = generateUuidV7();

var LAUNCHER_SAMPLE_OFFSET_X = 60;
var LAUNCHER_SAMPLE_OFFSET_Y = 40;
var LAUNCHER_DARK_LUMINANCE_THRESHOLD = 0.42;

// Kept in sync with storage so synchronous payload builders can read it.
var languageProfile = getDefaultLanguageProfile();

// Off by default: gates the ad-hoc "analyze whatever text I just selected"
// popup flow so ordinary text selection (including double-click word
// selection) does not trigger an uninvited analysis on every page. Reusing
// an already-preloaded article's sentences from the reading panel is not
// gated by this — that only fires for text that came from the loaded
// preload, which the learner already explicitly requested.
var selectionAnalysisEnabled = false;

var activeExtensionRuntimeId = (() => {
  try {
    return chrome.runtime.id || '';
  } catch {
    return '';
  }
})();

// Named handlers live at module scope so teardownOrphanedInstance (also
// module scope) can unregister them when the extension context dies.
var handleDocumentMouseUp = (event) => {
  if (!ensureLiveExtensionContext()) return;
  if (isEventInExtensionUi(event)) return;

  window.clearTimeout(debounceTimer);
  debounceTimer = window.setTimeout(() => {
    handleSelection().catch((error) => {
      console.error('[Untangle] handleSelection failed:', error);
    });
  }, 180);
};

var handleDocumentEscape = (event) => {
  if (event.key === 'Escape') closePopup();
};

var handleDocumentMouseDownForPopup = (event) => {
  const popup = document.getElementById(POPUP_ID);
  if (popup && !popup.contains(event.target)) closePopup();
};

if (window.top !== window.self) {
  // Ignore embedded frames (ads, embeds). Untangle only runs on the top-level page.
} else if (
  activeExtensionRuntimeId &&
  globalThis.__ERA_READING_ASSISTANT_RUNTIME__ !== activeExtensionRuntimeId
) {
  globalThis.__ERA_READING_ASSISTANT_RUNTIME__ = activeExtensionRuntimeId;

  document.addEventListener('mouseup', handleDocumentMouseUp);
  document.addEventListener('keydown', handleDocumentEscape);
  document.addEventListener('mousedown', handleDocumentMouseDownForPopup);

  // A fresh injection after an extension reload runs in a new isolated world,
  // but the previous instance's UI nodes survive in the shared DOM (with a
  // dead iframe / dead handlers). Replace them; they are recreated on demand.
  document.getElementById(POPUP_ID)?.remove();
  document.getElementById(IN_PAGE_PANEL_ID)?.remove();
  document.getElementById(LAUNCHER_ID)?.remove();
  document.getElementById('era-inline-gloss')?.remove();

  function safeSendResponse(sendResponse, payload) {
    try {
      sendResponse(payload);
    } catch {
      // The tabs/runtime channel can close before an async reply arrives.
    }
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message.type === 'PING') {
      sendResponse({ ok: true, documentNonce: contentDocumentNonce, pageUrl: getPageUrl() });
      return false;
    }

    if (message.type === 'EXTRACT_PAGE_HTML') {
      try {
        sendResponse({
          ok: true,
          payload: {
            page_url: getPageUrl(),
            page_title: document.title,
            html: extractPageHtml(),
            detected_language: detectPageLanguage(),
            document_nonce: contentDocumentNonce,
          },
        });
      } catch (error) {
        sendResponse({ ok: false, error: error.message });
      }
      return false;
    }

    if (message.type === 'PAGE_FOCUS_REQUEST') {
      handlePageFocusRequest(message.payload);
      sendResponse({ ok: true });
      return false;
    }

    if (message.type === 'PAGE_HIGHLIGHT_STATE') {
      applyReadingHighlightState(message.payload);
      sendResponse({ ok: true });
      return false;
    }

    if (message.type === 'SHOW_SENTENCE_PANEL') {
      Promise.resolve(
        publishReadingSession(message.payload?.preload, {
          openPanel: true,
          authScope: message.payload?.authScope,
          documentNonce: message.payload?.documentNonce,
          pageUrl: message.payload?.pageUrl,
        }),
      )
        .then((published) => safeSendResponse(sendResponse, { ok: published }))
        .catch((error) => safeSendResponse(sendResponse, { ok: false, error: error.message }));
      return true;
    }

    if (message.type === 'RUN_PAGE_PRELOAD') {
      runPagePreload()
        .then((preload) => safeSendResponse(sendResponse, { ok: true, preload }))
        .catch((error) => safeSendResponse(sendResponse, { ok: false, error: error.message }));
      return true;
    }

    if (message.type === 'CANCEL_PAGE_PRELOAD') {
      cancelPagePreload();
      sendResponse({ ok: true });
      return false;
    }

    if (message.type === 'OPEN_READING_PANEL') {
      // Local shell open only. Server fetches are owned by the background
      // script so this channel stays short-lived.
      openReadingPanelLocal()
        .then((preload) =>
          safeSendResponse(sendResponse, {
            ok: true,
            hasPreload: Boolean(preload?.sentences?.length),
            preload,
          }),
        )
        .catch((error) => safeSendResponse(sendResponse, { ok: false, error: error.message }));
      return true;
    }

    if (message.type === 'RESTORE_READING_SESSION') {
      restoreReadingSessionFromServer({
        localOnly: Boolean(message.payload?.localOnly),
        preload: message.payload?.preload || null,
        authScope: message.payload?.authScope || null,
        documentNonce: message.payload?.documentNonce || null,
        pageUrl: message.payload?.pageUrl || null,
      })
        .then((preload) =>
          safeSendResponse(sendResponse, {
            ok: Boolean(preload?.sentences?.length),
            preload,
          }),
        )
        .catch((error) => safeSendResponse(sendResponse, { ok: false, error: error.message }));
      return true;
    }

    return false;
  });

  restoreSentencePanel();
  setupPageAnchorInteraction();
  refreshPanelLauncher();
  getLanguageProfile()
    .then((profile) => {
      languageProfile = profile;
      setUiLocale(profile.native);
    })
    .catch(() => {});
  getSelectionAnalysisEnabled()
    .then((enabled) => {
      selectionAnalysisEnabled = enabled;
    })
    .catch(() => {});

  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local') return;

    if (changes.languageProfile) {
      languageProfile = normalizeLanguageProfile(changes.languageProfile.newValue);
      setUiLocale(languageProfile.native);
    }

    if (changes.selectionAnalysisEnabled) {
      selectionAnalysisEnabled = Boolean(changes.selectionAnalysisEnabled.newValue);
    }

    if (changes.learnerProfile || changes.learnerProfileRevision) {
      // A request submitted under the old profile must not publish its result
      // into this page after the learner changes level or notes.
      cancelPagePreload();
    }

    if (changes.panelTheme) {
      const panel = document.getElementById(IN_PAGE_PANEL_ID);
      if (panel) {
        panel.dataset.eraTheme = changes.panelTheme.newValue === 'dark' ? 'dark' : 'light';
      }
    }

    if (changes.authSession || changes.authSessionGeneration) {
      cancelPagePreload();
      clearActiveReadingState();
      return;
    }

    if (Object.keys(changes).some((key) => key.startsWith(READING_SESSION_STORAGE_PREFIX))) {
      applyScopedReadingSessionChange(changes).catch(() => {});
    }

    if (changes.preloadJob) {
      const job = changes.preloadJob.newValue;
      if (job?.pageUrl && pageUrlsMatch(job.pageUrl, getPageUrl()) && job.state === 'ready') {
        refreshPanelLauncher();
      }
    }
  });
} // end __ERA_READING_ASSISTANT_RUNTIME__ init guard

function setPreloadBadge(text) {
  chrome.runtime.sendMessage({ type: 'SET_PRELOAD_BADGE', payload: { text } }).catch(() => {});
}

function cancelPagePreload() {
  pagePreloadGeneration += 1;
  pagePreloadController?.abort();
  pagePreloadController = null;
}

async function runPagePreload() {
  pagePreloadGeneration += 1;
  const generation = pagePreloadGeneration;
  pagePreloadController?.abort();
  pagePreloadController = new AbortController();

  const pageUrl = getPageUrl();
  const authScope = await getAuthScope();

  try {
    await globalThis.updatePreloadJob(pageUrl, {
      state: 'loading',
      message: t('preloadSplitting'),
    });
    setPreloadBadge('…');

    if (!authScope || !(await authScopeMatches(authScope))) {
      throw new Error(t('preloadNeedLogin'));
    }

    const learnerProfile = await getLearnerProfile();
    const learnerLevel = formatLearnerLevelForApi(learnerProfile);
    const response = await chrome.runtime.sendMessage({
      type: 'CREATE_PAGE_PRELOAD',
      payload: withOperationId({
        page_url: pageUrl,
        page_title: document.title,
        html: extractPageHtml(),
        learner_level: learnerLevel,
        vocabulary_coverage_percent: getVocabularyCoveragePercent(learnerProfile),
        ...buildLanguageFields(),
      }),
    });

    if (generation !== pagePreloadGeneration || !(await authScopeMatches(authScope))) {
      throw new Error(t('preloadCancelled'));
    }

    if (!response?.ok) {
      throw new Error(response?.error || t('preloadFailed'));
    }

    const currentLearnerProfile = await getLearnerProfile();
    if (!learnerProfileRevisionMatches(learnerProfile, currentLearnerProfile)) {
      cancelPagePreload();
      throw new Error(t('preloadCancelled'));
    }

    const preload = response.preload;
    const sentenceCount = preload?.sentences?.length || 0;

    await globalThis.updatePreloadJob(pageUrl, {
      state: 'ready',
      message: t('preloadDonePanel', { count: sentenceCount }),
      sentenceCount,
    });
    setPreloadBadge('');
    const published = await publishReadingSession(preload, {
      openPanel: true,
      authScope,
      documentNonce: contentDocumentNonce,
      pageUrl,
    });
    if (!published) throw new Error(t('preloadCancelled'));
    return preload;
  } catch (error) {
    setPreloadBadge('');
    if (error.name === 'AbortError' || generation !== pagePreloadGeneration) {
      await globalThis.updatePreloadJob(pageUrl, {
        state: 'idle',
        message: t('preloadAborted'),
      });
      throw new Error(t('preloadCancelled'), { cause: error });
    }

    await globalThis.updatePreloadJob(pageUrl, {
      state: 'error',
      message: toUserFacingErrorMessage(error, t('preloadFailed')),
    });
    throw error;
  } finally {
    if (generation === pagePreloadGeneration) {
      pagePreloadController = null;
    }
  }
}

async function openReadingPanelFromServer() {
  await restoreReadingSessionFromServer().catch(() => null);
  await openInPageReadingPanel();
}

async function openReadingPanelLocal() {
  const preload = await restoreReadingSessionFromServer({ localOnly: true }).catch(() => null);
  await openInPageReadingPanel();
  return preload;
}

async function applySessionToPage(session) {
  if (!isValidReadingSession(session, getPageUrl(), session?.owner)) return false;
  if (!(await authScopeMatches(session.owner))) return false;

  activePreload = session.preload;
  activeReadingScope = session.owner;
  const ui = session.ui || {};
  activeSentenceId = ui.activeSentenceId || null;
  hoveredSentenceId = ui.hoveredSentenceId || null;
  activeStudyItemId = ui.activeStudyItemId || null;
  activeSentenceScreen = ui.activeSentenceScreen || 'list';
  await syncPageAnchorsFromPreload({ force: true });
  return true;
}

async function applyScopedReadingSessionChange(changes) {
  if (pageAnchorPersistInProgress) return;

  const pageUrl = getPageUrl();
  const authScope = activeReadingScope || (await getAuthScope());
  if (!authScope || !(await authScopeMatches(authScope))) return;

  const key = readingSessionStorageKey(pageUrl, authScope);
  const change = changes[key];
  if (!change) return;

  const nextSession = change.newValue;
  if (isValidReadingSession(nextSession, pageUrl, authScope)) {
    await applySessionToPage(nextSession);
    return;
  }

  if (authScopesMatch(activeReadingScope, authScope)) {
    clearActiveReadingState();
  }
}

async function restoreReadingSessionFromServer({
  localOnly = false,
  preload: providedPreload = null,
  authScope: providedScope = null,
  documentNonce = null,
  pageUrl: providedPageUrl = null,
} = {}) {
  if (!ensureLiveExtensionContext()) return null;
  const pageUrl = getPageUrl();
  const initiatingScope = await getAuthScope();
  if (!initiatingScope) return null;

  const suppliedEnvelope = providedPreload || providedScope || documentNonce || providedPageUrl;
  if (
    suppliedEnvelope &&
    (documentNonce !== contentDocumentNonce ||
      !pageUrlsMatch(providedPageUrl, pageUrl) ||
      !authScopesMatch(providedScope, initiatingScope) ||
      !(await authScopeMatches(initiatingScope)))
  ) {
    return null;
  }

  if (
    activePreload?.sentences?.length &&
    authScopesMatch(activeReadingScope, initiatingScope) &&
    (await authScopeMatches(initiatingScope))
  ) {
    await syncPageAnchorsFromPreload({ force: true });
    schedulePageAnchorSyncRetry();
    return activePreload;
  }
  if (activePreload?.sentences?.length) clearActiveReadingState();

  const session = await getReadingSession(pageUrl, initiatingScope);
  if (session?.preload?.sentences?.length && (await applySessionToPage(session))) {
    schedulePageAnchorSyncRetry();
    return session.preload;
  }

  // Background may supply a server preload so this path does not nest
  // GET_PRELOAD_STATUS under an open tabs.sendMessage channel.
  if (
    providedPreload?.sentences?.length &&
    (await publishReadingSession(providedPreload, {
      authScope: initiatingScope,
      documentNonce,
      pageUrl: providedPageUrl,
    }))
  ) {
    schedulePageAnchorSyncRetry();
    return providedPreload;
  }

  // In-page callers (launcher) may still fetch from the server here.
  if (localOnly) {
    return null;
  }

  const response = await chrome.runtime.sendMessage({
    type: 'GET_PRELOAD_STATUS',
    payload: { page_url: pageUrl },
  });

  if (
    !(await authScopeMatches(initiatingScope)) ||
    !response?.ok ||
    !response.status?.ready ||
    !response.status.preload?.sentences?.length
  ) {
    return null;
  }

  if (
    !(await publishReadingSession(response.status.preload, {
      authScope: initiatingScope,
      documentNonce: contentDocumentNonce,
      pageUrl,
    }))
  ) {
    return null;
  }
  schedulePageAnchorSyncRetry();
  return response.status.preload;
}

function removePanelLauncher() {
  document.getElementById(LAUNCHER_ID)?.remove();
}

function parseRgbColor(value) {
  const match = String(value || '').match(
    /rgba?\(\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)(?:\s*,\s*(\d+(?:\.\d+)?))?\s*\)/,
  );
  if (!match) return null;

  return {
    r: Number(match[1]),
    g: Number(match[2]),
    b: Number(match[3]),
    a: match[4] === undefined ? 1 : Number(match[4]),
  };
}

function relativeLuminance({ r, g, b }) {
  const channels = [r, g, b].map((value) => {
    const normalized = value / 255;
    return normalized <= 0.03928 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function blendOverWhite({ r, g, b, a }) {
  const alpha = Number.isFinite(a) ? a : 1;
  return {
    r: r * alpha + 255 * (1 - alpha),
    g: g * alpha + 255 * (1 - alpha),
    b: b * alpha + 255 * (1 - alpha),
  };
}

function getEffectiveBackgroundColor(element) {
  let node = element;

  while (node && node !== document.documentElement) {
    const backgroundColor = getComputedStyle(node).backgroundColor;
    const parsed = parseRgbColor(backgroundColor);
    if (parsed && parsed.a > 0.08) {
      return blendOverWhite(parsed);
    }
    node = node.parentElement;
  }

  const bodyColor = parseRgbColor(getComputedStyle(document.body).backgroundColor);
  if (bodyColor && bodyColor.a > 0.08) {
    return blendOverWhite(bodyColor);
  }

  const rootColor = parseRgbColor(getComputedStyle(document.documentElement).backgroundColor);
  if (rootColor && rootColor.a > 0.08) {
    return blendOverWhite(rootColor);
  }

  if (window.matchMedia?.('(prefers-color-scheme: dark)').matches) {
    return { r: 15, g: 23, b: 42 };
  }

  return { r: 255, g: 255, b: 255 };
}

function detectLauncherSurfaceTheme() {
  const sampleX = Math.max(0, window.innerWidth - LAUNCHER_SAMPLE_OFFSET_X);
  const sampleY = Math.max(0, window.innerHeight - LAUNCHER_SAMPLE_OFFSET_Y);
  let element = document.elementFromPoint(sampleX, sampleY);

  if (element?.closest(`#${LAUNCHER_ID}, #${POPUP_ID}`) || isNodeInExtensionUi(element)) {
    element = document.body;
  }

  const luminance = relativeLuminance(getEffectiveBackgroundColor(element || document.body));
  return luminance < LAUNCHER_DARK_LUMINANCE_THRESHOLD ? 'dark' : 'light';
}

function applyLauncherTheme(button) {
  const theme = detectLauncherSurfaceTheme();
  button.classList.toggle('era-launcher-on-dark', theme === 'dark');
  button.classList.toggle('era-launcher-on-light', theme === 'light');
}

function detectPageAnchorSurfaceTheme() {
  const sample =
    document.querySelector('.era-page-anchor-block, .w-richtext, article, main') || document.body;
  const luminance = relativeLuminance(getEffectiveBackgroundColor(sample || document.body));
  return luminance < LAUNCHER_DARK_LUMINANCE_THRESHOLD ? 'dark' : 'light';
}

function syncPageAnchorSurfaceTheme() {
  const theme = detectPageAnchorSurfaceTheme();
  document.documentElement.classList.toggle('era-page-anchors-on-dark', theme === 'dark');
}

function scheduleLauncherThemeRefresh() {
  window.clearTimeout(launcherThemeRefreshTimer);
  launcherThemeRefreshTimer = window.setTimeout(() => {
    const button = document.getElementById(LAUNCHER_ID);
    if (button) {
      applyLauncherTheme(button);
    }
    if (document.querySelector('.era-page-anchor')) {
      syncPageAnchorSurfaceTheme();
    }
  }, 120);
}

function bindLauncherThemeListeners() {
  if (launcherThemeListenersBound) return;
  launcherThemeListenersBound = true;

  window.addEventListener('resize', scheduleLauncherThemeRefresh, { passive: true });
  window.addEventListener('scroll', scheduleLauncherThemeRefresh, { passive: true, capture: true });
}

function ensurePanelLauncher() {
  const existing = document.getElementById(LAUNCHER_ID);
  if (existing) {
    applyLauncherTheme(existing);
    bindLauncherThemeListeners();
    return;
  }

  const button = document.createElement('button');
  button.id = LAUNCHER_ID;
  button.type = 'button';
  button.className = 'era-panel-launcher';
  button.textContent = t('launcherLabel');
  button.title = t('launcherTitle');
  button.addEventListener('click', () => {
    openReadingPanelFromServer().catch((error) => {
      console.error('[Untangle] openReadingPanelFromServer failed:', error);
    });
  });
  document.documentElement.appendChild(button);
  applyLauncherTheme(button);
  bindLauncherThemeListeners();
}

async function refreshPanelLauncher() {
  const storedSession = await getReadingSession(getPageUrl());
  if (activePreload?.sentences?.length || storedSession?.preload?.sentences?.length) {
    ensurePanelLauncher();
    return;
  }

  try {
    const response = await chrome.runtime.sendMessage({
      type: 'GET_PRELOAD_STATUS',
      payload: { page_url: getPageUrl() },
    });
    if (response?.ok && response.status?.ready && response.status.preload?.sentences?.length) {
      ensurePanelLauncher();
      return;
    }
  } catch {
    // Ignore status lookup failures.
  }

  removePanelLauncher();
}

async function handleSelection() {
  if (!isExtensionRuntimeAvailable()) return;
  const authScope = await getAuthScope();
  if (!authScope) return;

  const selection = window.getSelection();
  if (isSelectionInExtensionUi(selection)) return;

  const selectedText = selection?.toString().trim() || '';

  if (hasActiveReadingSession() && selectedText.length >= MIN_SELECTION_LENGTH) {
    const domStudyItem = findStudyItemFromDomSelection(selection);
    if (domStudyItem) {
      selectStudyItemFromPage(domStudyItem, { scrollPage: false });
      return;
    }

    const domSentence = findSentenceFromDomSelection(selection);
    if (domSentence) {
      selectSentenceFromPage(domSentence, { scrollPage: false });
      return;
    }
  }

  // Everything past this point analyzes a selection the learner did not
  // already preload (network call or fresh popup) — opt-in only.
  if (!selectionAnalysisEnabled) return;

  if (!selectedText || selectedText.length < MIN_SELECTION_LENGTH) return;
  if (selectedText === currentText && currentAnalysis) return;

  if (selectedText.length > MAX_SELECTION_LENGTH) {
    showPopup({
      state: 'error',
      text: selectedText.slice(0, MAX_SELECTION_LENGTH),
      error: t('popupSelectionTooLong', { max: MAX_SELECTION_LENGTH }),
    });
    return;
  }

  const rect = getSelectionRect(selection);
  if (!rect) return;

  currentText = selectedText;
  currentAnalysis = null;
  lastSelectionRect = rect;

  const cachedSentence = findCachedSentence(selectedText);
  if (cachedSentence) {
    currentAnalysis = toAnalysisResponse(cachedSentence);
    if (hasActiveReadingSession()) {
      selectSentenceFromPage(cachedSentence);
    } else {
      showPopup({
        state: 'success',
        text: cachedSentence.text,
        analysis: currentAnalysis,
        label: t('popupCachedSentence'),
      });
    }
    return;
  }

  showPopup({
    state: 'loading',
    text: selectedText,
    loadingMessage: activePreload ? t('popupAnalyzingSelection') : t('popupAnalyzingNoPreload'),
  });

  const payload = withOperationId({
    text: selectedText,
    page_url: getPageUrl(),
    page_title: document.title,
    ...buildLanguageFields(),
  });
  if (activePreload?.id) {
    payload.page_preload_id = activePreload.id;
  }

  chrome.runtime.sendMessage({ type: 'ANALYZE_SELECTION', payload }, (response) => {
    if (!isExtensionRuntimeAvailable()) return;
    authScopeMatches(authScope).then((scopeStillCurrent) => {
      if (!scopeStillCurrent) return;

      if (chrome.runtime.lastError) {
        showPopup({ state: 'error', text: selectedText, error: chrome.runtime.lastError.message });
        return;
      }

      if (!response?.ok) {
        showPopup({
          state: 'error',
          text: selectedText,
          error: response?.error || t('popupAnalyzeFailed'),
        });
        return;
      }

      currentAnalysis = response.analysis;
      showPopup({ state: 'success', text: selectedText, analysis: response.analysis });
    });
  });
}

async function restoreSentencePanel() {
  await restoreReadingSessionFromServer().catch(() => {});
}

function hasActiveReadingSession() {
  return Boolean(activePreload?.sentences?.length);
}

function isReadingDetailNavigationActive() {
  if (!hasActiveReadingSession()) return false;
  return activeSentenceScreen === 'detail' && Boolean(activeSentenceId);
}

function getReadingDetailAdjacent(direction) {
  if (activeSentenceScreen === 'detail' && activeSentenceId) {
    return getAdjacentSentence(
      activePreload,
      findSentenceById(activePreload, activeSentenceId),
      direction,
    );
  }
  return null;
}

async function navigateReadingDetailAdjacent(direction) {
  const adjacent = getReadingDetailAdjacent(direction);
  if (!adjacent) return false;

  await selectSentenceFromPage(adjacent, { scrollPage: true });
  return true;
}

function handleReadingDetailKeydown(event) {
  if (!ensureLiveExtensionContext()) return;
  if (!isReadingDetailNavigationActive()) return;
  if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
  if (isKeyboardEditableTarget(event.target)) return;
  if (event.target.closest(`#${POPUP_ID}`)) return;

  let direction = null;
  if (event.key === 'ArrowLeft' || event.key === '[') direction = 'prev';
  if (event.key === 'ArrowRight' || event.key === ']') direction = 'next';
  if (!direction || !getReadingDetailAdjacent(direction)) return;

  event.preventDefault();
  navigateReadingDetailAdjacent(direction).catch((error) => {
    console.error('[Untangle] navigateReadingDetailAdjacent failed:', error);
  });
}

function domLinkStatusFromMap(domLinks) {
  return Object.fromEntries(
    [...domLinks.entries()].map(([id, element]) => [id, element instanceof Node]),
  );
}

function relinkSentencesToDom(sentences = activePreload?.sentences || []) {
  sentenceDomLinks = linkSentencesToDom(sentences);
  return sentenceDomLinks;
}

function getSentenceDomElement(sentenceId) {
  const linked = sentenceDomLinks.get(sentenceId);
  return linked instanceof Node ? linked : null;
}

function ensureInPageReadingPanelShell() {
  let panel = document.getElementById(IN_PAGE_PANEL_ID);
  if (panel) {
    bindInPagePanelResize(panel);
    return panel;
  }

  panel = document.createElement('aside');
  panel.id = IN_PAGE_PANEL_ID;
  panel.setAttribute('aria-label', 'Untangle explanations');
  panel.hidden = true;
  panel.innerHTML = `
    <div
      class="era-panel-resizer"
      role="separator"
      aria-label="${escapeHtml(t('resizerAria'))}"
      aria-orientation="vertical"
      aria-valuemin="280"
      aria-valuemax="640"
      tabindex="0"
    ></div>
    <button class="era-panel-close era-page-panel-close" type="button" aria-label="${escapeHtml(t('panelCloseAria'))}">×</button>
    <iframe
      class="era-page-panel-frame"
      title="Untangle"
      src="${chrome.runtime.getURL(`sidepanel.html?pageUrl=${encodeURIComponent(getPageUrl())}`)}"
    ></iframe>
  `;
  panel.querySelector('.era-page-panel-close')?.addEventListener('click', closeInPageReadingPanel);
  bindInPagePanelResize(panel);
  // Async on purpose: the shell is usable immediately and the dark token
  // block in content.css activates once the stored theme resolves. Later
  // changes arrive through the storage.onChanged listener.
  if (typeof getPanelTheme === 'function') {
    getPanelTheme()
      .then((theme) => {
        panel.dataset.eraTheme = theme;
      })
      .catch(() => {});
  }
  document.documentElement.appendChild(panel);
  return panel;
}

function normalizeInPagePanelWidth(width) {
  if (typeof clampPanelWidth === 'function') {
    return clampPanelWidth(width);
  }

  const maxWidth = Math.min(640, window.innerWidth);
  return Math.min(Math.max(Math.round(Number(width) || 360), 280), maxWidth);
}

function applyInPagePanelWidth(panel, width) {
  const normalized = normalizeInPagePanelWidth(width);
  panel.style.width = `${normalized}px`;

  const resizer = panel.querySelector('.era-panel-resizer');
  resizer?.setAttribute('aria-valuenow', String(normalized));

  return normalized;
}

async function restoreInPagePanelWidth(panel) {
  try {
    const width = typeof getPanelWidth === 'function' ? await getPanelWidth() : 360;
    applyInPagePanelWidth(panel, width);
  } catch {
    applyInPagePanelWidth(panel, 360);
  }
}

async function persistInPagePanelWidth(width) {
  const normalized = normalizeInPagePanelWidth(width);
  if (typeof setPanelWidth === 'function') {
    await setPanelWidth(normalized);
    return;
  }
  await chrome.storage.local.set({ panelWidth: normalized });
}

function bindInPagePanelResize(panel) {
  const resizer = panel.querySelector('.era-panel-resizer');
  if (!resizer || resizer.dataset.eraResizeBound === 'true') {
    return;
  }

  resizer.dataset.eraResizeBound = 'true';
  resizer.addEventListener('pointerdown', (event) => {
    if (event.button !== 0) {
      return;
    }

    event.preventDefault();
    const startWidth = panel.getBoundingClientRect().width || normalizeInPagePanelWidth(360);
    inPagePanelResizeState = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startWidth,
      width: startWidth,
    };

    resizer.setPointerCapture(event.pointerId);
    panel.dataset.eraResizing = 'true';
    document.body.classList.add('era-panel-resizing');
  });

  resizer.addEventListener('pointermove', (event) => {
    if (!inPagePanelResizeState || event.pointerId !== inPagePanelResizeState.pointerId) {
      return;
    }

    const nextWidth =
      inPagePanelResizeState.startWidth + inPagePanelResizeState.startX - event.clientX;
    inPagePanelResizeState.width = applyInPagePanelWidth(panel, nextWidth);
  });

  const finishResize = (event) => {
    if (!inPagePanelResizeState || event.pointerId !== inPagePanelResizeState.pointerId) {
      return;
    }

    const width = inPagePanelResizeState.width;
    inPagePanelResizeState = null;
    panel.dataset.eraResizing = 'false';
    document.body.classList.remove('era-panel-resizing');
    persistInPagePanelWidth(width).catch((error) => {
      console.error('[Untangle] persistInPagePanelWidth failed:', error);
    });
  };

  resizer.addEventListener('pointerup', finishResize);
  resizer.addEventListener('pointercancel', finishResize);
}

function closeInPageReadingPanel() {
  const panel = document.getElementById(IN_PAGE_PANEL_ID);
  if (panel) {
    panel.hidden = true;
  }
  refreshPanelLauncher().catch(() => {});
}

async function openInPageReadingPanel() {
  const panel = ensureInPageReadingPanelShell();
  await restoreInPagePanelWidth(panel);
  panel.hidden = false;
  removePanelLauncher();
  return true;
}

function clearActiveReadingState() {
  activePreload = null;
  activeReadingScope = null;
  activeSentenceId = null;
  hoveredSentenceId = null;
  activeStudyItemId = null;
  activeSentenceScreen = 'list';
  sentenceDomLinks = new Map();
  clearPageHighlights();
  closePopup();
  clearContextChats();
}

async function publishReadingSession(
  preload,
  { openPanel = false, authScope = null, documentNonce = null, pageUrl = null } = {},
) {
  const currentPageUrl = getPageUrl();
  if (
    documentNonce !== contentDocumentNonce ||
    !pageUrlsMatch(pageUrl || currentPageUrl, currentPageUrl) ||
    !isValidStoredPreload(preload, currentPageUrl) ||
    !isAuthScope(authScope) ||
    !(await authScopeMatches(authScope))
  ) {
    return false;
  }

  const session = {
    pageUrl: currentPageUrl,
    pageTitle: document.title,
    preload,
    domLinkStatus: domLinkStatusFromMap(sentenceDomLinks),
    ui: {
      activeSentenceId,
      hoveredSentenceId,
      activeStudyItemId,
      activeSentenceScreen,
    },
    updatedAt: Date.now(),
  };

  pageAnchorPersistInProgress = true;
  try {
    if (!(await setReadingSession(session, authScope))) return false;
  } finally {
    pageAnchorPersistInProgress = false;
  }
  if (!(await authScopeMatches(authScope))) return false;

  activePreload = preload;
  activeReadingScope = authScope;
  clearPageHighlights();
  await syncPageAnchorsFromPreload({ force: true });

  if (openPanel) {
    await openInPageReadingPanel(preload);
  }
  chrome.runtime.sendMessage({ type: 'READING_SESSION_READY' }).catch(() => {});
  return true;
}

async function persistReadingDomLinkStatus() {
  if (!ensureLiveExtensionContext()) return;
  if (pageAnchorPersistInProgress) {
    return;
  }

  pageAnchorPersistInProgress = true;
  try {
    const pageUrl = getPageUrl();
    const session = await getReadingSession(pageUrl, activeReadingScope);
    if (!session?.preload?.sentences?.length) {
      return;
    }

    const nextStatus = domLinkStatusFromMap(sentenceDomLinks);
    const previousStatus = session.domLinkStatus || {};
    const unchanged =
      Object.keys(nextStatus).length === Object.keys(previousStatus).length &&
      Object.entries(nextStatus).every(([id, linked]) => previousStatus[id] === linked);

    if (unchanged) {
      return;
    }

    session.domLinkStatus = nextStatus;
    session.updatedAt = Date.now();
    await setReadingSession(session, activeReadingScope);
  } finally {
    pageAnchorPersistInProgress = false;
  }
}

async function syncPageAnchorsFromPreload({ force = false } = {}) {
  if (!activePreload?.sentences?.length) {
    return 0;
  }

  relinkSentencesToDom(activePreload.sentences);
  const appliedBefore = countAppliedSentenceAnchors();
  const mappedCount = [...sentenceDomLinks.values()].filter(Boolean).length;
  const shouldApplyMarkers =
    force || appliedBefore === 0 || (mappedCount > 0 && appliedBefore < mappedCount);

  if (shouldApplyMarkers) {
    applyPageAnchorMarkers();
    applyVocabularyMarkers();
    syncPageAnchorInteractivity();
    removePanelLauncher();
  }

  ensureHighlightsForActiveSentences();
  updatePageHighlights();

  const appliedAfter = countAppliedSentenceAnchors();
  if (appliedAfter > appliedBefore) {
    await persistReadingDomLinkStatus();
  }

  return appliedAfter;
}

function ensureHighlightsForActiveSentences() {
  if (activeSentenceId) {
    const sentence = findSentenceById(activePreload, activeSentenceId);
    if (sentence) {
      ensureSentenceAnchor(sentence);
    }
  }

  if (hoveredSentenceId && hoveredSentenceId !== activeSentenceId) {
    const sentence = findSentenceById(activePreload, hoveredSentenceId);
    if (sentence) {
      ensureSentenceAnchor(sentence);
    }
  }
}

function schedulePageAnchorSyncRetry() {
  window.clearTimeout(pageAnchorSyncRetryTimer);
  pageAnchorSyncRetryTimer = window.setTimeout(async () => {
    if (!ensureLiveExtensionContext()) return;
    if (!activePreload?.sentences?.length) {
      return;
    }

    const appliedBefore = countAppliedSentenceAnchors();
    const total = activePreload.sentences.length;
    if (appliedBefore >= total) {
      return;
    }

    await syncPageAnchorsFromPreload({ force: true });
    if (countAppliedSentenceAnchors() < total) {
      await persistReadingDomLinkStatus();
    }
  }, 1200);
}

async function persistPageReadingUi(extra = {}) {
  if (!ensureLiveExtensionContext()) return;
  if (!hasActiveReadingSession()) return;

  const pageUrl = getPageUrl();
  const session = await getReadingSession(pageUrl, activeReadingScope);
  if (!session) return;

  session.ui = {
    activeSentenceId,
    hoveredSentenceId,
    activeStudyItemId,
    activeSentenceScreen,
    ...extra,
  };
  session.updatedAt = Date.now();
  await setReadingSession(session, activeReadingScope);
}

// Hover events fire rapidly; batch the storage write so every hover does not
// pay a storage round-trip plus the onChanged fan-out to other contexts.
function schedulePersistPageReadingUi() {
  window.clearTimeout(hoverPersistTimer);
  hoverPersistTimer = window.setTimeout(() => {
    persistPageReadingUi().catch(() => {});
  }, 250);
}

async function selectSentenceFromPage(sentence, { scrollPage = false } = {}) {
  if (!sentence) return;

  activeSentenceScreen = 'detail';
  activeSentenceId = sentence.id;
  activeStudyItemId = null;
  currentText = sentence.text;
  currentAnalysis = toAnalysisResponse(sentence);

  if (scrollPage) {
    focusSentenceOnPage(sentence);
  } else {
    updatePageHighlights();
  }

  await persistPageReadingUi();
}

async function selectStudyItemFromPage(item, { scrollPage = false } = {}) {
  if (!item) return;

  activeStudyItemId = item.id;
  currentText = item.text;
  currentAnalysis = null;

  const linkedSentence = findSentenceById(activePreload, item.sentence_ids?.[0]);
  updatePageHighlights();

  if (scrollPage) {
    focusVocabularyOnPage(item, linkedSentence);
  }

  await persistPageReadingUi();
}

function applyReadingHighlightState(payload) {
  if (!payload || !pageUrlsMatch(payload.pageUrl, getPageUrl())) return;

  if (payload.activeSentenceId !== undefined) activeSentenceId = payload.activeSentenceId;
  if (payload.hoveredSentenceId !== undefined) hoveredSentenceId = payload.hoveredSentenceId;
  if (payload.activeStudyItemId !== undefined) activeStudyItemId = payload.activeStudyItemId;
  ensureHighlightsForActiveSentences();
  updatePageHighlights();
}

function handlePageFocusRequest(payload) {
  if (!payload || !pageUrlsMatch(payload.pageUrl, getPageUrl())) return;

  if (payload.type === 'sentence') {
    const sentence = findSentenceById(activePreload, payload.sentenceId);
    if (!sentence) return;
    ensureSentenceAnchor(sentence);
    if (payload.scroll) {
      focusSentenceOnPage(sentence);
      return;
    }
    activeSentenceId = sentence.id;
    updatePageHighlights();
    return;
  }

  if (payload.type === 'vocabulary') {
    const item = getStudyItemById(activePreload, payload.studyItemId);
    const sentence = findSentenceById(activePreload, payload.sentenceId);
    if (item) {
      focusVocabularyOnPage(item, sentence);
    }
  }
}

var EXCLUDED_CONTENT_SELECTOR =
  'nav, header, footer, aside, .entry-meta, .post-meta, .site-header, .site-footer, .widget, .menu, .navigation, .comments, .comment, #comments, .sharedaddy, .jp-relatedposts';
var CONTENT_BLOCK_SELECTOR = 'p, h1, h2, h3, h4, h5, h6, li, blockquote, div';
var FALLBACK_CONTENT_BLOCK_SELECTOR = `${CONTENT_BLOCK_SELECTOR}, section, article, main`;

function isExcludedContentElement(element) {
  return Boolean(element?.closest(EXCLUDED_CONTENT_SELECTOR));
}

function getContentRoot() {
  const dailyDevMarkdown = document.querySelector('[class*="markdown_markdown"]');
  if (dailyDevMarkdown) {
    return dailyDevMarkdown.parentElement || dailyDevMarkdown;
  }

  const articles = [...document.querySelectorAll('article')].filter(
    (element) => !isExcludedContentElement(element),
  );
  if (articles.length) {
    const article =
      articles.find((element) =>
        element.querySelector(
          '.entry-content, .post-content, .article-content, .article-body, [itemprop="articleBody"]',
        ),
      ) || articles[0];

    return (
      article.querySelector(
        '.entry-content, .post-content, .article-content, .article-body, [itemprop="articleBody"]',
      ) || article
    );
  }

  const main = document.querySelector('[role="main"]') || document.querySelector('main');
  if (main) {
    const mainArticleBody = main.querySelector(
      '[class*="markdown_markdown"], .entry-content, .post-content, .article-content, .article-body, [itemprop="articleBody"]',
    );
    if (mainArticleBody) {
      return mainArticleBody.parentElement || mainArticleBody;
    }
    return main;
  }

  return document.body;
}

function getContentBlocks() {
  const root = getContentRoot();
  const candidates = [...root.querySelectorAll(CONTENT_BLOCK_SELECTOR)].filter((element) =>
    isTextBlockElement(element),
  );

  return candidates.filter(
    (element) => !candidates.some((other) => other !== element && other.contains(element)),
  );
}

function getFallbackContentBlocks() {
  const root = getContentRoot();
  return [...root.querySelectorAll(FALLBACK_CONTENT_BLOCK_SELECTOR)].filter((element) => {
    if (element.closest(`#${POPUP_ID}, script, style, noscript`)) return false;
    if (isExcludedContentElement(element)) return false;
    return normalizeText(element.innerText || element.textContent).length >= MIN_SELECTION_LENGTH;
  });
}

function isTextBlockElement(element) {
  if (element.closest(`#${POPUP_ID}, script, style, noscript`)) {
    return false;
  }

  if (isExcludedContentElement(element)) {
    return false;
  }

  const text = normalizeText(element.innerText);
  if (text.length < MIN_SELECTION_LENGTH) {
    return false;
  }

  if (element.matches('p, h1, h2, h3, h4, h5, h6, li, blockquote')) {
    return true;
  }

  if (element.tagName !== 'DIV') {
    return false;
  }

  const nestedBlocks = [...element.querySelectorAll(CONTENT_BLOCK_SELECTOR)].filter(
    (child) => child !== element && normalizeText(child.innerText).length >= MIN_SELECTION_LENGTH,
  );

  return nestedBlocks.length === 0;
}

// Caches per matching pass: content blocks are collected once and each
// block's normalized text is computed at most once, instead of per sentence.
// Create one context per pass (linking, marker application, vocabulary
// highlighting); never keep it across DOM mutations.
function createSentenceMatchContext() {
  return {
    blocks: null,
    fallbackBlocks: null,
    normalizedText: new Map(),
    vocabularyText: new Map(),
  };
}

function getContextContentBlocks(ctx) {
  if (!ctx.blocks) {
    ctx.blocks = getContentBlocks();
  }
  return ctx.blocks;
}

function getContextFallbackBlocks(ctx) {
  if (!ctx.fallbackBlocks) {
    ctx.fallbackBlocks = getFallbackContentBlocks();
  }
  return ctx.fallbackBlocks;
}

// Full normalized text of a block, INCLUDING text inside vocabulary/sentence
// marks, so already-marked paragraphs still match their sentence.
function getElementSentenceText(element, ctx = null) {
  if (!(element instanceof Element)) return '';
  if (!ctx) {
    return normalizeTextForMatch(element.textContent || '');
  }

  let normalized = ctx.normalizedText.get(element);
  if (normalized === undefined) {
    normalized = normalizeTextForMatch(element.textContent || '');
    ctx.normalizedText.set(element, normalized);
  }
  return normalized;
}

function canHighlightSentenceInElement(element, sentenceText, ctx = null) {
  if (!element || !sentenceText) return false;
  const normalizedHaystack = getElementSentenceText(element, ctx);
  // Whole-paragraph sentence: matches even when vocabulary marks are present.
  if (normalizedHaystack === normalizeTextForMatch(sentenceText)) {
    return true;
  }
  // Match against the full text content (including vocabulary/sentence marks)
  // so sentences that contain marked vocabulary still resolve to their block.
  return Boolean(findNeedleInText(element.textContent || '', sentenceText, normalizedHaystack));
}

function scoreSentenceBlockMatch(block, sentenceText, normalizedNeedle, ctx) {
  // Use the full text content (including marks) so vocabulary marks don't
  // break scoring, and already-marked whole paragraphs still win.
  const normalizedHaystack = getElementSentenceText(block, ctx);
  if (!normalizedHaystack) return 0;

  if (normalizedHaystack === normalizedNeedle) return 1000;
  if (normalizedHaystack.includes(normalizedNeedle)) return 900 + normalizedNeedle.length;

  const match = findNeedleInText(block.textContent || '', sentenceText, normalizedHaystack);
  if (match) return 800 + match.length;

  const words = normalizedNeedle.split(' ').filter(Boolean);
  if (words.length <= 1) return 0;

  let matchedWords = 0;
  for (const word of words) {
    if (normalizedHaystack.includes(word)) matchedWords += 1;
  }

  return matchedWords;
}

function findBestSentenceBlock(sentenceText, blocks, excludedElements, ctx) {
  const normalizedNeedle = normalizeTextForMatch(sentenceText);
  if (!normalizedNeedle) return null;

  let bestBlock = null;
  let bestScore = 0;
  let bestLength = Number.MAX_SAFE_INTEGER;

  for (const block of blocks) {
    if (excludedElements.has(block)) continue;

    const score = scoreSentenceBlockMatch(block, sentenceText, normalizedNeedle, ctx);
    if (score < 800) continue;

    const textLength = getElementSentenceText(block, ctx).length;
    if (score > bestScore || (score === bestScore && textLength < bestLength)) {
      bestScore = score;
      bestLength = textLength;
      bestBlock = block;
    }
  }

  return bestBlock;
}

function linkSentencesToDom(sentences) {
  const ctx = createSentenceMatchContext();
  const links = new Map();
  const exclusiveElements = new Set();

  for (const sentence of sentences) {
    const element = findSentenceElement(sentence.text, exclusiveElements, ctx);
    const canHighlight = Boolean(
      element && canHighlightSentenceInElement(element, sentence.text, ctx),
    );
    links.set(sentence.id, canHighlight ? element : null);
    if (
      canHighlight &&
      getElementSentenceText(element, ctx) === normalizeTextForMatch(sentence.text)
    ) {
      exclusiveElements.add(element);
    }
  }

  return links;
}

function findSentenceElement(sentenceText, exclusiveElements, ctx = createSentenceMatchContext()) {
  const primaryBlock = findBestSentenceBlock(
    sentenceText,
    getContextContentBlocks(ctx),
    exclusiveElements,
    ctx,
  );
  if (primaryBlock) {
    return primaryBlock;
  }

  const fallbackBlock = findBestSentenceBlock(
    sentenceText,
    getContextFallbackBlocks(ctx),
    exclusiveElements,
    ctx,
  );
  if (fallbackBlock) {
    return fallbackBlock;
  }

  return findTextRangeElement(sentenceText);
}

function pickDistinctivePhrase(text) {
  const parts = text
    .split(/(?<=[.!?])\s+/)
    .map((part) => part.trim())
    .filter(Boolean);
  if (parts.length > 1) {
    return parts.find((part) => part.length >= 20) || parts[0];
  }
  return text.slice(0, 60);
}

function findTextRangeElement(sentenceText) {
  const needles = [
    sentenceText,
    pickDistinctivePhrase(sentenceText),
    sentenceText.slice(0, 80),
  ].filter((value) => normalizeText(value).length >= 12);

  const root = getContentRoot();
  if (!(root instanceof Node)) return null;

  const seen = new Set();

  for (const needle of needles) {
    const normalizedNeedle = normalizeTextForMatch(needle);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node = walker.nextNode();

    while (node) {
      const parent = node.parentElement;
      if (
        parent &&
        !parent.closest(`#${POPUP_ID}, script, style, noscript`) &&
        !isExcludedContentElement(parent) &&
        normalizeTextForMatch(node.textContent).includes(normalizedNeedle)
      ) {
        const block = parent.closest('p, h1, h2, h3, h4, li, blockquote, div') || parent;
        if (!seen.has(block)) {
          seen.add(block);
          if (canHighlightSentenceInElement(block, sentenceText)) {
            return block;
          }
        }
      }
      node = walker.nextNode();
    }
  }

  return null;
}

function countAppliedSentenceAnchors() {
  let count = 0;
  for (const sentence of activePreload?.sentences || []) {
    if (getSentenceAnchorElement(sentence.id)) count += 1;
  }
  return count;
}

function applySentenceAnchor(sentence, root) {
  if (!root || !sentence) return false;

  // Tag-based anchoring: emphasize the whole containing block instead of
  // slicing individual sentences. When several sentences share one tag they
  // all point at the same block; the first one wins the click target.
  root.classList.add('era-page-anchor', 'era-page-anchor-block');
  if (!root.dataset.eraSentenceId) {
    root.dataset.eraSentenceId = sentence.id;
  }
  return true;
}

// Some pages (e.g. status/incident pages) repeat the exact same sentence
// verbatim in more than one place (a "latest update" summary and the same
// entry in a chronological log). Only one physical block becomes the click
// target for the sentence, but every block whose full text matches it
// exactly should still get the same visual "analyzed" treatment, or the
// duplicate looks unanalyzed even though its words are vocabulary-marked.
function applyDuplicateSentenceAnchors(sentence, root, ctx) {
  const normalizedSentence =
    getElementSentenceText(root, ctx) || normalizeTextForMatch(sentence.text);
  if (!normalizedSentence) return;

  // Only search the same tier `root` came from. Content blocks are already
  // deduplicated by DOM containment (see getContentBlocks), but the broader
  // fallback tier (section/article/main) is not, so mixing tiers would tag
  // both a paragraph and its own wrapping section as "duplicates".
  const contentBlocks = getContextContentBlocks(ctx);
  const candidates = contentBlocks.includes(root) ? contentBlocks : getContextFallbackBlocks(ctx);

  for (const block of candidates) {
    if (block === root) continue;
    if (block.classList.contains('era-page-anchor-block')) continue;
    if (block.contains(root) || root.contains(block)) continue;
    if (getElementSentenceText(block, ctx) !== normalizedSentence) continue;
    applySentenceAnchor(sentence, block);
  }
}

function ensureSentenceAnchor(sentence) {
  if (!sentence?.id) return false;
  if (getSentenceAnchorElement(sentence.id)) return true;

  const ctx = createSentenceMatchContext();
  const root = findSentenceElement(sentence.text, new Set(), ctx);
  if (!root) return false;

  sentenceDomLinks.set(sentence.id, root);
  const applied = applySentenceAnchor(sentence, root);
  if (applied) {
    applyDuplicateSentenceAnchors(sentence, root, ctx);
    syncPageAnchorSurfaceTheme();
    syncPageAnchorInteractivity();
  }
  return applied;
}

function applyPageAnchorMarkers() {
  clearSentenceMarkers();
  document.querySelectorAll('.era-page-anchor-block').forEach((element) => {
    element.classList.remove(
      'era-page-anchor',
      'era-page-anchor-block',
      'era-page-anchor-hover',
      'era-page-anchor-active',
    );
    delete element.dataset.eraSentenceId;
  });

  const ctx = createSentenceMatchContext();
  for (const sentence of activePreload?.sentences || []) {
    let root = getSentenceDomElement(sentence.id);
    if (!root || !canHighlightSentenceInElement(root, sentence.text, ctx)) {
      root = findSentenceElement(sentence.text, new Set(), ctx);
      if (root) {
        sentenceDomLinks.set(sentence.id, root);
      }
    }
    if (!root) continue;
    applySentenceAnchor(sentence, root);
    applyDuplicateSentenceAnchors(sentence, root, ctx);
  }

  syncPageAnchorSurfaceTheme();
  syncPageAnchorInteractivity();
}

function collectHighlightableTextSegments(root) {
  if (!(root instanceof Node)) return [];

  const segments = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode();

  while (node) {
    if (isHighlightableTextNode(node) && node.textContent) {
      segments.push({ node, text: node.textContent });
    }
    node = walker.nextNode();
  }

  return segments;
}

function sliceSegmentRanges(segments, start, end) {
  const ranges = [];
  let position = 0;

  for (const segment of segments) {
    const segmentStart = position;
    const segmentEnd = position + segment.text.length;

    if (segmentEnd <= start || segmentStart >= end) {
      position = segmentEnd;
      continue;
    }

    ranges.push({
      node: segment.node,
      start: Math.max(0, start - segmentStart),
      end: Math.min(segment.text.length, end - segmentStart),
    });
    position = segmentEnd;
  }

  return ranges;
}

function wrapSentenceTextRange({ node, start, end }, sentenceId) {
  const parent = node.parentNode;
  if (!parent) return;

  const text = node.textContent;
  const before = text.slice(0, start);
  const matched = text.slice(start, end);
  const after = text.slice(end);

  const mark = document.createElement('mark');
  mark.className = 'era-page-anchor era-sentence-mark';
  mark.dataset.eraSentenceId = sentenceId;
  mark.textContent = matched;

  if (before) parent.insertBefore(document.createTextNode(before), node);
  parent.insertBefore(mark, node);
  if (after) parent.insertBefore(document.createTextNode(after), node);
  parent.removeChild(node);

  sentenceHighlightMarks.push(mark);
}

function highlightSentenceInElement(root, needle, sentenceId) {
  const segments = collectHighlightableTextSegments(root);
  if (!segments.length) return;

  const flatText = segments.map((segment) => segment.text).join('');
  const match = expandSentenceMatch(flatText, findNeedleInText(flatText, needle));
  if (!match) return;

  const ranges = sliceSegmentRanges(segments, match.index, match.index + match.length);
  for (let index = ranges.length - 1; index >= 0; index -= 1) {
    wrapSentenceTextRange(ranges[index], sentenceId);
  }
}

function expandSentenceMatch(text, match) {
  if (!match) return null;

  let { index, length } = match;

  if (index > 0 && /[""'\u201c\u2018]/.test(text[index - 1])) {
    index -= 1;
    length += 1;
  }

  return { index, length };
}

function clearSentenceMarkers() {
  for (const mark of sentenceHighlightMarks) {
    const parent = mark.parentNode;
    if (!parent) continue;

    parent.replaceChild(document.createTextNode(mark.textContent), mark);
    parent.normalize();
  }
  sentenceHighlightMarks = [];
}

function getSentenceAnchorElement(sentenceId) {
  const inlineMark = document.querySelector(
    `mark.era-sentence-mark[data-era-sentence-id="${CSS.escape(sentenceId)}"]`,
  );
  if (inlineMark) return inlineMark;

  const linked = getSentenceDomElement(sentenceId);
  if (linked?.dataset?.eraSentenceId === sentenceId) return linked;
  return linked;
}

function syncPageAnchorInteractivity() {
  const panelOpen = hasActiveReadingSession();
  document.querySelectorAll('.era-page-anchor').forEach((element) => {
    element.classList.toggle('era-page-anchor-interactive', panelOpen);
    element.setAttribute('role', panelOpen ? 'button' : 'presentation');
    if (panelOpen) {
      element.setAttribute('tabindex', '0');
      element.setAttribute(
        'aria-label',
        t('anchorAria', { num: getSentenceIndexById(element.dataset.eraSentenceId) + 1 }),
      );
    } else {
      element.removeAttribute('tabindex');
      element.removeAttribute('aria-label');
    }
  });
}

function getSentenceIndexById(sentenceId) {
  const sentence = activePreload?.sentences?.find((item) => item.id === sentenceId);
  return sentence?.index ?? -1;
}

// --- Orphaned-instance teardown -----------------------------------------------
// When the extension reloads (dev auto-reload, store update), this script's
// world loses its chrome bindings ("Extension context invalidated") while its
// DOM listeners keep firing. On the first sign of that, the instance mutes
// itself: listeners off, UI removed, timers cleared. The freshly injected
// script takes over.

var extensionContextTornDown = false;

function ensureLiveExtensionContext() {
  if (extensionContextTornDown) return false;
  if (isExtensionRuntimeAvailable()) return true;
  teardownOrphanedInstance();
  return false;
}

function teardownOrphanedInstance() {
  if (extensionContextTornDown) return;
  extensionContextTornDown = true;

  document.removeEventListener('mouseup', handleDocumentMouseUp);
  document.removeEventListener('keydown', handleDocumentEscape);
  document.removeEventListener('mousedown', handleDocumentMouseDownForPopup);
  document.removeEventListener('mousedown', handleVocabularyMarkMouseDown, true);
  document.removeEventListener('click', handleVocabularyMarkClick, true);
  document.removeEventListener('mouseover', handleVocabularyMarkHover, true);
  document.removeEventListener('click', handlePageAnchorClick, true);
  document.removeEventListener('mouseover', handlePageAnchorHover, true);
  document.removeEventListener('mouseout', handlePageAnchorHoverOut, true);
  document.removeEventListener('keydown', handlePageAnchorKeydown, true);
  document.removeEventListener('keydown', handleReadingDetailKeydown, true);
  window.removeEventListener('resize', scheduleLauncherThemeRefresh);
  window.removeEventListener('scroll', scheduleLauncherThemeRefresh, { capture: true });

  window.clearTimeout(debounceTimer);
  window.clearTimeout(pageAnchorSyncRetryTimer);
  window.clearTimeout(hoverPersistTimer);
  window.clearTimeout(launcherThemeRefreshTimer);

  document.getElementById(POPUP_ID)?.remove();
  document.getElementById(IN_PAGE_PANEL_ID)?.remove();
  document.getElementById(LAUNCHER_ID)?.remove();
  document.getElementById('era-inline-gloss')?.remove();

  console.info('[Untangle] Extension was reloaded; stale content script deactivated.');
}

function setupPageAnchorInteraction() {
  document.addEventListener('mousedown', handleVocabularyMarkMouseDown, true);
  document.addEventListener('click', handleVocabularyMarkClick, true);
  document.addEventListener('mouseover', handleVocabularyMarkHover, true);
  document.addEventListener('click', handlePageAnchorClick, true);
  document.addEventListener('mouseover', handlePageAnchorHover, true);
  document.addEventListener('mouseout', handlePageAnchorHoverOut, true);
  document.addEventListener('keydown', handlePageAnchorKeydown, true);
  document.addEventListener('keydown', handleReadingDetailKeydown, true);
}

function getVocabularyMarkFromEventTarget(target) {
  if (!target) return null;
  const node = target.nodeType === Node.ELEMENT_NODE ? target : target.parentElement;
  return node?.closest('mark.era-vocabulary-mark') || null;
}

function handleVocabularyMarkMouseDown(event) {
  const mark = getVocabularyMarkFromEventTarget(event.target);
  if (!mark?.dataset.eraStudyItemId) return;
  if (event.target.closest(`#${POPUP_ID}`)) return;

  event.preventDefault();
  event.stopPropagation();
  event.stopImmediatePropagation();
}

function handleVocabularyMarkHover(event) {
  if (!hasActiveReadingSession()) return;

  const mark = getVocabularyMarkFromEventTarget(event.target);
  if (!mark?.dataset.eraStudyItemId) return;

  if (hoveredSentenceId) {
    hoveredSentenceId = null;
    updatePageHighlights();
  }
}

function handleVocabularyMarkClick(event) {
  if (!ensureLiveExtensionContext()) return;
  if (!hasActiveReadingSession() || !activePreload) return;

  const mark = getVocabularyMarkFromEventTarget(event.target);
  if (!mark?.dataset.eraStudyItemId) return;
  if (event.target.closest(`#${POPUP_ID}`)) return;

  const item = getStudyItemById(activePreload, mark.dataset.eraStudyItemId);
  if (!item) return;

  event.preventDefault();
  event.stopPropagation();
  event.stopImmediatePropagation();
  void selectStudyItemFromPage(item, { scrollPage: false });
  window.getSelection()?.removeAllRanges();
}

function handlePageAnchorClick(event) {
  if (!ensureLiveExtensionContext()) return;
  if (!hasActiveReadingSession() || !activePreload) return;
  if (getVocabularyMarkFromEventTarget(event.target)) return;

  const anchor = event.target.closest('.era-page-anchor');
  if (!anchor?.dataset.eraSentenceId) return;
  if (event.target.closest(`#${POPUP_ID}`)) return;

  const selection = window.getSelection();
  if (selection && !selection.isCollapsed) return;

  const sentence = activePreload.sentences.find((item) => item.id === anchor.dataset.eraSentenceId);
  if (!sentence) return;

  event.preventDefault();
  void selectSentenceFromPage(sentence, { scrollPage: false });
  selection?.removeAllRanges();
}

function handlePageAnchorHover(event) {
  if (!ensureLiveExtensionContext()) return;
  if (!hasActiveReadingSession()) return;
  if (getVocabularyMarkFromEventTarget(event.target)) return;

  const anchor = event.target.closest('.era-page-anchor');
  if (!anchor?.dataset.eraSentenceId) return;
  if (event.relatedTarget && anchor.contains(event.relatedTarget)) return;

  hoveredSentenceId = anchor.dataset.eraSentenceId;
  updatePageHighlights();
  schedulePersistPageReadingUi();
}

function handlePageAnchorHoverOut(event) {
  if (!hasActiveReadingSession()) return;
  if (getVocabularyMarkFromEventTarget(event.relatedTarget)) return;

  const anchor = event.target.closest('.era-page-anchor');
  if (!anchor?.dataset.eraSentenceId) return;
  if (event.relatedTarget && anchor.contains(event.relatedTarget)) return;
  if (event.relatedTarget?.closest('.era-page-anchor')) return;
  hoveredSentenceId = null;
  updatePageHighlights();
  schedulePersistPageReadingUi();
}

function handlePageAnchorKeydown(event) {
  if (event.key !== 'Enter' && event.key !== ' ') return;

  const anchor = event.target.closest('.era-page-anchor');
  if (!anchor) return;

  event.preventDefault();
  anchor.click();
}

function findStudyItemFromDomSelection(selection) {
  if (!selection?.rangeCount || !activePreload?.study_items?.length) return null;

  const range = selection.getRangeAt(0);
  const nodes = [
    range.commonAncestorContainer,
    range.startContainer,
    range.endContainer,
    selection.anchorNode,
    selection.focusNode,
  ];

  for (const node of nodes) {
    const element = node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement;
    const mark = element?.closest('mark.era-vocabulary-mark');
    if (!mark?.dataset.eraStudyItemId) continue;

    const item = getStudyItemById(activePreload, mark.dataset.eraStudyItemId);
    if (item) return item;
  }

  return null;
}

function findSentenceFromDomSelection(selection) {
  if (!selection?.rangeCount || !activePreload?.sentences?.length) return null;

  const selectedText = selection.toString().trim();
  if (!selectedText) return null;

  const range = selection.getRangeAt(0);
  const node = range.commonAncestorContainer;
  const element = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
  if (element?.closest('mark.era-vocabulary-mark')) return null;

  const anchor = element?.closest('.era-page-anchor');
  if (anchor?.dataset.eraSentenceId) {
    return (
      activePreload.sentences.find((sentence) => sentence.id === anchor.dataset.eraSentenceId) ||
      null
    );
  }

  return findCachedSentence(selectedText);
}

function updatePageHighlights() {
  document.querySelectorAll('.era-page-anchor').forEach((element) => {
    element.classList.remove('era-page-anchor-hover', 'era-page-anchor-active');
  });

  document.querySelectorAll('mark.era-vocabulary-mark').forEach((mark) => {
    mark.classList.remove('era-vocabulary-mark-active');
  });

  if (activeStudyItemId) {
    document
      .querySelectorAll(
        `mark.era-vocabulary-mark[data-era-study-item-id="${CSS.escape(activeStudyItemId)}"]`,
      )
      .forEach((mark) => {
        mark.classList.add('era-vocabulary-mark-active');
      });
  }

  if (hoveredSentenceId) {
    getSentenceAnchorElement(hoveredSentenceId)?.classList.add('era-page-anchor-hover');
  }

  if (activeSentenceId) {
    getSentenceAnchorElement(activeSentenceId)?.classList.add('era-page-anchor-active');
  }
}

function applyVocabularyMarkers() {
  clearAllVocabularyMarks();
  if (!activePreload?.study_items?.length) return;

  const items = [...activePreload.study_items].sort(
    (left, right) => normalizeText(right.text).length - normalizeText(left.text).length,
  );

  const ctx = createSentenceMatchContext();
  for (const item of items) {
    highlightVocabularyOnPage(item, ctx);
  }
}

function focusVocabularyOnPage(item, linkedSentence = null) {
  const marks = item?.id
    ? [
        ...document.querySelectorAll(
          `mark.era-vocabulary-mark[data-era-study-item-id="${CSS.escape(item.id)}"]`,
        ),
      ]
    : [];
  const firstMark = marks[0];
  if (firstMark) {
    firstMark.scrollIntoView({ behavior: 'smooth', block: 'center' });
    lastSelectionRect = firstMark.getBoundingClientRect();
    return;
  }

  const sentence = linkedSentence || findSentenceById(activePreload, item.sentence_ids?.[0]);
  if (sentence) {
    focusSentenceOnPage(sentence);
  }
}

function clearAllVocabularyMarks() {
  for (const mark of vocabularyHighlightMarks) {
    const parent = mark.parentNode;
    if (!parent) continue;

    parent.replaceChild(document.createTextNode(mark.textContent), mark);
    parent.normalize();
  }
  vocabularyHighlightMarks = [];
}

function highlightVocabularyOnPage(item, ctx = createSentenceMatchContext()) {
  const needle = normalizeText(item.text);
  if (!needle) return;

  for (const root of getVocabularySearchRoots(item, ctx)) {
    highlightTextInElement(root, needle, item.id);
  }
}

function getVocabularyBlockText(ctx, block) {
  let text = ctx.vocabularyText.get(block);
  if (text === undefined) {
    text = normalizeText(block.innerText).toLowerCase();
    ctx.vocabularyText.set(block, text);
  }
  return text;
}

function getVocabularySearchRoots(item, ctx) {
  const needle = normalizeText(item.text).toLowerCase();
  const searchRoots = [];
  const seen = new Set();

  for (const sentenceId of item.sentence_ids || []) {
    const element = getSentenceDomElement(sentenceId);
    if (element && !seen.has(element)) {
      searchRoots.push(element);
      seen.add(element);
    }
  }

  for (const block of getContextContentBlocks(ctx)) {
    if (seen.has(block)) continue;
    if (getVocabularyBlockText(ctx, block).includes(needle)) {
      searchRoots.push(block);
      seen.add(block);
    }
  }

  return searchRoots;
}

function highlightTextInElement(root, needle, studyItemId) {
  while (true) {
    const node = findHighlightableTextNode(root, needle);
    if (!node) break;

    const match = findNeedleInText(node.textContent, needle);
    if (!match) break;

    const { index, length } = match;
    const text = node.textContent;
    const before = text.slice(0, index);
    const matched = text.slice(index, index + length);
    const after = text.slice(index + length);

    const mark = document.createElement('mark');
    mark.className = 'era-vocabulary-mark';
    mark.dataset.eraStudyItemId = studyItemId;
    mark.textContent = matched;

    const parent = node.parentNode;
    if (!parent) break;

    if (before) parent.insertBefore(document.createTextNode(before), node);
    parent.insertBefore(mark, node);
    if (after) parent.insertBefore(document.createTextNode(after), node);
    parent.removeChild(node);

    vocabularyHighlightMarks.push(mark);
  }
}

function findHighlightableTextNode(root, needle) {
  if (!(root instanceof Node)) return null;

  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode();

  while (node) {
    if (isHighlightableTextNode(node) && findNeedleInText(node.textContent, needle)) {
      return node;
    }
    node = walker.nextNode();
  }

  return null;
}

function isHighlightableTextNode(node) {
  const parent = node.parentElement;
  if (!parent) return false;
  if (parent.closest('mark.era-vocabulary-mark, mark.era-sentence-mark, script, style, noscript'))
    return false;
  if (parent.closest(`#${POPUP_ID}`)) return false;
  return true;
}

function focusSentenceOnPage(sentence) {
  ensureSentenceAnchor(sentence);
  const element = getSentenceAnchorElement(sentence.id);
  if (!element) return;

  element.scrollIntoView({ behavior: 'smooth', block: 'center' });
  lastSelectionRect = element.getBoundingClientRect();
  updatePageHighlights();
}

function clearPageHighlights() {
  clearAllVocabularyMarks();
  clearSentenceMarkers();
  document.documentElement.classList.remove('era-page-anchors-on-dark');
  document.querySelectorAll('.era-page-anchor-block').forEach((element) => {
    element.classList.remove(
      'era-page-anchor',
      'era-page-anchor-block',
      'era-page-anchor-hover',
      'era-page-anchor-active',
    );
    delete element.dataset.eraSentenceId;
  });
  sentenceDomLinks = new Map();
}

function bindPopupEvents(popup) {
  bindExtensionUiSelectionGuard(popup);
  popup.querySelector('.era-close')?.addEventListener('click', closePopup);
  popup.querySelector('.era-selection-toggle-off')?.addEventListener('click', () => {
    selectionAnalysisEnabled = false;
    closePopup();
    setSelectionAnalysisEnabled(false).catch((error) => {
      console.error('[Untangle] setSelectionAnalysisEnabled failed:', error);
    });
  });
}

function findCachedSentence(selectedText) {
  if (!activePreload?.sentences?.length) return null;

  const normalizedSelection = normalizeText(selectedText);
  return (
    activePreload.sentences.find(
      (sentence) => normalizeText(sentence.text) === normalizedSelection,
    ) ||
    activePreload.sentences.find((sentence) =>
      normalizeText(sentence.text).includes(normalizedSelection),
    ) ||
    null
  );
}

function extractPageHtml() {
  const clone = document.documentElement.cloneNode(true);
  clone
    .querySelectorAll('script, style, noscript, iframe, svg, [aria-hidden="true"]')
    .forEach((element) => element.remove());

  const html = `<!DOCTYPE html>\n${clone.outerHTML}`;
  if (html.length < 200) {
    throw new Error(t('pageHtmlFailed'));
  }

  return html.slice(0, MAX_PAGE_HTML_LENGTH);
}

function getPageUrl(pageUrl = window.location.href) {
  return normalizePageUrl(pageUrl);
}

function detectPageLanguage() {
  return (
    normalizeLanguageCode(document.documentElement.lang) ||
    normalizeLanguageCode(document.body?.lang) ||
    ''
  );
}

// Language fields sent with analyze/preload/chat requests. When the target
// language is set to auto, it is resolved from the page's lang attribute.
function buildLanguageFields() {
  const target =
    languageProfile.target === AUTO_TARGET_LANGUAGE
      ? detectPageLanguage() || getDefaultLanguageProfile().target
      : languageProfile.target;

  return {
    target_language: target,
    native_language: languageProfile.native,
  };
}

function buildSelectionChatPayload(text, analysis) {
  return {
    message: '',
    context_label: 'selection',
    context_text: text,
    context_analysis: analysis
      ? {
          translation: analysis.translation || '',
          grammar: analysis.grammar || '',
          nuance: analysis.nuance || '',
          vocabulary: analysis.vocabulary || [],
          examples: analysis.examples || [],
          study_tip: analysis.study_tip || '',
        }
      : null,
    page_preload_id: activePreload?.id || null,
    page_url: getPageUrl(),
    page_title: document.title,
    history: [],
    ...buildLanguageFields(),
  };
}

function bindExtensionUiSelectionGuard(root) {
  root.addEventListener('mouseup', (event) => {
    if (event.target.closest('.era-panel-resizer')) return;
    event.stopPropagation();
  });
}

function isNodeInExtensionUi(node) {
  if (!node) return false;

  const element = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
  return Boolean(element?.closest(`#${POPUP_ID}`));
}

function isEventInExtensionUi(event) {
  return isNodeInExtensionUi(event.target);
}

function isSelectionInExtensionUi(selection) {
  if (!selection?.rangeCount) return false;

  const range = selection.getRangeAt(0);
  const nodes = [
    selection.anchorNode,
    selection.focusNode,
    range.commonAncestorContainer,
    range.startContainer,
    range.endContainer,
  ];

  return nodes.some((node) => isNodeInExtensionUi(node));
}

function getSelectionRect(selection) {
  if (!selection || selection.rangeCount === 0) return null;

  const range = selection.getRangeAt(0);
  const rect = range.getBoundingClientRect();
  if (rect.width || rect.height) return rect;

  return range.getClientRects()[0] || null;
}

function showPopup({ state, text, analysis, error, loadingMessage, label }) {
  closePopup();

  const popup = document.createElement('section');
  popup.id = POPUP_ID;
  popup.className = SELECTED_CLASS;
  popup.innerHTML = renderPopup({ state, text, analysis, error, loadingMessage, label });
  document.documentElement.appendChild(popup);
  positionPopup(popup);
  bindPopupEvents(popup);

  if (state === 'success' && analysis && text) {
    attachContextChat(popup, {
      chatKey: getSelectionChatKey(text),
      payload: buildSelectionChatPayload(text, analysis),
    });
  }
}

function renderPopup({ state, text, analysis, error, loadingMessage, label }) {
  const successBody =
    state === 'success' && analysis && text
      ? `${renderAnalysis(analysis)}${renderContextChat(getSelectionChatKey(text), { quickActions: SENTENCE_QUICK_CHAT_ACTIONS })}`
      : '';

  const body = {
    loading: `<div class="era-status"><span class="era-spinner"></span><span>${escapeHtml(loadingMessage || t('popupAnalyzing'))}</span></div>`,
    error: `<div class="era-error">${escapeHtml(error || t('popupAnalyzeFailed'))}</div>`,
    success: successBody,
  }[state];

  const preloadBadge = analysis?.used_preload
    ? `<span class="era-preload-badge">${escapeHtml(t('popupPreloadedBadge'))}</span>`
    : '';

  return `
    <div class="era-header">
      <div>
        <p class="era-label">${escapeHtml(label || t('popupSelectedText'))} ${preloadBadge}</p>
        <p class="era-selected">${escapeHtml(text)}</p>
      </div>
      <button class="era-close" type="button" aria-label="Close">×</button>
    </div>
    <button class="era-selection-toggle-off" type="button">${escapeHtml(t('popupDisableSelectionAnalysis'))}</button>
    <div class="era-body">${body}</div>
  `;
}

function positionPopup(popup) {
  const rect = lastSelectionRect || { left: 24, top: 24, bottom: 24 };
  const margin = 12;
  const width = Math.min(420, window.innerWidth - margin * 2);
  const left = Math.min(Math.max(rect.left, margin), window.innerWidth - width - margin);
  const topCandidate = rect.bottom + margin;
  const top =
    topCandidate + 360 > window.innerHeight
      ? Math.max(rect.top - 360 - margin, margin)
      : topCandidate;

  popup.style.width = `${width}px`;
  popup.style.left = `${left + window.scrollX}px`;
  popup.style.top = `${top + window.scrollY}px`;
}

function closePopup() {
  document.getElementById(POPUP_ID)?.remove();
}
