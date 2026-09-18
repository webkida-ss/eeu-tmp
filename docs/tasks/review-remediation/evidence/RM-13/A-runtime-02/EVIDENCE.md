# RM-13A conditional identity runtime checkpoint

Three frozen sources and increment are against the accepted pre-RM13 snapshot
in /private/tmp/untangle-remediation-20260914/rm13-base. Auth uses existing store
transaction interfaces; the shared Dynamo store is unchanged. Two fixture stores
model conditional transaction behavior, including all-or-none writes, contention,
identity consistency, nonconditional failure and UUIDv7/session TTL regressions.

Canonical format:backend, lint:backend, format:backend:check, test:backend:unit
and test:backend:admin passed. Unit: 918 passed, 6 skipped, 47 subtests. Admin:
102 passed. Final exit 0. Source, increment and receipt hashes are recorded.
Earlier A-runtime-01's 917/102 receipt predates malformed-error refinement.

Parent ran all checks in the credential-free network-denied owned container
using fake Dynamo only. No host application execution or live AWS calls.
Independent exact-source final review remains required. JSON session subunit B
has not started; this checkpoint does not imply release or deployment approval.
