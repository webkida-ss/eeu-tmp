# RM-09B review correction and runtime checkpoint

Three frozen files supersede B-runtime-01's corresponding sources; the other
five B files remain unchanged there. Increment is against B-runtime-01.
B-runtime-02 is the preformat static checkpoint; format-only.diff establishes
the line wrapping and indentation corrections after its narrow static review. Do not attribute
this runtime receipt to the unformatted checkpoint.

Accepted A's full provider request, including subscription_data.metadata, is
restored. The corrected replay test asserts every SDK argument. Earlier B-compat-red
absence expectations were incorrect and remain historical, as documented in
B-runtime-01/REVIEW.md. Differing terminal resources cannot replace nonterminal
tracked subscriptions, and differing nonterminal resources require reconciliation.

Two adapters now perform a real revision race with bounded synchronization: a
stale active snapshot loses to canceled state, retrieves again, and commits the
current canceled snapshot. Actual bounded-history eviction/replay and malformed
active snapshot regressions supplement the existing lifecycle cases.

Parent canonical format:backend, lint:backend, format:backend:check and
test:backend:unit passed: 891 tests, 6 skipped, 40 subtests; exit 0.
All execution used the credential-free, network-denied, mount-free owned
container and fake providers. No external providers or host application runtime.
Independent Astra acceptance of these exact sources remains required; C has not
started. No release approval is implied.
