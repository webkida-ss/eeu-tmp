# RM-09C final attempted-operation cancellation fence

Two frozen sources supersede C-runtime-02's flow and account tests. Worker test
remains C-runtime-02; other 15 C sources remain C-runtime-01. Increment compares
these two files with C-runtime-02. Original attempted fence is retained across
retry, and superseding cancellation is checked before redispatch. New regression
cancels immediately before created-state CAS: one provider call, old operation
terminal, no mock activation. All three prior cancellation timings remain tested.

Canonical format:backend, lint:backend, format:backend:check and test:backend:unit
passed: 907 tests, 6 skipped, 47 subtests; exit 0. Source, diff and receipt hashes
are recorded. Runtime uses the credential-free network-denied owned container
and fake providers, without host application execution or external calls.
Independent exact-source final C acceptance remains required; no release approval.
