# Reading Assistant Plan

## Purpose

The reading assistant is a Chrome extension PoC for reducing friction while reading English articles.

The core problem is that copying unknown words or sentences into an AI chat breaks the reading flow. The PoC should let the user stay on the original web page, select English text, and immediately see an AI explanation.

## Current Scope

The tool lives at the repository root.

- `extension/`: Chrome extension loaded via `chrome://extensions`.
- `backend/`: Local FastAPI server that calls OpenAI API.
- `docs/`: Tool-specific documentation.

The extension uses local API port `18765` for development to avoid common port conflicts.

## Current User Flow

1. Start the local backend.
2. Load `extension/` as an unpacked Chrome extension.
3. Turn on analysis mode from the extension popup.
4. Open an English article such as BBC.
5. Select text on the page.
6. The extension sends the selected text to the local backend.
7. The backend calls OpenAI and returns translation, grammar, nuance, vocabulary, examples, and a study tip.
8. The extension displays the result in an in-page popup.
9. The user can save the phrase to the local phrase list.

## Immediate User Tasks

1. Create the backend environment file.

```bash
cp backend/.env.example backend/.env
```

2. Add `OPENAI_API_KEY` to `backend/.env`.

3. Start the backend.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 18765
```

4. Load the Chrome extension.

- Open `chrome://extensions`.
- Enable Developer mode.
- Click Load unpacked.
- Select `extension/`.

5. Turn on analysis mode and test text selection on an English article.

## Implementation Plan

### Phase 1: Local PoC Verification

Goal: prove the reading experience is useful before adding more product surface.

- Confirm the extension loads successfully in Chrome.
- Confirm the backend starts on port `18765`.
- Confirm selecting text triggers an analysis popup.
- Confirm phrase saving writes to `backend/data/phrases.json`.
- Test on at least BBC and one additional English article site.

### Phase 2: UX Hardening

Goal: make the extension comfortable enough for daily use.

- Add request caching for repeated selected text.
- Improve popup positioning near viewport edges.
- Add a clearer loading and error state.
- Add a short explanation mode for single-word selections.
- Add a longer explanation mode for sentence or paragraph selections.
- Consider adding a side panel mode if the popup becomes too cramped.

### Phase 3: Data and Review Experience

Goal: make saved phrases useful after reading.

- Add a simple phrase list view.
- Add delete and edit operations for saved phrases.
- Store source page title and URL with each phrase.
- Add export to JSON or CSV.
- Consider a minimal web UI if local JSON becomes hard to review.

### Phase 4: Production Readiness

Goal: prepare for use beyond a local-only PoC.

- Move storage from local JSON to a database.
- Add authentication before exposing the backend.
- Add user-level rate limiting.
- Verify requests from the extension origin.
- Add AI usage limits and error monitoring.
- Decide whether to keep the backend as a hosted service or a local-first tool.

## Open Decisions

- Whether the first real target site should be BBC only or any English article site.
- Whether saved phrases should stay local-first or sync across devices.
- Whether the next UI surface should be a side panel, a phrase review page, or both.
- Whether mobile support should be handled later via PWA reader mode.

## Validation Checklist

- `python3` syntax check passes for `backend/main.py`.
- `node --check` passes for extension JavaScript files.
- `manifest.json` is valid JSON.
- Chrome extension can call `http://localhost:18765`.
- No API key is stored in extension code.
