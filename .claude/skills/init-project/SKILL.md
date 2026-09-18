---
name: init-project
description: >
  Sets up the project structure with standard directories and files following project rules.
  Use when: initializing a new project, scaffolding a module, setting up directory structure,
  adding a new module, or creating project boilerplate. Triggers on "init", "scaffold",
  "initialize project", "create module", "set up directories", or similar phrases.
---

# Scaffold

## Steps

1. **Sync script with rules**
   - Read `11_structure.mdc` (directories and standard files)
   - Compare with `scripts/scaffold.sh`
   - If there are differences, update the script to reflect the current rules before proceeding

2. **Run the script**

```bash
bash .claude/skills/init-project/scripts/scaffold.sh <project-root>
```

If no project root is specified, run from the repository root (defaults to `.`).

The script also scaffolds `contracts/openapi/` with an OpenAPI entry file and split schema/path directories.

The script also scaffolds `frontend/src/` with the Bulletproof React structure (Next.js convention).

The script also scaffolds empty GitHub Actions deploy workflows for backend, infra, and frontend under `.github/workflows/`.
