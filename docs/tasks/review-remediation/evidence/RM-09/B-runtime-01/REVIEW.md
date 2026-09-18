# Independent Astra review: changes required

Reviewed eight frozen files against accepted A and baseline
3c4fae5d2c03e6592ebd1f51debf5c798294a476. Runtime read-only review;
all source hashes and receipts verified. Increment SHA-256:
8fbe31f97a5c9ef3c54523af89514f7fd172d0e55de7f20b83db72b67ff6086a.

1. Medium: stripe_billing.py removes accepted A's subscription_data.metadata.
   Retrying an existing idempotency key changes provider arguments. Restore the
   exact accepted A request and compare complete requests in a replay fixture.
   The parent and implementer incorrectly inferred that A lacked this field;
   B-compat-red's absence assertion is an invalid oracle. Historical evidence is
   retained without rewriting it. This review supersedes EVIDENCE.md's claim
   that all compatibility failures were resolved.
2. Medium: billing_flow.py protects differing subscription IDs only for existing
   active/trialing status. Unresolved past_due/paused/incomplete/unpaid or unknown
   resources must not be replaced by another resource without terminal proof.
   Include unrelated historical canceled subscriptions in regression fixtures.
3. Medium: a mocked CAS failure without a competing write does not establish
   simultaneous handler safety. Add separate adapters and controlled retrieval
   barriers with a real revision conflict and fresh retrieval, bounded history
   eviction replay, and malformed/unsupported active snapshots.

Revision-before-retrieval, fresh retrieval after conflict, and atomic snapshot
plus event-history writes are sound statically. Ownership checks, metadata-free
legacy binding, and terminal revocation without plan/period are present.
Canonical lint/format and 886 tests passed, 6 skipped, 33 subtests; focused 105
passed. These valid receipts do not close the three findings. C is unreviewed.
No provider calls, runtime execution, edits, or release approval by the reviewer.
