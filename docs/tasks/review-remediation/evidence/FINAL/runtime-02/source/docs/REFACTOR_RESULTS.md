# Reading Lifecycle Refactor Results

Date: 2026-09-08 (JST). Base: `6113f9c37936f7e7b4a6ef8e8180164d0030cb7c`.
Branch: `codex/reading-refactor`.

## Scope and integration status

The user authorized implementation of Phase B of the
[consolidation refactor plan](CONSOLIDATION_REFACTOR_PLAN.md). This branch includes
the earlier repair commit and preserves all original branches and worktrees.
At the initial handoff, local `main` remained at `26de968`. The subsequent
user-authorized continuation completed the remaining checks and integrated the
candidate locally; see [final integration results](INTEGRATION_RESULTS.md).
No remote, push, deployment, release approval, or branch deletion is part of
this work.

Implementation is complete. Final validation and independent review evidence
from the initial handoff are recorded below. The subsequent validation-input
change resolved the offline Lambda/provider-registry limitation without skipping
checks; the linked final results supersede the initial blockers.

## Implemented units

| Unit | Interface and responsibility | Preserved behavior |
| --- | --- | --- |
| B1 | `TerminalActivityOutcome` and `record_terminal_activity` in the existing activity module | Source identity, first-write semantics, null versus zero usage, sanitized metadata, and distinct operation/telemetry failure handling |
| B2 | `SynchronousExecution` owns replay, execution claims, heartbeat, dispatch evidence, durable results, and settlement | Selection/chat entry points, response contracts, one dispatch per acquired claim, replay without another charge, and uncertain-dispatch accounting |
| B3 | `preloading` owns submit/worker orchestration; `reading_queries` owns status/vocabulary projections | Preload cancellation/recovery, profile invalidation, inline/SQS interface, legacy records, ordering, and 30-preload/600-item bounds |
| B4 | A service-free backend/Terraform default-consistency test | Existing basic/pro/max limits and deployment/environment override interfaces |

`reading.py` remains the compatible public entry point. Its orchestration now
delegates to cohesive modules; shared hashing/usage/logging helpers live in
`reading_support`. The preload lifecycle deliberately does not reuse the
synchronous coordinator: ownership, cancellation, and pending settlement remain
different workflows. Repository adapters, persisted documents, UUID7 generation,
contracts, plan limits, and product behavior were not redesigned.

Selection analysis did not produce admin activity in the baseline, so it still
does not. The plan's suggested selection-event migration was corrected rather
than interpreted as permission to add events. A shared plan catalog was not
introduced: the consistency guard addresses the demonstrated drift risk without
adding a new build/deployment dependency. Its parser supports the repository's
current literal Terraform defaults, not general HCL expressions.

Three bounded characterization/extraction tasks used Luna: terminal activity,
query projections, and configuration consistency. The parent implemented the
coordinator and caller migration, executed tests, and retained responsibility for
the integrated result. Independent reviewers did not implement or execute tests.

## Initial verification

Runtime checks use the existing credential-free Linux development container with
no attached networks, mock identity/billing, JSON storage, inline jobs, and dotenv
isolation. Managed Chromium uses ephemeral profiles and local fixtures. There
are no provider API calls or production credentials.

New characterization tests cover unknown versus zero activity cost, snapshot
fallback/retry, original failure preservation, same-source replay, user isolation,
legacy ready records, projection metadata, vocabulary bounds/order, one dispatch
per context, result replay, and backend/Terraform default agreement. Existing
concurrency, lease, settlement failure-injection, handler, and contract tests
remain the primary behavioral evidence; private test patches moved only where
their implementation moved. The recovery-log test now uses the coordinator's
public interface.

During implementation, existing privacy coverage caught a changed exception
context: recording a telemetry failure inside a provider-error handler could
include the original provider error in the log traceback. The original
outside-handler ordering was restored before final verification. No new logging
policy or error-suppression behavior was introduced.

All canonical Task commands used `./scripts/bootstrap.sh --exec task`.

| Check | Result |
| --- | --- |
| Agent configuration/integrity, online/deploy/workflow policy | Pass; 20, 7, 96, and 14 tests respectively |
| Workflow lint, dev-container validation, formatting and lint | Pass |
| Canonical schema/generation drift | Pass with admin disabled and enabled |
| Default-mode API contracts | 46 passed |
| Admin-enabled authorization/learner/contract compatibility | 102 passed |
| ZIP build/dependency closure | 8 passed, 14 subtests passed |
| Backend coverage suite | 789 passed, 6 admin-disabled skips, 33 subtests passed; 83% coverage |
| Extension coverage suite and automation static contract | 170 passed and 1 passed |
| Source-extension and exact packaged-ZIP browser smoke | Both passed |
| Article extraction fidelity | 18/18 fixtures match managed Chromium |
| Concurrent runs, diagnostic-write failure, and SIGTERM cleanup | 3 passed |
| Complete `task check` | Exit 201 at Lambda dependency download under network denial; downstream Terraform steps not reached |

The fidelity command initially lacked `CHROME_BIN`; it passed after explicitly
selecting the already provisioned managed Chromium. No code changed for that
environment correction. A TestClient/httpx deprecation warning remains. Final
logs are retained locally in the ignored `output/refactor/` directory:
`check.log`, `browser-initial.log`, and `browser-extra.log`.

The code/test snapshot reviewed and tested has SHA-256
`588bb4e9d9f8fc67085b659dfb75965ad1d2f30a33d4b5938ddd20dfdc4f96fc`.
It was frozen against the base commit before narrative plan/results updates.
Independent correctness and security reviewers inspected that exact snapshot
and the parent-owned verification evidence without executing tests or changing
files. Neither found an introduced actionable defect. These advisory reviews
are not release approval.

The security review also identified unchanged residual risks: preload failure
logs may contain a URL or raw exception, and activity source deduplication does
not include the user ID. These existed in the base and were not changed as part
of the extraction. Evaluate them separately, including migration consequences
for source identity, rather than silently changing observable behavior here.

## Initial acceptance limits and resolution

- Lambda package construction/import checks and Terraform lock/validate checks
  subsequently passed using pre-provisioned inputs and unchanged isolation.
- The four service-backed DynamoDB Local integration cases subsequently passed
  in an isolated loopback namespace, with no skipped cases.
- Managed Linux Chromium is not the normal macOS Chrome user-gesture/unpacked
  reload flow. Repeat that release-oriented check when preparing a release.
- The unfinished admin endpoints/frontend remain a separate feature backlog.
