---
name: design-direction
description: Defines overall UI look and feel for engineers — mood, reference decomposition (This/Not That), direction selection, and anti-patterns. Writes docs/DESIGN.md. Use when the user is unsure about visual direction, says a site "feels right", wants a design brief or mood board, or mentions デザイン方向, 概要感, 雰囲気, 参考サイト, look and feel, or design direction. Does not implement UI.
---
# Design Direction

Help the user lock **overall look and feel** before colors, components, or code.

Focus on direction (mood, references, what to borrow/avoid). Defer implementation
to frontend work and design tokens.

## When to use

- User is stuck on "sites like X feel good" without knowing why
- Starting a new screen, app, or redesign
- Multiple conflicting references (e.g. Notion + Duolingo + Anki)
- No designer on the team

## Before starting

1. Read project context if present: `docs/MEMO.md`, existing `docs/DESIGN.md`
2. Confirm scope: whole app vs single flow/screen
3. Do **not** jump to fonts, hex colors, or component libraries yet

## Workflow

CRITICAL: Do not interrupt the user between steps. You MUST batch the questions for Steps 1 through 7 into a **single** `AskQuestion` tool call. Present all options at once so the user can complete the entire direction setup in one go.

Copy this checklist and track progress:

```
Direction Progress:
- [ ] Step 1: Mood (3 words)
- [ ] Step 2: Reference sites (up to 3)
- [ ] Step 3: Decompose references (This / Not That)
- [ ] Step 4: Compare on shared axes
- [ ] Step 5: Pick base direction (A / B / C or hybrid)
- [ ] Step 6: Anti-reference list
- [ ] Step 7: One-line first impression
- [ ] Step 8: Write docs/DESIGN.md
- [ ] Step 9: Confirm with user before implementation
```

### Step 1 — Mood (3 words)

Use the `AskQuestion` tool to present 2–3 preset triads of adjectives based on the product type. Include an option for the user to provide their own custom keywords.

Examples of adjectives: `Calm`, `Focused`, `Encouraging`, `Playful`, `Serious`, `Minimal`, `Warm`, `Tool-like`, `Editorial`.

### Step 2 — Reference sites (up to 3)

Use the `AskQuestion` tool to present 3-4 well-known comparable apps/sites as options, plus an option for the user to provide their own custom references.

Rules:
- Mix categories if helpful (learning app + writing tool + unrelated inspiration)
- Ask **what specifically** feels right — not "I like Notion" but which parts

### Step 3 — This / Not That

For **each** reference, use the `AskQuestion` tool to present a list of specific UI traits to borrow (This) and reject (Not That). Allow the user to select multiple options for both.

Rule: every "This" must be **visual or interaction-level**, not vague ("feels clean").

### Step 4 — Comparison matrix

Create a shared-axis table comparing the references. Then, use the `AskQuestion` tool to ask the user if they agree with the comparison or if they want to adjust specific axes (like Information density: Low/Medium/High).

| Reference | Mood | Information density | Color tone | Primary borrow | Reject |
|-----------|------|---------------------|------------|----------------|--------|

Density: `Low` / `Medium` / `High`

### Step 5 — Base direction (A / B / C)

Use the `AskQuestion` tool to propose **three distinct directions** and let the user pick one base direction (or a hybrid option).

| ID | Summary | Typical references |
|----|---------|-------------------|
| A | Calm writing / focus tool | Notion, iA Writer, Readwise |
| B | Gentle gamification | Duolingo (muted), Streaks apps |
| C | Tool-first / dense utility | Anki, Quizlet, admin dashboards |

Output must state explicitly:

```markdown
**Base:** [A | B | C]
**Also borrow from:** [reference + specific traits]
**Explicitly not using:** [reference or direction + why]
```

Default for writing-heavy learning apps: **A base + selective B** (calm writing,
light streak/motivation on home only).

### Step 6 — Anti-reference

Use the `AskQuestion` tool to present a list of 3–7 **hard rejects** (anti-patterns) for the user to select from. Include common AI-slop patterns as options:

- Purple gradient on white
- Generic Inter/Roboto-only typography with no intent
- Mascots / excessive badges / notification spam
- Dashboard cramming unrelated metrics

### Step 7 — One-line first impression

Use the `AskQuestion` tool to present 3 variations of a single sentence a user would say after opening the app, based on the formula:

> "It feels like ___ — I can ___ without feeling ___."

Example: "A quiet daily English notebook — I can write for five minutes without feeling gamified or overwhelmed."
Include an option for the user to write their own.

### Step 8 — Write direction doc

Save (or update) using [references/design-direction-template.md](references/design-direction-template.md).

Path: **`docs/DESIGN.md`**

English for the doc body (project convention).

### Step 9 — Confirm before code

Present the doc summary to the user. Use the `AskQuestion` tool to confirm:

Options should include:
1. Approve and proceed to design tokens/wireframes
2. Revise base direction
3. Flip a This/Not That line

Do **not** scaffold frontend or pick shadcn themes until the user approves direction
(or explicitly says "go ahead" / "implement").

## Facilitation rules

- **Decompose, don't name-drop:** "X-like" → list 2–4 concrete traits
- **One base direction:** hybrids allowed; "everything from everyone" is invalid
- **Screen priority:** if scope is whole app, note P0 flow (core loop) in the doc
- **No premature pixels:** no hex codes, font files, or Tailwind config in this skill
- **Batch questioning:** Do not stop and wait after each step. Group Steps 1-7 into a single `AskQuestion` call to minimize interruptions.

## Handoff (after approval)

When direction is approved, suggest next steps in order:

1. P0 screen list + simple wireframe (structure only)
2. Design tokens in `tailwind.config` (colors, spacing, radius, type scale)
3. shadcn/ui or project component baseline
4. Style tile or one HTML mock for the P0 writing surface

Point to `.cursor/rules/frontend/next.mdc` for stack conventions.

## Additional resources

- Output template: [references/design-direction-template.md](references/design-direction-template.md)
