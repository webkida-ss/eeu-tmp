---
root: false
targets:
  - '*'
description: Documentation conventions for the project
globs:
  - docs/**/*.md
cursor:
  alwaysApply: false
  description: Documentation conventions for the project
  globs:
    - docs/**/*.md
---
## Ubiquitous Language

Update `docs/Ubiquitous.md` whenever project terms, domain concepts, or naming decisions are added or changed.

## ADR

Use `docs/adr/` to record architectural and technical decisions. Each ADR should explain what was decided, why it was chosen, what alternatives were considered, and any important trade-offs.
