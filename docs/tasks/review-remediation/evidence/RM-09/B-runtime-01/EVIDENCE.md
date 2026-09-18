# RM-09B authoritative lifecycle checkpoint

Eight frozen files and incremental diff against accepted A: flow/test_billing
base from A-runtime-03, existing billing ports/providers from A-runtime-01, and
unchanged container/account/manual-contract test bases from repository commit
3c4fae5d2c03e6592ebd1f51debf5c798294a476. Base copies are included. Subscription
adapters are unchanged; they reuse A's atomic revision/index boundary.

Verified events identify resources; current provider snapshots drive entitlement.
The service reads revision before retrieval, conditionally persists snapshot and
bounded event IDs together, retrieves again after conflict and limits retries.
Container wiring supplies the configured plan catalog. Compatibility corrections
preserve A's same-key requests, allow verified legacy owner bindings without user
metadata, and allow terminal revocation without paid-plan/period information.

The RED compatibility receipt is retained separately in B-compat-red. Its four
behavior failures are corrected; the focused billing suite passed 105 tests.
Canonical lint:backend, format:backend:check and test:backend:unit then passed:
886 tests, 6 skipped, 33 subtests, final exit 0. All application runtime used the
credential-free, network-disconnected owned container and fake providers. No host
application execution, real Stripe/Dynamo calls or public API contract changes.

Independent Astra review of B's lifecycle ordering, ownership, deduplication,
snapshot validation, revision races and compatibility remains required. A remains
accepted; C's legacy entitlement resolver/provenance work has not started. No
release approval is implied by this checkpoint.
