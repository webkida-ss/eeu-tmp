# Independent RM-09A review

Reviewer: rm03_security_rereview, Astra/high, runtime read-only. Changes required
before B. All nine frozen files and diff SHA-256
752f9eb99a0234834bc5346a7c0cc0742c13d2ccd13065239f72f5cf4dbe5d3d
verified. Canonical receipt: lint/format and 857 tests passed, 6 skipped,
33 subtests, exit 0. No tests or provider calls executed by reviewer.

1. High: all adapters accept stale pending snapshots with the same operation ID.
   A legacy/webhook upsert can erase durable creation-attempt/session evidence.
   Preserve current pending data in legacy writes; enforce immutable request and
   monotonic evidence in explicit CAS transitions. Test all adapter interleavings.
2. High: Stripe history normalization collapses conflicting metadata and client
   reference identities; service filtering can ignore known-customer conflicts.
   Preserve and validate every ownership signal and operation metadata. Test
   actual SDK normalization/pagination, not only pre-normalized service fixtures.
3. Medium: email is absent from the immutable request. An account email change
   alters provider arguments on retry under the same key. Persist and reuse it.
4. Medium: saved URLs are reused indefinitely and pending identities cannot be
   replaced. Add authoritative terminal reconciliation and conditional replacement
   only after terminal proof; local expiry alone is insufficient.
5. Medium: Dynamo index conditions require a new owner_user_id field absent in
   legacy indexes that store ownership inside document. Add an atomic verified
   upgrade path and actual old-shape fixtures, including collision/remap checks.

Parent assigned these corrections to the original Terra implementer. B/C remain
unstarted. Prior passing tests do not establish the missing cases. No release
approval or live duplicate cancellation/refund is authorized.
