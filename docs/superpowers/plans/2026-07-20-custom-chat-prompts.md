# Custom Chat Prompts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users register their own follow-up-question ("追加質問") buttons alongside the fixed built-in presets, shown in every chat surface (sentence, word, selection).

**Architecture:** User prompts are stored in `chrome.storage.local` under `customChatPrompts` as `[{id, label, message}]`. Pure normalize/CRUD/reorder helpers live in `settings.js`; an in-memory cache in `shared.js` (warmed at load, refreshed via `chrome.storage.onChanged`) feeds the synchronous `renderContextChat`, which appends custom buttons after the built-in presets. The management UI is a new section in the side-panel settings view. The backend is unchanged — custom prompt text flows through the existing `/chat` path.

**Tech Stack:** Vanilla JS Chrome extension (MV3), `chrome.storage.local`, i18n via `extension/i18n.js`, unit tests with `node:test` + `node:vm` (`extension/test/shared.test.mjs`), browser smoke test with Playwright (`extension/test/smoke.mjs`).

**Conventions:** Repo rules require English for all code and comments. UI display strings live in `i18n.js` (canonical locale is `ja`; every locale must define every key — enforced by the parity test at `extension/test/shared.test.mjs:371`). Reuse the existing `generateUuidV7()` helper for ids (UUID v7 per `.claude/rules/data-model.md`).

---

## File Structure

- `extension/settings.js` — new storage key + limit constant, pure helpers (`normalizeCustomChatPrompts`, `addCustomChatPrompt`, `updateCustomChatPrompt`, `removeCustomChatPrompt`, `moveCustomChatPrompt`), async accessors (`getCustomChatPrompts`, `saveCustomChatPrompts`).
- `extension/shared.js` — in-memory cache (`customChatPromptsCache` + getters/loaders/watcher/init), `resolveQuickChatActions`, updated `renderContextChat` + quick-action click handler.
- `extension/i18n.js` — new UI strings for all 10 locales.
- `extension/sidepanel.html` — new "custom prompts" settings section.
- `extension/panel-ui.js` — element refs, list render, add/edit/delete/reorder handlers, restore-on-open wiring.
- `extension/test/shared.test.mjs` — unit tests for the pure helpers and the resolve/render logic.

Built-in presets (`syntax`/`paraphrase`) and the backend (`/chat`, `pipeline.py`) are **not** touched. The three chat surfaces need no per-site change: `renderContextChat` auto-appends cached custom prompts, so the sentence, selection, and study-item call sites keep working (study-item, which passes no `quickActions`, will show custom-only buttons).

---

## Task 1: Storage layer + pure helpers (`settings.js`)

**Files:**
- Modify: `extension/settings.js` (add constants after line 10; append helper section at end of file)
- Test: `extension/test/shared.test.mjs`

- [ ] **Step 1: Write the failing tests**

Append to `extension/test/shared.test.mjs` (uses the `S` sandbox, which loads `settings.js` + `i18n.js` + `shared.js`, so `generateUuidV7` is available):

```javascript
test('normalizeCustomChatPrompts trims, drops invalid, assigns ids, caps at 20', () => {
  const out = S.normalizeCustomChatPrompts([
    { label: '  Etymology  ', message: '  Explain the origin.  ' },
    { label: '', message: 'no label' },
    { label: 'no message', message: '   ' },
    { id: 'keep-me', label: 'Kept', message: 'Body' },
  ]);
  assert.equal(out.length, 2);
  assert.deepEqual({ label: out[0].label, message: out[0].message }, {
    label: 'Etymology',
    message: 'Explain the origin.',
  });
  assert.match(out[0].id, /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  assert.equal(out[1].id, 'keep-me');

  const many = Array.from({ length: 25 }, (_, i) => ({ label: `L${i}`, message: `M${i}` }));
  assert.equal(S.normalizeCustomChatPrompts(many).length, 20);

  assert.deepEqual(S.normalizeCustomChatPrompts(null), []);
  assert.deepEqual(S.normalizeCustomChatPrompts('nope'), []);
});

test('addCustomChatPrompt appends valid, rejects invalid and over-limit', () => {
  const first = S.addCustomChatPrompt([], { label: 'A', message: 'B' });
  assert.equal(first.ok, true);
  assert.equal(first.list.length, 1);

  const invalid = S.addCustomChatPrompt(first.list, { label: '  ', message: 'B' });
  assert.equal(invalid.ok, false);
  assert.equal(invalid.error, 'invalid');
  assert.equal(invalid.list.length, 1);

  const full = Array.from({ length: 20 }, (_, i) => ({ id: `id${i}`, label: `L${i}`, message: `M${i}` }));
  const overLimit = S.addCustomChatPrompt(full, { label: 'X', message: 'Y' });
  assert.equal(overLimit.ok, false);
  assert.equal(overLimit.error, 'limit');
});

test('updateCustomChatPrompt replaces by id, keeps id, rejects missing/invalid', () => {
  const list = [{ id: 'a', label: 'A', message: 'MA' }, { id: 'b', label: 'B', message: 'MB' }];
  const ok = S.updateCustomChatPrompt(list, 'b', { label: 'B2', message: 'MB2' });
  assert.equal(ok.ok, true);
  assert.deepEqual(ok.list[1], { id: 'b', label: 'B2', message: 'MB2' });

  assert.equal(S.updateCustomChatPrompt(list, 'zzz', { label: 'x', message: 'y' }).error, 'missing');
  assert.equal(S.updateCustomChatPrompt(list, 'a', { label: '', message: 'y' }).error, 'invalid');
});

test('removeCustomChatPrompt drops the matching id', () => {
  const list = [{ id: 'a', label: 'A', message: 'MA' }, { id: 'b', label: 'B', message: 'MB' }];
  const out = S.removeCustomChatPrompt(list, 'a');
  assert.equal(out.length, 1);
  assert.equal(out[0].id, 'b');
});

test('moveCustomChatPrompt swaps neighbours and clamps at bounds', () => {
  const list = [{ id: 'a', label: 'A', message: 'MA' }, { id: 'b', label: 'B', message: 'MB' }];
  assert.deepEqual(S.moveCustomChatPrompt(list, 'b', -1).map((p) => p.id), ['b', 'a']);
  assert.deepEqual(S.moveCustomChatPrompt(list, 'a', -1).map((p) => p.id), ['a', 'b']);
  assert.deepEqual(S.moveCustomChatPrompt(list, 'b', 1).map((p) => p.id), ['a', 'b']);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test extension/test/shared.test.mjs`
Expected: FAIL — `S.normalizeCustomChatPrompts is not a function` (and the other new helpers undefined).

- [ ] **Step 3: Add the constants**

In `extension/settings.js`, immediately after line 10 (`var READING_SESSION_KEY = 'eraReadingSession';`), add:

```javascript
var CUSTOM_CHAT_PROMPTS_KEY = 'customChatPrompts';
var MAX_CUSTOM_CHAT_PROMPTS = 20;
```

- [ ] **Step 4: Append the helper section at the end of `settings.js`**

Add at the end of the file (after `pageUrlsMatch`):

```javascript

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
  return value
    .map(normalizeCustomChatPrompt)
    .filter(Boolean)
    .slice(0, MAX_CUSTOM_CHAT_PROMPTS);
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `node --test extension/test/shared.test.mjs`
Expected: PASS (all new tests green; existing tests still green).

- [ ] **Step 6: Commit**

```bash
git add extension/settings.js extension/test/shared.test.mjs
git commit -m "feat: add custom chat prompt storage and helpers"
```

---

## Task 2: Cache + render integration (`shared.js`)

**Files:**
- Modify: `extension/shared.js` (add cache/resolve near the context-chat section; edit `renderContextChat` at lines 334-368; edit the quick-action click handler at lines 492-498; add an init call at end of file)
- Test: `extension/test/shared.test.mjs`

- [ ] **Step 1: Write the failing tests**

Append to `extension/test/shared.test.mjs`:

```javascript
test('resolveQuickChatActions returns built-ins then customs, dropping empties', () => {
  const custom = [
    { id: 'c1', label: 'Etymology', message: 'Explain the origin.' },
    { id: 'c2', label: '', message: 'dropped' },
  ];
  const builtInOnly = S.resolveQuickChatActions(['syntax'], []);
  assert.equal(builtInOnly.length, 1);
  assert.ok(builtInOnly[0].label && builtInOnly[0].message);

  const combined = S.resolveQuickChatActions(['syntax'], custom);
  assert.equal(combined.length, 2);
  assert.deepEqual(combined[1], { label: 'Etymology', message: 'Explain the origin.' });

  const customOnly = S.resolveQuickChatActions([], custom);
  assert.equal(customOnly.length, 1);
});

test('renderContextChat appends cached custom prompts as quick actions', () => {
  S.setCustomChatPromptsCache([{ id: 'c1', label: 'Etymology', message: 'Explain "it".' }]);
  const html = S.renderContextChat('sentence:1', { quickActions: [] });
  assert.match(html, /era-context-chat-quick-action/);
  assert.match(html, />Etymology</);
  // Message is carried on the button and HTML-escaped in the attribute.
  assert.match(html, /data-quick-message="Explain &quot;it&quot;\."/);
  S.setCustomChatPromptsCache([]); // reset shared cache for other tests
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test extension/test/shared.test.mjs`
Expected: FAIL — `S.resolveQuickChatActions is not a function` / `S.setCustomChatPromptsCache is not a function`.

- [ ] **Step 3: Add cache + resolver near the context-chat section**

In `extension/shared.js`, immediately after `var contextChats = new Map();` (line 308), add:

```javascript

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

function resolveQuickChatActions(actionIds = [], customPrompts = getCachedCustomChatPrompts()) {
  const builtIn = actionIds.map((id) => getQuickChatAction(id)).filter(Boolean);
  const custom = customPrompts
    .map((prompt) => ({ label: prompt.label, message: prompt.message }))
    .filter((prompt) => prompt.label && prompt.message);
  return [...builtIn, ...custom];
}

function watchCustomChatPrompts() {
  if (typeof chrome === 'undefined' || !chrome.storage?.onChanged) return;
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local' || !changes[CUSTOM_CHAT_PROMPTS_KEY]) return;
    setCustomChatPromptsCache(changes[CUSTOM_CHAT_PROMPTS_KEY].newValue);
  });
}

function initCustomChatPrompts() {
  if (typeof chrome === 'undefined' || !chrome.storage?.local) return;
  loadCustomChatPromptsCache();
  watchCustomChatPrompts();
}
```

- [ ] **Step 4: Update `renderContextChat` to append custom prompts and carry the message**

Replace the body of `renderContextChat` (lines 334-352, from `const messages =` through the `quickActionsHtml` assignment) with:

```javascript
function renderContextChat(chatKey, { quickActions = [] } = {}) {
  const messages = getContextChatMessages(chatKey);
  const actions = resolveQuickChatActions(quickActions);
  const quickActionButtons = actions
    .map(
      (action) => `
        <button
          type="button"
          class="era-context-chat-quick-action"
          data-quick-message="${escapeHtml(action.message)}"
        >${escapeHtml(action.label)}</button>
      `,
    )
    .join('');
  const quickActionsHtml = quickActionButtons
    ? `<div class="era-context-chat-quick-actions">${quickActionButtons}</div>`
    : '';
```

(Leave the `return` template that follows unchanged.)

- [ ] **Step 5: Update the quick-action click handler to read the embedded message**

Replace the quick-action binding block in `bindContextChatEvents` (lines 492-498) with:

```javascript
  chatSection.querySelectorAll('.era-context-chat-quick-action').forEach((button) => {
    button.addEventListener('click', () => {
      const message = button.dataset.quickMessage;
      if (!message) return;
      sendContextChatMessage(chatSection, chatKey, payloadTemplate, input, sendButton, message);
    });
  });
```

(The disable-during-send loops in `sendContextChatMessage` already target `.era-context-chat-quick-action`, so they keep working for both built-in and custom buttons. `getQuickChatAction` is still used by `resolveQuickChatActions`; do not delete it.)

- [ ] **Step 6: Warm the cache at load**

At the very end of `extension/shared.js`, add:

```javascript

// Warm the custom-prompt cache and subscribe to changes. Guarded so the
// unit-test sandbox (no `chrome`) is unaffected.
initCustomChatPrompts();
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `node --test extension/test/shared.test.mjs`
Expected: PASS (new + existing tests green).

- [ ] **Step 8: Commit**

```bash
git add extension/shared.js extension/test/shared.test.mjs
git commit -m "feat: render custom chat prompts from a cached quick-action list"
```

---

## Task 3: i18n strings for the settings UI (`i18n.js`)

**Files:**
- Modify: `extension/i18n.js` (add the keys below to every `UI_MESSAGES.<locale>` object)
- Test: `extension/test/shared.test.mjs` (existing parity test at line 371)

Add these 16 keys to **each** locale object. In every locale, place them right after `chatSendFailed` (search each block for `quickParaphraseMessage` — they belong in the same neighbourhood). `{max}` is an interpolation placeholder consumed by `t('customPromptLimit', { max: MAX_CUSTOM_CHAT_PROMPTS })`.

- [ ] **Step 1: Add the `ja` (canonical) strings**

```javascript
    customPromptsTitle: '追加質問のカスタムボタン',
    customPromptsDesc: 'よく使う質問をボタンとして登録できます。文・単語・選択の追加質問に表示されます。',
    customPromptNameLabel: 'ボタン名',
    customPromptNamePlaceholder: '例: 語源を教えて',
    customPromptBodyLabel: 'プロンプト本文',
    customPromptBodyPlaceholder: '例: この語の語源と成り立ちを日本語で説明してください。',
    customPromptAdd: '追加',
    customPromptSave: '保存',
    customPromptCancel: 'キャンセル',
    customPromptEdit: '編集',
    customPromptDelete: '削除',
    customPromptMoveUp: '上へ',
    customPromptMoveDown: '下へ',
    customPromptEmpty: 'カスタムボタンはまだありません。',
    customPromptLimit: '登録できるのは最大 {max} 件です。',
    customPromptInvalid: 'ボタン名と本文を入力してください。',
```

- [ ] **Step 2: Add the `en` strings**

```javascript
    customPromptsTitle: 'Custom follow-up buttons',
    customPromptsDesc: 'Save questions you use often as buttons. They appear in the sentence, word, and selection follow-up chats.',
    customPromptNameLabel: 'Button name',
    customPromptNamePlaceholder: 'e.g. Explain the etymology',
    customPromptBodyLabel: 'Prompt text',
    customPromptBodyPlaceholder: 'e.g. Explain the origin and formation of this word.',
    customPromptAdd: 'Add',
    customPromptSave: 'Save',
    customPromptCancel: 'Cancel',
    customPromptEdit: 'Edit',
    customPromptDelete: 'Delete',
    customPromptMoveUp: 'Move up',
    customPromptMoveDown: 'Move down',
    customPromptEmpty: 'No custom buttons yet.',
    customPromptLimit: 'You can save up to {max} buttons.',
    customPromptInvalid: 'Enter both a button name and prompt text.',
```

- [ ] **Step 3: Add the remaining 8 locales**

Use this translation matrix (key order matches the `ja`/`en` blocks above):

| key | zh (中文) | ko (한국어) | fr (Français) | de (Deutsch) | es (Español) | it (Italiano) | pt (Português) | ru (Русский) |
|---|---|---|---|---|---|---|---|---|
| customPromptsTitle | 自定义追问按钮 | 추가 질문 커스텀 버튼 | Boutons de question personnalisés | Eigene Rückfrage-Schaltflächen | Botones de pregunta personalizados | Pulsanti di domanda personalizzati | Botões de pergunta personalizados | Свои кнопки вопросов |
| customPromptsDesc | 可将常用问题保存为按钮，会显示在句子、单词和选中文本的追问中。 | 자주 쓰는 질문을 버튼으로 등록할 수 있습니다. 문장·단어·선택 영역의 추가 질문에 표시됩니다. | Enregistrez vos questions fréquentes comme boutons. Ils apparaissent dans les questions de suivi des phrases, mots et sélections. | Speichern Sie häufige Fragen als Schaltflächen. Sie erscheinen in den Rückfragen zu Sätzen, Wörtern und Auswahl. | Guarda tus preguntas frecuentes como botones. Aparecen en las preguntas de seguimiento de frases, palabras y selección. | Salva le domande che usi spesso come pulsanti. Compaiono nelle domande di approfondimento per frasi, parole e selezione. | Salve perguntas frequentes como botões. Eles aparecem nas perguntas de acompanhamento de frases, palavras e seleção. | Сохраняйте частые вопросы как кнопки. Они появляются в дополнительных вопросах для предложений, слов и выделения. |
| customPromptNameLabel | 按钮名称 | 버튼 이름 | Nom du bouton | Name der Schaltfläche | Nombre del botón | Nome del pulsante | Nome do botão | Название кнопки |
| customPromptNamePlaceholder | 例：解释词源 | 예: 어원 알려줘 | ex. : Expliquer l'étymologie | z. B. Etymologie erklären | p. ej.: Explica la etimología | es.: Spiega l'etimologia | ex.: Explique a etimologia | напр.: Объясни этимологию |
| customPromptBodyLabel | 提示内容 | 프롬프트 내용 | Texte de l'invite | Prompt-Text | Texto del prompt | Testo del prompt | Texto do prompt | Текст запроса |
| customPromptBodyPlaceholder | 例：请说明这个词的词源和构成。 | 예: 이 단어의 어원과 구성을 설명해 주세요. | ex. : Expliquez l'origine et la formation de ce mot. | z. B. Erkläre Herkunft und Bildung dieses Wortes. | p. ej.: Explica el origen y la formación de esta palabra. | es.: Spiega l'origine e la formazione di questa parola. | ex.: Explique a origem e a formação desta palavra. | напр.: Объясните происхождение и образование этого слова. |
| customPromptAdd | 添加 | 추가 | Ajouter | Hinzufügen | Añadir | Aggiungi | Adicionar | Добавить |
| customPromptSave | 保存 | 저장 | Enregistrer | Speichern | Guardar | Salva | Salvar | Сохранить |
| customPromptCancel | 取消 | 취소 | Annuler | Abbrechen | Cancelar | Annulla | Cancelar | Отмена |
| customPromptEdit | 编辑 | 편집 | Modifier | Bearbeiten | Editar | Modifica | Editar | Изменить |
| customPromptDelete | 删除 | 삭제 | Supprimer | Löschen | Eliminar | Elimina | Excluir | Удалить |
| customPromptMoveUp | 上移 | 위로 | Monter | Nach oben | Subir | Su | Subir | Вверх |
| customPromptMoveDown | 下移 | 아래로 | Descendre | Nach unten | Bajar | Giù | Descer | Вниз |
| customPromptEmpty | 还没有自定义按钮。 | 아직 커스텀 버튼이 없습니다. | Aucun bouton personnalisé pour l'instant. | Noch keine eigenen Schaltflächen. | Aún no hay botones personalizados. | Ancora nessun pulsante personalizzato. | Ainda não há botões personalizados. | Пока нет своих кнопок. |
| customPromptLimit | 最多可保存 {max} 个按钮。 | 최대 {max}개까지 등록할 수 있습니다. | Vous pouvez enregistrer jusqu'à {max} boutons. | Sie können bis zu {max} Schaltflächen speichern. | Puedes guardar hasta {max} botones. | Puoi salvare fino a {max} pulsanti. | Você pode salvar até {max} botões. | Можно сохранить до {max} кнопок. |
| customPromptInvalid | 请输入按钮名称和提示内容。 | 버튼 이름과 프롬프트 내용을 입력하세요. | Saisissez un nom de bouton et le texte de l'invite. | Geben Sie einen Namen und den Prompt-Text ein. | Introduce un nombre de botón y el texto del prompt. | Inserisci un nome del pulsante e il testo del prompt. | Insira um nome de botão e o texto do prompt. | Введите название кнопки и текст запроса. |

- [ ] **Step 4: Run the parity test**

Run: `node --test extension/test/shared.test.mjs`
Expected: PASS. The locale-parity test (`extension/test/shared.test.mjs:371`) compares every locale's key set against `ja`; if a locale is missing any of the 16 keys, it fails and names the offending locale — add the missing keys and re-run until green.

- [ ] **Step 5: Commit**

```bash
git add extension/i18n.js
git commit -m "i18n: add custom chat prompt settings strings"
```

---

## Task 4: Settings section markup (`sidepanel.html`)

**Files:**
- Modify: `extension/sidepanel.html` (insert a section inside `#settingsView`, between the learner-level section that ends at line 136 and the `preload-panel` that starts at line 138)

- [ ] **Step 1: Insert the custom-prompts section**

After the closing `</section>` of the learner-level panel (line 136) and before `<section class="preload-panel">` (line 138), add:

```html

        <section class="learner-panel">
          <div class="learner-copy">
            <strong data-i18n="customPromptsTitle">追加質問のカスタムボタン</strong>
            <small data-i18n="customPromptsDesc">よく使う質問をボタンとして登録できます。文・単語・選択の追加質問に表示されます。</small>
          </div>
          <ul id="customPromptsList" class="custom-prompts-list"></ul>
          <label class="field learner-field">
            <span data-i18n="customPromptNameLabel">ボタン名</span>
            <input
              id="customPromptName"
              type="text"
              maxlength="40"
              data-i18n-placeholder="customPromptNamePlaceholder"
              placeholder="例: 語源を教えて"
            />
          </label>
          <label class="field learner-field">
            <span data-i18n="customPromptBodyLabel">プロンプト本文</span>
            <textarea
              id="customPromptBody"
              rows="3"
              data-i18n-placeholder="customPromptBodyPlaceholder"
              placeholder="例: この語の語源と成り立ちを日本語で説明してください。"
            ></textarea>
          </label>
          <div class="custom-prompts-form-actions">
            <button id="customPromptAddButton" type="button" class="preload-button" data-i18n="customPromptAdd">追加</button>
            <button id="customPromptCancelButton" type="button" class="preload-button preload-button-secondary" hidden data-i18n="customPromptCancel">キャンセル</button>
          </div>
          <p id="customPromptStatus" class="learner-summary" aria-live="polite"></p>
        </section>
```

(Japanese inline defaults match the existing convention in this file; the visible text is overwritten by `applyDomTranslations` at runtime.)

- [ ] **Step 2: Verify the markup loads without error**

Run: `node --test extension/test/shared.test.mjs`
Expected: PASS (no functional change yet; this confirms nothing else broke). Visual verification happens in Task 5.

- [ ] **Step 3: Commit**

```bash
git add extension/sidepanel.html
git commit -m "feat: add custom chat prompt settings markup"
```

---

## Task 5: Settings UI logic (`panel-ui.js`)

**Files:**
- Modify: `extension/panel-ui.js` (add element refs near lines 1-7; add render + handlers; wire listeners in `bindPanelUiEvents` at line 140; warm cache + render in `refreshPanelContext` at line 739)

This task has no unit tests (DOM/interaction wiring); it is verified by the browser smoke test and a manual pass in the real extension.

- [ ] **Step 1: Add element references**

Near the top of `extension/panel-ui.js` (with the other `document.getElementById` refs, after line 7), add:

```javascript
const customPromptsList = document.getElementById('customPromptsList');
const customPromptName = document.getElementById('customPromptName');
const customPromptBody = document.getElementById('customPromptBody');
const customPromptAddButton = document.getElementById('customPromptAddButton');
const customPromptCancelButton = document.getElementById('customPromptCancelButton');
const customPromptStatus = document.getElementById('customPromptStatus');
let editingCustomPromptId = null;
```

- [ ] **Step 2: Add the render + handler functions**

Add these functions to `extension/panel-ui.js` (near the other settings helpers, e.g. after `restoreSettings`):

```javascript
function renderCustomPromptsList() {
  if (!customPromptsList) return;
  const prompts = getCachedCustomChatPrompts();
  if (!prompts.length) {
    customPromptsList.innerHTML = `<li class="custom-prompts-empty">${escapeHtml(t('customPromptEmpty'))}</li>`;
    return;
  }
  customPromptsList.innerHTML = prompts
    .map(
      (prompt, index) => `
      <li class="custom-prompts-item" data-prompt-id="${escapeHtml(prompt.id)}">
        <div class="custom-prompts-item-text">
          <strong>${escapeHtml(prompt.label)}</strong>
          <small>${escapeHtml(prompt.message)}</small>
        </div>
        <div class="custom-prompts-item-actions">
          <button type="button" class="custom-prompt-move" data-direction="-1" ${index === 0 ? 'disabled' : ''} title="${escapeHtml(t('customPromptMoveUp'))}" aria-label="${escapeHtml(t('customPromptMoveUp'))}">▲</button>
          <button type="button" class="custom-prompt-move" data-direction="1" ${index === prompts.length - 1 ? 'disabled' : ''} title="${escapeHtml(t('customPromptMoveDown'))}" aria-label="${escapeHtml(t('customPromptMoveDown'))}">▼</button>
          <button type="button" class="custom-prompt-edit">${escapeHtml(t('customPromptEdit'))}</button>
          <button type="button" class="custom-prompt-delete">${escapeHtml(t('customPromptDelete'))}</button>
        </div>
      </li>
    `,
    )
    .join('');
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
```

- [ ] **Step 3: Wire the listeners in `bindPanelUiEvents`**

Inside `bindPanelUiEvents()` (starts at line 140), add (e.g. after the `nativeLanguageSelect` listener on line 156):

```javascript
  customPromptAddButton?.addEventListener('click', handleCustomPromptSubmit);
  customPromptCancelButton?.addEventListener('click', resetCustomPromptForm);
  customPromptsList?.addEventListener('click', handleCustomPromptListClick);
```

- [ ] **Step 4: Warm the cache and render on panel open**

In `refreshPanelContext()` (line 739), after `await restoreSettings();` (line 747), add:

```javascript
  await loadCustomChatPromptsCache();
  renderCustomPromptsList();
```

- [ ] **Step 5: Run the unit + smoke tests**

Run: `node --test extension/test/shared.test.mjs`
Expected: PASS.

Run: `node extension/test/smoke.mjs`
Expected: PASS — loads the extension in Chromium and fails on any console/page error. Confirms the new markup + `panel-ui.js` wiring load cleanly and the chat form still renders (`.era-context-chat-form` assertion at `smoke.mjs:790`).

- [ ] **Step 6: Manual verification in the real extension**

Load the unpacked extension (or use `/reload`) and confirm:
1. Settings view shows the "Custom follow-up buttons" section; adding a prompt (name + body) makes it appear in the list.
2. Open a sentence detail → the custom button appears after 構文解析 / 言い換えを見る; clicking it sends that prompt and gets a reply.
3. Open a word/study item → the custom button appears (custom-only, no built-ins).
4. Select text on a page → the custom button appears after the built-ins in the popup.
5. Edit, delete, and reorder (▲▼) all update the list and the buttons on next chat open.
6. Adding a 21st prompt shows the limit message; empty name or body shows the invalid message.
7. Editing a prompt in the side panel updates the button in an already-open page popup (via `storage.onChanged`).

- [ ] **Step 7: Commit**

```bash
git add extension/panel-ui.js
git commit -m "feat: manage custom chat prompts in the settings view"
```

---

## Self-Review Notes

- **Spec coverage:** data model + storage (Task 1); render in all 3 surfaces via cache (Task 2); i18n all locales (Task 3); management UI markup (Task 4) + logic incl. add/edit/delete/reorder + 20-item limit (Tasks 1 & 5). Built-in presets untouched; backend untouched. ✓
- **Deviation from spec §2:** the spec's original "read from storage at render time, no `onChanged`" was replaced by a cache + `chrome.storage.onChanged` because `renderContextChat` is synchronous. Spec §2 has been updated to match.
- **Type consistency:** helper names (`normalizeCustomChatPrompts`, `add/update/remove/moveCustomChatPrompt`, `get/saveCustomChatPrompts`, `getCachedCustomChatPrompts`, `setCustomChatPromptsCache`, `loadCustomChatPromptsCache`, `resolveQuickChatActions`) and the storage shape `{id, label, message}` are identical across all tasks. The DOM ids (`customPromptsList`, `customPromptName`, `customPromptBody`, `customPromptAddButton`, `customPromptCancelButton`, `customPromptStatus`) match between Task 4 markup and Task 5 refs. The `data-quick-message` attribute set in Task 2's `renderContextChat` is the same one read by its click handler.
