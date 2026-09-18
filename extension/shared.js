// Shared utilities for the Untangle extension.
//
// Loaded before content.js on web pages, and before reading-panel.js /
// panel-ui.js inside sidepanel.html. Everything in this file is
// context-free: no page-specific or panel-specific state beyond the
// context chat history, which is scoped to the loading document.

var MAX_CHAT_HISTORY = 20;
var SENTENCE_QUICK_CHAT_ACTIONS = ['syntax', 'paraphrase', 'meaning'];

function generateUuidV7(now = Date.now()) {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  let timestamp = BigInt(now);
  for (let index = 5; index >= 0; index -= 1) {
    bytes[index] = Number(timestamp & 0xffn);
    timestamp >>= 8n;
  }
  bytes[6] = 0x70 | (bytes[6] & 0x0f);
  bytes[8] = 0x80 | (bytes[8] & 0x3f);
  const hex = [...bytes].map((value) => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function withOperationId(payload, operationId = null) {
  return { ...payload, operation_id: operationId || generateUuidV7() };
}

// The content script and service worker publish the same preload progress
// record, so this helper must remain available in both extension contexts.
globalThis.updatePreloadJob = async function updatePreloadJob(pageUrl, patch) {
  await chrome.storage.local.set({
    preloadJob: {
      pageUrl: normalizePageUrl(pageUrl),
      updatedAt: Date.now(),
      ...patch,
    },
  });
};

async function releaseRetryResponseBody(response) {
  const body = response?.body;
  if (!body) return;
  if (typeof body.cancel === 'function' && body.locked !== true) {
    await body.cancel();
    return;
  }
  if (typeof response.arrayBuffer === 'function') {
    await response.arrayBuffer();
  }
}

async function runIdempotentRequest(payload, send, maxAttempts = 2) {
  const requestPayload = withOperationId(payload, payload?.operation_id);
  let lastError;
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    try {
      const result = await send(requestPayload);
      const retryableHttpFailure = Number(result?.status) >= 500;
      if (retryableHttpFailure && attempt + 1 < maxAttempts) {
        await releaseRetryResponseBody(result);
        continue;
      }
      return result;
    } catch (error) {
      lastError = error;
      if (error?.name !== 'ApiNetworkError' || attempt + 1 >= maxAttempts) {
        throw error;
      }
    }
  }
  throw lastError;
}

// Quick chat actions resolve their label and AI request text from the
// current UI locale, so the request is written in the learner's native
// language (and the reply comes back in it).
function getQuickChatAction(actionId) {
  if (actionId === 'syntax') {
    return { label: t('quickSyntaxLabel'), message: t('quickSyntaxMessage') };
  }
  if (actionId === 'paraphrase') {
    return { label: t('quickParaphraseLabel'), message: t('quickParaphraseMessage') };
  }
  if (actionId === 'meaning') {
    return { label: t('quickMeaningLabel'), message: t('quickMeaningMessage') };
  }
  return null;
}

// --- Text normalization ----------------------------------------------------

function normalizeText(value) {
  return String(value ?? '')
    .replace(/[\u00a0\u202f\u2007]/g, ' ')
    .replace(/[\u200b-\u200d\ufeff]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function normalizeQuotes(value) {
  return String(value ?? '')
    .replace(/[\u201c\u201d]/g, '"')
    .replace(/[\u2018\u2019]/g, "'");
}

function normalizeDashes(value) {
  return String(value ?? '').replace(/[\u2010-\u2015\u2212\uFE58\uFE63\uFF0D]/g, '-');
}

function normalizeTextForMatch(value) {
  return normalizeDashes(normalizeQuotes(normalizeText(value)));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function isExtensionRuntimeAvailable() {
  try {
    return Boolean(chrome?.runtime?.id);
  } catch {
    return false;
  }
}

// --- Text matching ----------------------------------------------------------

// Finds `needle` inside `text`, tolerating the whitespace/quote/dash
// variations handled by normalizeTextForMatch. Pass `normalizedHaystack`
// when the caller already normalized `text` to avoid re-normalizing it.
function findNeedleInText(text, needle, normalizedHaystack = normalizeTextForMatch(text)) {
  const normalizedNeedle = normalizeTextForMatch(needle);
  if (!normalizedNeedle) return null;

  const directIndex = normalizedHaystack.indexOf(normalizedNeedle);
  if (directIndex !== -1) {
    return findRawSpanForNormalizedMatch(text, directIndex, normalizedNeedle.length);
  }

  const words = normalizedNeedle.split(' ').filter(Boolean);
  if (words.length <= 1) return null;

  const pattern = words.map((word) => escapeRegExp(word)).join('[\\s\\u00a0\\u202f\\u2007]+');
  const regex = new RegExp(pattern, 'i');
  const match = normalizedHaystack.match(regex);
  if (!match || match.index === undefined) return null;

  return findRawSpanForNormalizedMatch(text, match.index, match[0].length);
}

var ZERO_WIDTH_CHAR_PATTERN = /[\u200b-\u200d\ufeff]/;
var WHITESPACE_CHAR_PATTERN = /\s/;

// Maps a match found in normalized text back to the corresponding span of the
// raw text. Walks the raw text once, tracking the normalized index each raw
// character lands on: normalizeTextForMatch keeps 1:1 character mappings,
// removes zero-width characters, and collapses/trims whitespace. The span
// starts at the raw character that covers `normStart` and ends right after
// the raw character that completes the match, so surrounding whitespace is
// never included.
function findRawSpanForNormalizedMatch(rawText, normStart, normLength) {
  const normEnd = normStart + normLength;
  if (normLength <= 0) return null;

  let rawStart = null;
  let normalizedLength = 0;
  let pendingSpace = false;

  for (let rawIndex = 0; rawIndex < rawText.length; rawIndex += 1) {
    const char = rawText[rawIndex];
    if (ZERO_WIDTH_CHAR_PATTERN.test(char)) continue;
    if (WHITESPACE_CHAR_PATTERN.test(char)) {
      // Collapsed and trimmed: only counts once a non-space character follows.
      if (normalizedLength > 0) pendingSpace = true;
      continue;
    }

    if (pendingSpace) {
      normalizedLength += 1;
      pendingSpace = false;
    }
    // This character occupies normalized index `normalizedLength`.
    if (rawStart === null && normalizedLength + 1 > normStart) {
      rawStart = rawIndex;
    }
    normalizedLength += 1;
    if (rawStart !== null && normalizedLength >= normEnd) {
      return { index: rawStart, length: rawIndex + 1 - rawStart };
    }
  }

  return null;
}

// --- Preload model helpers --------------------------------------------------

function findSentenceById(preload, sentenceId) {
  if (!sentenceId || !preload?.sentences?.length) return null;
  return preload.sentences.find((sentence) => sentence.id === sentenceId) || null;
}

function getStudyItemById(preload, itemId) {
  return (preload?.study_items || []).find((item) => item.id === itemId) || null;
}

function getStudyItemAppearanceOrder(preload, item) {
  const sentenceIds = item.sentence_ids || [];
  if (!sentenceIds.length || !preload?.sentences?.length) {
    return Number.MAX_SAFE_INTEGER;
  }

  const needle = normalizeText(item.text).toLowerCase();
  let bestOrder = Number.MAX_SAFE_INTEGER;

  for (const sentenceId of sentenceIds) {
    const sentence = preload.sentences.find((entry) => entry.id === sentenceId);
    if (!sentence) continue;

    const sentenceText = normalizeText(sentence.text).toLowerCase();
    const charOffset = needle ? sentenceText.indexOf(needle) : -1;
    const order = sentence.index * 10000 + (charOffset >= 0 ? charOffset : 9999);
    bestOrder = Math.min(bestOrder, order);
  }

  return bestOrder;
}

function sortStudyItems(preload) {
  return [...(preload?.study_items || [])].sort((left, right) => {
    const orderDiff =
      getStudyItemAppearanceOrder(preload, left) - getStudyItemAppearanceOrder(preload, right);
    if (orderDiff !== 0) return orderDiff;
    return left.text.localeCompare(right.text, 'en');
  });
}

function getAdjacentStudyItem(preload, item, direction) {
  if (!item) return null;
  const items = sortStudyItems(preload);
  const index = items.findIndex((candidate) => candidate.id === item.id);
  if (index < 0) return null;
  const targetIndex = direction === 'prev' ? index - 1 : index + 1;
  if (targetIndex < 0 || targetIndex >= items.length) return null;
  return items[targetIndex];
}

function getAdjacentSentence(preload, sentence, direction) {
  if (!sentence || !preload?.sentences?.length) return null;
  const targetIndex = direction === 'prev' ? sentence.index - 1 : sentence.index + 1;
  if (targetIndex < 0 || targetIndex >= preload.sentences.length) return null;
  return preload.sentences[targetIndex] || null;
}

function toAnalysisResponse(sentence) {
  return {
    original_text: sentence.text,
    used_preload: true,
    ...sentence.analysis,
  };
}

function isKeyboardEditableTarget(target) {
  if (!target) return false;
  const element = target.nodeType === Node.ELEMENT_NODE ? target : target.parentElement;
  if (!element) return false;
  const tag = element.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || element.isContentEditable;
}

// --- Analysis rendering -----------------------------------------------------

function formatPartOfSpeechBadge(partOfSpeech) {
  if (!partOfSpeech) return '';
  return `<span class="era-vocab-pos">${escapeHtml(partOfSpeech)}</span>`;
}

// Splits a vocabulary line ("term [pos]: meaning" or "term: meaning") into
// its parts. `term` is the studied word/phrase; empty when the line has no
// recognizable "term: meaning" shape.
function parseVocabularyItem(item) {
  const posMatch = item.match(/^(.+?)\s+\[([^\]]+)\]:\s*(.+)$/);
  if (posMatch) {
    return {
      term: posMatch[1].trim(),
      partOfSpeech: posMatch[2].trim(),
      explanation: posMatch[3].trim(),
    };
  }

  const colonIndex = item.indexOf(':');
  if (colonIndex === -1) return { term: '', partOfSpeech: '', explanation: item };
  return {
    term: item.slice(0, colonIndex).trim(),
    partOfSpeech: '',
    explanation: item.slice(colonIndex + 1).trim(),
  };
}

function formatVocabularyItem(item) {
  const { term, explanation } = parseVocabularyItem(item);
  if (!term) return escapeHtml(explanation);
  return `<strong>${escapeHtml(term)}</strong>: ${escapeHtml(explanation)}`;
}

// `renderVocabPrefix(term, index)` may return HTML placed before each
// vocabulary line (used by the side panel to swap the list bullet for a
// read-aloud button). When omitted, the default list bullet is kept.
function renderAnalysis(analysis, { renderVocabPrefix } = {}) {
  if (!analysis || typeof analysis !== 'object') {
    return `<div class="era-error">${escapeHtml(t('analysisUnavailable'))}</div>`;
  }

  const vocabulary = (Array.isArray(analysis.vocabulary) ? analysis.vocabulary : [])
    .map((item, index) => {
      const { term } = parseVocabularyItem(item);
      const prefix = typeof renderVocabPrefix === 'function' ? renderVocabPrefix(term, index) : '';
      return `<li class="era-vocab-line">${prefix}<span class="era-vocab-line-body">${formatVocabularyItem(item)}</span></li>`;
    })
    .join('');

  return `
    <div class="era-section"><h3>${escapeHtml(t('sectionTranslation'))}</h3><p>${escapeHtml(analysis.translation || '')}</p></div>
    <div class="era-section"><h3>${escapeHtml(t('sectionGrammar'))}</h3><p>${escapeHtml(analysis.grammar || '')}</p></div>
    ${vocabulary ? `<div class="era-section"><h3>${escapeHtml(t('sectionVocabulary'))}</h3><ul>${vocabulary}</ul></div>` : ''}
  `;
}

// --- Context chat -----------------------------------------------------------

var contextChats = new Map();

// Custom prompts (user-defined quick actions) are cached in memory so the
// synchronous render path can include them. The cache is warmed at load
// (initCustomChatPrompts) and kept fresh via chrome.storage change events,
// which also propagates side-panel edits to the content-script context.
var customChatPromptsCache = [];

function getCachedCustomChatPrompts() {
  return customChatPromptsCache;
}

function setCustomChatPromptsCache(list) {
  customChatPromptsCache = normalizeCustomChatPrompts(list);
  return customChatPromptsCache;
}

async function loadCustomChatPromptsCache() {
  customChatPromptsCache = await getCustomChatPrompts();
  return customChatPromptsCache;
}

// Hidden quick-action ids, cached like the custom prompts so the synchronous
// render path can filter them. Warmed at load and refreshed via storage events.
var hiddenQuickActionsCache = [];

function getCachedHiddenQuickActions() {
  return hiddenQuickActionsCache;
}

function setHiddenQuickActionsCache(list) {
  hiddenQuickActionsCache = normalizeHiddenQuickActions(list);
  return hiddenQuickActionsCache;
}

async function loadHiddenQuickActionsCache() {
  hiddenQuickActionsCache = await getHiddenQuickActions();
  return hiddenQuickActionsCache;
}

function resolveQuickChatActions(
  actionIds = [],
  customPrompts = getCachedCustomChatPrompts(),
  hidden = getCachedHiddenQuickActions(),
) {
  const hiddenSet = new Set(hidden);
  const builtIn = actionIds
    .filter((id) => !hiddenSet.has(id))
    .map((id) => getQuickChatAction(id))
    .filter(Boolean);
  const custom = customPrompts
    .filter((prompt) => !hiddenSet.has(prompt.id))
    .map((prompt) => ({ label: prompt.label, message: prompt.message }))
    .filter((prompt) => prompt.label && prompt.message);
  return [...builtIn, ...custom];
}

function watchCustomChatPrompts() {
  if (typeof chrome === 'undefined' || !chrome.storage?.onChanged) return;
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local') return;
    if (changes[CUSTOM_CHAT_PROMPTS_KEY]) {
      setCustomChatPromptsCache(changes[CUSTOM_CHAT_PROMPTS_KEY].newValue);
    }
    if (changes[HIDDEN_QUICK_ACTIONS_KEY]) {
      setHiddenQuickActionsCache(changes[HIDDEN_QUICK_ACTIONS_KEY].newValue);
    }
  });
}

function initCustomChatPrompts() {
  if (typeof chrome === 'undefined' || !chrome.storage?.local) return;
  loadCustomChatPromptsCache();
  loadHiddenQuickActionsCache();
  watchCustomChatPrompts();
}

function getSentenceChatKey(sentenceId) {
  return `sentence:${sentenceId}`;
}

function getStudyItemChatKey(studyItemId) {
  return `study:${studyItemId}`;
}

function getSelectionChatKey(text) {
  return `selection:${normalizeText(text).slice(0, 120)}`;
}

function getContextChatMessages(chatKey) {
  return contextChats.get(chatKey) || [];
}

function setContextChatMessages(chatKey, messages) {
  contextChats.set(chatKey, messages.slice(-MAX_CHAT_HISTORY));
}

function clearContextChats() {
  contextChats.clear();
}

function renderContextChat(chatKey, { quickActions = [] } = {}) {
  const messages = getContextChatMessages(chatKey);
  const actions = resolveQuickChatActions(quickActions);
  const quickActionButtons = actions
    .map(
      (action) => `
        <button
          type="button"
          class="era-context-chat-quick-action"
          title="${escapeHtml(action.message)}"
          data-quick-message="${escapeHtml(action.message)}"
        >${escapeHtml(action.label)}</button>
      `,
    )
    .join('');
  const quickActionsHtml = quickActionButtons
    ? `<div class="era-context-chat-quick-actions">${quickActionButtons}</div>`
    : '';

  return `
    <section class="era-context-chat" data-chat-key="${escapeHtml(chatKey)}">
      <h3 class="era-context-chat-title">${escapeHtml(t('chatTitle'))}</h3>
      ${quickActionsHtml}
      <div class="era-context-chat-messages">${renderChatMessages(messages)}</div>
      <form class="era-context-chat-form">
        <textarea
          class="era-context-chat-input"
          rows="2"
          placeholder="${escapeHtml(t('chatPlaceholder'))}"
        ></textarea>
        <button class="era-context-chat-send" type="submit" disabled>${escapeHtml(t('chatSend'))}</button>
      </form>
    </section>
  `;
}

function applyInlineMarkdown(text) {
  return text
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>');
}

function renderChatMarkdown(text) {
  const lines = String(text).split('\n');
  const blocks = [];
  let listType = null;
  let listItems = [];

  function flushList() {
    if (!listType) return;
    blocks.push(
      `<${listType}>${listItems.map((item) => `<li>${applyInlineMarkdown(item)}</li>`).join('')}</${listType}>`,
    );
    listType = null;
    listItems = [];
  }

  for (const rawLine of lines) {
    const trimmed = rawLine.trim();

    if (!trimmed) {
      flushList();
      continue;
    }

    if (/^---+$/.test(trimmed)) {
      flushList();
      blocks.push('<hr>');
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,3})\s+(.+)$/);
    if (headingMatch) {
      flushList();
      const tag = `h${headingMatch[1].length}`;
      blocks.push(`<${tag}>${applyInlineMarkdown(escapeHtml(headingMatch[2]))}</${tag}>`);
      continue;
    }

    const ulMatch = trimmed.match(/^[-*]\s+(.+)$/);
    if (ulMatch) {
      if (listType && listType !== 'ul') flushList();
      listType = 'ul';
      listItems.push(escapeHtml(ulMatch[1]));
      continue;
    }

    const olMatch = trimmed.match(/^\d+\.\s+(.+)$/);
    if (olMatch) {
      if (listType && listType !== 'ol') flushList();
      listType = 'ol';
      listItems.push(escapeHtml(olMatch[1]));
      continue;
    }

    flushList();
    blocks.push(`<p>${applyInlineMarkdown(escapeHtml(trimmed))}</p>`);
  }

  flushList();
  return blocks.join('');
}

function renderChatMessageBody(message) {
  if (message.role === 'assistant') {
    return `<div class="era-chat-message-body">${renderChatMarkdown(message.content)}</div>`;
  }

  return `<p class="era-chat-message-text">${escapeHtml(message.content)}</p>`;
}

function renderChatMessages(messages) {
  if (!messages.length) {
    return `<p class="era-context-chat-empty">${escapeHtml(t('chatEmpty'))}</p>`;
  }

  return messages
    .map((message) => {
      const roleClass =
        message.role === 'user' ? 'era-chat-message-user' : 'era-chat-message-assistant';
      return `
        <div class="era-chat-message ${roleClass}">
          <p class="era-chat-message-role">${message.role === 'user' ? 'You' : 'AI'}</p>
          ${renderChatMessageBody(message)}
        </div>
      `;
    })
    .join('');
}

function attachContextChat(container, { chatKey, payload }) {
  const chatSection = container.querySelector('.era-context-chat');
  if (!chatSection) return;
  bindContextChatEvents(chatSection, chatKey, payload);
}

function syncContextChatSendButton(input, sendButton) {
  if (input.disabled) {
    sendButton.disabled = true;
    return;
  }
  sendButton.disabled = !String(input.value).trim();
}

function bindContextChatEvents(chatSection, chatKey, payloadTemplate) {
  const form = chatSection.querySelector('.era-context-chat-form');
  const input = chatSection.querySelector('.era-context-chat-input');
  const sendButton = chatSection.querySelector('.era-context-chat-send');
  if (!form || !input || !sendButton) return;

  syncContextChatSendButton(input, sendButton);
  input.addEventListener('input', () => {
    syncContextChatSendButton(input, sendButton);
  });

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    sendContextChatMessage(chatSection, chatKey, payloadTemplate, input, sendButton);
  });

  // Enter sends; Shift+Enter (and IME composition) inserts a newline.
  input.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
    if (!String(input.value).trim()) return;
    event.preventDefault();
    if (form.requestSubmit) {
      form.requestSubmit();
    } else {
      sendContextChatMessage(chatSection, chatKey, payloadTemplate, input, sendButton);
    }
  });

  chatSection.querySelectorAll('.era-context-chat-quick-action').forEach((button) => {
    button.addEventListener('click', () => {
      const message = button.dataset.quickMessage;
      if (!message) return;
      sendContextChatMessage(chatSection, chatKey, payloadTemplate, input, sendButton, message);
    });
  });
}

async function sendContextChatMessage(
  chatSection,
  chatKey,
  payloadTemplate,
  input,
  sendButton,
  messageOverride = null,
) {
  const message = String(messageOverride ?? input.value).trim();
  if (!message) return;
  const authScope = await getAuthScope();
  if (!authScope) return;

  const history = getContextChatMessages(chatKey);
  const nextHistory = [...history, { role: 'user', content: message }];
  setContextChatMessages(chatKey, nextHistory);
  updateContextChatMessages(chatSection, chatKey);

  if (messageOverride === null) {
    input.value = '';
  }

  input.disabled = true;
  sendButton.disabled = true;
  chatSection.querySelectorAll('.era-context-chat-quick-action').forEach((button) => {
    button.disabled = true;
  });

  const payload = withOperationId({
    ...payloadTemplate,
    message,
    history: history.map((item) => ({ role: item.role, content: item.content })),
  });

  chrome.runtime.sendMessage({ type: 'CHAT_FOLLOW_UP', payload }, (response) => {
    input.disabled = false;
    syncContextChatSendButton(input, sendButton);
    chatSection.querySelectorAll('.era-context-chat-quick-action').forEach((button) => {
      button.disabled = false;
    });

    if (!isExtensionRuntimeAvailable()) return;
    authScopeMatches(authScope).then((scopeStillCurrent) => {
      if (!scopeStillCurrent) return;

      if (chrome.runtime.lastError || !response?.ok) {
        const errorMessage =
          chrome.runtime.lastError?.message || response?.error || t('chatSendFailed');
        setContextChatMessages(chatKey, [
          ...nextHistory,
          { role: 'assistant', content: errorMessage },
        ]);
        updateContextChatMessages(chatSection, chatKey);
        return;
      }

      setContextChatMessages(chatKey, [
        ...nextHistory,
        { role: 'assistant', content: response.reply || '' },
      ]);
      updateContextChatMessages(chatSection, chatKey);
    });
  });
}

function updateContextChatMessages(chatSection, chatKey) {
  const messagesContainer = chatSection.querySelector('.era-context-chat-messages');
  if (!messagesContainer) return;
  messagesContainer.innerHTML = renderChatMessages(getContextChatMessages(chatKey));
  const scrollRoot = chatSection.closest('.era-panel-detail');
  if (scrollRoot) {
    scrollRoot.scrollTop = scrollRoot.scrollHeight;
    return;
  }
  messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

// Warm the custom-prompt cache and subscribe to changes. Guarded so the
// unit-test sandbox (no `chrome`) is unaffected.
initCustomChatPrompts();
