# RM-13 identity and session atomicity contract

Parent Astra preparation, September 14, 2026. RM-05 and RM-09 must be accepted
before implementation. Review A independently before assigning B. Scope is local
source and service-free evidence; no real accounts, sessions or cloud records
may be migrated, merged or revoked by this task.

## A: conditional first-login identity creation

DynamoEmailAuthService currently writes the normalized-email index and profile
separately after a pre-read. Replace first creation with one transaction that
requires both keys to be absent. The email claim and UUIDv7 profile are all-or-none.
The existing unconditional put_documents_atomically is insufficient; use the
store's transaction boundary or a narrowly scoped conditional helper without
altering other callers' semantics. backend/storage/dynamodb_store.py may be
extended for this explicit seam after checking concurrent ownership.

An actual conditional claim conflict re-reads the winning index and matching
profile consistently, then issues a session for that identity. Do not treat
transport errors, malformed records, permissions errors or an orphan index as
ordinary contention. Missing/mismatched winner data fails safely with a bounded
outcome; never overwrite the index to repair it automatically. UUID collision
must not overwrite an existing profile. Preserve configured session expiry from
RM-05 and existing display-name behavior without changing account identity.
Both ordinary lookup and conflict recovery must validate that index user_id
equals profile id and that the normalized profile email matches the requested
email before issuing any session. A mismatch must not issue a session or change
records; test both paths, including a profile containing another user's ID.

Tests must interleave two independent service instances at the creation boundary
against a faithful fake transaction: one email index, one profile and sessions
that resolve to the same user. Assert actual generated transaction conditions and
all-or-none behavior, conditional conflict recovery, dangling/malformed index,
and non-conditional failure propagation. Existing TTL cases remain mandatory.

## B: one session-file mutation boundary

All JSON session writers must use the same canonical path lock across read,
filter/append and replace: login insertion, logout, expiry cleanup invoked by
resolve_user or login, and administrative bulk revocation. Reuse json_list_lock;
remove redundant independent lock layers when safe. Use locked wrappers with
explicit unlocked helpers or pure filtering to avoid nested flock acquisition.
Atomic file replacement alone is not a read-modify-write lock.

Keep token, user and expiry compatibility. Corrupt session data must not be
silently rewritten as an empty successful revocation. Path aliases resolving to
the same file must coordinate. Canonicalize the path for reads and atomic
replacement as well as locking, or reject unsupported aliases: replacing a
symlink pathname can otherwise split the store. Test an actual symlink alias.
No private token values appear in task evidence.
Do not extend this change into historical account merging or authentication UX.

Tests use separate adapters and controlled competing operations, not a mocked
lock call. Pause login around its read and attempt logout; after both complete,
the old token remains revoked while an acknowledged new token is preserved.
Interleave expiry cleanup with administrator bulk revocation and reactivation;
revoked tokens must not reappear through a stale write. Assert bounded completion
to detect deadlocks and preserve unrelated users' sessions. Suspension controls
remain authoritative; this task addresses stale session resurrection, not a new
cross-store transaction for concurrent identity verification and suspension.

## Evidence

Owner paths and acceptance follow PLAN.md RM-13, including focused auth, session
and administrator tests. Parent executes test:backend:unit, test:backend:admin,
lint:backend and format:backend:check in the credential-free network-denied
container for each subunit. Astra independently reviews frozen sources and
receipts. Live Dynamo semantics remain unverified; no external integration is
implied. Preparation does not mark either finding implemented or accepted.

A also owns backend/test_uuid7_domain_ids.py solely to update its independent
fake store for the conditional transaction API while retaining UUIDv7 assertions.
There is no non-atomic fallback for old fakes or production stores.

Independent Astra preparation review identified ordinary-lookup identity checks
and canonical I/O through symlinks. Both requirements above were incorporated.
