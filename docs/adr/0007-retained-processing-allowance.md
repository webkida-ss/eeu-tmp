# ADR 0007: Carry one retained processing allowance through execution

Status: Accepted, RM-12A.

## Context

The billing display retained a month's higher sentence and source-token caps,
while preload preparation still used the current plan. A downgrade could therefore
advertise content limits that execution did not honor. Independent reservation
and preparation decisions could also diverge during retries and concurrent calls.

## Decision

Represent the accounting month and both processing caps as an explicit effective
processing allowance. New work uses the maximum of current-plan and same-account,
same-month retained caps. Persist processing-only maxima for shadow creation too;
this does not grant paid entitlement, quota limits or reserved usage.

Existing operations retain their authoritative month and positive caps without
requiring the old plan to remain resolvable. Legacy operations use complete saved
preload context or the validated pinned plan when caps are missing; unavailable
context fails explicitly rather than adopting a later plan. After a reservation
race, reprepare and reestimate from the original extracted input using the winning
operation's allowance before handing content to the worker.

The billing display, preparation, estimator, persisted operation and worker all
consume this decision. New months and other accounts do not inherit it. Current
paid entitlement and monthly admission remain separate decisions.

## Tradeoffs

The resolver adds a retained-usage read for new processing. Rebuilding input after
a concurrent reservation costs local CPU but avoids delivering differently capped
content under the same operation. There is no historical migration or public API
change. Existing unknown legacy context remains an explicit recovery limitation.

## Evidence

See [the RM-12 contract](../tasks/review-remediation/RM-12-CONTRACT.md) and
[remediation status](../tasks/review-remediation/STATUS.md) for exact source,
independent review and isolated runtime receipts.
