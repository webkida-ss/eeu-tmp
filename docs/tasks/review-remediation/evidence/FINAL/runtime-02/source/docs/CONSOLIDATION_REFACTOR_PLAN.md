# Consolidation Remediation and Refactor Plan

Date: 2026-09-08. Baseline: `26de968fa435f96a629d9665b0215c76c175cfe0`.

Status: implementation plan with progress recorded below. Original evidence and
provenance are in [the consolidation review](CONSOLIDATION_REVIEW.md).

Update after the scheduled resumption: Phase A correctness repairs are implemented
on `codex/consolidation-repairs`. See
[repair results](CONSOLIDATION_REPAIR_RESULTS.md) for passing regressions and the
remaining offline build/registry gate limitation. Phase B is implemented on
`codex/reading-refactor`, based on repair commit `6113f9c`. B4 adds a consistency
guard only; a shared catalog is deliberately deferred. See
[refactor results](REFACTOR_RESULTS.md) for validation and remaining limits.
The user-authorized continuation completed the previously blocked full gate and
local DynamoDB integration. [Final integration results](INTEGRATION_RESULTS.md)
record the local consolidation outcome and supersede those validation blockers.

## Objective and limits

Recover the intended behavior of the integrated branches, make the quality gate
exercise the supported configurations, then reduce the number of places a
maintainer must change for one operation-lifecycle or contract change.

Keep the existing Python backend and vanilla JavaScript MV3 extension. Do not
migrate frameworks, change plan prices/limits, alter persisted IDs, redesign the
billing state machine, or complete the admin frontend as incidental cleanup.
The admin feature backlog is separate from consolidation repairs.

Each numbered unit below is independently reviewable and should use a focused
`codex/` branch. Split a unit further if its behavior change and structural move
cannot be verified independently. Commit tests with the behavior they protect;
do not leave deliberately failing test commits as merge candidates.

## Phase A: Restore integration correctness

### A1. Repair the release artifact and its acceptance test

Files: `extension/scripts/build_release.py`,
`extension/test/test_build_release.py`, and a focused packaged-extension smoke
entry point under `extension/test/` if the restored smoke harness can support it.

- Include the three missing runtime dependencies and preserve nested paths in
  the ZIP. Retain deterministic ordering/timestamps, API URL injection, icon
  validation, and rejection of development/secret files.
- Validate the dependency closure from manifest, HTML scripts, and worker
  imports. Do not replace the allowlist with an unrestricted directory copy.
- Replace the duplicated expected-file-list test with reference-resolution
  assertions against the actual archive. Keep determinism and source-integrity
  assertions. A missing imported script must fail the build/test.
- Fix Ruff formatting/import findings. Preserve the URL parser's deliberate
  port validation when addressing B018; accessing `parsed.port` can raise and
  must not simply be removed.

Acceptance: packaging tests and Python lint/format pass; the generated archive
contains all referenced files. Once A2 is available, unpack that exact ZIP into
a temporary profile and verify service-worker startup and side-panel sign-in
rendering using local fixtures. Do not point a smoke test at a production API.

### A2. Recover browser automation lost by the merge

Files: `extension/test/smoke.mjs`, existing automation tests,
`extension/package.json`, and Taskfile/CI only where wiring is necessary.

- Use `bd5e567:extension/test/smoke.mjs` as a reference for portable managed
  Chromium launch, ephemeral ports, per-run artifacts, signal handling, and
  idempotent cleanup. Preserve newer product assertions from the integrated file;
  do not replace the entire file with an old branch version.
- Update mock login interaction to the existing account chooser. Use accessible
  controls or stable product selectors instead of the removed `#authEmail` and
  `#loginButton` fields.
- Restore assertions that distinguish a missing element from an enabled one;
  optional chaining followed by `=== true` must not silently pass missing UI.
- Exercise two concurrent runs, forced failure, artifact-write failure, and
  SIGTERM using the existing lifecycle tests. Preserve the original failure even
  when diagnostics fail. Verify that cleanup removes only this run's resources.

Acceptance: `task test:extension:smoke` and
`task test:extension:automation:lifecycle` pass on managed Linux and macOS;
intentional failures preserve trace, screenshot, and sanitized logs. The Linux
run must reach the browser, not merely pass a static source-pattern assertion.

### A3. Make admin configuration coverage explicit

Files: `Taskfile.yaml`, relevant CI workflow, `backend/test_admin_auth.py`,
`backend/test_learner_suspension.py`, `backend/test_admin_runtime.py`, and
configuration/test composition only as needed.

- Add a canonical admin-enabled test invocation and retain default-disabled
  coverage. Ensure `task check` and CI both call it.
- Run pure policy tests regardless of feature flags. Isolate enabled/disabled
  application initialization in separate processes or explicit app construction,
  avoiding module-cache leakage between modes.
- Set mock providers, JSON storage, inline jobs, and dotenv isolation explicitly
  in the service-free runner. Keep network denial in the execution environment.
- Run learner authentication/contract checks with admin both off and on, not
  just the admin-specific happy paths. The fresh review's 33 passing tests do
  not cover the observed contract and CORS gaps.

Acceptance: enabled-mode authorization/suspension cases execute rather than
skip, disabled mode does not expose admin routes, and ordinary learner behavior
is unchanged between modes except the intended suspended-account restriction.

### A4. Reconcile admin contracts, transport errors, and origin policy

Files: canonical YAML and generators, `backend/main.py`, admin HTTP adapters,
generated artifacts through generation commands, contract/security tests.

- Keep a single authored canonical root. Include the implemented session
  endpoint with explicit runtime availability when admin is disabled. Keep the
  seven proposed endpoints in planning documentation until implemented; do not
  claim conformance by adding empty route stubs.
- Wire admin component generation/drift checks into `task api:generate/check`.
  Make generation honor the configured backend virtual environment rather than
  hardcoding `backend/.venv`. Resolve duplicate auth declarations/operation IDs.
- Preserve the learner `ApiError` body for learner routes. Scope admin error
  translation to admin transport. Test 401 and suspended-account 403 response
  shapes with both feature-flag configurations.
- Enforce the configured admin origin on admin preflights and responses while
  preserving extension access on learner routes. Test allowed/disallowed
  origins with `Authorization`, error responses, and header variations. CORS is
  additional browser policy, not a substitute for per-request authorization.
- Update the conflicting admin implementation-plan CORS guidance and document
  implemented versus planned endpoints. Do not introduce broad compatibility
  waivers to suppress mismatches.

Acceptance: canonical generation is reproducible; every supported runtime mode
has contract/security evidence; the merged learner wire contract stays stable.
If the canonical tool needs a feature-availability mechanism, keep it narrowly
defined and test unrecognized modes fail closed rather than silently filtering
all admin routes out of validation.

## Phase B: Refactor behind stable interfaces

Begin only after Phase A behavior is protected. The `codebase-design` approach
used here prioritizes depth and locality: a small interface should hide real
coordination work. File length by itself is not a reason to introduce another
layer. Keep existing repository interfaces and their JSON/in-memory adapters.

### B1. Consolidate terminal activity recording

Current seam: `AdminActivityRepository`, already implemented by JSON and memory
adapters. Target module: extend/refine the existing admin-activity module rather
than adding a second generic event framework.

Move outcome-to-event translation out of `reading.py`: usage-field conversion,
safe metadata, source identity conventions, and success/failure recording. The
interface should accept one typed terminal outcome rather than a repeated group
of optional token/cost/model arguments. Inject the clock/ID supplier only where
deterministic behavior or existing adapters require variation.

Preserve first-write/idempotent event semantics, null-versus-zero accounting,
sanitized metadata, and the current distinction between original operation
failure and telemetry failure. Do not silently change whether telemetry failure
fails a successful request; decide that behavior separately if improvement is
needed. Source-ID format changes require a migration decision and are excluded
from this extraction.

Acceptance: existing admin activity repository/service, chat activity, and
preload tests pass across success, provider failure, quota rejection, and replay.
Add only missing behavioral cases through the outcome interface. Callers should
no longer know the event-field translation details.

### B2. Extract synchronous execution coordination

Current code: `_recover_synchronous_result`, `_claim_or_await_synchronous_execution`,
`_SynchronousExecutionHeartbeat`, dispatch markers, and settlement helpers in
`backend/services/reading.py`.

Target module: a focused synchronous-execution coordinator used by selection
analysis and chat. Its interface owns claim/replay/dispatch/settlement sequencing;
the caller provides operation-specific request hashing and provider work.
`UsageMeter` and repository adapters remain responsible for accounting/storage.
Do not create a pass-through wrapper exposing every existing private helper.

Move one caller first, preserving wire output and repository state, then the
other. Retain the old entry-point signatures during migration. Preserve exactly
one provider dispatch for concurrent retries, lease ownership checks, durable
result-before-finalize ordering, replay without new charges, and conservative
settlement after an uncertain dispatch.

Acceptance: relevant `test_pipeline_usage`, `test_usage_meter`,
`test_preload_jobs`, and handler-independence cases remain green. Concurrency and
failure-injection checks must use existing repository contracts. Do not share
this coordinator with preload jobs until their distinct lifecycle has been
characterized; similarity alone is insufficient.

### B3. Separate preload processing from read-only projections

Move vocabulary assembly and preload response projection into a focused query
module, leaving thin compatible entry points where needed. Extract preload
submit/worker coordination separately, retaining the existing inline/SQS runner
interface and content-store adapters.

Preserve latest-record selection, learner-profile invalidation, result-size
limits, cancellation, enqueue uncertainty, lease recovery, and pending-settlement
repair. Keep vocabulary ordering and bounds (30 preloads, 600 items) unchanged.

Acceptance: vocabulary/handler tests, preload/worker tests, and local DynamoDB
contract tests exercise both repository adapters where applicable. A structural
move must not change persisted documents or billing counters.

### B4. Reduce duplicated configuration only where it earns its cost

The plan-limit defaults currently agree across Python and three Terraform
locations. First add a focused cross-representation consistency check. Then
consider one non-secret, language-neutral plan catalog consumed by both Python
and Terraform, retaining explicit environment overrides and existing deployment
interfaces. Do not add build-time code generation merely to relocate literals.

Acceptance: unchanged effective basic/pro/max limits, billing responses, and
Terraform variable validation; malformed/unknown configuration fails clearly.
This is lower priority than execution correctness and may be deferred.

## Suggested green-commit sequence

Following the `request-refactor-plan` discipline, keep each structural step
independently testable. These are local planning units, not posted GitHub issues
or independent authorization to implement the structural changes. The user
subsequently authorized Phase B implementation. The list records the original
proposed sequence, not a claim that each item requires a separate commit.

1. Add characterization cases for success, provider failure, quota rejection,
   replay, and missing usage fields in terminal activity recording.
2. Define a typed terminal outcome accepted by the existing activity service;
   preserve all currently observable event fields and error behavior.
3. Verify selection-analysis outcome behavior. Baseline selection analysis does
   not emit admin activity; preserve that behavior rather than inventing events.
4. Move chat outcome translation, using the same characterization cases.
5. Move preload terminal translation, then remove only unused duplicate mapping.
6. Add concurrent-retry and uncertain-dispatch cases at the existing execution
   boundary; assert dispatch count, response, and persisted settlement state.
7. Extract synchronous execution coordination without migrating either caller.
8. Migrate selection analysis while keeping its public entry point unchanged.
9. Migrate chat, then remove the now-unused coordination helpers.
10. Characterize vocabulary ordering, source-record selection, and bounds.
11. Extract the read-only vocabulary projection behind compatible entry points.
12. Characterize preload enqueue failure, cancellation, and recovery outcomes.
13. Extract preload coordination separately from synchronous execution; preserve
    its existing worker and storage ports.
14. Add a consistency check across current plan-limit representations before
    considering any shared catalog.

The testing decision is to assert public results, persisted state, and external
dispatch counts, not private helper names. Reuse the current memory/JSON adapter
tests and existing usage/preload failure fixtures. Keep one caller migration per
commit. No wire-schema, billing-policy, persistence-ID, or framework migration is
part of this sequence. A shared plan catalog and altered telemetry-failure
semantics require a separate decision after the characterization evidence exists.

Interview and issue publication are intentionally deferred: this is an optional
plan based on verified integration findings, no remote is configured, and the
request does not authorize an external issue write.

## Feature backlog, outside the refactor

The local admin design still requires seven HTTP endpoints, query/metrics/alert
modules, a generated frontend client, and the frontend itself. Follow the
existing approved admin backend/frontend plans as separate feature increments
after A3/A4. Each implemented endpoint should join the canonical contract and
tests in the same increment. A merged branch is not evidence that this feature
is complete.

Record `ActivityEvent`, `AccountControl`, `AdminAuditEvent`, and any agreed
operation/outcome terminology in `docs/Ubiquitous.md` when implementing B1.
Add an ADR only for a substantive interface or compatibility decision.

## Final verification and rollback

After the applicable units, run the canonical `task check`, explicit admin
enabled/disabled tests, source and packaged-extension smoke, lifecycle tests,
and service-backed local tests for affected storage behavior. Report skips and
environment limitations explicitly; the fresh supplemental review is not a
replacement for these release gates.

Use separate commits for integration fixes and structural refactors. Revert a
structural unit without reverting its prerequisite bug fixes. Preserve source
branches while restoring lost implementation. Worktree deletion, publication,
and deployment are separate actions, not completion criteria for this plan.
