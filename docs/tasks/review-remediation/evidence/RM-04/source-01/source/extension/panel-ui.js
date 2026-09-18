const learnerLevelPresetInput = document.getElementById('learnerLevelPreset');
const learnerLevelNotesInput = document.getElementById('learnerLevelNotes');
const learnerLevelSummaryElement = document.getElementById('learnerLevelSummary');
const targetLanguageSelect = document.getElementById('targetLanguageSelect');
const nativeLanguageSelect = document.getElementById('nativeLanguageSelect');
const languageSummaryElement = document.getElementById('languageSummary');
const selectionAnalysisToggle = document.getElementById('selectionAnalysisToggle');
const selectionAnalysisStatusElement = document.getElementById('selectionAnalysisStatus');
const preloadButton = document.getElementById('preloadButton');
const preloadConfirmElement = document.getElementById('preloadConfirm');
const preloadConfirmMessageElement = document.getElementById('preloadConfirmMessage');
const preloadConfirmButton = document.getElementById('preloadConfirmButton');
const preloadCancelButton = document.getElementById('preloadCancelButton');
const preloadStatusElement = document.getElementById('preloadStatus');
const authLoggedOutElement = document.getElementById('authLoggedOut');
const authLoggedInElement = document.getElementById('authLoggedIn');
const signInRootElement = document.getElementById('signInRoot');
const logoutButton = document.getElementById('logoutButton');
const authUserSummaryElement = document.getElementById('authUserSummary');
const authStatusElement = document.getElementById('authStatus');
const billingSummaryElement = document.getElementById('billingSummary');
const billingWarningElement = document.getElementById('billingWarning');
const BILLING_PLAN_RANK = Object.freeze({ basic: 0, pro: 1, max: 2 });
const darkModeToggle = document.getElementById('darkModeToggle');
const billingStatusElement = document.getElementById('billingStatus');
const billingUpgradeProButton = document.getElementById('billingUpgradeProButton');
const billingUpgradeMaxButton = document.getElementById('billingUpgradeMaxButton');
const billingPortalButton = document.getElementById('billingPortalButton');
const authenticatedFeaturesElement = document.getElementById('authenticatedFeatures');
const settingsViewButton = document.getElementById('settingsViewButton');
const readingViewButton = document.getElementById('readingViewButton');
const vocabBookViewButton = document.getElementById('vocabBookViewButton');
const vocabBookStatusElement = document.getElementById('vocabBookStatus');
const vocabBookListElement = document.getElementById('vocabBookList');
const readingEmptyState = document.getElementById('readingEmptyState');
const readingEmptyMessageElement = document.getElementById('readingEmptyMessage');
const goToPreloadButton = document.getElementById('goToPreloadButton');
const customPromptsList = document.getElementById('customPromptsList');
const customPromptName = document.getElementById('customPromptName');
const customPromptBody = document.getElementById('customPromptBody');
const customPromptAddButton = document.getElementById('customPromptAddButton');
const customPromptCancelButton = document.getElementById('customPromptCancelButton');
const customPromptStatus = document.getElementById('customPromptStatus');
let editingCustomPromptId = null;

const boundPageUrl = resolveBoundPageUrl();

let activePageUrl = boundPageUrl;
let activeTabId = null;
let isAuthenticated = false;
let activeSidePanelView = 'settings';
let readingViewSyncInProgress = false;
let activePreloadSentenceCount = 0;
let cachedActivePreload = null;
let cachedActivePreloadScope = null;
let sidePanelRefreshTimer = null;
let sidePanelRefreshInProgress = false;
let panelUiInitialized = false;
let pendingPreloadOverwrite = null;
let preloadRetryMode = false;

function clearCachedActivePreload() {
  cachedActivePreload = null;
  cachedActivePreloadScope = null;
}

function cacheActivePreload(preload, authScope) {
  if (!preload?.sentences?.length || !isAuthScope(authScope)) {
    clearCachedActivePreload();
    return false;
  }
  cachedActivePreload = preload;
  cachedActivePreloadScope = { userId: authScope.userId, loginId: authScope.loginId };
  return true;
}

function getCachedActivePreload(authScope) {
  return authScopesMatch(cachedActivePreloadScope, authScope) ? cachedActivePreload : null;
}

function getActiveContentTabId() {
  return activeTabId;
}

function resolveBoundPageUrl() {
  const candidates = [
    new URLSearchParams(window.location.search).get('pageUrl'),
    document.referrer,
  ];

  for (const candidate of candidates) {
    if (!candidate) continue;
    try {
      const url = new URL(candidate);
      if (url.protocol === 'http:' || url.protocol === 'https:') {
        return normalizePageUrl(url.href);
      }
    } catch {
      // Try the next candidate.
    }
  }

  return '';
}

function isExpectedPanelContextError(error) {
  const message = error?.message || '';
  return (
    message.includes(t('errNeedWebPage')) ||
    message.includes(t('errPageUnavailable')) ||
    message.includes(t('domainUnavailable')) ||
    message.includes('Cannot access a chrome:// URL')
  );
}

function logPanelError(scope, error) {
  if (isExpectedPanelContextError(error)) {
    return;
  }
  console.error(`[Untangle] ${scope} failed:`, error);
}

async function handleSidePanelOpened() {
  window.clearTimeout(sidePanelRefreshTimer);
  sidePanelRefreshTimer = window.setTimeout(async () => {
    if (sidePanelRefreshInProgress) {
      return;
    }
    sidePanelRefreshInProgress = true;
    try {
      await refreshPanelContext();
    } catch (error) {
      logPanelError('handleSidePanelOpened', error);
    } finally {
      sidePanelRefreshInProgress = false;
    }
  }, 200);
}

function resolvePageUrl(pageUrl = '', preload = null) {
  if (pageUrl) {
    return normalizePageUrl(pageUrl);
  }
  if (preload?.page_url) {
    return normalizePageUrl(preload.page_url);
  }
  return activePageUrl || '';
}

function bindPanelUiEvents() {
  learnerLevelPresetInput?.addEventListener('change', saveLearnerProfile);
  learnerLevelNotesInput?.addEventListener('change', saveLearnerProfile);
  targetLanguageSelect?.addEventListener('change', () => {
    saveLanguageProfile();
    // The level scale depends on the studied language (JLPT/HSK/TOPIK/...).
    const previousPreset = learnerLevelPresetInput?.value || '';
    populateLearnerLevelPresets();
    // A preset from the previous scale (e.g. TOEIC after switching away
    // from English) no longer exists in the select; persist the reset so
    // the stale level stops being sent to the API.
    if (previousPreset && learnerLevelPresetInput?.value !== previousPreset) {
      saveLearnerProfile().catch(() => {});
    }
  });
  nativeLanguageSelect?.addEventListener('change', saveLanguageProfile);
  selectionAnalysisToggle?.addEventListener('change', () => {
    saveSelectionAnalysisSetting(selectionAnalysisToggle.checked).catch(() => {});
  });
  customPromptAddButton?.addEventListener('click', handleCustomPromptSubmit);
  customPromptCancelButton?.addEventListener('click', resetCustomPromptForm);
  customPromptsList?.addEventListener('click', handleCustomPromptListClick);
  preloadButton?.addEventListener('click', () => startPreload());
  preloadConfirmButton?.addEventListener('click', () => {
    const pending = pendingPreloadOverwrite;
    hidePreloadOverwriteConfirm();
    startPreload({ forceOverwrite: true, tab: pending?.tab }).catch((error) => {
      setPreloadStatus('idle', toUserFacingErrorMessage(error, t('preloadFailed')));
    });
  });
  preloadCancelButton?.addEventListener('click', () => {
    const pending = pendingPreloadOverwrite;
    hidePreloadOverwriteConfirm();
    if (pending?.preload?.sentences?.length) {
      setPreloadStatus(
        'ready',
        t('statusPreloadedConfirm', { count: pending.preload.sentences.length }),
      );
    }
  });
  billingUpgradeProButton?.addEventListener('click', () => {
    handleBillingUpgrade('pro').catch(() => {});
  });
  billingUpgradeMaxButton?.addEventListener('click', () => {
    handleBillingUpgrade('max').catch(() => {});
  });
  billingPortalButton?.addEventListener('click', () => {
    handleBillingPortal().catch(() => {});
  });
  darkModeToggle?.addEventListener('click', () => {
    const theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    // Apply immediately for responsiveness; setPanelTheme persists it and
    // storage.onChanged fans the change out to every other context.
    applySidePanelTheme(theme);
    window.ReadingPanel?.applyExternalTheme?.(theme);
    setPanelTheme(theme).catch(() => {});
  });
  logoutButton?.addEventListener('click', () => {
    handleLogout().catch((error) => {
      console.error('[Untangle] handleLogout failed:', error);
      authStatusElement.textContent = error?.message || t('statusLogoutFailed');
    });
  });

  settingsViewButton?.addEventListener('click', () => setSidePanelView('settings'));
  readingViewButton?.addEventListener('click', () => {
    if (!isAuthenticated) {
      setSidePanelView('settings');
      return;
    }
    setSidePanelView('reading');
    // Settings may have changed quick-action visibility while this view was
    // hidden; refresh the open sentence chat before syncing session state.
    window.ReadingPanel?.refreshContextChatActions?.();
    ensureActivePageUrl()
      .then(() =>
        syncReadingViewUi({
          preload: cachedActivePreload,
          sentenceCount: activePreloadSentenceCount || cachedActivePreload?.sentences?.length || 0,
          authScope: cachedActivePreloadScope,
        }),
      )
      .catch(() => {});
  });
  goToPreloadButton?.addEventListener('click', () => {
    setSidePanelView('settings');
    if (!isAuthenticated) {
      signInRootElement?.querySelector('button')?.focus();
      return;
    }
    preloadButton?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  });
  vocabBookViewButton?.addEventListener('click', () => {
    if (!isAuthenticated) {
      setSidePanelView('settings');
      return;
    }
    setSidePanelView('vocab');
    loadVocabularyBook().catch((error) => {
      logPanelError('loadVocabularyBook', error);
    });
  });
}

// --- Vocabulary book (cross-article word list) -------------------------------
// The single home for vocabulary: the reading tab shows sentences only, and
// every word interaction (list, detail, chat, jump-to-text) happens here.

let vocabBookLoadPromise = null;
let vocabBookItemsById = new Map();

// Narrows the fetched book to the article currently open in the panel, so
// the word book shows only the current screen's words (no cross-article
// accumulation). Prefers the loaded preload's id, falls back to the active
// page URL; if neither is known, the book is left as-is.
function scopeVocabularyToCurrentArticle(book) {
  const items = book?.items || [];
  const currentId = cachedActivePreload?.id || '';
  if (currentId) {
    return { ...book, items: items.filter((item) => item.preload_id === currentId) };
  }
  if (activePageUrl) {
    return {
      ...book,
      items: items.filter((item) => pageUrlsMatch(item.page_url, activePageUrl)),
    };
  }
  return book;
}

function loadVocabularyBook() {
  if (vocabBookLoadPromise) {
    return vocabBookLoadPromise;
  }
  if (!vocabBookStatusElement || !vocabBookListElement) {
    return Promise.resolve();
  }

  vocabBookStatusElement.textContent = t('vocabBookLoading');
  vocabBookLoadPromise = (async () => {
    try {
      const response = await chrome.runtime.sendMessage({ type: 'GET_VOCABULARY_BOOK' });
      if (!response?.ok) {
        throw new Error(response?.error || t('vocabBookFailed'));
      }
      renderVocabularyBook(scopeVocabularyToCurrentArticle(response.book));
    } catch (error) {
      vocabBookListElement.innerHTML = '';
      vocabBookStatusElement.textContent = error?.message || t('vocabBookFailed');
    }
  })().finally(() => {
    vocabBookLoadPromise = null;
  });
  return vocabBookLoadPromise;
}

function buildBookItemChatPayload(item) {
  const pos = item.part_of_speech ? ` [${item.part_of_speech}]` : '';
  return {
    message: '',
    study_item_id: item.id,
    context_label: 'study_item',
    context_text: item.text,
    context_analysis: {
      translation: item.meaning || '',
      grammar: '',
      nuance: '',
      vocabulary: item.meaning ? [`${item.text}${pos}: ${item.meaning}`] : [],
      examples: item.example ? [item.example] : [],
      study_tip: '',
    },
    page_preload_id: item.preload_id || null,
    page_url: item.page_url,
    page_title: item.page_title || '',
    history: [],
    target_language: item.target_language || null,
    native_language: item.native_language || null,
  };
}

function renderVocabBookDetail(item) {
  const exampleHtml = item.example
    ? `<div class="era-section era-vocab-example"><h3>${escapeHtml(t('sectionExample'))}</h3><p>${escapeHtml(item.example)}</p></div>`
    : '';
  return `${exampleHtml}${renderContextChat(getStudyItemChatKey(item.id))}`;
}

function refreshOpenVocabBookContextChats() {
  vocabBookListElement
    ?.querySelectorAll('.vocab-book-item-open .vocab-book-detail[data-rendered="true"]')
    .forEach((detail) => {
      const itemId = detail.closest('.vocab-book-item')?.dataset.bookItemId;
      const item = itemId ? vocabBookItemsById.get(itemId) : null;
      if (!item) return;
      detail.innerHTML = renderVocabBookDetail(item);
      attachContextChat(detail, {
        chatKey: getStudyItemChatKey(item.id),
        payload: buildBookItemChatPayload(item),
      });
    });
}

function toggleVocabBookEntry(itemId, { expand = null, scroll = false } = {}) {
  const entry = vocabBookListElement?.querySelector(
    `.vocab-book-item[data-book-item-id="${CSS.escape(itemId)}"]`,
  );
  if (!entry) return false;

  const detail = entry.querySelector('.vocab-book-detail');
  const toggle = entry.querySelector('.vocab-book-entry');
  const shouldExpand = expand === null ? !entry.classList.contains('vocab-book-item-open') : expand;

  if (shouldExpand && detail.dataset.rendered !== 'true') {
    const item = vocabBookItemsById.get(itemId);
    if (item) {
      detail.innerHTML = renderVocabBookDetail(item);
      detail.dataset.rendered = 'true';
      attachContextChat(detail, {
        chatKey: getStudyItemChatKey(item.id),
        payload: buildBookItemChatPayload(item),
      });
    }
  }

  if (shouldExpand) {
    detail.hidden = false;
  }
  entry.classList.toggle('vocab-book-item-open', shouldExpand);
  entry.querySelector('.era-vocab-card')?.classList.toggle('era-vocab-card-active', shouldExpand);
  toggle?.setAttribute('aria-expanded', String(shouldExpand));
  window.ReadingPanel?.animateAccordionContent?.(detail, {
    expand: shouldExpand,
    container: entry,
    onFinish: () => {
      detail.hidden = !shouldExpand;
      toggle?.setAttribute('aria-expanded', String(shouldExpand));
    },
  });
  if (scroll) {
    entry.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
  return true;
}

// Entry point for vocabulary marks clicked on the article page: open the
// book tab and expand that word.
async function openVocabularyBookEntry(studyItemId) {
  if (!isAuthenticated || !studyItemId) return;
  setSidePanelView('vocab');
  if (!vocabBookItemsById.has(studyItemId)) {
    await loadVocabularyBook();
  }
  toggleVocabBookEntry(studyItemId, { expand: true, scroll: true });
}

function renderVocabularyBook(book) {
  // Renders a flat, title-less list of the words it is given. Scoping to the
  // current article happens upstream in loadVocabularyBook, so this stays a
  // pure renderer (and deterministic to test).
  const items = book?.items || [];
  vocabBookItemsById = new Map(items.map((item) => [item.id, item]));

  if (!items.length) {
    vocabBookListElement.innerHTML = '';
    vocabBookStatusElement.textContent = t('vocabBookEmpty');
    return;
  }

  const speak = window.ReadingPanel;
  const rows = items
    .map((item) => {
      const detailId = `vocab-book-detail-${item.id}`;
      return `
        <li class="vocab-book-item" data-book-item-id="${escapeHtml(item.id)}">
          <div class="era-vocab-card">
            <button class="era-learning-point-button vocab-book-entry" type="button" data-book-item-id="${escapeHtml(item.id)}" aria-controls="${escapeHtml(detailId)}" aria-expanded="false">
              <span class="era-vocab-card-head">
                <span class="era-vocab-term">${escapeHtml(item.text)}</span>
                ${item.part_of_speech ? formatPartOfSpeechBadge(item.part_of_speech) : ''}
              </span>
              ${item.meaning ? `<span class="era-vocab-meaning">${escapeHtml(item.meaning)}</span>` : ''}
            </button>
            ${
              speak?.renderSpeakButton
                ? speak.renderSpeakButton({
                    key: `book:${item.id}`,
                    text: item.text,
                    label: t('speakTerm'),
                    extraClass: 'era-vocab-card-speak',
                    lang: item.target_language || '',
                  })
                : ''
            }
          </div>
          <div id="${escapeHtml(detailId)}" class="vocab-book-detail" hidden></div>
        </li>`;
    })
    .join('');

  vocabBookListElement.innerHTML = `<ul class="era-learning-points-list">${rows}</ul>`;
  vocabBookListElement.querySelectorAll('.vocab-book-entry').forEach((button) => {
    button.addEventListener('click', () => {
      toggleVocabBookEntry(button.dataset.bookItemId);
    });
  });
  speak?.bindSpeechEvents?.(vocabBookListElement);
  vocabBookStatusElement.textContent = t('vocabBookCount', { count: items.length });
}

// Resolves once the UI locale (from the native-language setting) has been
// applied to the static DOM and the selects. Context refreshes await this so
// dynamic status text never renders in the wrong language.
let uiLocaleBootstrap = Promise.resolve();

function applyUiLocaleToPanel() {
  applyDomTranslations(document);
  populateLearnerLevelPresets();
  populateLanguageSelects();
}

// Mirrors the stored panel theme onto the side panel document root so the
// shell chrome (settings, word book, empty states) themes via
// :root[data-theme] in panel-ui.css / reading-panel.css.
function renderShellThemeIcon(isDark) {
  // Sun while dark (press = back to light), moon while light.
  if (isDark) {
    return `
      <svg class="era-theme-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" aria-hidden="true">
        <circle cx="12" cy="12" r="4"></circle>
        <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"></path>
      </svg>
    `;
  }

  return `
    <svg class="era-theme-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" aria-hidden="true">
      <path d="M21 14.5A8.5 8.5 0 1 1 9.5 3a6.5 6.5 0 1 0 11.5 11.5z"></path>
    </svg>
  `;
}

function applySidePanelTheme(theme) {
  const normalized = theme === 'dark' ? 'dark' : 'light';
  document.documentElement.dataset.theme = normalized;
  if (darkModeToggle) {
    const isDark = normalized === 'dark';
    darkModeToggle.setAttribute('aria-pressed', String(isDark));
    darkModeToggle.setAttribute('aria-label', isDark ? t('themeToLight') : t('themeToDark'));
    darkModeToggle.title = isDark ? t('themeLight') : t('themeDark');
    darkModeToggle.innerHTML = renderShellThemeIcon(isDark);
  }
}

function initPanelUi() {
  if (panelUiInitialized) {
    return;
  }
  panelUiInitialized = true;

  bindPanelUiEvents();
  bindPanelStorageListeners();
  resetAuthButtonState();

  getPanelTheme()
    .then(applySidePanelTheme)
    .catch(() => {});

  uiLocaleBootstrap = getLanguageProfile()
    .then((profile) => {
      setUiLocale(profile.native);
    })
    .catch(() => {})
    .then(() => {
      applyUiLocaleToPanel();
    });

  handleSidePanelOpened().catch((error) => {
    logPanelError('handleSidePanelOpened', error);
  });
}

function resetAuthButtonState() {
  if (logoutButton) {
    logoutButton.disabled = false;
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initPanelUi, { once: true });
} else {
  initPanelUi();
}

function bindPanelStorageListeners() {
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local') return;

    if (changes.authSession || changes.authSessionGeneration) {
      clearCachedActivePreload();
      activePreloadSentenceCount = 0;
      window.ReadingPanel?.clearReadingPanel?.();
      updateReadingTabState(false);
      updateReadingEmptyState(false);
      handleSidePanelOpened().catch(() => {});
    }

    if (changes.languageProfile) {
      const profile = normalizeLanguageProfile(changes.languageProfile.newValue);
      setUiLocale(profile.native);
      applyUiLocaleToPanel();
      restoreLanguageProfile().catch(() => {});
      updateReadingTabState(activePreloadSentenceCount > 0, activePreloadSentenceCount);
      window.ReadingPanel?.applyUiLocale?.(profile.native);
      if (activeSidePanelView === 'vocab') {
        loadVocabularyBook().catch(() => {});
      }
      handleSidePanelOpened().catch(() => {});
    }

    if (changes.selectionAnalysisEnabled && selectionAnalysisToggle) {
      selectionAnalysisToggle.checked = Boolean(changes.selectionAnalysisEnabled.newValue);
    }

    if (changes.panelTheme) {
      const theme = changes.panelTheme.newValue === 'dark' ? 'dark' : 'light';
      applySidePanelTheme(theme);
      // Keep the mounted reading panel (data-era-theme + toggle icon) in
      // sync when the theme was changed from another context.
      window.ReadingPanel?.applyExternalTheme?.(theme);
    }

    if (changes.preloadJob) {
      applyPreloadJobStatus(changes.preloadJob.newValue).catch((error) => {
        logPanelError('applyPreloadJobStatus', error);
      });
    }

    if (Object.keys(changes).some((key) => key.startsWith(READING_SESSION_STORAGE_PREFIX))) {
      handleScopedReadingSessionChange(changes).catch((error) => {
        logPanelError('handleScopedReadingSessionChange', error);
      });
    }

    if (changes.hiddenQuickActions || changes.customChatPrompts) {
      if (changes.hiddenQuickActions) {
        setHiddenQuickActionsCache(changes.hiddenQuickActions.newValue);
      }
      if (changes.customChatPrompts) {
        setCustomChatPromptsCache(changes.customChatPrompts.newValue);
      }
      window.ReadingPanel?.refreshContextChatActions?.();
      refreshOpenVocabBookContextChats();
    }
  });

  chrome.runtime.onMessage.addListener((message) => {
    if (message.type === 'PAGE_HIGHLIGHT_STATE') {
      window.ReadingPanel?.applyExternalHighlightState(message.payload);
    }
  });

  chrome.tabs.onActivated.addListener(() => {
    handleSidePanelOpened().catch((error) => {
      logPanelError('handleSidePanelOpened', error);
    });
  });

  chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
    if (!changeInfo.url && changeInfo.status !== 'complete') return;

    getActiveTab()
      .then((tab) => {
        if (tab.id === tabId) {
          return handleSidePanelOpened();
        }
      })
      .catch(() => {});
  });
}

function isReadingPanelMounted(preloadId = '') {
  const root = document.getElementById('readingPanelRoot');
  if (!root || root.hidden || !root.innerHTML.trim()) {
    return false;
  }
  if (!preloadId) {
    return Boolean(root.querySelector('.era-sentence-list, .era-panel-detail-view'));
  }
  return (
    Boolean(root.querySelector('.era-sentence-list, .era-panel-detail-view')) &&
    root.dataset.preloadId === preloadId
  );
}

function applyReadingPanelVisibility(hasContent) {
  if (readingEmptyState) {
    readingEmptyState.hidden = Boolean(hasContent);
  }
  const root = document.getElementById('readingPanelRoot');
  if (root) {
    root.hidden = !hasContent;
  }
}

async function waitForReadingPanelApi(maxAttempts = 12) {
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    if (window.ReadingPanel?.mountReadingPanel) {
      return window.ReadingPanel;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 25));
  }
  return null;
}

async function mountReadingViewFromPreload(preload, pageUrl, pageTitle = '', authScope = null) {
  if (!preload?.sentences?.length) {
    return false;
  }

  const resolvedPageUrl = resolvePageUrl(pageUrl, preload);
  if (!resolvedPageUrl) {
    return false;
  }
  if (!authScope || !(await authScopeMatches(authScope))) return false;

  const readingPanel = await waitForReadingPanelApi();
  if (!readingPanel?.mountReadingPanel) {
    console.warn('[Untangle] ReadingPanel API unavailable in side panel');
    return false;
  }

  const storedSession = await getReadingSession(resolvedPageUrl, authScope);
  if (!(await authScopeMatches(authScope))) return false;
  const sessionForMount =
    storedSession &&
    pageUrlsMatch(storedSession.pageUrl, resolvedPageUrl) &&
    storedSession.preload?.id === preload.id
      ? storedSession
      : {
          pageUrl: resolvedPageUrl,
          pageTitle: pageTitle || preload.page_title || '',
          preload,
          domLinkStatus: storedSession?.domLinkStatus || {},
          ui: storedSession?.ui || {},
        };

  for (let attempt = 0; attempt < 3; attempt += 1) {
    if (!(await authScopeMatches(authScope))) return false;
    const mounted = await readingPanel.mountReadingPanel(sessionForMount);

    if (mounted) {
      if (await authScopeMatches(authScope)) {
        applyReadingPanelVisibility(true);
        return true;
      }
      window.ReadingPanel?.clearReadingPanel?.();
      return false;
    }

    if (!document.getElementById('readingPanelRoot')) {
      await new Promise((resolve) => window.setTimeout(resolve, 50));
    }
  }

  return false;
}

function populateLearnerLevelPresets() {
  const selected = learnerLevelPresetInput.value;
  // The preset scale follows the language being studied (the target select
  // mirrors the stored profile once restored).
  const target = targetLanguageSelect?.value || '';
  learnerLevelPresetInput.innerHTML = getLearnerLevelPresets(target)
    .map((preset) => `<option value="${preset.id}">${preset.label}</option>`)
    .join('');
  if (selected) {
    learnerLevelPresetInput.value = selected;
    window.SelectUI?.refresh(learnerLevelPresetInput);
  }
}

function populateLanguageSelects() {
  const options = LANGUAGE_OPTIONS.map(
    (option) => `<option value="${option.code}">${option.label}</option>`,
  ).join('');

  if (targetLanguageSelect) {
    targetLanguageSelect.innerHTML = `<option value="${AUTO_TARGET_LANGUAGE}">${t('langAutoOption')}</option>${options}`;
  }
  if (nativeLanguageSelect) {
    nativeLanguageSelect.innerHTML = options;
  }
}

function updateLanguageSummary(profile) {
  if (!languageSummaryElement) return;

  const targetLabel =
    profile.target === AUTO_TARGET_LANGUAGE
      ? t('langAutoShort')
      : getLanguageLabel(profile.target) || profile.target;
  const nativeLabel = getLanguageLabel(profile.native) || profile.native;
  languageSummaryElement.textContent = t('langSummary', {
    target: targetLabel,
    native: nativeLabel,
  });
}

async function restoreLanguageProfile() {
  const profile = await getLanguageProfile();
  if (targetLanguageSelect) {
    targetLanguageSelect.value = profile.target;
    window.SelectUI?.refresh(targetLanguageSelect);
  }
  if (nativeLanguageSelect) {
    nativeLanguageSelect.value = profile.native;
    window.SelectUI?.refresh(nativeLanguageSelect);
  }
  updateLanguageSummary(profile);
}

async function saveLanguageProfile() {
  const profile = await setLanguageProfile({
    target: targetLanguageSelect?.value,
    native: nativeLanguageSelect?.value,
  });
  updateLanguageSummary(profile);
}

async function restoreSelectionAnalysisSetting() {
  const enabled = await getSelectionAnalysisEnabled();
  if (selectionAnalysisToggle) {
    selectionAnalysisToggle.checked = enabled;
  }
}

async function saveSelectionAnalysisSetting(enabled) {
  const normalized = await setSelectionAnalysisEnabled(enabled);
  if (selectionAnalysisStatusElement) {
    selectionAnalysisStatusElement.textContent = t(
      normalized ? 'selectionAnalysisEnabledStatus' : 'selectionAnalysisDisabledStatus',
    );
  }
}

async function refreshPanelContext() {
  await uiLocaleBootstrap;
  resetAuthButtonState();
  await refreshAuthProviderConfig();
  // Auth state must be resolved before restoreSettings: the latter only
  // restores the learner level (and other gated fields) when isAuthenticated
  // is already true, so running it first left the level blank on every open.
  await refreshAuthUi();
  await restoreSettings();
  await loadCustomChatPromptsCache();
  await loadHiddenQuickActionsCache();
  renderCustomPromptsList();
  await refreshPreloadStatus();
  await refreshBillingInfo();
}

// --- Billing ------------------------------------------------------------------
// The settings tab shows the current plan and monthly usage, with upgrade
// buttons (Stripe Checkout in production, instant switch with the mock
// provider) and the customer portal for paid plans.

async function refreshBillingInfo() {
  if (!isAuthenticated) {
    billingSummaryElement.textContent = '';
    renderBillingWarning('');
    billingUpgradeProButton.hidden = true;
    billingUpgradeMaxButton.hidden = true;
    billingPortalButton.hidden = true;
    return;
  }

  try {
    const response = await chrome.runtime.sendMessage({ type: 'GET_BILLING_ME' });
    if (!response?.ok) throw new Error(response?.error || t('billingLoadFailed'));
    const billing = response.billing;

    const resetDate = new Intl.DateTimeFormat(getUiLocale(), {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      timeZone: 'UTC',
    }).format(new Date(billing.reset_at));
    const planRank = BILLING_PLAN_RANK[billing.plan];
    const quotaPlanRank = BILLING_PLAN_RANK[billing.quota_plan];
    const hasRankedMismatch =
      Number.isInteger(planRank) && Number.isInteger(quotaPlanRank) && planRank !== quotaPlanRank;
    const mismatchKey =
      planRank > quotaPlanRank
        ? 'billingQuotaPlanUpgradePending'
        : 'billingQuotaPlanDeferredDowngrade';
    const planLine = hasRankedMismatch
      ? t(mismatchKey, {
          plan: billing.plan,
          quotaPlan: billing.quota_plan,
        })
      : t('billingPlanSummary', { plan: billing.plan });
    const summaryLines = [
      planLine,
      t('billingArticlesUsage', {
        used: billing.articles_used,
        pending: billing.articles_pending,
        remaining: billing.articles_remaining,
      }),
      t('billingChatsUsage', {
        used: billing.chats_used,
        pending: billing.chats_pending,
        remaining: billing.chats_remaining,
      }),
      t('billingResetAt', { date: resetDate }),
    ];
    // A scheduled cancellation keeps the paid plan until its end date.
    if (billing.plan_ends_at) {
      const date = new Intl.DateTimeFormat(getUiLocale(), {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      }).format(new Date(billing.plan_ends_at * 1000));
      summaryLines.push(t('billingEndsAt', { date }));
    }
    billingSummaryElement.textContent = summaryLines.join('\n');
    const atLimit = billing.articles_remaining === 0 || billing.chats_remaining === 0;
    const approaching = Array.isArray(billing.warning_codes) && billing.warning_codes.length > 0;
    renderBillingWarning(
      atLimit ? t('billingQuotaLimit') : approaching ? t('billingQuotaWarning') : '',
      atLimit ? 'limit' : 'warning',
    );
    // Checkout is for new subscriptions only; existing subscribers change
    // plans (incl. pro -> max) through the customer portal.
    billingUpgradeProButton.hidden = billing.plan !== 'basic';
    billingUpgradeMaxButton.hidden = billing.plan !== 'basic';
    billingPortalButton.hidden = billing.plan === 'basic';
  } catch {
    billingSummaryElement.textContent = t('billingLoadFailed');
    renderBillingWarning('');
    billingUpgradeProButton.hidden = true;
    billingUpgradeMaxButton.hidden = true;
    billingPortalButton.hidden = true;
  }
}

function renderBillingWarning(message, state = 'warning') {
  if (!billingWarningElement) return;
  const nextMessage = String(message || '');
  if (billingWarningElement.textContent !== nextMessage) {
    billingWarningElement.textContent = nextMessage;
  }
  billingWarningElement.hidden = !nextMessage;
  if (nextMessage) {
    billingWarningElement.dataset.state = state;
  } else {
    delete billingWarningElement.dataset.state;
  }
}

async function openExternalUrl(url) {
  try {
    await chrome.tabs.create({ url });
  } catch {
    window.open(url, '_blank');
  }
}

async function handleBillingUpgrade(plan) {
  billingStatusElement.textContent = '';
  try {
    const response = await chrome.runtime.sendMessage({
      type: 'BILLING_CHECKOUT',
      payload: { plan },
    });
    if (!response?.ok) throw new Error(response?.error || t('billingLoadFailed'));

    if (response.checkout.activated) {
      billingStatusElement.textContent = t('billingActivated');
      await refreshBillingInfo();
      return;
    }
    await openExternalUrl(response.checkout.url);
    billingStatusElement.textContent = t('billingCheckoutOpened');
  } catch (error) {
    billingStatusElement.textContent = error.message || t('billingLoadFailed');
  }
}

async function handleBillingPortal() {
  billingStatusElement.textContent = '';
  try {
    const response = await chrome.runtime.sendMessage({ type: 'BILLING_PORTAL' });
    if (!response?.ok) throw new Error(response?.error || t('billingLoadFailed'));
    await openExternalUrl(response.portal.url);
  } catch (error) {
    billingStatusElement.textContent = error.message || t('billingLoadFailed');
  }
}

async function restoreSettings() {
  try {
    const tab = await getActiveTab();
    activePageUrl = normalizePageUrl(tab.url);
  } catch {
    activePageUrl = '';
  }

  await restoreLanguageProfile();
  await restoreSelectionAnalysisSetting();
  // The preset scale depends on the restored target language; repopulate
  // before applying the stored preset id so the option exists.
  populateLearnerLevelPresets();

  if (isAuthenticated) {
    const profile = await getLearnerProfile();
    learnerLevelPresetInput.value = profile.preset || '';
    window.SelectUI?.refresh(learnerLevelPresetInput);
    learnerLevelNotesInput.value = profile.notes || '';
    updateLearnerLevelSummary(profile);
  } else {
    updateLearnerLevelSummary(null, { loggedOut: true });
  }
}

function renderQuickActionToggle(id, isHidden) {
  const label = isHidden ? t('customPromptShow') : t('customPromptHide');
  return `<button type="button" class="custom-prompt-toggle">${escapeHtml(label)}</button>`;
}

function renderCustomPromptsList() {
  if (!customPromptsList) return;
  const hiddenSet = new Set(getCachedHiddenQuickActions());

  const presetRows = SENTENCE_QUICK_CHAT_ACTIONS.map((id) => {
    const action = getQuickChatAction(id);
    if (!action) return '';
    const isHidden = hiddenSet.has(id);
    return `
      <li
        class="custom-prompts-item is-preset${isHidden ? ' is-hidden' : ''}"
        data-prompt-id="${escapeHtml(id)}"
        data-prompt-message="${escapeHtml(action.message)}"
      >
        <div class="custom-prompts-item-text"><strong>${escapeHtml(action.label)}</strong></div>
        <div class="custom-prompts-item-actions">${renderQuickActionToggle(id, isHidden)}</div>
      </li>`;
  }).join('');

  const prompts = getCachedCustomChatPrompts();
  const customRows = prompts.length
    ? prompts
        .map((prompt, index) => {
          const isHidden = hiddenSet.has(prompt.id);
          return `
      <li
        class="custom-prompts-item${isHidden ? ' is-hidden' : ''}"
        data-prompt-id="${escapeHtml(prompt.id)}"
        data-prompt-message="${escapeHtml(prompt.message)}"
      >
        <div class="custom-prompts-item-text"><strong>${escapeHtml(prompt.label)}</strong></div>
        <div class="custom-prompts-item-actions">
          ${renderQuickActionToggle(prompt.id, isHidden)}
          <button type="button" class="custom-prompt-move" data-direction="-1" ${index === 0 ? 'disabled' : ''} title="${escapeHtml(t('customPromptMoveUp'))}" aria-label="${escapeHtml(t('customPromptMoveUp'))}">▲</button>
          <button type="button" class="custom-prompt-move" data-direction="1" ${index === prompts.length - 1 ? 'disabled' : ''} title="${escapeHtml(t('customPromptMoveDown'))}" aria-label="${escapeHtml(t('customPromptMoveDown'))}">▼</button>
          <button type="button" class="custom-prompt-edit">${escapeHtml(t('customPromptEdit'))}</button>
          <button type="button" class="custom-prompt-delete">${escapeHtml(t('customPromptDelete'))}</button>
        </div>
      </li>`;
        })
        .join('')
    : `<li class="custom-prompts-empty">${escapeHtml(t('customPromptEmpty'))}</li>`;

  customPromptsList.innerHTML = `
    <li class="custom-prompts-group">${escapeHtml(t('customPromptsPresetGroup'))}</li>
    ${presetRows}
    <li class="custom-prompts-group">${escapeHtml(t('customPromptsCustomGroup'))}</li>
    ${customRows}`;
}

function resetCustomPromptForm() {
  editingCustomPromptId = null;
  if (customPromptName) customPromptName.value = '';
  if (customPromptBody) customPromptBody.value = '';
  if (customPromptAddButton) customPromptAddButton.textContent = t('customPromptAdd');
  if (customPromptCancelButton) customPromptCancelButton.hidden = true;
  if (customPromptStatus) customPromptStatus.textContent = '';
}

async function persistCustomPrompts(list) {
  const saved = await saveCustomChatPrompts(list);
  setCustomChatPromptsCache(saved);
  renderCustomPromptsList();
  return saved;
}

async function handleCustomPromptSubmit() {
  const label = customPromptName?.value ?? '';
  const message = customPromptBody?.value ?? '';
  const current = getCachedCustomChatPrompts();
  const result = editingCustomPromptId
    ? updateCustomChatPrompt(current, editingCustomPromptId, { label, message })
    : addCustomChatPrompt(current, { label, message });
  if (!result.ok) {
    if (customPromptStatus) {
      customPromptStatus.textContent =
        result.error === 'limit'
          ? t('customPromptLimit', { max: MAX_CUSTOM_CHAT_PROMPTS })
          : t('customPromptInvalid');
    }
    return;
  }
  await persistCustomPrompts(result.list);
  resetCustomPromptForm();
}

function beginEditCustomPrompt(id) {
  const prompt = getCachedCustomChatPrompts().find((item) => item.id === id);
  if (!prompt) return;
  editingCustomPromptId = id;
  if (customPromptName) customPromptName.value = prompt.label;
  if (customPromptBody) customPromptBody.value = prompt.message;
  if (customPromptAddButton) customPromptAddButton.textContent = t('customPromptSave');
  if (customPromptCancelButton) customPromptCancelButton.hidden = false;
  if (customPromptStatus) customPromptStatus.textContent = '';
  customPromptName?.focus();
}

async function handleCustomPromptListClick(event) {
  const item = event.target.closest('.custom-prompts-item');
  if (!item) return;
  const id = item.dataset.promptId;
  if (event.target.closest('.custom-prompt-toggle')) {
    const saved = await setHiddenQuickActions(
      toggleHiddenQuickAction(getCachedHiddenQuickActions(), id),
    );
    setHiddenQuickActionsCache(saved);
    renderCustomPromptsList();
    return;
  }
  if (event.target.closest('.custom-prompt-delete')) {
    await persistCustomPrompts(removeCustomChatPrompt(getCachedCustomChatPrompts(), id));
    if (editingCustomPromptId === id) resetCustomPromptForm();
    return;
  }
  if (event.target.closest('.custom-prompt-edit')) {
    beginEditCustomPrompt(id);
    return;
  }
  const moveButton = event.target.closest('.custom-prompt-move');
  if (moveButton) {
    const delta = Number(moveButton.dataset.direction);
    await persistCustomPrompts(moveCustomChatPrompt(getCachedCustomChatPrompts(), id, delta));
  }
}

function updateAuthenticatedFeaturesUi() {
  const featuresEnabled = isAuthenticated;

  authenticatedFeaturesElement?.classList.toggle('features-locked', !featuresEnabled);

  if (learnerLevelPresetInput) {
    learnerLevelPresetInput.disabled = !featuresEnabled;
  }
  if (learnerLevelNotesInput) {
    learnerLevelNotesInput.disabled = !featuresEnabled;
  }
  if (targetLanguageSelect) {
    targetLanguageSelect.disabled = !featuresEnabled;
  }
  if (nativeLanguageSelect) {
    nativeLanguageSelect.disabled = !featuresEnabled;
  }
  if (selectionAnalysisToggle) {
    selectionAnalysisToggle.disabled = !featuresEnabled;
  }

  if (vocabBookViewButton) {
    vocabBookViewButton.disabled = !featuresEnabled;
  }

  if (!featuresEnabled) {
    updateLearnerLevelSummary(null, { loggedOut: true });
    if (activeSidePanelView === 'reading' || activeSidePanelView === 'vocab') {
      setSidePanelView('settings');
    }
    window.ReadingPanel?.clearReadingPanel();
    applyReadingPanelVisibility(false);
    updateReadingTabState(false);
    updateReadingEmptyState(false);
  }
}

async function saveLearnerProfile() {
  if (!isAuthenticated) {
    updateLearnerLevelSummary(null, { loggedOut: true });
    return;
  }
  const previousProfile = await getLearnerProfile();
  const profile = await setLearnerProfile({
    preset: learnerLevelPresetInput.value,
    notes: learnerLevelNotesInput.value,
  });
  const profileChanged =
    previousProfile.preset !== profile.preset || previousProfile.notes !== profile.notes;
  if (profileChanged) {
    await invalidateCurrentPagePreloadSession();
  }
  updateLearnerLevelSummary(profile);
  learnerLevelSummaryElement.textContent = profileChanged
    ? `${t('learnerSaved')} ${t('learnerSectionDesc')}`
    : t('learnerSaved');
  window.setTimeout(() => {
    if (learnerLevelSummaryElement.textContent.startsWith(t('learnerSaved'))) {
      updateLearnerLevelSummary(profile);
    }
  }, 1800);
}

async function invalidateCurrentPagePreloadSession() {
  hidePreloadOverwriteConfirm();

  // Keep the current reading view. The new learner level only affects the next
  // explicit re-preload (with overwrite confirmation when a ready record exists).
  const count = activePreloadSentenceCount || cachedActivePreload?.sentences?.length || 0;
  setPreloadStatus(
    'idle',
    count > 0
      ? `${t('learnerSectionDesc')} ${t('statusPreloadedReconfirm', { count })}`
      : t('learnerSectionDesc'),
  );
}

function updateLearnerLevelSummary(profile, options = {}) {
  if (options.loggedOut) {
    learnerLevelSummaryElement.textContent = t('learnerLoginRequired');
    return;
  }

  const formatted = formatLearnerLevelForApi(profile);
  learnerLevelSummaryElement.textContent = formatted
    ? t('learnerSummary', { level: formatted })
    : t('learnerSummaryUnset');
}

async function refreshAuthUi() {
  const session = await getAuthSession();
  isAuthenticated = Boolean(session?.accessToken);

  authLoggedOutElement.hidden = isAuthenticated;
  authLoggedInElement.hidden = !isAuthenticated;

  if (isAuthenticated) {
    authUserSummaryElement.textContent = `${session.user.display_name} (${session.user.email})`;
  } else {
    authUserSummaryElement.textContent = '';
  }

  updateAuthenticatedFeaturesUi();

  if (!isAuthenticated) {
    authStatusElement.textContent = t('authLoginPrompt');
  } else if (
    authStatusElement.textContent === t('authLoginPrompt') ||
    authStatusElement.textContent === UI_MESSAGES.ja.authLoginPrompt
  ) {
    authStatusElement.textContent = '';
  }
}

// The server decides the sign-in flow (mock locally, Google SSO in
// production); the panel fetches it once and renders the matching UI.
let authProviderConfig = { provider: 'mock', google_client_id: null };

async function refreshAuthProviderConfig() {
  try {
    const response = await chrome.runtime.sendMessage({ type: 'GET_AUTH_CONFIG' });
    if (response?.ok && response.config?.provider) {
      authProviderConfig = response.config;
    }
  } catch {
    // Keep the mock default when the server is unreachable.
  }
  applyAuthProviderUi();
}

// Hands the panel over to whichever sign-in method the server named. This
// function knows that methods exist, not which ones: see signin-methods.js.
function applyAuthProviderUi() {
  if (!signInRootElement) {
    return;
  }
  signInRootElement.replaceChildren();

  const method = signInMethodFor(authProviderConfig.provider);
  if (!method) {
    const notice = document.createElement('small');
    notice.className = 'signin-notice signin-notice-error';
    notice.textContent = t('authProviderUnsupported', {
      provider: authProviderConfig.provider,
    });
    signInRootElement.appendChild(notice);
    return;
  }

  method.render(signInRootElement, {
    config: authProviderConfig,
    submit: submitLogin,
    setStatus: (message) => {
      authStatusElement.textContent = message;
    },
  });
}

// Sends the credential a method produced to the server and installs the
// returned session. Provider-agnostic: the credential is opaque here.
// Rejects on failure so the method can restore its own controls.
async function submitLogin(credential) {
  authStatusElement.textContent = t('authLoggingIn');

  try {
    const response = await chrome.runtime.sendMessage({
      type: 'LOGIN',
      payload: { credential },
    });

    if (chrome.runtime.lastError) {
      throw new Error(chrome.runtime.lastError.message);
    }

    if (!response?.ok) {
      throw new Error(response?.error || t('statusLoginFailed'));
    }

    await refreshAuthUi();
    authStatusElement.textContent = t('authLoggedInMsg');
    await restoreSettings();
    await refreshPreloadStatus();
    await refreshBillingInfo();
  } catch (error) {
    authStatusElement.textContent = error.message || t('statusLoginFailed');
    throw error;
  }
}

async function handleLogout() {
  logoutButton.disabled = true;

  try {
    const response = await chrome.runtime.sendMessage({ type: 'LOGOUT' });

    if (chrome.runtime.lastError) {
      throw new Error(chrome.runtime.lastError.message);
    }

    if (!response?.ok) {
      throw new Error(response?.error || t('statusLogoutFailed'));
    }

    await refreshAuthUi();
    await refreshBillingInfo();
    authStatusElement.textContent = t('authLoggedOutMsg');
    clearCachedActivePreload();
    activePreloadSentenceCount = 0;
    setPreloadStatus('idle', t('statusPreloadLoginRequired'));
    setSidePanelView('settings');
  } catch (error) {
    authStatusElement.textContent = error.message || t('statusLogoutFailed');
  } finally {
    logoutButton.disabled = false;
  }
}

async function getActiveTab() {
  const response = await chrome.runtime.sendMessage({
    type: 'GET_ACTIVE_TAB',
    payload: activePageUrl ? { pageUrl: activePageUrl } : {},
  });

  if (chrome.runtime.lastError) {
    throw new Error(chrome.runtime.lastError.message);
  }

  if (!response?.ok || !response.tab?.id) {
    throw new Error(response?.error || t('errPageUnavailable'));
  }

  activeTabId = response.tab.id;
  if (!activePageUrl) {
    activePageUrl = normalizePageUrl(response.tab.url);
  }
  return response.tab;
}

async function ensureActivePageUrl() {
  if (activePageUrl) {
    return activePageUrl;
  }

  const tab = await getActiveTab();
  activePageUrl = normalizePageUrl(tab.url);
  return activePageUrl;
}

async function restorePageReadingSession(tabId) {
  if (!tabId || !activePageUrl) {
    return;
  }

  await chrome.runtime
    .sendMessage({
      type: 'RESTORE_PAGE_READING_SESSION',
      payload: { tabId, pageUrl: activePageUrl },
    })
    .catch(() => {});
}

async function preloadMatchesCurrentLearnerProfile(preload) {
  if (!preload) {
    return false;
  }
  const profile = await getLearnerProfile();
  const preloadFingerprint = JSON.stringify({
    learner_level: normalizeLearnerProfileText(preload?.learner_level),
    vocabulary_coverage_percent: Number(
      preload?.vocabulary_coverage_percent ?? DEFAULT_VOCABULARY_COVERAGE_PERCENT,
    ),
  });
  return preloadFingerprint === getLearnerProfileCacheFingerprint(profile);
}

async function refreshPreloadStatus() {
  try {
    const tab = await getActiveTab();
    activePageUrl = normalizePageUrl(tab.url);

    if (!isAuthenticated) {
      setPreloadStatus('idle', t('statusPreloadLoginRequired'));
      clearCachedActivePreload();
      activePreloadSentenceCount = 0;
      updateReadingTabState(false);
      updateReadingEmptyState(false);
      return;
    }
    const authScope = await getAuthScope();
    if (!authScope) return;

    setPreloadStatus('loading', t('statusChecking'));

    const { preloadJob } = await chrome.storage.local.get('preloadJob');
    if (!(await authScopeMatches(authScope))) return;
    if (
      preloadJob?.pageUrl &&
      pageUrlsMatch(preloadJob.pageUrl, activePageUrl) &&
      preloadJob.state === 'loading'
    ) {
      setPreloadStatus('loading', `${preloadJob.message} ${t('bgContinueNote')}`);
      return;
    }

    const response = await chrome.runtime.sendMessage({
      type: 'GET_PRELOAD_STATUS',
      payload: { page_url: activePageUrl },
    });
    if (!(await authScopeMatches(authScope))) return;

    if (!response?.ok) {
      setPreloadStatus('idle', toUserFacingErrorMessage(response?.error, t('statusFetchFailed')));
      updateReadingTabState(false);
      updateReadingEmptyState(false);
      return;
    }

    if (response.status?.ready && (response.status.preload?.sentences?.length || 0) > 0) {
      const preload = response.status.preload;
      const count = preload.sentences.length;
      const profileMatches = await preloadMatchesCurrentLearnerProfile(preload);
      if (!(await authScopeMatches(authScope))) return;
      activePreloadSentenceCount = count;
      cacheActivePreload(preload, authScope);
      setPreloadStatus(
        profileMatches ? 'ready' : 'idle',
        profileMatches
          ? t('statusPreloadedReadTab', { count })
          : `${t('learnerSectionDesc')} ${t('statusPreloadedReconfirm', { count })}`,
      );

      await syncReadingViewUi({
        preload,
        pageTitle: tab.title,
        sentenceCount: count,
        switchToReading: activeSidePanelView === 'reading',
        authScope,
      });
      return;
    }

    // The record exists but the async analysis is still running (no active
    // local preloadJob, e.g. the job was started elsewhere). Show the loading
    // state, not "not loaded", so the reader knows it is on the way.
    const recordStatus = response.status?.status ?? response.status?.preload?.status ?? null;
    if (recordStatus === 'processing') {
      setPreloadStatus('loading', `${t('preloadSplitting')} ${t('bgContinueNote')}`);
      updateReadingTabState(false);
      updateReadingEmptyState(false);
      return;
    }

    if (recordStatus === 'failed') {
      setPreloadStatus('idle', response.status?.error || t('preloadFailedStatus'));
      updateReadingTabState(false);
      updateReadingEmptyState(false);
      return;
    }

    if (
      preloadJob?.pageUrl &&
      pageUrlsMatch(preloadJob.pageUrl, activePageUrl) &&
      preloadJob.state === 'error'
    ) {
      setPreloadStatus('idle', preloadJob.message);
      updateReadingTabState(false);
      updateReadingEmptyState(false);
      return;
    }

    setPreloadStatus('idle', t('statusNotLoaded'));
    clearCachedActivePreload();
    activePreloadSentenceCount = 0;
    window.ReadingPanel?.clearReadingPanel();
    updateReadingTabState(false);
    updateReadingEmptyState(false);
  } catch (error) {
    setPreloadStatus('idle', toUserFacingErrorMessage(error, t('statusFetchFailed')));
    updateReadingTabState(false);
    updateReadingEmptyState(false);
  }
}

async function applyPreloadJobStatus(preloadJob) {
  if (!isAuthenticated) return;
  if (!activePageUrl || !preloadJob?.pageUrl || !pageUrlsMatch(preloadJob.pageUrl, activePageUrl))
    return;
  const authScope = await getAuthScope();
  if (!authScope || !(await authScopeMatches(authScope))) return;

  if (preloadJob.state === 'loading') {
    hidePreloadOverwriteConfirm();
    setPreloadStatus('loading', `${preloadJob.message} ${t('bgContinueNote')}`);
    return;
  }

  if (preloadJob.state === 'ready') {
    hidePreloadOverwriteConfirm();
    const count = preloadJob.sentenceCount || 0;
    if (count > 0) {
      activePreloadSentenceCount = count;
    }
    setPreloadStatus('ready', count ? t('statusDonePanel', { count }) : preloadJob.message);
    syncReadingViewUi({
      switchToReading: activeSidePanelView === 'reading',
      sentenceCount: count,
      authScope,
    }).catch(() => {});
    return;
  }

  if (preloadJob.state === 'error' || preloadJob.state === 'idle') {
    hidePreloadOverwriteConfirm();
    setPreloadStatus('idle', toUserFacingErrorMessage(preloadJob.message, t('preloadAborted')));
  }
}

function showPreloadOverwriteConfirm({ preload, count, tab, authScope, retainLocal = true }) {
  pendingPreloadOverwrite = { preload, count, tab, authScope };
  if (retainLocal) {
    cacheActivePreload(preload, authScope);
    activePreloadSentenceCount = count;
  }

  if (preloadConfirmMessageElement) {
    preloadConfirmMessageElement.textContent = t('confirmOverwriteMsg', { count });
  }

  if (preloadConfirmElement) {
    preloadConfirmElement.hidden = false;
  }
  preloadConfirmButton?.focus();
}

function hidePreloadOverwriteConfirm() {
  pendingPreloadOverwrite = null;
  if (preloadConfirmElement) {
    preloadConfirmElement.hidden = true;
  }
}

async function startPreload({ forceOverwrite = false, tab: providedTab = null } = {}) {
  try {
    if (!isAuthenticated) {
      hidePreloadOverwriteConfirm();
      setPreloadStatus('idle', t('statusPreloadLoginRequired'));
      return;
    }
    const authScope = await getAuthScope();
    if (!authScope) return;

    const tab = providedTab || (await getActiveTab());
    activePageUrl = normalizePageUrl(tab.url);

    if (preloadRetryMode) {
      preloadRetryMode = false;
      await chrome.runtime.sendMessage({ type: 'CANCEL_PRELOAD' }).catch(() => {});
      await chrome.storage.local.set({
        preloadJob: {
          pageUrl: activePageUrl,
          state: 'idle',
          message: t('statusRetrying'),
          updatedAt: Date.now(),
        },
      });
    }

    const existing = await chrome.runtime.sendMessage({
      type: 'GET_PRELOAD_STATUS',
      payload: { page_url: activePageUrl },
    });
    if (!(await authScopeMatches(authScope))) return;

    if (
      !forceOverwrite &&
      existing?.ok &&
      existing.status?.ready &&
      (existing.status.preload?.sentences?.length || 0) > 0
    ) {
      const preload = existing.status.preload;
      const count = preload.sentences.length;
      const profileMatches = await preloadMatchesCurrentLearnerProfile(preload);
      if (!(await authScopeMatches(authScope))) return;
      setPreloadStatus(
        profileMatches ? 'ready' : 'idle',
        profileMatches
          ? t('statusPreloadedReconfirm', { count })
          : `${t('learnerSectionDesc')} ${t('statusPreloadedReconfirm', { count })}`,
      );
      showPreloadOverwriteConfirm({ preload, count, tab, authScope, retainLocal: true });
      await syncReadingViewUi({
        preload,
        pageTitle: tab.title,
        sentenceCount: count,
        switchToReading: activeSidePanelView === 'reading',
        authScope,
      });
      return;
    }

    hidePreloadOverwriteConfirm();
    setPreloadStatus('loading', `${t('preloadSplitting')} ${t('bgContinueNote')}`);
    preloadButton.disabled = true;

    chrome.runtime
      .sendMessage({
        type: 'START_PRELOAD',
        payload: { tabId: tab.id },
      })
      .then(async (response) => {
        if (!(await authScopeMatches(authScope))) {
          throw new Error(t('preloadCancelled'));
        }
        if (!response?.ok) {
          throw new Error(response?.error || t('preloadFailed'));
        }

        const count = response.preload?.sentences?.length || 0;
        setPreloadStatus('ready', t('statusDonePanel', { count }));
        syncReadingViewUi({
          switchToReading: activeSidePanelView === 'reading',
          preload: response.preload,
          sentenceCount: count,
          authScope,
        }).catch(() => {});
      })
      .catch((error) => {
        let message = toUserFacingErrorMessage(error, t('preloadFailed'));
        if (message.includes('Receiving end does not exist')) {
          message = t('errNotInjected');
        }
        if (message.includes('message port closed')) {
          return;
        }
        if (message === t('preloadCancelled') || message === UI_MESSAGES.ja.preloadCancelled) {
          setPreloadStatus('idle', t('preloadAborted'));
          return;
        }
        setPreloadStatus('idle', message);
      })
      .finally(() => {
        preloadButton.disabled = !isAuthenticated;
      });
  } catch (error) {
    setPreloadStatus('idle', toUserFacingErrorMessage(error, t('preloadFailed')));
    preloadButton.disabled = false;
  }
}

function setSidePanelView(view) {
  activeSidePanelView = view;
  const panelMain = document.querySelector('.panel-ui');
  panelMain?.classList.toggle('view-settings', view === 'settings');
  panelMain?.classList.toggle('view-reading', view === 'reading');
  panelMain?.classList.toggle('view-vocab', view === 'vocab');

  const tabs = [
    [settingsViewButton, 'settings'],
    [readingViewButton, 'reading'],
    [vocabBookViewButton, 'vocab'],
  ];
  for (const [button, tabView] of tabs) {
    button?.classList.toggle('side-panel-view-active', view === tabView);
    button?.setAttribute('aria-selected', String(view === tabView));
  }
}

function updateReadingTabState(hasContent, sentenceCount = 0) {
  if (!readingViewButton) return;

  if (sentenceCount > 0) {
    activePreloadSentenceCount = sentenceCount;
  } else if (!hasContent) {
    activePreloadSentenceCount = 0;
  }

  const tabAvailable = isAuthenticated && (hasContent || activePreloadSentenceCount > 0);
  readingViewButton.disabled = !tabAvailable;
  // Label stays clean: the sentence count lives in the reading view's own
  // meta line, not on the tab.
  readingViewButton.textContent = t('tabReadingView');
}

function updateReadingEmptyState(hasContent, sentenceCount = 0) {
  if (!readingEmptyState) return;

  const hasMountedPanel = isReadingPanelMounted();
  const shouldShowContent = Boolean(hasContent || hasMountedPanel);
  readingEmptyState.hidden = shouldShowContent;
  if (shouldShowContent) {
    return;
  }

  if (!hasContent && !isAuthenticated) {
    if (readingEmptyMessageElement) {
      readingEmptyMessageElement.textContent = t('readingEmptyLogin');
    }
    if (goToPreloadButton) {
      goToPreloadButton.textContent = t('btnLogin');
    }
    return;
  }

  if (!hasContent && sentenceCount > 0) {
    if (readingEmptyMessageElement) {
      readingEmptyMessageElement.textContent = t('readingEmptyRetry');
    }
    if (goToPreloadButton) {
      goToPreloadButton.textContent = t('btnRetry');
    }
    return;
  }

  if (readingEmptyMessageElement) {
    readingEmptyMessageElement.textContent = t('readingEmptyDefault');
  }
  if (goToPreloadButton) {
    goToPreloadButton.textContent = t('btnGoToSettings');
  }
}

async function hydrateReadingSessionFromPreload(
  preload,
  pageUrl,
  pageTitle = '',
  authScope = null,
) {
  if (!preload?.sentences?.length || !pageUrl) {
    return null;
  }

  const resolvedAuthScope = authScope || (await getAuthScope());
  if (!resolvedAuthScope || !(await authScopeMatches(resolvedAuthScope))) return null;

  const normalizedPageUrl = normalizePageUrl(pageUrl);
  const existing = await getReadingSession(normalizedPageUrl, resolvedAuthScope);
  if (
    pageUrlsMatch(existing?.pageUrl, normalizedPageUrl) &&
    existing?.preload?.sentences?.length &&
    existing.preload.id === preload.id
  ) {
    return existing.preload;
  }

  const stored = await setReadingSession(
    {
      pageUrl: normalizedPageUrl,
      pageTitle: pageTitle || existing?.pageTitle || '',
      preload,
      domLinkStatus: pageUrlsMatch(existing?.pageUrl, normalizedPageUrl)
        ? existing.domLinkStatus || {}
        : {},
      ui: pageUrlsMatch(existing?.pageUrl, normalizedPageUrl) ? existing.ui || {} : {},
      updatedAt: Date.now(),
    },
    resolvedAuthScope,
  );

  return stored ? preload : null;
}

async function removeReadingSessionForSupersededScope(pageUrl, authScope, preload) {
  if (!pageUrl || !isAuthScope(authScope) || !preload?.id) return false;

  const key = readingSessionStorageKey(pageUrl, authScope);
  if (!key) return false;

  try {
    const stored = await chrome.storage.local.get(key);
    const session = stored[key];
    if (!authScopesMatch(session?.owner, authScope) || session?.preload?.id !== preload.id) {
      return false;
    }
    await chrome.storage.local.remove(key);
    return true;
  } catch (error) {
    logPanelError('removeReadingSessionForSupersededScope', error);
    return false;
  }
}

async function ensureReadingSessionHydrated(preload, pageUrl, pageTitle = '', authScope = null) {
  const normalizedPageUrl = resolvePageUrl(pageUrl, preload);
  const initiatingScope = authScope || (await getAuthScope());
  if (!initiatingScope || !(await authScopeMatches(initiatingScope))) return null;

  if (preload?.sentences?.length) {
    if (normalizedPageUrl) {
      return hydrateReadingSessionFromPreload(
        preload,
        normalizedPageUrl,
        pageTitle,
        initiatingScope,
      );
    }
    return preload;
  }

  if (!normalizedPageUrl) {
    const cached = getCachedActivePreload(initiatingScope);
    return cached?.sentences?.length ? cached : null;
  }

  const existing = await getReadingSession(normalizedPageUrl, initiatingScope);
  if (existing?.preload?.sentences?.length) {
    return existing.preload;
  }

  if (!isAuthenticated) {
    return null;
  }

  const response = await chrome.runtime.sendMessage({
    type: 'GET_PRELOAD_STATUS',
    payload: { page_url: normalizedPageUrl },
  });

  if (
    response?.ok &&
    response.status?.ready &&
    response.status.preload?.sentences?.length &&
    (await authScopeMatches(initiatingScope))
  ) {
    return hydrateReadingSessionFromPreload(
      response.status.preload,
      normalizedPageUrl,
      pageTitle,
      initiatingScope,
    );
  }

  return null;
}

async function syncReadingViewUi(options = {}) {
  if (!isAuthenticated) {
    updateReadingTabState(false);
    updateReadingEmptyState(false);
    return false;
  }

  const { switchToReading = false, sentenceCount, preload, pageTitle, authScope = null } = options;
  const initiatingScope = authScope || (await getAuthScope());
  if (!initiatingScope || !(await authScopeMatches(initiatingScope))) return false;
  const preloadCandidate = preload
    ? authScopesMatch(authScope, initiatingScope)
      ? preload
      : null
    : getCachedActivePreload(initiatingScope);

  readingViewSyncInProgress = true;
  let hydratedSession = null;
  try {
    await ensureActivePageUrl().catch(() => {});
    if (!(await authScopeMatches(initiatingScope))) return false;
    const pageUrl = resolvePageUrl(activePageUrl, preloadCandidate);
    if (pageUrl) {
      activePageUrl = pageUrl;
    }

    const resolvedPreload = await ensureReadingSessionHydrated(
      preloadCandidate,
      pageUrl,
      pageTitle,
      initiatingScope,
    );
    if (resolvedPreload?.sentences?.length) {
      hydratedSession = { pageUrl, preload: resolvedPreload };
    }
    if (!(await authScopeMatches(initiatingScope))) return false;
    if (resolvedPreload?.sentences?.length) {
      cacheActivePreload(resolvedPreload, initiatingScope);
    }

    let hasContent = false;
    if (resolvedPreload) {
      if (isReadingPanelMounted(resolvedPreload.id)) {
        hasContent = true;
        applyReadingPanelVisibility(true);
      } else {
        hasContent = await mountReadingViewFromPreload(
          resolvedPreload,
          pageUrl,
          pageTitle || resolvedPreload.page_title || '',
          initiatingScope,
        );
      }
    }
    let count = sentenceCount ?? resolvedPreload?.sentences?.length ?? 0;
    if (!count && hasContent) {
      const storedSession = await getReadingSession(pageUrl, initiatingScope);
      if (!(await authScopeMatches(initiatingScope))) return false;
      count = storedSession?.preload?.sentences?.length || 0;
    }

    if (!(await authScopeMatches(initiatingScope))) return false;

    updateReadingTabState(hasContent || count > 0, count || 0);
    updateReadingEmptyState(hasContent, count || 0);
    applyReadingPanelVisibility(hasContent);

    if (switchToReading && hasContent) {
      setSidePanelView('reading');
    }

    try {
      const tab = await getActiveTab();
      await restorePageReadingSession(tab.id);
    } catch {
      // Ignore tabs where the content script is unavailable until refresh.
    }

    return hasContent;
  } catch (error) {
    console.error('[Untangle] syncReadingViewUi failed:', error);
    const fallbackCount =
      sentenceCount || preload?.sentences?.length || activePreloadSentenceCount || 0;
    updateReadingTabState(false, fallbackCount);
    updateReadingEmptyState(false, fallbackCount);
    return false;
  } finally {
    try {
      if (hydratedSession && !(await authScopeMatches(initiatingScope))) {
        await removeReadingSessionForSupersededScope(
          hydratedSession.pageUrl,
          initiatingScope,
          hydratedSession.preload,
        );
      }
    } catch (error) {
      logPanelError('syncReadingViewUi cleanup', error);
    } finally {
      readingViewSyncInProgress = false;
    }
  }
}

async function handleReadingSessionChange(previousSession, nextSession) {
  if (readingViewSyncInProgress) {
    return;
  }

  if (!isAuthenticated) {
    updateReadingTabState(false);
    updateReadingEmptyState(false);
    return;
  }

  const authScope = await getAuthScope();
  if (!authScope || !(await authScopeMatches(authScope))) return;
  if (nextSession?.owner && !authScopesMatch(nextSession.owner, authScope)) return;

  if (!nextSession?.preload?.sentences?.length) {
    if (cachedActivePreload?.sentences?.length) {
      await syncReadingViewUi({
        switchToReading: activeSidePanelView === 'reading',
        preload: cachedActivePreload,
        sentenceCount: cachedActivePreload.sentences.length,
        authScope: cachedActivePreloadScope,
      });
      return;
    }

    window.ReadingPanel?.clearReadingPanel();
    updateReadingTabState(false, activePreloadSentenceCount);
    updateReadingEmptyState(false, activePreloadSentenceCount);
    if (activePreloadSentenceCount === 0 && activeSidePanelView === 'reading') {
      setSidePanelView('settings');
    }
    return;
  }

  if (activePageUrl && !pageUrlsMatch(nextSession.pageUrl, activePageUrl)) {
    if (
      cachedActivePreload?.sentences?.length &&
      pageUrlsMatch(cachedActivePreload.page_url, activePageUrl)
    ) {
      await syncReadingViewUi({
        switchToReading: activeSidePanelView === 'reading',
        preload: cachedActivePreload,
        sentenceCount: cachedActivePreload.sentences.length,
        authScope: cachedActivePreloadScope,
      });
      return;
    }

    window.ReadingPanel?.clearReadingPanel();
    updateReadingTabState(false, activePreloadSentenceCount);
    updateReadingEmptyState(false, activePreloadSentenceCount);
    return;
  }

  const preloadChanged =
    previousSession?.preload?.id !== nextSession.preload?.id ||
    (previousSession?.preload?.sentences?.length || 0) !==
      (nextSession.preload?.sentences?.length || 0);

  const domLinksChanged =
    JSON.stringify(previousSession?.domLinkStatus || {}) !==
    JSON.stringify(nextSession.domLinkStatus || {});

  if (preloadChanged || !previousSession?.preload) {
    if (isReadingPanelMounted(nextSession.preload?.id)) {
      if (domLinksChanged) {
        window.ReadingPanel?.refreshDomLinkStatus(nextSession.domLinkStatus);
      }
      updateReadingTabState(true, nextSession.preload.sentences.length);
      updateReadingEmptyState(true, nextSession.preload.sentences.length);
      applyReadingPanelVisibility(true);
      return;
    }

    await syncReadingViewUi({
      switchToReading: activeSidePanelView === 'reading',
      preload: nextSession.preload,
      pageTitle: nextSession.pageTitle,
      sentenceCount: nextSession.preload?.sentences?.length || 0,
      authScope: nextSession.owner,
    });
    return;
  }

  if (domLinksChanged) {
    window.ReadingPanel?.refreshDomLinkStatus(nextSession.domLinkStatus);
  }

  const previousUi = previousSession?.ui || {};
  const nextUi = nextSession.ui || {};
  // A vocabulary mark clicked on the page opens that word in the book tab;
  // sentence selections open the reading tab as before.
  const studyItemSelected =
    nextUi.activeStudyItemId && previousUi.activeStudyItemId !== nextUi.activeStudyItemId;
  if (studyItemSelected) {
    openVocabularyBookEntry(nextUi.activeStudyItemId).catch((error) => {
      logPanelError('openVocabularyBookEntry', error);
    });
    return;
  }

  const selectionChanged =
    previousUi.activeSentenceId !== nextUi.activeSentenceId ||
    previousUi.activeSentenceScreen !== nextUi.activeSentenceScreen;

  if (selectionChanged) {
    window.ReadingPanel?.applyExternalSelection({
      pageUrl: nextSession.pageUrl,
      type: 'sentence',
      sentenceId: nextUi.activeSentenceId,
      activeSentenceScreen: nextUi.activeSentenceScreen,
    });
    updateReadingTabState(true, nextSession.preload?.sentences?.length || 0);
    setSidePanelView('reading');
    return;
  }

  if (previousUi.hoveredSentenceId !== nextUi.hoveredSentenceId) {
    window.ReadingPanel?.applyExternalHighlightState({
      pageUrl: nextSession.pageUrl,
      hoveredSentenceId: nextUi.hoveredSentenceId,
    });
  }
}

async function handleScopedReadingSessionChange(changes) {
  if (readingViewSyncInProgress || !activePageUrl) return;

  const authScope = await getAuthScope();
  if (!authScope || !(await authScopeMatches(authScope))) return;

  const key = readingSessionStorageKey(activePageUrl, authScope);
  const change = changes[key];
  if (!change) return;

  await handleReadingSessionChange(change.oldValue, change.newValue);
}

function setPreloadStatus(state, message) {
  preloadRetryMode = state === 'loading';
  preloadStatusElement.textContent = message;
  preloadStatusElement.dataset.state = state;
  preloadButton.textContent =
    state === 'ready'
      ? t('preloadBtnReload')
      : state === 'loading'
        ? t('preloadBtnAbortReload')
        : t('preloadBtnStart');
  preloadButton.disabled = !isAuthenticated;
}
