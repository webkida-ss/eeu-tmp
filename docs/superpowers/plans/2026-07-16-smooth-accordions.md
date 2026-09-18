# Smooth Accordion Animations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Smoothly animate opening and closing for the reading-summary and vocabulary-book detail accordions without compromising accessibility.

**Architecture:** A small shared animation utility will drive the native summary `<details>` element with measured height transitions while retaining its semantic behavior. Vocabulary details will use the same measured-height lifecycle instead of the current immediate `hidden` toggle. CSS supplies a short opacity/transform transition, a reduced-motion override, and existing focus styles remain unchanged.

**Tech Stack:** Vanilla JavaScript, CSS, Chrome extension side panel, Playwright smoke test.

---

### Task 1: Test accordion state and reduced-motion behavior

**Files:**
- Modify: `extension/test/smoke.mjs`

- [ ] **Step 1: Add test coverage for both accordion types**

Exercise the summary `<details>` and a rendered vocabulary detail. Assert their content becomes visible after opening and is hidden after closing; set reduced motion through `page.emulateMedia({ reducedMotion: 'reduce' })` before reopening one accordion to confirm it reaches its final state without waiting for an animation.

- [ ] **Step 2: Run the smoke test to verify the new assertions fail**

Run: `node extension/test/smoke.mjs`

Expected: FAIL because no smooth-accordion lifecycle exists yet.

### Task 2: Implement interruptible accordion transitions

**Files:**
- Modify: `extension/reading-panel.js`
- Modify: `extension/panel-ui.js`

- [ ] **Step 1: Add an internal height-animation helper**

Create a helper that cancels an element’s prior animation, measures `scrollHeight`, transitions `height` and `opacity` over 220 milliseconds with `ease-out` for opening and `ease-in` for closing, then removes temporary inline styles. Skip the animation when `matchMedia('(prefers-reduced-motion: reduce)').matches` is true.

- [ ] **Step 2: Bind the summary `<details>` lifecycle**

In `bindPanelEvents`, listen for clicks on `.era-panel-summary-toggle`. Prevent the default native toggle, animate the content container, then set the `open` attribute after opening or remove it after the closing animation. Preserve keyboard operation through the native summary control.

- [ ] **Step 3: Apply the lifecycle to vocabulary details**

Replace the immediate `detail.hidden = !shouldExpand` assignment in `toggleVocabBookEntry` with the helper. Keep content mounted while closing until the animation completes; only then set `hidden = true`. Reopening during a close cancels the close and transitions to the open state.

- [ ] **Step 4: Run the smoke test to verify it passes**

Run: `node extension/test/smoke.mjs`

Expected: PASS, including the summary and vocabulary detail assertions.

### Task 3: Add motion styles and reduced-motion fallback

**Files:**
- Modify: `extension/reading-panel.css`
- Modify: `extension/panel-ui.css`

- [ ] **Step 1: Add visual continuity styles**

Add opacity and `transform: translateY(-2px)` transitions to the animated content wrappers. Limit this to accordion content so no unrelated UI animates.

- [ ] **Step 2: Add a reduced-motion override**

Use `@media (prefers-reduced-motion: reduce)` to disable the accordion content transitions.

- [ ] **Step 3: Run regression tests**

Run: `cd extension && node --test test/shared.test.mjs && node test/smoke.mjs`

Expected: Both commands pass.

### Task 4: Commit feature-only changes

**Files:**
- Add: `docs/superpowers/plans/2026-07-16-smooth-accordions.md`
- Modify: `extension/reading-panel.js`
- Modify: `extension/panel-ui.js`
- Modify: `extension/reading-panel.css`
- Modify: `extension/panel-ui.css`
- Modify: `extension/test/smoke.mjs`

- [ ] **Step 1: Inspect the staged file list**

Run: `git status --short && git diff --cached --name-only`

Expected: Existing backend changes and unrelated vocabulary-book changes are not staged.

- [ ] **Step 2: Commit the implementation**

Run:

```bash
git add docs/superpowers/plans/2026-07-16-smooth-accordions.md extension/reading-panel.js extension/panel-ui.js extension/reading-panel.css extension/panel-ui.css extension/test/smoke.mjs
git commit -m "Smooth reading and vocabulary accordions"
```

- [ ] **Step 3: Verify unrelated changes remain unstaged**

Run: `git status --short`

Expected: Only the pre-existing unrelated modifications remain.
