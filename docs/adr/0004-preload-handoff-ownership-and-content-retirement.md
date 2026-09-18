# ADR 0004: Preload handoff ownership and content retirement

Status: accepted with RM-10/B-runtime-04; integration evidence tracked in
[RM-10](../tasks/review-remediation/STATUS.md).

## Context

Concurrent submissions can observe the same absent preload, then overwrite one
another's processing lease, result or reservation. Extracted article text lives
outside the preload record, so winning record creation alone is not sufficient:
a crash before content publication would leave an unusable runnable operation.
A delayed content writer can also recreate private text after a worker deletes it.

## Decision

Use the request's immutable account-scoped operation identity for every preload
mode. Initial persistence returns the existing winner or atomically creates a
non-runnable content-pending record. Payload hash, normalized page URL and learner
fingerprint must match before replay or recovery. A bounded token grants one
submitter ownership of content publication; only an expired matching handoff can
be taken over.

Publish content conditionally and validate any existing body against the prepared
canonical content. A conditional record transition establishes readiness before
enqueue. Failure cleanup requires ownership proof and a persisted recovery state
before releasing usage. Ambiguous queue delivery preserves the operation for
reconciliation. A losing submitter or worker cannot release another owner's usage
or replace its record.

On a successful owned terminal transition, persist a retirement-pending marker,
then atomically replace private content with an empty, nonprivate tombstone.
Clear the pending marker only after retirement succeeds. Existing operation
replay retries unfinished cleanup without provider execution. A tombstone reads
as unavailable content and cannot satisfy a matching-content handoff.

## Alternatives

An ordinary overwrite after an initial lookup does not protect concurrent owners.
Conditional record creation without an explicit content handoff leaves a crash
gap. Token-specific content keys avoid some stale writes but leave abandoned
filesystem bodies without an existing cleanup mechanism. Physical deletion of
the stable key lets a delayed conditional writer recreate the body.

## Consequences and limits

JSON writers share the same read-condition-write file lock; Dynamo adapters use
conditional writes and transactions. Content publication is atomic for filesystem
readers and conditional in S3. Provider work and content I/O stay outside record
locks. The implementation adds bounded recovery states rather than a new service.

Filesystem tombstones remain as nonprivate markers. S3's existing one-day lifecycle
also expires tombstones; an arbitrarily delayed writer after that expiry can
recreate a body, which remains subject to the existing lifecycle. This decision
does not promise an exact physical deletion deadline or a permanent S3 fence,
and does not change infrastructure or retention policy.

Durable accounting evidence and shadow settlement ordering remain separate RM-11
work. This decision and its tests do not imply that those findings are closed.
