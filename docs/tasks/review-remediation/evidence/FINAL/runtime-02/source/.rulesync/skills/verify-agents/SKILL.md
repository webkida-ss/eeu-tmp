---
name: verify-agents
description: >-
  Verify repository agent configuration setup, generation, drift detection,
  hooks, MCP safety, and integration evidence without external side effects.
targets:
  - '*'
disable-model-invocation: true
---
# Verify Agent Configuration

Run from the repository root:

1. `./scripts/bootstrap.sh`
2. `./scripts/bootstrap.sh --exec task setup:agents`
3. `./scripts/bootstrap.sh --exec task agents:generate`
4. `./scripts/bootstrap.sh --exec task agents:check`
5. `./scripts/bootstrap.sh --exec task test:agents`
6. `./scripts/bootstrap.sh --exec task check`

For smoke evidence, inspect generated Cursor, Claude Code, Codex CLI, and
`AGENTS.md` outputs; confirm formatter hook timeouts, Claude deny rules, and
locked local MCP commands. Prove drift detection in a temporary repository
copy by changing and deleting generated files, adding an unexpected generated
file, changing source, and verifying the check fails. Run generation twice and
verify the second run produces no diff.

Do not authenticate, start MCP servers, install browser binaries, call external
services, change GitHub or cloud settings, commit, push, open a pull request,
or deploy. Report exact commands, exit codes, and any skipped integration
evidence.
