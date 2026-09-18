# ADR 0008: Retain usage uncertainty across fallback and recovery

Status: Accepted (RM-12C C-runtime-05).

## Context

A failed provider call can incur cost without returning usage. Successful fallback
responses must not make that whole operation appear completely measured. Failure
settlement also discarded available numeric evidence by substituting only the
reservation, and response-building failure could lose an already measured call.

## Decision

Mark incurred-call uncertainty under the tally lock at the actual provider
invocation boundary. Resolve the client callable and authorize dispatch first.
Later successful responses add measured counters without clearing uncertainty.
Build settlement cost, counters and completeness from one snapshot.

Complete nonzero measurements remain exact. Incomplete measurements retain all
known counters and use max(known cost, pinned reservation floor). Thus known 17
and floor 13 settle 17, while unknown remainder with known 5 and floor 13 settle
13. The reservation is not added again on top of measured cost.

Promote numeric evidence before failure settlement in preload and synchronous
paths. Accounting-only evidence is not a response to replay. Preserve existing
response-bearing private results, finalization fences and immutable shadow
outcomes. A promotion failure must not authorize sealing a lower value while
known evidence is still available; retain a retryable decision when necessary.

## Tradeoffs

Conservative costs are bounds, not claims of exact provider charges. Unknown
legacy evidence remains conservative. If no persistence boundary is writable,
execution cannot claim successful durable accounting. Recovery retains the
existing distinction between accounting evidence and private-result expiration.
There is no provider, public API, pricing-table or quota-policy change.

## Evidence

See [the RM-12 contract](../tasks/review-remediation/RM-12-CONTRACT.md) and
[remediation status](../tasks/review-remediation/STATUS.md) for exact source,
independent review and network-denied runtime receipts.
