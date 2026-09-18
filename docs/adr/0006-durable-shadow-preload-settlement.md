# ADR 0006: Settle shadow preload usage before publication

Status: Accepted, RM-11B.

## Context

Shadow preload accounting used independent article, token and cost increments
after ready publication. A failure or replay between those writes could lose or
duplicate usage. Private-result expiration also removed the recovery evidence.

## Decision

All new shadow preloads use an explicit durable accounting mode on the existing
account/operation identity. Creation pins month, payload and rate context without
quota reservation or reserved aggregate effects. The preload owns its durable
meter; synchronous disabled callers retain their existing behavior.

Persist dispatch evidence before provider work. Validate a complete private result
and the page adapter's publication representation before preparing success.
Preparation persists an immutable outcome and minimal numeric usage separately
from private-response retention. Settlement atomically applies operation, event
and monthly effects. Only then publish ready. Failures after incurred work retain
cost and known tokens without counting a successful article.

Complete priced measurements remain exact. Incomplete or unpriced evidence retains
the higher of the estimate and known cost with known token counters. Once an
outcome is prepared, subsequent dispatch or completion reports fail explicitly
before acknowledgment; they cannot mutate or silently replace that decision.

Recovery uses the prepared decision or retained validated result before provider
work. Expired private content cannot authorize another provider call. A previously
settled success can become an unavailable-result display without changing its
accounting. Transient recovery metadata is excluded from publication size, and
the adapter owns size validation. Content cleanup remains conditional on RM-10
ownership and separate from accounting. Observation logs have no additive effects.

## Tradeoffs and scope

Old terminal shadow records remain readable. Old in-flight records without trusted
durable evidence fail closed; no live migration invents historical usage. The
prepared decision deliberately seals late evidence instead of reopening settled
accounting. This change covers preload readiness, not every legacy synchronous
shadow path. No background service, infrastructure or public contract is added.

## Evidence

See [remediation status](../tasks/review-remediation/STATUS.md) for the final exact
source, independent review and canonical network-denied container receipts.
