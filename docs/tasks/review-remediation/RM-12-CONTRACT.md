# RM-12 processing and usage consistency contract

Parent Astra design decision during the September 14 manual continuation,
incorporating independent Astra source tracing. Implement only after RM-11 is
accepted. Review the following units in order; R08/R21/R22 are not accepted by
this preparatory document.

## A: one effective monthly processing allowance

Resolve sentence and source-token allowances from the maximum of the current
plan and the account's retained caps for the applicable current month. Reuse
that decision for entitlement display, source preparation, cost estimation,
reservation metadata and worker delivery. Carry the accounting month with it.
Retries of an existing operation retain that operation's pinned month and caps;
they must not reinterpret an older payload under new limits. New-month and
other-account requests do not inherit another snapshot's retained allowance.
Upgrades take effect immediately. Do not change monthly quota semantics or
grant paid entitlement based solely on a historical processing allowance.

Add backend/services/usage_meter.py to PLAN.md's existing RM-12 owner paths:
its current-plan/reservation interface participates in this decision. Prefer a
single explicit resolver over independent calculations at display and execution
boundaries. Keep RM-09's configured-provider and finite entitlement rules intact.

Regression oracle: establish Pro usage, downgrade to Basic in the same month,
then assert displayed limits, prepared content, estimator inputs, persisted
operation/preload caps and actual delivered output agree. Exercise sentence and
source-token boundaries separately. Cover month rollover, another account,
upgrade and a retry of an operation pinned before the plan change.

Selected interface: an EffectiveProcessingAllowance value carries month, sentence
cap and source-token cap. A shared resolver reads the guard's account/current
month and takes the retained/current-plan maximum. UsageMeter resolves an existing
operation's pinned allowance first; otherwise it uses this shared resolver. Pass
that explicit allowance from preparation into reservation instead of recalculating
it at each stage. Current article/chat/cost admission and paid entitlement remain
independent of the retained processing caps. The existing operation fields can
carry this decision without changing public contracts or repository storage.

Independent review identified three integration requirements. Reconcile prepared
content with the canonical operation returned by reserve before handing off any
content; a concurrent same-ID winner can pin different caps/month. Legacy
operations missing cap fields must not receive zero-cap preparation before a
valid terminal replay. Prefer retained preload context or canonical replay over
adopting the current upgraded plan, and document unresolved legacy behavior.

Shadow creation must retain processing-only monthly caps as well. Parent approves
the narrow JSON/Dynamo start_shadow extension: atomically retain the maximum
sentence/source caps with operation creation, without plan_id, article/chat/cost
limit ratchets, admission checks or reserved aggregate increments. Existing
same-operation replay keeps its original decision. This is processing allowance
retention, not paid entitlement or quota reservation. Test both adapters and the
public durable-shadow downgrade/month/account paths.

## B: propagate the explicit sentence allowance

The pipeline's inner finalization, tool handler, chunk preparation and mechanical
fallback impose a default 200-sentence cap independently of the outer allowance.
Propagate the explicit allowance through those paths, or leave inner validation
uncapped and enforce the authoritative allowance at the correct output boundary.
An outer merge cannot recover sentences already discarded. Preserve verbatim
validation, deduplication, lower-plan bounds and existing unmetered defaults.

Regression oracle: 250 unique short sentences in one chunk with Max's allowance
of 300 survive real one-shot, agent fallback and mechanical fallback paths.
Stub provider responses rather than the splitter under test. Basic and Pro
limits must still hold. Use focused pipeline/splitting tests.

## C: retain uncertainty from an incurred failed call

At the provider-call boundary, mark usage incomplete under UsageTally's lock
when a dispatched call raises. Successful fallback and analysis responses add
measured usage without clearing that uncertainty. Pre-dispatch client setup,
preflight and dispatch-marker persistence failures do not imply an incurred
provider call and must not acquire incurred-call uncertainty.

RM-11's durable settlement boundary must carry measured usage plus the sticky
uncertainty before publication. Define the cost arithmetic explicitly in the
implementation evidence. Use a conservative floor consistent with the pinned
reservation policy, retain all known measured cost, and never charge the entire
reservation again on top of measured cost merely because uncertainty exists.
Zero measured tokens are not proof of no dispatch. Preserve idempotent recovery
and outcome-specific accounting established by RM-11.

Regression oracle: provider timeout after dispatch, then successful fallback
and analysis, through the actual preload workflow. Assert sticky incompleteness,
measured later tokens and conservative durable cost exactly once. Include
concurrent response aggregation, known cost above the reservation, replay, and
pre-dispatch client/preflight/marker failures.

## Scope and evidence

Use PLAN.md's preload, entitlement, usage repository, pipeline and reading-support
paths plus the usage-meter seam above and focused tests. No public API change,
provider calls, infrastructure or historical migration is authorized. Parent
executes canonical lint:backend, format:backend:check and test:backend:unit in the
credential-free, network-denied container. Independent Astra review consumes
frozen source and receipts. Keep each unit's implementation, runtime result and
acceptance distinct in STATUS.md.

### C failure-path ownership clarification

Independent Astra tracing confirmed that retaining sticky uncertainty also needs
narrow changes in services/preloading.py and services/synchronous_execution.py.
Parent approves those paths within R21: persist known numeric tally evidence before
failure settlement instead of replacing it with the reservation alone. Include
response-building failure before private-result persistence. Preserve existing
lease/version fencing, canonical winners and outcome-specific article counters.
Do not refactor the recovery state machine or reopen prepared shadow decisions.

Use one snapshot to derive counters, completeness and conservative cost. The
incomplete cost is max(known measured cost, pinned reservation floor); complete
measured cost remains exact. For example, known 17 with estimate 13 settles 17,
not 13 or 30. Verify lower-than-floor, fully measured, failed-preload and synchronous
response-building paths as well as the successful fallback case. TTL expiry and
replay must not call the provider or change settled numeric evidence.

### C durable-only promotion correction

Independent review found that page-only numeric retry context is invisible to
shared usage reclaim: a marker-only operation could settle the lower floor after
expiry before the worker retries. Parent approves the minimal repository seam
`record_dispatch_usage`: kind and numeric usage only, promoted on the canonical
operation through existing JSON lock / Dynamo evidence-version CAS. Add this to
UsageRepository, JSON and Dynamo adapters and UsageMeter, reusing existing
validation. It must not store a private response or touch its TTL.

Use canonical numeric promotion before preparing a shadow outcome when private
result storage fails. A page-only copy is not proof of durable accounting. Verify
both adapters and expiry/reclaim before worker retry with known17/floor13. Preserve
prepared/finalized winners, privacy, version fences and all RM-11 quota semantics.
If all canonical accounting writes fail, do not claim durable completion.
