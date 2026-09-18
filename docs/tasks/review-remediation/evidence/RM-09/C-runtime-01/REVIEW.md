# RM-09C correction review: changes required

Independent Astra verified 18 frozen sources and increment. Finite/provenance
resolution, explicit consumer mode, immutable origin/customer-result evidence,
cross-mode conflict and saved mock-result recovery look sound statically.

Medium: cancellation committed during provider creation or before activation
reread can be overwritten. The helper receives the already-canceled current
revision and writes active successfully. Revision equality alone is not a
cancellation fence. The existing regression cancels inside CAS and covers only
a stale revision. Add durable operation-specific cancellation protection and
tests canceling before activation reread, while preserving an explicitly new
checkout after an earlier cancellation. No additional bounded review findings.

Canonical lint/format passed. Runtime: 903 passed, 1 failed, 6 skipped,
47 subtests; exit 201. The new worker mode test incorrectly treats a tuple of
patch context managers as one manager; fix its fixture syntax. No C acceptance.
Reviewer executed no runtime, edits or provider calls. No release approval.
