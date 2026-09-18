# ADR 0001: Composite Usage Metering

Status: Accepted

## Context

Independent article, chat, token, and cost checks leave a race between checking
and recording. Concurrent Lambda invocations can all pass before any one
writes usage. Provider retries also need a durable distinction between work
that was never dispatched and work whose result is uncertain.

## Decision

Reserve the visible unit (article or chat) and estimated provider cost in one
atomic operation before dispatch. Finalize actual usage after success, release
only known pre-dispatch failures, and conservatively finalize uncertain
post-dispatch attempts.

Each operation has a stable UUID v7 ID and canonical payload hash. The same ID
and hash is idempotent; a different hash is a conflict. Private replay results
have bounded size and retention, with DynamoDB TTL on `expires_at_epoch`.
Execution leases allow one provider owner and support lease recovery after a
crash. Pending preload/result states are repaired without provider re-dispatch.

Quota periods are UTC calendar months. The first operation creates a pinned
snapshot of limits, model, tokenizer, rate card, and rates. Upgrades may
ratchet capacity upward; a downgrade is deferred to the next month.

The hidden cost policy exposes only article/chat used, pending, remaining,
reset date, and warning state. Raw tokens, micro-USD, model, and rate values
remain server-side.

Rollout is a shadow migration: deploy records, TTL, observability, and tests
with `USAGE_RESERVATION_ENABLED=false`; enable only after staging concurrency
verification. Operational recovery uses idempotent repository transitions and
structured events, never direct counter edits. Shadow mode persists a hidden
monthly cost total, and compatibility counters remain synchronized with
committed counters, so enabling or rolling back enforcement does not reset or
undercount the active month.

## Alternatives considered

- Check then record after success: simple, but oversubscribes under concurrency.
- Separate cost and visible-meter reservations: can partially succeed and
  requires compensation.
- Charge estimates permanently: safe for cost, but unfair when actual usage is
  lower.
- Unlimited replay retention: easier recovery, but retains private results
  unnecessarily.

## Consequences

The design adds reservation, settlement, lease, replay, and repair states.
Atomicity and conservative uncertainty handling protect quota and spend, while
idempotency makes retries safe. Operators must monitor blocked/reserved/
finalized/released/reclaimed events plus lease and pending-result recovery.
