# RM-10 submission ownership contract

Parent Astra preparation, September 14, 2026. Implement only after RM-09 is
accepted. Scope is PLAN.md RM-10; preserve C's configured-provider wiring.

Add a repository create-if-absent boundary keyed by user and preload operation
identity. It returns the winning record and whether this caller created it.
A stale initial record must never replace processing leases, ready results,
failure states, enqueue evidence, or latest-page ownership of an existing ID.
The same user's same operation must have matching immutable payload identity;
otherwise return a conflict without dispatch or accounting mutation.

JSON must hold the shared file lock across read/condition/write, coordinated
with every writer of that preload file. Refactor unlocked private helpers as
needed to avoid nested independent flock acquisitions in existing save/claim/
finish paths. A process-local RLock alone is insufficient. Dynamo initial ID
creation and its latest-page index write form one conditional transaction.
Condition failures read the winning ID consistently; unexpected failures must
propagate, not masquerade as an ordinary losing submission. Existing legacy
page-index-only records must not be overwritten by an assumed-absent ID.

This includes initial create/save, mark/confirm enqueue, claim, finish and lease
renewal. Fake Dynamo must exercise the actual two-item conditions and consistent
winner read. Cover claim_processing's legacy direct-ID materialization path;
its existing unconditional save(make_latest=True) can also replace an index.

Only the winning creation may enter initial enqueue/error cleanup. A losing
submitter returns or uses the existing bounded recovery path for the winner;
it must not reset state, release the winner's usage reservation, overwrite or
delete its transient content, or enqueue a finished/running winner. Pay special
attention to submit_preload's existing exception handler: mark-enqueue failure
is not proof that provider/job dispatch never happened elsewhere.

Keep the durable reservation's operation and payload identities aligned with
the preload record. Claiming ownership before transient content persistence
requires an explicit recoverable handoff state; do not expose a runnable job
whose content is not available. Avoid solving a stale record overwrite by
introducing an unrecoverable crash gap or deleting another owner's content.
Ambiguous enqueue delivery retains existing retry/reconciliation semantics.

Compare canonical payload hash, normalized URL and learner-profile fingerprint
for an existing operation before touching content or changing its accounting.
The existing atomic idempotent reservation may establish accounting identity;
an initial-record loser cannot treat its replay as ownership to release it.
If using a content-pending handoff state, mark-enqueue and worker claim must reject
it until content persistence succeeds, and owner failure/recovery must be bounded.
Record the chosen handoff protocol before implementing its transitions.

Required tests pause B after lookup, let A start and separately finish, then
resume B. Verify A's record, lease/result, content and reservation survive and
no duplicate provider work is dispatched. Use two JSON adapters plus a faithful
fake Dynamo transaction with conditions; include winner failure and loser
cleanup paths, conflicting payloads and unrelated user IDs. Synchronization
must have bounded waits so a locking regression fails rather than hanging.

Parent runs canonical lint:backend, format:backend:check and test:backend:unit
inside the network-denied container and freezes source/receipts for independent
review. No live Dynamo, new infrastructure, background service or data migration.
RM-11 accounting durability remains a separate ordered task.

## Ordered implementation units

Implement A (persistence primitives and focused adapter tests), review it, then B
(submission/handoff integration and adversarial workflow tests). R05 is accepted
only after both are integrated. A must not claim that unused primitives fix the
submission workflow. This subdivision keeps the state-machine change reviewable.

A adds create-if-absent and token-conditional content handoff ownership to both
preload adapters. New records use a non-runnable content-pending state, opaque
UUIDv7 handoff token and bounded expiry. Recovery may claim an expired handoff
only for the same immutable operation/payload identity. Token-conditional ready
and failure transitions prevent stale owners from dispatching or releasing
another owner's reservation. Ordinary enqueue/worker claims reject pending
content. Existing legacy ready/processing records retain their meaning.

Additional approved path: backend/storage/preload_content_store.py and focused
content-store tests. Add conditional create without changing existing put callers
until B integrates it. Filesystem publication must be complete and atomic (for
example, a flushed temporary file plus exclusive hard-link publication), not an
exclusive open that exposes a partly-written final file. Existing content is
never overwritten. S3 conditional PutObject uses IfNoneMatch="*"; 412 means an
existing object, while 409 or other failures must not masquerade as successful
existing-content recovery. Tests use SDK fakes; no S3 calls or IAM changes.
[AWS conditional write behavior](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html).

B uses request.operation_id uniformly in reservation and shadow modes. It must
validate matching content on an existing conditional-create result before marking
ready. Persisted readiness, not local write success, authorizes enqueue. Same-ID
losers return the winner or claim an expired pending handoff; they cannot enter
creator cleanup. Release needs a successful token-conditional failure transition.
Specify late-owner writes and private-content retention in B before integration;
conditional creation alone cannot stop re-creation after a worker deletes content.
No new background service or indefinite private-content retention is authorized.

The shared DynamoDbStore and JSON lock helper are not assigned to A: use their
existing transaction/lock interfaces inside the owned adapters to keep RM-13A
disjoint. Escalate a necessary helper change to the parent before editing it.

## B private-content retirement decision

Independent Astra design review selected operation-key tombstones over
token-specific content keys, which would leave uncollected filesystem payloads.
Add a scoped retire operation to the content store: atomically replace private
content with an empty distinguishable nonprivate tombstone. A retired key reads
as unavailable content and is never valid matching-content recovery. Filesystem
tombstones remain and prevent a paused conditional publication from recreating
private content after the worker finishes. Do not change legacy put/delete
callers until B deliberately migrates the authorized preload paths.

Only the valid worker or a successful token-conditional terminal failure may
retire content. Losing submitters cannot do so. Retirement is idempotent and its
failure retains retryable cleanup through existing recovery paths; do not report
successful physical cleanup merely after logging an error. Test a paused old
publication resumed after winner completion/retirement, stale-owner cleanup and
no readiness/enqueue or reservation release from the old owner.

S3 retains its existing one-day lifecycle policy; it expires tombstones as well
as bodies. An arbitrarily delayed straggler after tombstone expiry can recreate
an object, which remains subject to existing lifecycle cleanup. This is not an
exact physical deletion deadline or a permanent S3 fence. No lifecycle/IAM change
is authorized; report this limitation honestly and test fake tombstone expiry.
Nonprivate filesystem tombstones do not authorize indefinite private-body storage.

Integration clarification: do not introduce new shadow accounting at submission;
its durable accounting redesign belongs to RM-11B. After content readiness,
enqueue failure needs an atomic exact-owner transition from processing with no
worker lease into failed_pending_release. If a worker or another owner advanced
the record, return its current state and retain its reservation. Persist recovery
state before idempotent release; acknowledge terminal failure and retire only
after release succeeds. A losing worker's unconditional finally block is not
authority to retire content. Small owned-adapter transition extensions are
allowed to express these boundaries; unconditional save is not a substitute.

Integration review clarification: superseded cleanup must use the actual atomic
claim's prior-state evidence, or execution/result recovery before release. A
stale processing observation cannot authorize releasing a subsequently reclaimed
running operation. Released reservations with abandoned running preload leases
also need conditional expired-lease recovery and content retirement; preserve
active lease owners. A shadow cache shortcut validates the actual candidate
returned after concurrent lookups, not only an earlier absent ID snapshot.

Never-started eligibility also requires trustworthy creation/claim provenance:
previously claimed work can return to processing after failing to acquire an
execution lease. Missing or invalid legacy attempt metadata is not proof of no
dispatch. Evaluate all eligibility predicates at the atomic claim boundary and
include them in Dynamo conditions. Transient claim evidence must not be copied
into persisted result records. Unknown or previously claimed work uses normal
execution/result recovery instead of superseded release.

Additional narrow fixture path: backend/test_admin_chat_activity.py may assign
a distinct UUIDv7 for an intended new analysis that previously reused a fixed
operation ID. Preserve actual same-operation replay assertions; no activity
implementation change is authorized here.

Independent Terra preparation review identified the explicit writer list,
payload identity, content-pending recovery and legacy materialization cases;
the parent incorporated these requirements without waiving dependencies.
