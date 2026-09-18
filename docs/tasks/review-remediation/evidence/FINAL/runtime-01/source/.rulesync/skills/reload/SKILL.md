---
name: reload
description: >-
  Make current changes live in the Untangle development environment by
  reloading the extension and starting the backend only when needed.
targets:
  - claudecode
---
# Reload the Untangle Development Environment

## Extension

1. Check `http://127.0.0.1:18766/` without starting a duplicate process.
2. If unavailable, start `extension/dev.sh` in the background and confirm that
   the reload server is listening.
3. POST to `http://127.0.0.1:18766/reload`. If no extension is connected, ask
   the user to reload the unpacked extension once at `chrome://extensions`.
4. Remind the user to refresh existing tabs after content-script changes.

The reload server cannot reload extensions launched by Playwright with
`--load-extension`; it only works with the user's normal Chrome after the
extension is installed through **Load unpacked**. Content scripts in already
open tabs still require a page refresh.

## Backend

1. Check `http://127.0.0.1:18765/health`.
2. If healthy, rely on Uvicorn `--reload`. Restart only for environment or
   dependency changes.
3. If unavailable, require `backend/.env`, then start the managed Uvicorn
   executable in the background from `backend/` and verify `/health`.
4. Never kill or replace a backend process started by the user.

Report what was already running, what was started or reloaded, and why.
Processes started by an agent may stop when its session ends.
