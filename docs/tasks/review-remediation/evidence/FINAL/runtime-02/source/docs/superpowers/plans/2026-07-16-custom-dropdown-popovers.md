# Custom Dropdown Popovers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace browser-rendered select menus with a reusable, accessible Untangle dropdown popover.

**Architecture:** A `select-ui.js` controller upgrades marked native selects into button-triggered listbox popovers while preserving the native select as the source of truth for forms and existing change listeners. It observes dynamically rendered audio controls, keeps labels and disabled state synchronized, and dispatches the native `change` event after an option is selected. Panel CSS supplies a single shared component visual language for settings and audio controls.

**Tech Stack:** Vanilla JavaScript, ARIA listbox patterns, CSS, Playwright smoke test.

---

### Task 1: Build the reusable dropdown controller

**Files:**
- Create: `extension/select-ui.js`
- Modify: `extension/sidepanel.html`

- [ ] Load `select-ui.js` after existing panel scripts. Upgrade marked selects into a hidden native source select plus an adjacent button/listbox popover.
- [ ] Support click, Enter, Space, ArrowUp/ArrowDown, Home/End, Escape, Tab, outside click, and focus restoration.
- [ ] Synchronize options, selected value, labels, and disabled state; observe dynamically created audio-rate controls and option-list changes.

### Task 2: Apply the standard component

**Files:**
- Modify: `extension/sidepanel.html`
- Modify: `extension/reading-panel.js`
- Modify: `extension/panel-ui.css`
- Modify: `extension/reading-panel.css`

- [ ] Mark all target language, native language, learner-level, and audio-rate selects for upgrade.
- [ ] Replace native-select visual rules with shared button/listbox styles using current theme tokens, including dark mode, focus, disabled, reduced motion, and forced-colors behavior.

### Task 3: Test dropdown behavior

**Files:**
- Modify: `extension/test/smoke.mjs`

- [ ] Verify settings and audio-rate controls are upgraded; confirm option choice updates the source select and dispatches the existing change behavior.
- [ ] Test keyboard navigation, Escape close/focus restoration, and outside-click close.
- [ ] Run unit tests and browser smoke test.

### Task 4: Commit only the custom-dropdown implementation

**Files:**
- Add: `extension/select-ui.js`
- Add: `docs/superpowers/plans/2026-07-16-custom-dropdown-popovers.md`
- Modify: `extension/sidepanel.html`
- Modify: `extension/reading-panel.js`
- Modify: `extension/panel-ui.css`
- Modify: `extension/reading-panel.css`
- Modify: `extension/test/smoke.mjs`

- [ ] Commit only after both tests pass and the implementation receives spec and code-quality review.
