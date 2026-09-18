# RM-09A complete-history correction

Two frozen files and incremental diff relative to A-runtime-02. Exact saved
session/operation validation no longer narrows the relevant history used for
multiple-open and subscription-state safety checks. New fixtures cover adopted
S1 alongside open S2, and terminal S1 alongside completed/active S2. Other billing
sources remain unchanged from A-runtime-01. No B/C implementation.

Parent canonical lint:backend, format:backend:check and test:backend:unit passed:
871 tests, 6 skipped, 33 subtests, exit 0. Execution used the same credential-free,
network-denied owned container. No host application runtime or real provider calls.
Exact source, diff and receipt hashes are supplied for narrow independent Astra
closure of A-runtime-02/REVIEW.md. No release approval.
