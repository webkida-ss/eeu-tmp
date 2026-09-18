# Quick-Action Visibility Toggle + Meaning Preset — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a third built-in follow-up preset ("meaning") and let users show/hide any quick-action button (built-in presets and custom prompts) without deleting it.

**Architecture:** A new `hiddenQuickActions` id list in `chrome.storage.local` records which quick-action ids (preset ids or custom UUIDs) are hidden. `resolveQuickChatActions` filters them out of every chat surface. The settings view lists built-in presets and custom prompts together, each with a show/hide toggle. The "meaning" preset is a new hardcoded quick action alongside `syntax`/`paraphrase`. Backend unchanged.

**Tech Stack:** Vanilla JS MV3 extension, `chrome.storage.local`, i18n in `extension/i18n.js` (canonical `ja`, parity test enforced), unit tests `node --test extension/test/shared.test.mjs`, browser smoke test `node extension/test/smoke.mjs`.

**Conventions:** English for all code/comments. `ja` is the canonical i18n locale; every locale must define every key (parity test at `extension/test/shared.test.mjs`). The `S` unit-test sandbox loads `settings.js`+`i18n.js`+`shared.js`; reach globals as `S.name`. Cross-realm caveat: rebuild vm-realm arrays/objects (`[...arr]`, `{...obj}`) before `assert.deepEqual`.

---

## File Structure

- `extension/settings.js` — `HIDDEN_QUICK_ACTIONS_KEY`, pure helpers `normalizeHiddenQuickActions`/`toggleHiddenQuickAction`, accessors `getHiddenQuickActions`/`setHiddenQuickActions`.
- `extension/shared.js` — add `'meaning'` to `SENTENCE_QUICK_CHAT_ACTIONS` + `getQuickChatAction`; hidden-actions cache + accessors; extend `watchCustomChatPrompts`/`initCustomChatPrompts`; filter hidden in `resolveQuickChatActions`.
- `extension/i18n.js` — 6 new keys × 10 locales (`quickMeaningLabel`, `quickMeaningMessage`, `customPromptShow`, `customPromptHide`, `customPromptsPresetGroup`, `customPromptsCustomGroup`).
- `extension/panel-ui.js` — render presets + customs with toggles; handle toggle clicks; load hidden cache on open.
- `extension/panel-ui.css` — group headings, hidden-row dim, toggle button.
- `extension/test/shared.test.mjs` — unit tests for Tasks 1 & 2.

---

## Task 1: Hidden-actions storage + pure helpers (`settings.js`)

**Files:** Modify `extension/settings.js`; Test `extension/test/shared.test.mjs`.

- [ ] **Step 1: Append failing tests to `extension/test/shared.test.mjs`**

```javascript
test('normalizeHiddenQuickActions dedupes, trims, drops empty, non-array -> []', () => {
  assert.deepEqual([...S.normalizeHiddenQuickActions(['a', ' b ', 'a', '', 'b'])], ['a', 'b']);
  assert.deepEqual([...S.normalizeHiddenQuickActions(null)], []);
  assert.deepEqual([...S.normalizeHiddenQuickActions('x')], []);
});

test('toggleHiddenQuickAction adds then removes an id', () => {
  const once = S.toggleHiddenQuickAction([], 'syntax');
  assert.deepEqual([...once], ['syntax']);
  const twice = S.toggleHiddenQuickAction(once, 'syntax');
  assert.deepEqual([...twice], []);
  assert.deepEqual([...S.toggleHiddenQuickAction(['a'], 'b')], ['a', 'b']);
});
```

- [ ] **Step 2: Run tests, confirm the 2 new ones FAIL** — `node --test extension/test/shared.test.mjs` (functions undefined).

- [ ] **Step 3: Add the key constant.** In `extension/settings.js`, immediately after line 12 (`var MAX_CUSTOM_CHAT_PROMPTS = 20;`) add:

```javascript
var HIDDEN_QUICK_ACTIONS_KEY = 'hiddenQuickActions';
```

- [ ] **Step 4: Append this section at the END of `extension/settings.js`:**

```javascript

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
  return current.includes(key)
    ? current.filter((item) => item !== key)
    : [...current, key];
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
```

- [ ] **Step 5: Run tests, confirm ALL pass.**

- [ ] **Step 6: Commit**

```bash
git add extension/settings.js extension/test/shared.test.mjs
git commit -m "feat: add hidden quick-action storage and helpers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Meaning preset + hidden filtering (`shared.js`)

**Files:** Modify `extension/shared.js`; Test `extension/test/shared.test.mjs`.

- [ ] **Step 1: Append failing tests to `extension/test/shared.test.mjs`**

```javascript
test('SENTENCE_QUICK_CHAT_ACTIONS includes meaning and getQuickChatAction resolves it', () => {
  assert.deepEqual([...S.SENTENCE_QUICK_CHAT_ACTIONS], ['syntax', 'paraphrase', 'meaning']);
  const a = S.getQuickChatAction('meaning');
  assert.ok(a && typeof a.label === 'string' && typeof a.message === 'string');
  assert.ok(a.label.length > 0 && a.message.length > 0);
});

test('resolveQuickChatActions filters hidden built-ins and customs by id', () => {
  const custom = [
    { id: 'c1', label: 'Etymology', message: 'Explain the origin.' },
    { id: 'c2', label: 'Tone', message: 'Describe the tone.' },
  ];
  const all = S.resolveQuickChatActions(['syntax', 'paraphrase'], custom, []);
  assert.equal(all.length, 4);
  const filtered = S.resolveQuickChatActions(['syntax', 'paraphrase'], custom, ['paraphrase', 'c1']);
  assert.equal(filtered.length, 2);
  // Remaining: syntax (built-in, first) + c2 (custom). Shape stays {label,message}.
  assert.deepEqual({ ...filtered[1] }, { label: 'Tone', message: 'Describe the tone.' });
});
```

- [ ] **Step 2: Run tests, confirm the 2 new ones FAIL.** (`SENTENCE_QUICK_CHAT_ACTIONS` lacks `meaning`; `getQuickChatAction('meaning')` returns null; the 3rd `hidden` arg is ignored so `filtered.length` is 4, not 2.)

- [ ] **Step 3: Add `'meaning'` to the preset list.** In `extension/shared.js` line 9, replace:

```javascript
var SENTENCE_QUICK_CHAT_ACTIONS = ['syntax', 'paraphrase'];
```

with:

```javascript
var SENTENCE_QUICK_CHAT_ACTIONS = ['syntax', 'paraphrase', 'meaning'];
```

- [ ] **Step 4: Add the `meaning` branch in `getQuickChatAction`.** In `extension/shared.js`, inside `getQuickChatAction` (lines 53-61), add before `return null;` (after the `paraphrase` branch that ends at line 59):

```javascript
  if (actionId === 'meaning') {
    return { label: t('quickMeaningLabel'), message: t('quickMeaningMessage') };
  }
```

- [ ] **Step 5: Add the hidden-actions cache.** In `extension/shared.js`, immediately after `loadCustomChatPromptsCache` (ends at line 328, before `resolveQuickChatActions`), add:

```javascript

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
```

- [ ] **Step 6: Filter hidden ids in `resolveQuickChatActions`.** Replace the whole function (lines 330-336) with:

```javascript
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
```

- [ ] **Step 7: Watch + load the hidden key.** Replace `watchCustomChatPrompts` and `initCustomChatPrompts` (lines 338-350) with:

```javascript
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
```

- [ ] **Step 8: Run tests, confirm ALL pass** (existing custom-prompt tests still green — the new 3rd arg defaults keep them working).

- [ ] **Step 9: Commit**

```bash
git add extension/shared.js extension/test/shared.test.mjs
git commit -m "feat: add meaning preset and hidden quick-action filtering

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: i18n strings (`i18n.js`)

**Files:** Modify `extension/i18n.js`; verified by the parity test.

Add these 6 keys to **each** of the 10 locales. Put `quickMeaningLabel`/`quickMeaningMessage` next to `quickParaphraseMessage`; put the 4 `customPrompt*` keys next to the existing `customPrompt*` block. Each locale's `quickMeaningMessage` is written in that locale's own language (matching how `quickSyntaxMessage` names the language). Match existing indentation/comma style.

- [ ] **Step 1: `ja` (canonical)**

```javascript
    quickMeaningLabel: '意味理解',
    quickMeaningMessage:
      'この文の意味を日本語でわかりやすく説明してください。文法や構文の分析ではなく、この文が全体として何を言おうとしているのかを、含意やニュアンスも含めて理解できるように説明してください。',
    customPromptShow: '表示',
    customPromptHide: '非表示',
    customPromptsPresetGroup: 'プリセット',
    customPromptsCustomGroup: 'カスタム',
```

- [ ] **Step 2: `en`**

```javascript
    quickMeaningLabel: 'Understand meaning',
    quickMeaningMessage:
      'Explain what this sentence means in clear English. Focus on what it is saying as a whole, including implication and nuance, rather than analyzing its grammar or syntax.',
    customPromptShow: 'Show',
    customPromptHide: 'Hide',
    customPromptsPresetGroup: 'Built-in',
    customPromptsCustomGroup: 'Custom',
```

- [ ] **Step 3: Remaining 8 locales.** `quickMeaningLabel` / `quickMeaningMessage`:

**zh:** `理解含义` / `请用中文清楚地解释这句话的意思。请着重说明整句话想表达什么，包括言外之意和语气，而不是分析它的语法或句法结构。`
**ko:** `의미 이해` / `이 문장의 의미를 한국어로 알기 쉽게 설명해 주세요. 문법이나 구문 분석이 아니라, 이 문장이 전체적으로 무엇을 말하려는지 함의와 뉘앙스까지 포함해 이해할 수 있도록 설명해 주세요.`
**fr:** `Comprendre le sens` / `Expliquez le sens de cette phrase dans un français clair. Concentrez-vous sur ce qu'elle exprime dans son ensemble, y compris les sous-entendus et les nuances, plutôt que sur l'analyse de sa grammaire ou de sa syntaxe.`
**de:** `Bedeutung verstehen` / `Erkläre die Bedeutung dieses Satzes in klarem Deutsch. Konzentriere dich darauf, was der Satz als Ganzes aussagt – einschließlich Implikationen und Nuancen – statt seine Grammatik oder Syntax zu analysieren.`
**es:** `Entender el significado` / `Explica el significado de esta frase en un español claro. Céntrate en lo que expresa en conjunto, incluyendo las implicaciones y los matices, en lugar de analizar su gramática o sintaxis.`
**it:** `Capire il significato` / `Spiega il significato di questa frase in un italiano chiaro. Concentrati su ciò che esprime nel complesso, comprese le implicazioni e le sfumature, invece di analizzarne la grammatica o la sintassi.`
**pt:** `Entender o significado` / `Explique o significado desta frase em português claro. Concentre-se no que ela expressa como um todo, incluindo implicações e nuances, em vez de analisar sua gramática ou sintaxe.`
**ru:** `Понять смысл` / `Объясните смысл этого предложения понятным русским языком. Сосредоточьтесь на том, что оно выражает в целом, включая подтекст и нюансы, а не на разборе его грамматики или синтаксиса.`

The 4 `customPrompt*` keys — `customPromptShow` / `customPromptHide` / `customPromptsPresetGroup` / `customPromptsCustomGroup`:

**zh:** `显示` / `隐藏` / `预设` / `自定义`
**ko:** `표시` / `숨김` / `프리셋` / `커스텀`
**fr:** `Afficher` / `Masquer` / `Préréglages` / `Personnalisés`
**de:** `Anzeigen` / `Ausblenden` / `Voreinstellungen` / `Eigene`
**es:** `Mostrar` / `Ocultar` / `Preajustes` / `Personalizados`
**it:** `Mostra` / `Nascondi` / `Preimpostati` / `Personalizzati`
**pt:** `Mostrar` / `Ocultar` / `Predefinidos` / `Personalizados`
**ru:** `Показать` / `Скрыть` / `Пресеты` / `Свои`

Note: escape apostrophes in fr (`qu'elle`) as `\'` inside single-quoted strings, matching the existing convention in the file.

- [ ] **Step 4: Run the parity test.** `node --test extension/test/shared.test.mjs` — must pass. The parity test names any locale missing keys; fix and re-run until green.

- [ ] **Step 5: Commit**

```bash
git add extension/i18n.js
git commit -m "i18n: add meaning preset and visibility toggle strings

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Settings manager with presets + visibility toggle (`panel-ui.js`, `panel-ui.css`)

**Files:** Modify `extension/panel-ui.js`, `extension/panel-ui.css`. Verified by unit tests + browser smoke test + manual.

- [ ] **Step 1: Replace `renderCustomPromptsList`** (currently lines 935-960) with the version below. It renders a "Built-in" group (from `SENTENCE_QUICK_CHAT_ACTIONS`, toggle only) and a "Custom" group (toggle + edit/delete/reorder). A row is dimmed (`is-hidden`) when its id is in the hidden cache.

```javascript
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
      <li class="custom-prompts-item is-preset${isHidden ? ' is-hidden' : ''}" data-prompt-id="${escapeHtml(id)}">
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
      <li class="custom-prompts-item${isHidden ? ' is-hidden' : ''}" data-prompt-id="${escapeHtml(prompt.id)}">
        <div class="custom-prompts-item-text">
          <strong>${escapeHtml(prompt.label)}</strong>
          <small>${escapeHtml(prompt.message)}</small>
        </div>
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
```

- [ ] **Step 2: Handle the toggle click.** In `handleCustomPromptListClick` (currently lines 1010-1028), add this branch immediately after `const id = item.dataset.promptId;` (before the delete branch):

```javascript
  if (event.target.closest('.custom-prompt-toggle')) {
    const saved = await setHiddenQuickActions(
      toggleHiddenQuickAction(getCachedHiddenQuickActions(), id),
    );
    setHiddenQuickActionsCache(saved);
    renderCustomPromptsList();
    return;
  }
```

- [ ] **Step 3: Load the hidden cache on panel open.** In `refreshPanelContext` (line 749+), the code added earlier reads:

```javascript
  await loadCustomChatPromptsCache();
  renderCustomPromptsList();
```

Insert `await loadHiddenQuickActionsCache();` between them:

```javascript
  await loadCustomChatPromptsCache();
  await loadHiddenQuickActionsCache();
  renderCustomPromptsList();
```

- [ ] **Step 4: Append CSS to `extension/panel-ui.css`.** First read the file's existing `.custom-prompts-*` rules and CSS variables, then add rules for the new pieces, matching conventions:

```css
.custom-prompts-group {
  margin-top: 8px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--shell-muted, #6b7280);
}

.custom-prompts-group:first-child {
  margin-top: 0;
}

.custom-prompts-item.is-hidden {
  opacity: 0.5;
}

.custom-prompt-toggle {
  font-size: 12px;
}
```

(Adjust variable names/values to match the file. If `.custom-prompt-edit`/`.custom-prompt-delete` already define the small-button look, make `.custom-prompt-toggle` share it — e.g. extend the existing selector list rather than duplicating.)

- [ ] **Step 5: Verify.**
  - `node --test extension/test/shared.test.mjs` → pass.
  - `node --check extension/panel-ui.js` → clean.
  - Browser smoke test: `node extension/test/smoke.mjs`. If it fails only because `playwright-core`/Chromium is unavailable in this environment, report that as an environment limitation (not a blocker). A real console/page error IS a blocker — fix it.

- [ ] **Step 6: Manual verification (in the real extension, after reload).**
  1. Settings view shows a "Built-in" group with 意味理解 / 構文解析 / 言い換え and a "Custom" group.
  2. The 意味理解 button appears in the sentence and selection chats and returns a meaning-focused answer.
  3. Hiding a preset (e.g. 構文解析) removes its button from all chat surfaces; showing it again restores it.
  4. Hiding a custom prompt removes its chat button but keeps its settings row (still editable/deletable).
  5. Hiding every button leaves only the free-text input in the chat.
  6. A hidden state set in the side panel is reflected in an already-open page popup on its next open (via storage.onChanged).

- [ ] **Step 7: Commit**

```bash
git add extension/panel-ui.js extension/panel-ui.css
git commit -m "feat: manage preset and custom quick-action visibility in settings

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review Notes

- **Spec coverage:** meaning preset (Task 2 + i18n Task 3); hidden storage/helpers (Task 1); render-time filtering across all surfaces (Task 2 `resolveQuickChatActions`); settings UI with presets + toggle (Task 4); i18n all locales (Task 3). Backend untouched, presets not editable/deletable (toggle only). ✓
- **Type consistency:** `hiddenQuickActions` is always a string-id array; `normalizeHiddenQuickActions`/`toggleHiddenQuickAction`/`get/setHiddenQuickActions` (settings.js) and `getCachedHiddenQuickActions`/`setHiddenQuickActionsCache`/`loadHiddenQuickActionsCache` (shared.js) share that shape. `resolveQuickChatActions` keeps returning `{label, message}` (render + existing tests unaffected); the 3rd `hidden` param is optional and defaults to the cache, so existing 2-arg calls and tests keep working. `SENTENCE_QUICK_CHAT_ACTIONS` is the single source for both chat rendering and the settings preset list.
- **Backward-compat:** existing custom-prompt unit tests (`resolveQuickChatActions(['syntax'], custom)`, render test) still pass because `hidden` defaults to an empty cache in the test sandbox.
