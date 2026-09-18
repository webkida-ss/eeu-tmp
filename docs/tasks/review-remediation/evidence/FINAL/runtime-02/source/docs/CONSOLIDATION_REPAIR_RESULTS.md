# Consolidation Repair Results

Date: 2026-09-08 (JST). Base: `26de968fa435f96a629d9665b0215c76c175cfe0`.
Repair branch: `codex/consolidation-repairs`.

Historical handoff: the network-related blockers below describe the initial
repair run. The subsequent authorized continuation completed the full gate and
local integration; see [final integration results](INTEGRATION_RESULTS.md).

## Outcome and integration status

All five original source branches are already ancestors of local `main`. The six
original worktrees remain intact. No remote is configured. This resumption
repairs defects found in that integrated code; it does not repeat those merges
or claim the unfinished admin feature was completed.

The repair candidate passes the application regressions and independent static
reviews below. The complete `task check` gate is **not green**: its unchanged
Lambda build requires another public dependency download, which fails under
network denial. A separate Terraform lock check also requires registry access.
Keep this repair on its focused branch until the remaining gate can be completed;
do not treat this evidence as authorization to merge into a protected branch,
publish the extension, push, or deploy.

## Implemented repairs

- Packaging includes the generated API contract, its runtime helper, and the
  sign-in implementation. The explicit production allowlist now validates
  manifest, HTML, and transitive classic-worker references before creating a
  deterministic ZIP. Missing/unsafe dependencies fail the build.
- Browser automation again uses repository-managed Chromium, ephemeral ports,
  per-run artifacts, signal handling, and owned-resource cleanup. Updated login
  interactions retain newer product assertions. An additional entry point builds
  and extracts an actual ZIP and checks worker/content/panel startup.
- The restored browser test exposed a settings re-injection failure:
  `API_ERROR_CODE_KEYS` and `SETTINGS_HAS_OWN` were global lexical declarations.
  Re-declarable bindings retain the frozen, null-prototype error mapping. A
  minimal double-load regression protects this behavior.
- Audio control tests use a controlled speech engine to avoid OS-voice errors
  racing the pause assertion in headless Chromium. They still drive the real UI
  and completion callback; audible output itself is not verified.
- Admin-enabled execution preserves learner `ApiError` responses. Admin error
  mapping and CORS are namespace-scoped. Admin origins fail closed for wildcard,
  credential, and non-origin URL configurations; bearer/allowlist authorization
  remains independent of CORS.
- The implemented admin session joins the sole canonical OpenAPI contract.
  Feature availability, generated admin models, drift, and authorization checks
  run in both modes. Historical unimplemented declarations are preserved under
  the admin API backlog, not presented as live endpoints.
- Canonical tasks and CI now execute admin-enabled and ZIP dependency tests.
  Pure policies and learner suspension tests run in default mode as well.

## Execution environment

Tests ran in a disposable Ubuntu 24.04 Linux ARM64 development container using
the repository's pinned Python 3.12.7, Node 22.23.1, Task 3.40.0, and Terraform
1.15.5. Python development dependencies were installed from the hash-locked file;
root/extension Node dependencies came from `npm ci --ignore-scripts`. Managed
Playwright Chromium and checksum-verified quality tools were provisioned first.

The source snapshot excluded ignored secrets, local data, and dependency folders.
No host credential stores or browser profiles were mounted. Public dependency
provisioning finished before disconnecting the container network. Docker then
reported an empty attached-network map for every test phase. Mock identity and
billing, JSON storage, inline jobs, and dotenv isolation were explicit.

## Verification evidence

All Task commands below used `./scripts/bootstrap.sh --exec task`.

| Check | Result |
| --- | --- |
| Agent generation/integrity/security | Pass |
| Agent configuration tests | 20 passed |
| Online operations, deploy policy, workflow security | 7, 96, and 14 passed |
| Workflow lint and dev-container validation | Pass |
| Python/extension formatting and lint | Pass |
| Canonical schema, generated drift, adapter and route-security checks | Pass with admin disabled and enabled |
| API contracts, default mode | 46 passed |
| Admin-enabled contracts/auth/learner compatibility | 102 passed |
| ZIP dependency/build tests | 8 passed, 14 subtests passed |
| Backend coverage suite, default mode | 764 passed, 6 admin-disabled skips, 31 subtests passed; 83% coverage |
| Extension unit/coverage suite | 170 passed |
| Automation static contract | 1 passed |
| Source-extension browser smoke | Pass |
| Exact packaged ZIP startup | Pass |
| Concurrent/failure-artifact/SIGTERM lifecycle | 3 passed |
| Article parsing versus managed Chromium | 18/18 fixtures match |
| Terraform formatting | Pass |
| Complete `task check` | Stops at Lambda dependency download under network denial |
| Terraform lock reproducibility | Stops at provider registry discovery under network denial |

The ZIP startup run produced SHA-256
`ed56ae949b33f9327e6bad98eea6410b2a5c9b8e9f0e5846cf94e44220f026a2`
with a deliberately invalid example API hostname. Tests used local fixtures, not
a deployed service. ZIP startup does not simulate a real user gesture granting
`activeTab` for programmatic re-injection; full source smoke verifies that path
using the development permissions. This is not a Chrome Web Store install test.

The final canonical log is retained in
`output/consolidation-repairs/check-final.log`; provider-lock diagnostics are in
`output/consolidation-repairs/infra-lock-final.log`. These are ignored local
evidence, not source artifacts. A FastAPI TestClient/httpx deprecation warning
remains; it did not fail tests.

## Independent review and reproducibility

An independent correctness reviewer and a separate security-boundary reviewer
inspected the immutable repair snapshot against the base without executing tests,
editing files, contacting external systems, or approving a release. Neither
reported an actionable new correctness/authentication/CORS/schema-bypass defect.

Initial reviewed archive SHA-256:
`e42b1ed5549d7be420e9a4d3288d96cb2b022e0f7714c3a3d4e6588216115222`.
Final code/test snapshot SHA-256:
`bd54af3aa3105aa9fb76944383b268c5856929f0834a60ba46f3804db742fa4f`.
The final delta strengthens disabled-mode suspension coverage and preserves
byte-for-byte canonical generator output. The independent correctness reviewer
also inspected this two-file delta and reported no findings. Narrative
result/plan updates followed the code/test snapshot.

RED evidence preceded repairs: missing ZIP dependencies failed packaging tests;
admin transport had seven failures; settings double-loading raised the exact
browser declaration error. The full browser loop passed after the repairs.

## Remaining work and limits

1. Complete the supported gate with pre-provisioned/offline dependency inputs or
   an explicitly approved validation environment. Do not remove checks or weaken
   network/credential isolation to label the candidate green.
2. Recheck Lambda package contents/imports and Terraform validation/locks before
   release. These scripts and provider locks were not changed in this repair.
3. Perform normal-Chrome user-gesture/unpacked-extension verification locally
   when preparing a release; only managed Linux Chromium was executed here.
4. Keep seven admin endpoints and the frontend in their separate feature backlog.
5. The optional [refactor plan](CONSOLIDATION_REFACTOR_PLAN.md) is now broken into
   small green-commit units. Structural refactors and GitHub issue publication
   were not performed.

No worktrees or branches were deleted; historical contract proposals were moved
and preserved. No push, cloud call, production credential access, or deployment
occurred. The five-hour resumption ran once and its future heartbeat was paused.
