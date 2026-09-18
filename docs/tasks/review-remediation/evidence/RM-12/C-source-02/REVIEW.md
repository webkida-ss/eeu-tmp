# Independent Astra source review: one correction required

Reviewer rm03_security_rereview verified all six source hashes and the increment.
Numeric-only synchronous replay now uses the bounded error path. Enforced and
synchronous local fallback preserve canonical winners through repository fences;
the full-private-response finalization-retry regression is meaningful.

High finding: known usage retained only in shadow_evidence_retry_usage on a page
record is invisible to shared usage reclaim. After lease/expiry, marker-only
reclaim can seal floor13 before the worker recovers known17. Make numeric evidence
atomically visible to usage reclaim and test expiry/reclaim before worker retry.
The parent selected the durable-only canonical promotion port in the contract.
No runtime acceptance or release approval is granted by this read-only review.
