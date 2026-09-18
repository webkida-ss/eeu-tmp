# ADR 0005: Separate accounting evidence from private response retention

Status: Accepted for RM-11A; shadow publication integration remains pending.

## Context

The private result record previously served as evidence that a provider request
had incurred cost. Expiring that response could make later reclaim treat the
operation as unused, or permit recovery to issue another provider request.

## Decision

Embed versioned, minimal accounting evidence in the durable usage operation.
Persist first-dispatch authorization before provider work. Retain only the
operation's existing account, month and rate context, execution kind, usage
completeness and whitelisted numeric counters. Private responses keep their
separate retention policy and are never reconstructed from accounting evidence.

New operations explicitly begin without dispatch. Legacy missing evidence remains
unknown. All operation mutations share the JSON file lock or Dynamo conditional
version boundary. Reclaim additionally checks expiry and execution ownership in
the same atomic mutation. A fresh execution cannot reuse an earlier dispatch
marker as authorization; multiple calls within one authorized execution share a
thread-safe permit.

Complete measured evidence settles once. Incomplete evidence preserves the higher
of the pinned estimate and known cost, together with known token counters. Later
partial evidence cannot reduce known bounds or erase incompleteness. Deleting a
private result neither clears accounting evidence nor authorizes another dispatch.

## Alternatives and tradeoffs

Keeping private responses indefinitely would retain unnecessary private content.
A second durable receipt store would introduce another identity and consistency
boundary. Operation-embedded evidence reuses the existing atomic settlement.

Unknown legacy operations without surviving trustworthy evidence stay unresolved
instead of being silently released. This change does not migrate live history or
add automated receipt cleanup. Accounting recovery cannot recover an expired
private response and may return an uncertain-result failure after settling cost.

## Evidence

[RM-11A acceptance](../tasks/review-remediation/evidence/RM-11/A-runtime-03/REVIEW.md)
records independent source review and 977 passing backend tests, with mocked
providers and a faithful Dynamo transaction fake in a network-denied container.
