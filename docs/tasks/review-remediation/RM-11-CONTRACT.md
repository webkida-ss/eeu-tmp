# RM-11 accounting durability contract

Parent Astra design decision during September 14 manual continuation. This is
preparation for PLAN.md RM-11, not permission to implement ahead of accepted
RM-09/RM-10 dependencies. Implement and independently review A before B. Preserve
all accepted checkout/index changes on the shared Dynamo adapter path.

## A: durable dispatch and settlement evidence

Private response retention and accounting retention are separate. The existing
preload dispatch callback persists its marker through save_result, whose private
response TTL is also swept before JSON reclaim and may be deleted natively by
Dynamo. That record must not remain the only proof of incurred cost.

Persist minimal accounting evidence outside private-result TTL, either on the
durable operation or in an account/operation-owned receipt with no response TTL.
Retain operation identity, accounting month, pinned rate/reservation context,
dispatch evidence and sufficient measured/conservative settlement data. Do not
copy article text, prompts, model responses, email or access tokens into receipts.

New operations must distinguish explicit no-dispatch evidence from unknown legacy
state. Persist the dispatch transition before any provider call; failure to persist
must prevent dispatch. Evidence is monotonic: a retry, old snapshot, result cleanup
or expired execution lease cannot restore no-dispatch or erase incurred cost.
The shared repository also receives synchronous article/chat dispatch markers
from services/synchronous_execution.py through UsageMeter.save_result. Preserve
durable evidence for those callers as well, preferably within the shared result
persistence boundary. If an explicit caller change is necessary, document and
assign that small synchronous-execution seam before editing it.
Provider calls remain outside locks. Concurrent repository instances must share
the JSON lock or Dynamo conditional/transactional boundary, not only a local lock.

On reclaim, expired private content is not proof of no dispatch. Use durable
measured usage when complete; otherwise preserve conservative cost according to
the pinned reservation and the existing incomplete-usage policy. An unresolved
legacy operation lacking both a result and explicit no-dispatch evidence remains
unknown and cannot be silently released as unused. Record this compatibility
tradeoff; do not rewrite or migrate live historical records.

Settlement and aggregate effects must be idempotent for the account/operation.
Keep evidence until durable settlement is established, and retain enough terminal
identity to prevent replay from settling again. This task does not authorize an
automatic receipt cleanup or a new background service. Private response cleanup
continues to remove private content according to its existing policy.

Durable evidence also governs service recovery before the next reservation
reclaim. An expired private response must not let a queued worker or synchronous
retry dispatch again merely because its response lookup is empty. Accounting-only
recovery does not restore the deleted private response. Response completion is
separate from usage completeness; malformed or incomplete usage never becomes
measured zero. A stale dispatch marker cannot downgrade completed evidence or
silently authorize another provider attempt.

Required regressions: dispatch then crash, expire private response and reservation,
simulate native Dynamo TTL deletion, reclaim through two repository instances and
verify conservative/actual accounting once. Include pre-dispatch failure, missing
legacy evidence, concurrent reclaim/finalization and failure of the marker write.
Assert receipt fields contain accounting metadata only.

## B: durable shadow accounting before publication

Shadow mode disables quota reservation enforcement, not accounting durability.
The current path publishes readiness before separate article/token/shadow-cost
writes; observe_shadow logs and swallows an aggregate-write failure. Replace that
success-path dependency with an idempotent, account/operation-owned settlement
boundary. Keep observability separate from the durable decision to publish.

Persist pending shadow settlement data before final readiness. Pin operation ID,
accounting month, measured token/article increments, cost/rate context and usage
completeness. Apply its applicable article, token and shadow-cost effects together
with an operation settlement receipt under the repository's atomic boundary.
Do not implement three independently retryable additive writes. Repeated delivery
or recovery must acknowledge the same settlement without incrementing it again.

Publish ready only after accounting succeeds. A crash after settlement but before
publication must repair publication from the receipt without another provider
call or another charge. A failed accounting write leaves recoverable pending
work and a retryable failure; logging alone cannot acknowledge success. Preserve
the existing meaning of failed/pre-dispatch outcomes and shadow's non-enforcing
quota behavior. Do not convert shadow into paid admission control.

A's durable pre-dispatch evidence also applies to shadow operations, including
crashes before pending-result persistence. Accounting recovery must not depend
on a successful ready result: provider failure, result-too-large rejection,
failed-result replay and loss of publication ownership must retain incurred
measured or conservative cost. An early return from an unsuccessful publication
cannot skip settlement. Preserve outcome-specific article/token increments while
settling incurred cost once; failed operations need not count as successful
articles. Add explicit shadow regressions for each of these boundaries.

Use RM-10's submission identity and ownership boundary. Private result expiry
must not remove pending shadow settlement evidence. Unknown provider usage must
remain distinguishable from measured zero and must not be erased by successful
fallbacks; RM-12 will improve propagation through the remaining pipeline seams.

Required regressions: fail around pending evidence, aggregate settlement and final
readiness, then replay. Cover concurrent handlers and duplicate requests, month
boundaries, same IDs under different accounts and private-result TTL deletion.
Prove every real operation's accounting is retained once, with no successful
ready result permanently bypassing it. JSON and faithful fake Dynamo coverage
are required; live providers are not authorized.

## Scope and evidence

Use PLAN.md RM-11 ownership: usage repository/adapters, preload workflow and
usage-meter seam, plus focused service-free tests. Internal typed state/ports may
be extended as necessary; do not change public contracts, provision infrastructure,
introduce another source language or run data migrations. Document any additional
necessary ownership seam before editing it.

Each subunit requires canonical lint:backend, format:backend:check and
test:backend:unit in the credential-free, network-disconnected container, followed
by independent Astra review of frozen source and receipts. No host runtime,
credentials, AWS/Stripe calls, publication or deployment. Implementers cannot
approve their own work. This document records a design contract, not completed
implementation or acceptance.

Independent Astra design review identified the unsuccessful-publication shadow
gap above. Parent incorporated the explicit dispatch/failure/replay/ownership
requirements before implementation. No dependency or runtime gate was waived.

## Existing regression fixtures

Read-only Terra preparation identified test_usage_repository.py's reservation
factory, JSON lifecycle cases and _MemoryDynamoStore as the primary reusable
fixtures. They already support transaction failures, consistent reads, barriers
and direct native-item deletion. Extend faithful conditions only when needed by
the new atomic evidence boundary. Add independent-instance reclaim and private
result deletion cases to these fixtures rather than another approximate store.

Separate explicit no-dispatch new operations from unknown legacy fixtures;
do not blanket-rewrite every old missing-result expectation. Assert actual
accounting and event effects once, retained minimal metadata and absence of
private response data. Existing synchronous-execution tests should exercise
marker persistence failure before provider invocation and recovery after private
response expiry. Any change to disabled/shadow execution belongs to ordered B
unless A needs a shared compatibility adjustment explicitly documented first.

## A selected implementation design

Independent Astra design review supports operation-embedded accounting evidence.
Reuse the durable operation's existing account, month and pinned rate context;
add a versioned dispatch state, kind, strictly typed minimal numeric usage and
separate usage-completeness metadata. New reserve explicitly records no dispatch;
missing legacy fields remain unknown. JSON uses the shared lock. Every Dynamo
operation writer uses the same evidence-version fence together with operation
state and applicable expiry conditions, reloading after a conflict.

Shared save_result promotes accounting evidence before private response storage.
Dispatch promotion is first-dispatch authorization, not a reusable permit;
stale markers cannot authorize another call or regress completed evidence.
Completion-storage failure retains the prior dispatched evidence and blocks
successful publication. Release requires explicit persisted no-dispatch evidence
in the same atomic mutation; renewal and settlement preserve newer evidence.
Reclaim applies measured complete usage or a conservative floor no lower than
the pinned reservation and known partial cost. Conflicting kind/context fails
closed; legacy trustworthy result evidence may support settlement, while missing
evidence cannot support release.

Private get_result remains private-only. The narrowly approved
services/synchronous_execution.py recovery seam, its tests and preload recovery
inspect operation evidence before redispatch even when no reclaim ran yet.
An accounting record must not be presented as a recovered private response.

UsageTally invokes its dispatch callback for every provider call, including
concurrent analysis chunks. Preserve legitimate multi-call execution using a
thread-safe once-per-execution authorization closure at the owned service/meter
seam. Only a successful durable first promotion opens subsequent calls through
that same closure. A fresh execution cannot reuse persisted dispatched/completed
state as permission. Failed or ambiguous promotion must not set the local permit.
This integration does not require changing RM-12's pipeline uncertainty logic.

## B selected implementation design

Reuse the account/operation identity and A's evidence state machine with an
explicit persisted shadow accounting mode. Missing legacy mode remains enforced.
Shadow creation pins month, payload and pricing context without admission checks
or monthly reservation increments. Every inherited mutation must handle that mode
explicitly or reject it; an estimated cost floor is not a reserved aggregate.

Add explicit durable-shadow configuration to UsageMeter for preload integration.
Existing synchronous disabled callers in reading.py remain unchanged in this
bounded R07 task; this work does not claim all synchronous shadow paths are durable.
Their legacy observability must not be used by the new preload settlement path.

A validated, durably stored pending private result establishes successful analysis
and one article. Provider failure or an oversized result establishes failure and
zero successful articles. Persist the selected outcome and minimal settlement
data on the operation before applying aggregate effects. Prepare and settle are
separate retryable boundaries; aggregate effects, terminal operation and event
are atomic. A conflicting later worker cannot overwrite the prepared outcome.
Numeric usage is derived from canonical durable evidence, preserving partial
bounds and conservative cost when usage or pricing is uncertain.

Use existing pending-usage preload statuses with explicit accounting mode/version.
Settlement precedes final readiness. Failed settlement leaves pending work; a
crash after settlement can repair publication once. Lost publication ownership
does not permit content cleanup or outcome replacement, and does not erase
incurred accounting. Expired private content cannot reconstruct a response:
recover accounting and return a bounded unavailable-result failure without another
provider dispatch, preserving any already prepared or settled article count.

Old terminal shadow records remain readable without migration. Old in-flight
records lacking trustworthy durable evidence must fail closed, not invent a new
no-dispatch receipt. Missing rate calibration remains explicit uncertainty rather
than measured zero. Tests cover these transitions, inherited-mode fences,
concurrent conflicting outcomes and account/month isolation.

The page repository's actual serialized-size boundary must be checked before
immutable success accounting. Parent authorizes the narrow validate_publication
port on PagePreloadRepository and its existing JSON/Dynamo adapters. Dynamo uses
the same normalization and validation as finish_processing; JSON does not inherit
an artificial Dynamo ceiling. The service must not duplicate adapter constants
or serialization formulas. Preserve RM-10's identity and conditional ownership
behavior. Test the actual page adapter limit separately from private-result limits.
