# RM-10B first integrated runtime checkpoint

Seven exact sources retrieved from the tested container; increment uses accepted
pre-B source in the parent snapshot, with the new workflow test added. Parent
ran canonical format:backend, lint:backend, format:backend:check and
test:backend:unit with PYTEST_ADDOPTS selecting the three preload test files.
Formatting/lint passed; 105 tests and 9 subtests passed, 7 tests failed.

Failures include a real early replay return preventing expired handoff takeover,
and enqueue admission failing to reject the new failed_pending_release status.
Existing put/save injection fixtures and unconditional enqueue-error release
oracles also need the new conditional persistence and ambiguous-dispatch rules.
Corrections are assigned; no test acceptance or R05 completion is claimed.

Execution used the credential-free network-denied owned container, mock providers
and local files/fake storage only. Source is fixed for preliminary independent
review while the owner repairs the known failures in the active working tree.
