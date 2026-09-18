# ADR 0003: Durable billing reconciliation and finite entitlement

Date: 2026-09-14
Status: Accepted for local implementation; deployment remains separately approved.

## Context

Review findings R01–R03 identified duplicate checkout risk, stale lifecycle events
overwriting current subscriptions, and paid access without a finite expiration.
Provider calls and local persistence cannot share a transaction. Notifications
can arrive out of order, and historical records lack some modern identity fields.

## Decision

Persist an account-owned checkout operation and its immutable provider request
before provider creation. Retain its idempotency key and ambiguous creation
evidence across retries. Reconcile provider history before a second purchase;
missing, partial or conflicting evidence requires reconciliation rather than
automatic cancellation or another sale. All subscription adapters use revision
compare-and-swap with atomic customer-index ownership.

Verified lifecycle events identify the resource to retrieve. Read local revision
before fetching the current provider subscription, then atomically write the
validated snapshot and bounded event history. A revision conflict requires fresh
retrieval; an old event body never supplies the entitlement update. Replaying an
event evicted from retained history still retrieves current provider state.

Resolve paid access through one shared rule: catalogued paid plan, active/trialing
status, valid finite period and the existing one-day renewal grace. Missing or
malformed legacy expiry falls back to Basic. Valid finite legacy Stripe records
remain compatible. Explicit mock provenance permits local activation only in
configured mock mode, and all HTTP/worker consumers receive that configured mode.
Pending provider origin prevents a mock URL being reported as a Stripe purchase.
Mock recovery uses operation-specific revision evidence so cancellation cannot
be rebased into a new permission to activate an old attempt.

## Alternatives considered

Timestamp-only webhook ordering cannot establish current provider state and is
ambiguous for equal timestamps. Merging event payloads retains stale fields.
Blind same-key retry beyond provider retention can create another purchase.
Treating local timeout or missing history as proof of cancellation is unsafe.
Allowing absent expiry for all providers leaves missed notifications capable of
granting permanent access; inferring mock permission from stored data alone
survives an unintended switch to real billing.

## Consequences

Ambiguous historical purchases may require support intervention. No automatic
live migrations, refunds or cancellations are introduced. Deployment must retire
old checkout writers before exposing the revised flow. Real provider integrations
remain unverified here: tests use isolated fake SDKs and repositories.

Implementation contract and exact acceptance evidence are maintained in
[RM-09](../tasks/review-remediation/RM-09-CONTRACT.md) and
[the final review](../tasks/review-remediation/evidence/RM-09/C-runtime-03/REVIEW.md).
