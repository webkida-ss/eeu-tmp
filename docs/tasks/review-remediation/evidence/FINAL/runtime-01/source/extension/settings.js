var SELECTION_ANALYSIS_KEY = 'selectionAnalysisEnabled';
var LEGACY_DOMAIN_ANALYSIS_KEY = 'domainAnalysisMode';
var LEGACY_ANALYSIS_MODE_KEY = 'analysisMode';
var LEARNER_PROFILE_KEY = 'learnerProfile';
var LEARNER_PROFILE_REVISION_KEY = 'learnerProfileRevision';
var LANGUAGE_PROFILE_KEY = 'languageProfile';
var PANEL_WIDTH_KEY = 'panelWidth';
var PANEL_THEME_KEY = 'panelTheme';
var AUDIO_READING_RATE_KEY = 'audioReadingRate';
var AUTH_SESSION_KEY = 'authSession';
var READING_SESSION_KEY = 'eraReadingSession';
var READING_SESSION_STORAGE_PREFIX = 'eraReadingSession:';
var READING_SESSION_SCHEMA_VERSION = 1;
var CUSTOM_CHAT_PROMPTS_KEY = 'customChatPrompts';
var MAX_CUSTOM_CHAT_PROMPTS = 20;
var HIDDEN_QUICK_ACTIONS_KEY = 'hiddenQuickActions';
var READING_PANEL_ROOT_ID = 'readingPanelRoot';
// Backend origin. This is a packaging-time constant: release builds
// replace it with the deployed API URL (see infra/README.md). The
// chrome.storage `apiBaseUrl` override below is a developer-only escape
// hatch (no UI) for testing against other environments.
var DEFAULT_API_BASE_URL = 'http://localhost:18765';
var API_BASE_URL_KEY = 'apiBaseUrl';
var PANEL_THEMES = ['light', 'dark'];
var DEFAULT_PANEL_WIDTH = 360;
var MIN_PANEL_WIDTH = 280;
var MAX_PANEL_WIDTH = 640;

function normalizeApiBaseUrl(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  try {
    const url = new URL(raw);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return '';
    if (url.search || url.hash) return '';
    return url.toString().replace(/\/+$/, '');
  } catch {
    return '';
  }
}

async function getApiBaseUrl() {
  const storage = await chrome.storage.local.get(API_BASE_URL_KEY);
  return normalizeApiBaseUrl(storage[API_BASE_URL_KEY]) || DEFAULT_API_BASE_URL;
}

// Empty (or invalid) input clears the override back to the default.
async function setApiBaseUrl(value) {
  const normalized = normalizeApiBaseUrl(value);
  if (normalized) {
    await chrome.storage.local.set({ [API_BASE_URL_KEY]: normalized });
  } else {
    await chrome.storage.local.remove(API_BASE_URL_KEY);
  }
  return normalized || DEFAULT_API_BASE_URL;
}

// Machine-readable error codes the server attaches to quota failures,
// mapped onto localized messages (the raw detail string is English).
// Classic content scripts can be injected again by the background recovery path.
// Use re-declarable bindings while retaining immutable, own-property-only data.
var API_ERROR_CODE_KEYS = Object.freeze(
  Object.assign(Object.create(null), {
    article_quota_exceeded: 'quotaArticleExceeded',
    chat_quota_exceeded: 'quotaChatExceeded',
    token_budget_exceeded: 'quotaTokenExceeded',
  }),
);
var SETTINGS_HAS_OWN = Function.call.bind(Object.prototype.hasOwnProperty);

function isAuthErrorMessage(message) {
  const text = String(message || '');
  if (!text) return false;
  if (typeof t === 'function') {
    if (
      text === t('preloadNeedLogin') ||
      text === t('authSessionExpired') ||
      text === t('statusPreloadLoginRequired') ||
      text === t('authLoginPrompt')
    ) {
      return true;
    }
  }
  return /invalid or expired session/i.test(text) || /authentication required/i.test(text);
}

function toUserFacingErrorMessage(error, fallback) {
  const message = String(error?.message || error || '');
  if (isAuthErrorMessage(message)) {
    return typeof t === 'function' ? t('authSessionExpired') : fallback;
  }
  return message || fallback;
}

async function readApiErrorMessage(response, fallback) {
  try {
    const data = await response.json();
    const code =
      data && typeof data === 'object' && SETTINGS_HAS_OWN(data, 'code') ? data.code : null;
    const codeKey =
      typeof code === 'string' && SETTINGS_HAS_OWN(API_ERROR_CODE_KEYS, code)
        ? API_ERROR_CODE_KEYS[code]
        : null;
    if (codeKey && typeof t === 'function') {
      return t(codeKey);
    }
  } catch {
    // Fall through to generic message.
  }
  return fallback;
}

// Whether selecting text on any page (mouse drag, or a native double-click
// word selection) should trigger an automatic AI analysis popup. Off by
// default: learners opt in, since selection fires on ordinary copy/paste
// interactions too and an uninvited popup on every page is disruptive.
async function getSelectionAnalysisEnabled() {
  const storage = await chrome.storage.local.get([
    SELECTION_ANALYSIS_KEY,
    LEGACY_DOMAIN_ANALYSIS_KEY,
    LEGACY_ANALYSIS_MODE_KEY,
  ]);
  if (Object.prototype.hasOwnProperty.call(storage, SELECTION_ANALYSIS_KEY)) {
    return Boolean(storage[SELECTION_ANALYSIS_KEY]);
  }

  // Migrate the older per-domain toggle (removed along with its UI, and
  // never wired to the selection flow): any site that had it on is enough
  // to opt the learner into the new single global switch.
  const legacyDomainModes = storage[LEGACY_DOMAIN_ANALYSIS_KEY] || {};
  const enabled =
    Object.values(legacyDomainModes).some(Boolean) || storage[LEGACY_ANALYSIS_MODE_KEY] === true;
  await chrome.storage.local.set({ [SELECTION_ANALYSIS_KEY]: enabled });
  await chrome.storage.local.remove([LEGACY_DOMAIN_ANALYSIS_KEY, LEGACY_ANALYSIS_MODE_KEY]);
  return enabled;
}

async function setSelectionAnalysisEnabled(enabled) {
  const normalized = Boolean(enabled);
  await chrome.storage.local.set({ [SELECTION_ANALYSIS_KEY]: normalized });
  return normalized;
}

// Language pair for the learner. `target` is the language being studied
// (the article language) and `native` is the language used for
// explanations. `target` may also be AUTO_TARGET_LANGUAGE to detect the
// article language from the page.
var AUTO_TARGET_LANGUAGE = 'auto';

// Labels are endonyms (each language named in itself), the standard for
// language pickers: every user can find their own language regardless of
// the current UI locale.
var LANGUAGE_OPTIONS = [
  { code: 'en', label: 'English', ttsTag: 'en-US' },
  { code: 'ja', label: '日本語', ttsTag: 'ja-JP' },
  { code: 'zh', label: '中文', ttsTag: 'zh-CN' },
  { code: 'ko', label: '한국어', ttsTag: 'ko-KR' },
  { code: 'fr', label: 'Français', ttsTag: 'fr-FR' },
  { code: 'de', label: 'Deutsch', ttsTag: 'de-DE' },
  { code: 'es', label: 'Español', ttsTag: 'es-ES' },
  { code: 'it', label: 'Italiano', ttsTag: 'it-IT' },
  { code: 'pt', label: 'Português', ttsTag: 'pt-BR' },
  { code: 'ru', label: 'Русский', ttsTag: 'ru-RU' },
];

function normalizeLanguageCode(code) {
  const normalized = String(code || '')
    .trim()
    .toLowerCase()
    .replace(/_/g, '-')
    .split('-')[0];
  return /^[a-z]{2,3}$/.test(normalized) ? normalized : '';
}

function getLanguageOption(code) {
  return LANGUAGE_OPTIONS.find((option) => option.code === normalizeLanguageCode(code)) || null;
}

function getLanguageLabel(code) {
  return getLanguageOption(code)?.label || normalizeLanguageCode(code) || '';
}

function getTtsLangTag(code) {
  return getLanguageOption(code)?.ttsTag || normalizeLanguageCode(code) || 'en-US';
}

function getDefaultLanguageProfile() {
  return { target: 'en', native: 'ja' };
}

function normalizeLanguageProfile(profile) {
  const defaults = getDefaultLanguageProfile();
  const target =
    profile?.target === AUTO_TARGET_LANGUAGE
      ? AUTO_TARGET_LANGUAGE
      : getLanguageOption(profile?.target)?.code || defaults.target;
  const native = getLanguageOption(profile?.native)?.code || defaults.native;
  return { target, native };
}

async function getLanguageProfile() {
  const storage = await chrome.storage.local.get(LANGUAGE_PROFILE_KEY);
  return normalizeLanguageProfile(storage[LANGUAGE_PROFILE_KEY]);
}

async function setLanguageProfile(profile) {
  const normalized = normalizeLanguageProfile(profile);
  await chrome.storage.local.set({ [LANGUAGE_PROFILE_KEY]: normalized });
  return normalized;
}

function getDefaultLearnerProfile() {
  return { preset: '', notes: '' };
}

var LEARNER_LEVEL_BAND_BY_PRESET_ID = Object.freeze({
  'toeic-500': 'beginner',
  'eiken-2': 'beginner',
  'cefr-a1': 'beginner',
  'cefr-a2': 'beginner',
  'jlpt-n5': 'beginner',
  'jlpt-n4': 'beginner',
  'hsk-1': 'beginner',
  'hsk-2': 'beginner',
  'topik-1': 'beginner',
  'topik-2': 'beginner',
  'toeic-600': 'intermediate',
  'toeic-700': 'intermediate',
  'eiken-p1': 'intermediate',
  'cefr-b1': 'intermediate',
  'cefr-b2': 'intermediate',
  'jlpt-n3': 'intermediate',
  'hsk-3': 'intermediate',
  'hsk-4': 'intermediate',
  'topik-3': 'intermediate',
  'topik-4': 'intermediate',
  'toeic-800': 'advanced',
  'toeic-900': 'advanced',
  'eiken-1': 'advanced',
  'cefr-c1': 'advanced',
  'cefr-c2': 'advanced',
  'jlpt-n2': 'advanced',
  'jlpt-n1': 'advanced',
  'hsk-5': 'advanced',
  'hsk-6': 'advanced',
  'topik-5': 'advanced',
  'topik-6': 'advanced',
});

var VOCABULARY_COVERAGE_BY_LEARNER_BAND = Object.freeze({
  beginner: 18,
  intermediate: 12,
  advanced: 7,
});

var DEFAULT_VOCABULARY_COVERAGE_PERCENT = 8;

function normalizeLearnerProfileText(value) {
  const normalized = String(value || '')
    .trim()
    .replace(/\s+/g, ' ');
  return normalized || null;
}

function getVocabularyCoveragePercent(profile) {
  const preset = String(profile?.preset || '');
  const band = LEARNER_LEVEL_BAND_BY_PRESET_ID[preset];
  if (band) {
    return VOCABULARY_COVERAGE_BY_LEARNER_BAND[band];
  }
  // A freeform-only profile intentionally uses the middle band. An entirely
  // unset profile preserves the backend's historical 8% default.
  return String(profile?.notes || '').trim()
    ? VOCABULARY_COVERAGE_BY_LEARNER_BAND.intermediate
    : DEFAULT_VOCABULARY_COVERAGE_PERCENT;
}

async function getLearnerProfile() {
  const storage = await chrome.storage.local.get([
    LEARNER_PROFILE_KEY,
    LEARNER_PROFILE_REVISION_KEY,
  ]);
  const revision = Number(storage[LEARNER_PROFILE_REVISION_KEY]);
  return {
    ...getDefaultLearnerProfile(),
    ...(storage[LEARNER_PROFILE_KEY] || {}),
    revision: Number.isSafeInteger(revision) && revision >= 0 ? revision : 0,
  };
}

async function setLearnerProfile(profile) {
  const storage = await chrome.storage.local.get([
    LEARNER_PROFILE_KEY,
    LEARNER_PROFILE_REVISION_KEY,
  ]);
  const previousRevision = Number(storage[LEARNER_PROFILE_REVISION_KEY]);
  const normalized = {
    preset: String(profile?.preset || ''),
    notes: String(profile?.notes || '').trim(),
  };
  const previousProfile = {
    ...getDefaultLearnerProfile(),
    ...(storage[LEARNER_PROFILE_KEY] || {}),
  };
  const unchanged =
    previousProfile.preset === normalized.preset && previousProfile.notes === normalized.notes;
  if (unchanged) {
    return {
      ...normalized,
      revision:
        Number.isSafeInteger(previousRevision) && previousRevision >= 0 ? previousRevision : 0,
    };
  }
  const revision =
    Number.isSafeInteger(previousRevision) && previousRevision >= 0 ? previousRevision + 1 : 1;
  await chrome.storage.local.set({
    [LEARNER_PROFILE_KEY]: normalized,
    [LEARNER_PROFILE_REVISION_KEY]: revision,
  });
  return { ...normalized, revision };
}

function learnerProfileRevisionMatches(snapshot, currentProfile) {
  return Number(snapshot?.revision) === Number(currentProfile?.revision);
}

function getLearnerProfileCacheFingerprint(profile) {
  return JSON.stringify({
    learner_level: normalizeLearnerProfileText(formatLearnerLevelForApi(profile)),
    vocabulary_coverage_percent: getVocabularyCoveragePercent(profile),
  });
}

// Preset labels live in i18n.js (getLearnerPresetLabel), resolved at call
// time. The empty preset id means "not set", so the check is id-based and
// survives label localization.
function formatLearnerLevelForApi(profile) {
  const presetId = String(profile?.preset || '');
  const presetLabel = presetId ? getLearnerPresetLabel(presetId) : '';
  const notes = String(profile?.notes || '').trim();

  if (presetLabel && notes) {
    return getUiLocale() === 'ja' ? `${presetLabel}。${notes}` : `${presetLabel}. ${notes}`;
  }
  if (presetLabel) {
    return presetLabel;
  }
  return notes || null;
}

function clampPanelWidth(width) {
  const maxWidth = Math.min(MAX_PANEL_WIDTH, window.innerWidth);
  return Math.min(Math.max(Math.round(width), MIN_PANEL_WIDTH), maxWidth);
}

async function getPanelWidth() {
  const storage = await chrome.storage.local.get(PANEL_WIDTH_KEY);
  return clampPanelWidth(storage[PANEL_WIDTH_KEY] ?? DEFAULT_PANEL_WIDTH);
}

async function setPanelWidth(width) {
  const normalized = clampPanelWidth(width);
  await chrome.storage.local.set({ [PANEL_WIDTH_KEY]: normalized });
  return normalized;
}

async function getPanelTheme() {
  const storage = await chrome.storage.local.get(PANEL_THEME_KEY);
  const theme = storage[PANEL_THEME_KEY] ?? 'light';
  return PANEL_THEMES.includes(theme) ? theme : 'light';
}

async function setPanelTheme(theme) {
  const normalized = PANEL_THEMES.includes(theme) ? theme : 'light';
  await chrome.storage.local.set({ [PANEL_THEME_KEY]: normalized });
  return normalized;
}

// Playback speed for the continuous read-aloud mode.
var AUDIO_READING_RATES = [0.75, 0.9, 1.0, 1.1, 1.25];

async function getAudioReadingRate() {
  const storage = await chrome.storage.local.get(AUDIO_READING_RATE_KEY);
  const rate = Number(storage[AUDIO_READING_RATE_KEY]);
  return AUDIO_READING_RATES.includes(rate) ? rate : 1.0;
}

async function setAudioReadingRate(rate) {
  const normalized = AUDIO_READING_RATES.includes(Number(rate)) ? Number(rate) : 1.0;
  await chrome.storage.local.set({ [AUDIO_READING_RATE_KEY]: normalized });
  return normalized;
}

function getDefaultAuthSession() {
  return null;
}

async function getAuthSession() {
  const storage = await chrome.storage.local.get(AUTH_SESSION_KEY);
  const session = storage[AUTH_SESSION_KEY];
  if (!session?.accessToken || !session?.user?.id) {
    return getDefaultAuthSession();
  }
  return session;
}

function isAuthScope(scope) {
  return (
    typeof scope?.userId === 'string' &&
    scope.userId.length > 0 &&
    typeof scope.loginId === 'string' &&
    scope.loginId.length > 0
  );
}

function authScopesMatch(left, right) {
  return (
    isAuthScope(left) &&
    isAuthScope(right) &&
    left.userId === right.userId &&
    left.loginId === right.loginId
  );
}

async function getAuthScope() {
  const storage = await chrome.storage.local.get(AUTH_SESSION_KEY);
  const session = storage[AUTH_SESSION_KEY];
  if (!session?.accessToken || !session?.user?.id || !session?.loginId) return null;
  return { userId: session.user.id, loginId: session.loginId };
}

async function authScopeMatches(expectedScope) {
  if (!isAuthScope(expectedScope)) return false;
  return authScopesMatch(await getAuthScope(), expectedScope);
}

async function setAuthSession(session) {
  const scopedSession = { ...session, loginId: crypto.randomUUID() };
  await chrome.storage.local.set({ [AUTH_SESSION_KEY]: scopedSession });
  return scopedSession;
}

async function clearAuthSession() {
  await chrome.storage.local.remove(AUTH_SESSION_KEY);
  await clearPrivateReadingData();
}

function readingSessionStorageKey(pageUrl, authScope) {
  if (!isAuthScope(authScope)) return '';
  try {
    return `${READING_SESSION_STORAGE_PREFIX}${encodeURIComponent(authScope.userId)}:${encodeURIComponent(authScope.loginId)}:${encodeURIComponent(
      normalizePageUrl(pageUrl),
    )}`;
  } catch {
    return '';
  }
}

function isValidStoredPreload(preload, pageUrl) {
  if (!preload || typeof preload !== 'object' || Array.isArray(preload)) return false;
  if (typeof preload.id !== 'string' || !preload.id) return false;
  if (!Array.isArray(preload.sentences) || preload.sentences.length === 0) return false;
  if (
    !preload.sentences.every(
      (sentence) =>
        sentence &&
        typeof sentence === 'object' &&
        !Array.isArray(sentence) &&
        typeof sentence.id === 'string' &&
        sentence.id.length > 0 &&
        typeof sentence.text === 'string' &&
        sentence.text.length > 0,
    )
  ) {
    return false;
  }
  if (typeof preload.page_url !== 'string' || !preload.page_url) return false;
  try {
    return pageUrlsMatch(preload.page_url, pageUrl);
  } catch {
    return false;
  }
}

function isValidReadingSession(session, pageUrl, authScope) {
  if (!session || typeof session !== 'object' || Array.isArray(session)) return false;
  if (session.schemaVersion !== READING_SESSION_SCHEMA_VERSION) return false;
  if (!authScopesMatch(session.owner, authScope)) return false;
  try {
    return (
      pageUrlsMatch(session.pageUrl, pageUrl) &&
      isValidStoredPreload(session.preload, pageUrl) &&
      typeof session.pageTitle === 'string' &&
      session.domLinkStatus &&
      typeof session.domLinkStatus === 'object' &&
      !Array.isArray(session.domLinkStatus) &&
      session.ui &&
      typeof session.ui === 'object' &&
      !Array.isArray(session.ui) &&
      Number.isSafeInteger(session.updatedAt)
    );
  } catch {
    return false;
  }
}

async function getReadingSession(pageUrl, expectedScope = null) {
  const authScope = expectedScope || (await getAuthScope());
  if (!isAuthScope(authScope) || !(await authScopeMatches(authScope))) return null;
  const key = readingSessionStorageKey(pageUrl, authScope);
  if (!key) return null;
  const storage = await chrome.storage.local.get(key);
  const session = storage[key];
  if (!(await authScopeMatches(authScope))) return null;
  return isValidReadingSession(session, pageUrl, authScope) ? session : null;
}

async function setReadingSession(session, expectedScope = null) {
  const authScope = expectedScope || (await getAuthScope());
  if (!isAuthScope(authScope) || !(await authScopeMatches(authScope))) return false;
  const pageUrl = session?.pageUrl;
  const record = {
    ...session,
    schemaVersion: READING_SESSION_SCHEMA_VERSION,
    owner: { userId: authScope.userId, loginId: authScope.loginId },
  };
  if (!isValidReadingSession(record, pageUrl, authScope)) return false;
  const key = readingSessionStorageKey(pageUrl, authScope);
  await chrome.storage.local.set({ [key]: record });
  if (await authScopeMatches(authScope)) return true;
  await chrome.storage.local.remove(key);
  return false;
}

async function clearPrivateReadingData() {
  const storage = await chrome.storage.local.get(null);
  const privateKeys = Object.keys(storage).filter((key) =>
    key.startsWith(READING_SESSION_STORAGE_PREFIX),
  );
  if (privateKeys.length) await chrome.storage.local.remove(privateKeys);
  await chrome.storage.local.remove('preloadJob');
}

async function getAuthHeaders() {
  const session = await getAuthSession();
  if (!session?.accessToken) {
    return {};
  }

  return {
    Authorization: `Bearer ${session.accessToken}`,
  };
}

function normalizePageUrl(pageUrl) {
  const url = new URL(String(pageUrl));
  url.hash = '';
  return url.toString().replace(/\/$/, '');
}

function pageUrlsMatch(left, right) {
  if (!left || !right) {
    return false;
  }

  try {
    return normalizePageUrl(left) === normalizePageUrl(right);
  } catch {
    return left === right;
  }
}

// --- Custom chat prompts ----------------------------------------------------
// User-defined follow-up-question buttons, stored next to the fixed built-in
// presets (syntax/paraphrase). shared.js caches these and appends them to the
// quick-action row rendered by renderContextChat. Ids are UUID v7 so a prompt
// keeps its identity across edits and reorders.

function normalizeCustomChatPrompt(entry) {
  const label = String(entry?.label ?? '').trim();
  const message = String(entry?.message ?? '').trim();
  if (!label || !message) return null;
  const id = String(entry?.id ?? '').trim() || generateUuidV7();
  return { id, label, message };
}

function normalizeCustomChatPrompts(value) {
  if (!Array.isArray(value)) return [];
  return value.map(normalizeCustomChatPrompt).filter(Boolean).slice(0, MAX_CUSTOM_CHAT_PROMPTS);
}

function addCustomChatPrompt(list, { label, message } = {}) {
  const current = normalizeCustomChatPrompts(list);
  const entry = normalizeCustomChatPrompt({ label, message });
  if (!entry) return { ok: false, error: 'invalid', list: current };
  if (current.length >= MAX_CUSTOM_CHAT_PROMPTS) {
    return { ok: false, error: 'limit', list: current };
  }
  return { ok: true, list: [...current, entry] };
}

function updateCustomChatPrompt(list, id, { label, message } = {}) {
  const current = normalizeCustomChatPrompts(list);
  const index = current.findIndex((item) => item.id === id);
  if (index === -1) return { ok: false, error: 'missing', list: current };
  const entry = normalizeCustomChatPrompt({ id, label, message });
  if (!entry) return { ok: false, error: 'invalid', list: current };
  const next = current.slice();
  next[index] = entry;
  return { ok: true, list: next };
}

function removeCustomChatPrompt(list, id) {
  return normalizeCustomChatPrompts(list).filter((item) => item.id !== id);
}

function moveCustomChatPrompt(list, id, delta) {
  const current = normalizeCustomChatPrompts(list);
  const index = current.findIndex((item) => item.id === id);
  if (index === -1) return current;
  const target = index + delta;
  if (target < 0 || target >= current.length) return current;
  const next = current.slice();
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

async function getCustomChatPrompts() {
  const storage = await chrome.storage.local.get(CUSTOM_CHAT_PROMPTS_KEY);
  return normalizeCustomChatPrompts(storage[CUSTOM_CHAT_PROMPTS_KEY]);
}

async function saveCustomChatPrompts(list) {
  const normalized = normalizeCustomChatPrompts(list);
  await chrome.storage.local.set({ [CUSTOM_CHAT_PROMPTS_KEY]: normalized });
  return normalized;
}

// --- Hidden quick actions ---------------------------------------------------
// Ids (built-in preset ids like 'syntax'/'paraphrase'/'meaning', or custom
// prompt UUIDs) the user has hidden from the follow-up-question quick-action
// row. Hiding is separate from deleting: a hidden custom prompt stays in the
// settings list. shared.js caches this list and filters it out at render time.

function normalizeHiddenQuickActions(value) {
  if (!Array.isArray(value)) return [];
  const seen = new Set();
  const out = [];
  for (const entry of value) {
    const id = String(entry ?? '').trim();
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push(id);
  }
  return out;
}

function toggleHiddenQuickAction(list, id) {
  const key = String(id ?? '').trim();
  const current = normalizeHiddenQuickActions(list);
  if (!key) return current;
  return current.includes(key) ? current.filter((item) => item !== key) : [...current, key];
}

async function getHiddenQuickActions() {
  const storage = await chrome.storage.local.get(HIDDEN_QUICK_ACTIONS_KEY);
  return normalizeHiddenQuickActions(storage[HIDDEN_QUICK_ACTIONS_KEY]);
}

async function setHiddenQuickActions(list) {
  const normalized = normalizeHiddenQuickActions(list);
  await chrome.storage.local.set({ [HIDDEN_QUICK_ACTIONS_KEY]: normalized });
  return normalized;
}
