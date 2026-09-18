# ADR 0002: Custom Chat Prompts

Status: Accepted

## Context

The follow-up-question chat ("追加質問" / context chat) offered only two
hardcoded preset buttons (syntax, paraphrase). Users want to register their own
reusable prompts. The chat renders in three surfaces (sentence, study item,
in-page selection), and `renderContextChat` builds its HTML synchronously,
while `chrome.storage` reads are asynchronous.

## Decision

Store user-defined prompts in `chrome.storage.local` under `customChatPrompts`
as an array of `{ id, label, message }`, capped at 20. Ids are UUID v7
(reusing the existing `generateUuidV7`), so a prompt keeps its identity across
edits and reorders.

Keep the built-in presets fixed and non-editable. Custom prompts are a single
global list appended after the built-ins in every chat surface (the study-item
surface, which passes no built-in quick actions, therefore shows custom-only
buttons).

Because rendering is synchronous, feed it from an in-memory cache
(`customChatPromptsCache`) warmed once at load and refreshed via
`chrome.storage.onChanged`. The change listener also propagates side-panel edits
to the separate content-script context. Each quick-action button carries its
message in a `data-quick-message` attribute (HTML-escaped), so the click handler
sends the text directly without re-resolving.

Management (add / edit / delete / reorder) lives in the side-panel settings
view. The backend is unchanged: custom prompt text flows through the existing
`/chat` path, which already attaches page and analysis context.

## Alternatives considered

- Read prompts from storage at render time: impossible without making the whole
  render path async, which would ripple through three call sites.
- Make the built-in presets user-editable too: rejected to keep a stable
  baseline; users add on top instead of managing everything.
- `chrome.storage.sync` for cross-device sync: rejected — per-item/total size
  limits, and account state is already server-side via auth.

## Consequences

The cache can be briefly empty before the initial load resolves, but chat
details open well after load. Rapid consecutive clicks on reorder/delete can
drop an update (each handler reads the cache before an async save); acceptable
for a low-frequency settings screen. An already-open selection popup refreshes
its button row on the next render rather than live. Pure, testable helpers in
`settings.js` cover storage and mutation; the render/resolve path is unit
tested; a browser smoke test confirms clean load.
