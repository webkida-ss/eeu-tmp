# RM-09B compatibility reproduction

Parent ran focused pytest against B-source-01 production and the added compatibility
fixtures inside the credential-free, network-disconnected container. The exact
test source was recovered from that container before any corrected source transfer.

Result: 4 failed, 1 passed, 98 deselected; exit 1. Failures reproduce same-key
request drift, missing legacy metadata with known customer index, first verified
checkout reference binding, and terminal revocation with no plan/period. The
conflicting ownership control passes. These are intended behavior failures, not
missing imports or setup errors. Source and receipt hashes are recorded.

Parent dispatched the bounded corrections under RM-09-CONTRACT.md's compatibility
clarification. GREEN canonical tests and independent review remain required.
