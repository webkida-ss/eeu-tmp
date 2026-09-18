# RM-09A legacy adoption closure

Narrow two-file correction relative to independently reviewed A-runtime-01.
Other seven billing sources are unchanged from that frozen checkpoint. Exact
historical session evidence now allows legacy reuse and terminal reconciliation
without operation metadata, while checking that metadata additionally if present.
Regression fixtures cover repeated open reuse, proven terminal replacement and
mismatched/missing historical session evidence. No B/C changes.

Canonical lint:backend, format:backend:check and test:backend:unit passed in the
same credential-free network-disconnected container: 869 tests, 6 skipped,
33 subtests, final exit 0. No host application execution or real provider calls.
Frozen source/diff/receipt hashes are recorded. A-runtime-01 remains immutable.
Independent narrow Astra acceptance is required before B. No release approval.
