# RM-14 account-scoped activity and phrase persistence contract

Parent Astra preparation with independent Astra source tracing, September 14.
RM-12 and RM-13 acceptance remain prerequisites. This document does not report
implementation or runtime acceptance for R20/R23.

## Activity deduplication

Use (user_id, source_id) at both JSON and memory persistence boundaries. Preserve
the existing operation:operation_id:status source string format so existing
persisted events remain compatible. A service-only account prefix is insufficient:
direct repository callers require the same isolation. Update the repository
protocol to state this scope. Same-account replay returns its original event
unchanged; another account with the same source gets its own event. Activity
remains telemetry and does not change usage enforcement or authorization.

Regression oracles: the same operation UUID and terminal status produce two
events for two accounts in each adapter; per-account queries remain isolated;
same-account replay preserves one original event. Load and reopen legacy-format
JSON events before repeating these cases. Exercise record_terminal_activity,
including quota_blocked, as well as direct repository calls. Correct the existing
test that expects cross-account suppression.

## Phrase saves

Hold the established json_list_lock across read, prepend and atomic replacement.
Resolve the repository path once for both locking and I/O, including supported
symlink aliases. Preserve pre-existing records, prepend order and the trusted
owner argument's override of any caller-supplied user_id. Use the existing UUIDv7
creation flow; no quota check, authentication change, public response change or
Dynamo phrase change belongs to this task.

Regression oracles: pause one adapter after reading while it owns the file lock,
start a second save and prove it cannot acknowledge until the first is released.
Use bounded synchronization and guaranteed thread cleanup. Both acknowledged
UUIDs and pre-existing records must remain exactly once. Cover same-owner,
cross-owner and actual symlink adapters; verify listing isolation and trusted
owner override. Include the reading.create_phrase service boundary.

## Scope and evidence

Use PLAN.md's activity protocol/adapters/service, JSON phrase repository and
focused tests. Reuse the accepted JSON lock without changing its implementation.
Parent executes canonical test:backend:unit, test:backend:admin, lint:backend and
format:backend:check in the credential-free, network-denied container. A separate
reviewer consumes frozen source and receipts before acceptance. No provider
calls, migration, publication or infrastructure action is authorized.
