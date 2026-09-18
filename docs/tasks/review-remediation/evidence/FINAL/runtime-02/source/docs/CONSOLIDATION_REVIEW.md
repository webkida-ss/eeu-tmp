# Consolidation Review

Review date: 2026-09-08 (JST).

Reviewed commit: `26de968fa435f96a629d9665b0215c76c175cfe0`.

Consolidation is complete in local Git history, but the integrated code is not
ready for release. Packaging and browser automation contain confirmed integration
defects. No implementation changes were made during this review.

Follow-up: the scheduled resumption implemented repairs on
`codex/consolidation-repairs`. See
[repair results](CONSOLIDATION_REPAIR_RESULTS.md) for current verification and
remaining gate limitations. Findings below describe the reviewed baseline.

## Scope and provenance

The review uses `git diff 33885fd...26de968`, retaining the previous review's
baseline. This includes the standalone sentence-splitting/release-planning commit
`244f92b`, followed by five integration merges. Findings were also compared with
each merge's parents and source branch to distinguish lost implementation from
unfinished work and pre-existing problems. The diff spans 413 files, including
generated configuration, schemas, and dependency locks; this is a focused review
of integration behavior, not proof that every execution path is defect-free.

| Source branch | Tip | Commits outside main | Working tree |
| --- | --- | --- | --- |
| `automation/full-test-automation` | `bd5e567` | 0 | Clean |
| `feature/local-admin-site` | `15b76c1` | 0 | Clean |
| `release/extension-packaging` | `5095a49` | 0 | Clean |
| `release/launch-pricing` | `d9efd3e` | 0 | Clean |
| `release/post-deploy-health` | `49b31c3` | 0 | Clean |

`main` and `codex/consolidate-worktrees` both point to the reviewed commit.
All six existing worktrees were clean at intake. No remotes are configured, so
this conclusion concerns local integration, not a published branch or GitHub PR.
The documentation is prepared on `codex/consolidation-review-plan`.

Specifications were taken from the matching local release, pricing, admin, and
test-automation documents. No issue reference was supplied or discovered in the
reviewed commit messages. The `code-review` skill was used for independent
Standards and Spec reviews; both reviewers inspected immutable Git history and
source, without executing tests or modifying files. The parent performed the
supplemental checks below.

## Standards

### S1 — P1: Canonical contract split introduced by the merge

`backend/scripts/generate_admin_models.sh:9` generates from
`contracts/openapi/admin-openapi.yaml`, while `scripts/schema/schema_tasks.py:26`
and the documented `task api:generate/check` workflow use `openapi.yaml`.
That root excludes admin routes. The separate admin-model drift script is not
connected to Taskfile or CI.

This violates the single-schema rule in
`.agents/memories/basic-strategy.md` and the canonical workflow in `AGENTS.md`.
Merge `372e8b7` introduced the split; the admin branch used the canonical
filename. Integrate implemented admin contracts and generated-model checks into
one workflow, while distinguishing future endpoints from implemented contracts.

### S2 — P3: Domain vocabulary omission inherited from the admin branch

`backend/repositories/admin_activity.py:17` introduces `ActivityEvent`;
account-control repositories introduce `AccountControl` and `AdminAuditEvent`.
They are absent from `docs/Ubiquitous.md`, although
`.agents/memories/documentation.md` requires terminology updates. Document their
meaning, identifiers, and the distinction between learner activity and admin audit.

### S3 — P2: Merge-created verification gap (judgment finding)

The merge added module-level `pytest.mark.skipif(not ADMIN_ENABLED, ...)` in
`backend/test_admin_auth.py:14` and `backend/test_learner_suspension.py:23`.
No canonical test task or CI invocation enables admin. Default checks therefore
skip authorization, suspension, and even framework-independent domain tests.
Add explicit enabled/disabled runtime coverage and stop skipping pure policy tests.
The supplemental enabled-mode run passed; the defect is missing gate coverage,
not evidence that these policy implementations currently fail their tests.

### S4 — P3: Divergent Change expanded in reading orchestration (heuristic)

`backend/services/reading.py:429` constructs `AdminActivityService` while adapting
terminal results throughout article and chat execution. The same module handles
dispatch, quota settlement, preload recovery, and vocabulary assembly. It already
had 2,171 lines at the baseline and now has 2,305. This is refactoring debt, not a
merge failure inferred from file length. Terminal-outcome recording is a focused
extraction candidate because its conventions currently span several callers.

## Spec

### F1 — P1: Release ZIP omits mandatory runtime dependencies

The release-readiness specification requires a reproducible store-ready ZIP
(`docs/superpowers/specs/2026-07-19-public-paid-release-readiness-design.md:225`).
`extension/scripts/build_release.py:22` omits three referenced files:

- `generated/api-contract.js`
- `api-contract-runtime.js`
- `signin-methods.js`

The first two are required by `extension/background.js:1`; the last is loaded
by `extension/sidepanel.html:336`. They were not dependencies of the packaging
branch's extension, so this is a cross-branch integration defect. The generated
ZIP is missing them even though all three existing packaging tests pass.
The service worker's required imports cannot load from this artifact; the
artifact must not be released. A store-installed browser run was not performed.

### F2 — P1: Automation implementation discarded during merge

`docs/TEST_AUTOMATION_PLAN.md:263` requires managed Chromium on macOS and Linux;
its failure gate at line 376 requires trace, screenshot, and console-log evidence.
The automation branch implemented portable launch, artifacts, signal handling,
and guaranteed cleanup. Merge `0739448` discarded that work in `smoke.mjs`.

Current `extension/test/smoke.mjs:43` searches only macOS cache paths, line 128
uses fixed port 18099, and lines 1269–1270 close resources only after successful
execution. Linux execution fails before browser launch. Failures and concurrent
runs also lack the source branch's cleanup and artifact guarantees.

### F3 — P1: Admin contract disconnected from the canonical gate

The admin design at
`docs/superpowers/specs/2026-07-20-admin-site-design.md:267` names
`contracts/openapi/openapi.yaml` as the source of truth. Admin declarations were
relocated to `admin-openapi.yaml` during integration without connecting the
generation and conformance gate. This is independently a specification mismatch
as well as the Standards finding S1.

### F4 — P1: Admin-enabled learner errors violate the merged contract

`contracts/openapi/components/schemas/ApiError.yaml:10` requires `detail`.
With admin enabled, `backend/main.py:124` rewrites every HTTP 401 to
`code/message/correlation_id`, including learner `/auth/me`. The combined
contract and runtime are incompatible. The body mismatch is confirmed; the
extension validates response metadata, so JSON-schema rejection by the extension
is not established and must not be claimed.

### F5 — P2: Admin feature remains incomplete, rather than lost in the merge

The admin design lists eight endpoints at lines 271–278. The source branch
`15b76c1` and current `backend/admin/router.py:12` implement only session.
Dashboard, user list/detail, suspension/reactivation, alerts, and audit APIs,
plus the admin frontend, remain backlog. Several application/repository pieces
already exist. Completing the whole design is feature work, not merge repair.

### F6 — P2: Admin origin policy mismatch inherited from the branch

The admin design at line 82 accepts only the configured admin frontend origin.
`backend/main.py:109` shares learner origins and an arbitrary Chrome-extension
origin pattern, and permits any requested header. An extension-origin preflight
with `Authorization` was accepted. This does not demonstrate authentication bypass;
it demonstrates failure to enforce the specified browser-origin restriction.
The mismatch already existed on the admin branch, whose implementation plan
unfortunately prescribes the broader configuration.

Standards: 4 findings, highest priority S1 (P1 canonical contract split).
Spec: 6 findings, highest priority P1 (F1–F4).

## Verification evidence

### Fresh supplemental checks

Tests used a `git archive` of the pinned commit, not the user's working data.
Execution occurred in the cached Ubuntu development image
`sha256:bcb424fa5881ecd8b6e7d7247b483fc566781a5a7a5f9a9d09c5fcdaa0db0a92`
with `--network none --cap-drop ALL --security-opt no-new-privileges`.
Source archives and dependency caches were mounted read-only; execution and
generated artifacts used disposable container storage. No host credentials or
environment files were mounted. Mock auth/billing, JSON storage, inline jobs,
and disabled dotenv loading were set explicitly.

The cached Linux environment was older than the integrated dependencies. For the
targeted admin run it was supplemented with cached pure-Python `email-validator`
2.3.0 and its DNS package. This is supplemental evidence, not a fresh full install
from the integrated lockfiles or a complete `task check` pass.

| Check | Result |
| --- | --- |
| Git ancestry, worktree status, `git diff --check 33885fd...26de968` | All five source branches included; no uncommitted work at intake; no whitespace errors |
| Packaging tests: `python -m unittest discover -s extension/test -p test_build_release.py` | 3 passed |
| `python extension/scripts/build_release.py --api-base-url https://api.example.test --output /tmp/untangle-review-release.zip` | Build succeeds; dependency inspection finds all three F1 omissions |
| `python -m ruff format --check extension/scripts/build_release.py extension/test/test_build_release.py` | Fails: build script needs formatting |
| `python -m ruff check extension/scripts/build_release.py extension/test/test_build_release.py` | Fails: two I001 import findings and B018 at build script line 56 |
| `ADMIN_ENABLED=true python -m pytest -q backend/test_admin_auth.py backend/test_learner_suspension.py backend/test_admin_runtime.py` | 33 passed; one FastAPI/TestClient deprecation warning |
| `./scripts/bootstrap.sh --exec task test:extension:smoke` in Linux | Fails: searches `/home/vscode/Library/Caches/ms-playwright` before browser launch |
| TestClient route/error/origin probes, admin enabled | Session 401; dashboard/users/alerts/audit 404; learner 401 lacks `detail`; extension-origin preflight permits `Authorization` |

The rebuilt ZIP SHA-256 was
`95398a4ceef70c808846f81d5a8cc5c0efe8f233cd83ce02c945d18adb022530`, matching
the previous review's artifact.

Initial container setup attempts encountered path/permission and missing-cache
problems. A broader extension-unit rerun remained incomplete because the reused
node-module cache could not resolve dependencies in three DOM test files; those
failures are environment limitations, not new product findings. Running Ruff
over an archived tree without Git metadata also traversed development-tool
dependencies; only the explicit project-file Ruff results above are used.

### Earlier evidence, not re-run in full

The prior session tested this same source commit and reported 714 backend tests
passed / 27 skipped, 169 extension tests passed, 41 API-contract tests passed,
and 18/18 Chromium fidelity fixtures passed. It also reported successful
Terraform lock/validation and Lambda package checks. The full `task check`
failed on packaging formatting. These results remain historical evidence and
are not presented as a fresh clean gate run.

### Corrections to the earlier review

- Stale `#authEmail` smoke selectors were already present at `33885fd`; their
  failure is not itself a newly introduced merge defect. F2 identifies the
  actual automation work discarded by the merge.
- The seven missing admin endpoints and frontend were already unfinished on
  their source branch. A clean merge cannot complete that backlog.
- Selecting providers from environment variables alone does not prove that
  tests contact external services. Explicit mocks and a network-denied test
  environment are useful hardening, but no live call is alleged here.
- The ZIP problem is a release blocker (P1), not evidence of an already
  occurring production outage.
- Worktree cleanup does not resolve these issues. The merged source branches
  are useful references for restoring lost behavior; no branch/worktree was
  deleted during this review.

## Recommended next work

Follow [the refactor and remediation plan](CONSOLIDATION_REFACTOR_PLAN.md).
Repair packaging, recover automation behavior, and close admin contract/test
gaps before structural refactoring. A release decision still needs a passing
full gate and browser verification against the actual packaged artifact.
