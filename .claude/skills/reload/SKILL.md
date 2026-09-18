---
name: reload
description: Make the current code changes live in the Untangle dev environment — reload the extension in the user's normal Chrome and (re)start the backend only when actually needed. Use when the user wants to reload the extension, apply changes, or bring the dev environment up (/reload).
---

# Reload the Untangle Dev Environment

Goal: after code changes, make sure the running extension and backend reflect
them — restarting as little as possible.

Components:

- **Extension**: loaded unpacked in the user's normal Chrome. A dev-only
  client at the end of `background.js` (active only on unpacked installs)
  connects to the local reload server
  (`tools/reading-assistant/extension/dev/reload-server.mjs`, started via
  `extension/dev.sh`, port 18766) and calls `chrome.runtime.reload()` when
  told. The server also watches the extension source and reloads on every
  file change.
- **Backend**: `uvicorn main:app --reload --port 18765` in
  `tools/reading-assistant/backend/`.

## Steps

### 1. Extension

1. Ensure the reload server is running: `curl -s http://127.0.0.1:18766/`.
   If it does not respond, start
   `tools/reading-assistant/extension/dev.sh` as a background Bash task
   (`run_in_background: true`) and confirm its output says it is listening.
2. Force a reload: `curl -s -X POST http://127.0.0.1:18766/reload` — the
   response reports how many extension instances were reloaded.
   - `{"reloaded": 1}` (or more) → done; the extension in the user's Chrome
     has reloaded.
   - `{"reloaded": 0}` → no extension is connected. Tell the user to reload
     the extension once manually at `chrome://extensions` (needed the first
     time after the dev-reload client was added, or if Chrome is not
     running / the extension is not loaded unpacked). After that one manual
     reload, everything is automatic.

Note: file saves already trigger reloads automatically while the server
runs; the forced POST just guarantees freshness. Content scripts on
already-open tabs need a page refresh (F5) to pick up new content-script
code.

### 2. Backend — restart only when needed

Check `curl -s http://localhost:18765/health`:

- **Healthy** → uvicorn runs with `--reload`, so Python changes are already
  applied automatically. Do NOT restart. Exceptions where a restart (or a
  heads-up to the user) is needed:
  - `.env` was changed (uvicorn does not reload env vars) — if this session
    changed `.env`, restart a backend this session started; if the backend
    runs in the user's own terminal, tell them to restart it instead of
    killing their process.
  - Dependencies changed (`requirements.txt` / new packages installed).
- **Not responding** → verify `tools/reading-assistant/backend/.env` exists
  (if missing, stop and tell the user to copy `.env.example` and set
  `OPENAI_API_KEY`), then start uvicorn as a background Bash task with the
  backend directory as cwd. Use the project venv if one exists
  (`.venv/bin/uvicorn`), otherwise `uvicorn`. Confirm `/health` responds.

### 3. Report

One short status line per component: what was already fine, what was
(re)started or reloaded, and why. Remind the user that processes started
here stop when the Claude Code session ends.

## Notes

- Never start a second uvicorn or a second reload server when one is
  running.
- Never kill a backend the user started in their own terminal; report and
  let them decide.
- The reload mechanism does not work for extensions injected with the
  `--load-extension` flag (e.g. Playwright test browsers) — Chrome unloads
  those without reloading. It only targets the user's normal Chrome with a
  proper "Load unpacked" install.
