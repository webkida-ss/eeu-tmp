---
name: extract-ubiquitous-language
description: >-
  Extracts ubiquitous language candidates from project notes, docs, code, and
  requirements, then updates docs/Ubiquitous.md. Use when the user asks to
  extract terms, organize domain language, update ubiquitous language, or
  mentions "ユビキタス".
---
# Extract Ubiquitous Language

## Goal

Extract domain terms and naming decisions from project materials, then keep `docs/Ubiquitous.md` up to date.

## Workflow

1. Read the requested files or the most relevant project documents.
2. Extract terms that represent domain concepts, user actions, business rules, feature names, or important naming decisions.
3. Ignore generic engineering words unless the project gives them a specific domain meaning.
4. Normalize names in English, even if the source notes are written in Japanese.
5. Present the extracted candidates to the user and ask for approval before editing files.
6. After approval, update `docs/Ubiquitous.md` with concise table entries.

## Output Format

Use this structure in `docs/Ubiquitous.md`:

```markdown
# Ubiquitous Language

## Terms

| Term | Meaning | Notes |
| --- | --- | --- |
| Term | Definition in English. | Optional usage note, naming rationale, or source context. |
```

## Notes

- Keep definitions short and practical.
- Prefer terms already used in the product or codebase.
- If multiple names are possible, record the chosen name and briefly note why.
- Use the table format so terms can be compared at a glance.
- Do not update `docs/Ubiquitous.md` until the user confirms the extracted candidates.
- Ask before overwriting or renaming existing terms when the intent is ambiguous.
