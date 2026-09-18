# ADR 0009: Separate product measurement, accounting and account erasure

Status: Proposed design, 2026-09-18. No implementation or deployment included.

## Context

The accepted reliability changes provide durable usage accounting, account-scoped
activity and reconciled billing. They do not measure client-rendered first value
or define an account-deletion workflow. Product experiments must preserve these
existing accounting and ownership boundaries.

## Proposed decisions

Use a first-party, allowlisted ProductEventRepository separate from usage and
billing ledgers. Client events describe rendering/actions, while server enrollment
and verified billing facts establish cohorts and payments. Bound queue/storage
behavior and disable collection without impairing reading. Use versioned cost
scenarios before changing prices or advertised allowances.

Coordinate account deletion with a durable job and deletion fence. Confirm no
future recurring charge before reporting completion, retain only justified retry
and policy records, and erase private data through adapter ports. An incomplete
cross-store operation remains resumable and visibly pending. Disabling new intake
does not abandon previously accepted jobs.

## Alternatives and tradeoffs

Reusing the usage ledger for client telemetry would blur authoritative accounting
and untrusted observations. An external analytics SDK introduces another data
processor and infrastructure requirement before this small pilot needs one.
Synchronous all-or-nothing deletion cannot atomically span provider calls, JSON,
Dynamo, object storage and delayed workers; a coordinator adds state but makes
partial failures explicit. Immediate profile removal would destroy the references
needed to resolve uncertain cancellation and may allow account recreation.

This proposal requires storage budgets, privacy/retention decisions, cancellation
and refund policy, replay horizons and adapter inventory before implementation
acceptance. These are not assertions about legal requirements.

## Detail and validation

See [the development design](../strategy/MONETIZATION_DEVELOPMENT_DESIGN.md) and
[product experience](../strategy/PRODUCT_EXPERIENCE_DESIGN.md) for proposed records,
contracts, states, acceptance tests and rollout/rollback. Existing contracts remain
authoritative until a later implementation generates reviewed schema changes.
