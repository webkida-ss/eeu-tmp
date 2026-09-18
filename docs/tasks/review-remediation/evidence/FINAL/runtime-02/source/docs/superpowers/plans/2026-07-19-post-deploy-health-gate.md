# Post-Deploy Health Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every applied dev or prod deployment fail visibly unless the deployed backend returns `{"status":"ok"}` from `/health`.

**Architecture:** Add a Python standard-library health checker with bounded retries, strict response validation, and unit tests using a local HTTP server. The deployment workflow reads Terraform's `api_endpoint` output and invokes the checker only after a successful apply; plan-only runs remain read-only.

**Tech Stack:** Python 3.12 standard library, pytest, GitHub Actions, Terraform outputs.

---

### Task 1: Specify health-check behavior

**Files:**
- Create: `backend/test_check_health.py`

- [ ] Test a successful JSON response.
- [ ] Test retry after a transient HTTP 503.
- [ ] Test failure after the configured attempts when the payload is invalid.
- [ ] Test URL normalization appends `/health` exactly once.
- [ ] Run `python3 -m pytest -q backend/test_check_health.py` and verify RED
  because `backend/scripts/check_health.py` does not exist.

### Task 2: Implement the checker

**Files:**
- Create: `backend/scripts/check_health.py`

- [ ] Accept `--api-endpoint`, `--attempts`, `--delay-seconds`, and
  `--timeout-seconds`.
- [ ] Require an absolute HTTP or HTTPS endpoint with no query or fragment.
- [ ] Request `<endpoint>/health` with `urllib.request`.
- [ ] Treat non-2xx responses, invalid JSON, and any response other than
  `{"status":"ok"}` as failed attempts.
- [ ] Retry with bounded delay and exit non-zero after exhaustion.
- [ ] Never print response bodies or credentials.
- [ ] Run the focused tests and verify GREEN.

### Task 3: Add the deployment gate

**Files:**
- Modify: `.github/workflows/deploy-reading-assistant.yml`
- Modify: `infra/README.md`

- [ ] After Terraform apply, capture `terraform output -raw api_endpoint` as a
  step output.
- [ ] Invoke `backend/scripts/check_health.py` with 12 attempts, a 5-second
  delay, and a 10-second request timeout.
- [ ] Skip both steps for `plan_only=true`.
- [ ] Document the post-deploy check and its maximum wait.

### Task 4: Verify

**Files:**
- No additional source changes.

- [ ] Run `python3 -m pytest -q backend/test_check_health.py`.
- [ ] Run `python3 -m pytest -q backend`.
- [ ] Parse the workflow as YAML when PyYAML is available; otherwise inspect
  the exact diff and rely on GitHub Actions validation after integration.
- [ ] Run `git diff --check`.
- [ ] Report results without committing unless explicitly requested.
