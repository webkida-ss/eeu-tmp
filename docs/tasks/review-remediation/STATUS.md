# Review remediation status

Updated: 2026-09-15. All 27 findings implemented, independently reviewed and accepted.

Current outcome: 14 of 14 tasks complete; no unstarted remediation, runtime
blockers or pending independent reviews. Canonical task check and separate managed
extension smoke both passed. Changes are preserved on the local remediation
branch; Git history is authoritative for the commit state.
[Final evidence](evidence/FINAL/runtime-02/EVIDENCE.md) and
[independent final acceptance](evidence/FINAL/runtime-02/REVIEW.md).
Historical checkpoints below do not describe outstanding work.
Plan: [PLAN.md](PLAN.md).
Baseline: `3c4fae5d2c03e6592ebd1f51debf5c798294a476`.
Current remediation branch: `codex/review-remediation`.
Active owners: all implementation/review ownership is released. Final evidence is
persisted; no further remediation execution is pending. RM-09 A/B/C is accepted.
RM-04 is accepted and extension ownership is released. Docker API now responds.
The owned container was started with its existing network-denied, mount-free
configuration. RM-04 and RM-09A canonical checks and reviews are complete.
No duplicate scheduled work should start.
User explicitly authorized a new one-time continuation for September 14, 2026
04:15 Asia/Tokyo if unfinished. App creation and persisted settings confirm
heartbeat untangle-remaining-fixes-at-04-15 was ACTIVE on this task. It fired at
04:15:16 JST and was set to PAUSED at the eligible start; app confirmation and
persisted settings were verified. Reject duplicates and do not add another date.
Older reservation paragraphs below remain historical.
Follow [the renewed scope and contract](RESUME-2026-09-12.md).
Historical run limits below are superseded by the user's renewed authorization.

Midnight heartbeat `untangle-review-fixes-at-midnight` fired at 2026-09-11
00:00 JST. Because work remains, the same heartbeat was successfully updated
to a single continuation at 2026-09-11 05:30 JST, named
"Untangle review fixes at 05:30". No second automation was created.
The single continuation has now fired; no additional run was scheduled.

| Task | Implementation | Independent review | Owner | Evidence |
| --- | --- | --- | --- | --- |
| RM-01 | accepted | prior static PASS + independent final runtime PASS | released | [static review](evidence/RM-01/midnight-01/REVIEW.md), [runtime closure](evidence/ENV-02/runtime-final/REVIEW.md) |
| RM-02 | accepted | static PASS + combined RM-03 runtime reviewed | released | [static review](evidence/RM-02/midnight-01/REVIEW.md), [combined receipt](evidence/RM-03/runtime-01/REVIEW.md) |
| RM-03 | accepted | Astra production/runtime PASS + Terra final test PASS | released | [production/runtime review](evidence/RM-03/runtime-01/REVIEW.md), [final test coverage](evidence/RM-03/runtime-api-01/REVIEW.md) |
| RM-04 | accepted | Astra source/runtime PASS; 190 unit, package and browser checks PASS | released | [acceptance](evidence/RM-04/runtime-02/REVIEW.md) |
| RM-05 | accepted | Astra security PASS + final backend runtime PASS | released | [security review](evidence/RM-05/continuation-02/REVIEW.md), [explicit final acceptance](evidence/RM-05/final-closure/REVIEW.md) |
| RM-06 | accepted | Astra security PASS + combined workflow/runtime reviewed | released | [security review](evidence/RM-06/resume-02/REVIEW.md), [combined receipt](evidence/RM-07/runtime-02/REVIEW.md) |
| RM-07 | accepted | Astra source and runtime PASS | released | [runtime review](evidence/RM-07/runtime-02/REVIEW.md), [build gate](evidence/RM-07/runtime-build-01/REVIEW.md) |
| RM-08 | accepted | Astra source/helper/native runtime PASS | released | [native closure](evidence/RM-08/native-01/REVIEW.md) |
| RM-09 | accepted | A/B/C independent Astra PASS; C 907 tests PASS | released | [C acceptance](evidence/RM-09/C-runtime-03/REVIEW.md) |
| RM-10 | accepted | A/B Astra PASS; 959 unit / 102 admin PASS | released | [B acceptance](evidence/RM-10/B-runtime-04/REVIEW.md) |
| RM-11 | accepted | A/B Astra PASS; B 1014 unit / 102 admin PASS | released | [B acceptance](evidence/RM-11/B-runtime-05/REVIEW.md) |
| RM-12 | accepted | A/B/C Astra PASS; C 1050 unit / 94 subtests PASS | released | [C acceptance](evidence/RM-12/C-runtime-05/REVIEW.md) |
| RM-13 | accepted | A/B Astra PASS; 940 unit / 102 admin plus final focused PASS | released | [B acceptance](evidence/RM-13/B-runtime-02/REVIEW.md) |
| RM-14 | accepted | Astra PASS; 1057 unit / 102 admin PASS | released | [acceptance](evidence/RM-14/runtime-02/REVIEW.md) |

Docker engine availability is restored at this manual invocation. The bounded
API ping returned OK; the owned container is running with networks={} and mounts=[].
Frozen RM-04/source-02 and RM-09/A-source-03 hashes matched before transfer. First
canonical lint checks passed; formatting found three files requiring standard
formatting before tests. No host runtime workaround or external provider calls.
Fourteen tasks and all twenty-seven findings are accepted at their individual
checkpoints. Final combined task check and managed extension smoke both passed
and received independent Astra acceptance. RM-09 checkpoints are A-runtime-03,
B-runtime-03 and C-runtime-03, with final 907 tests and independent Astra PASS.
RM-11 and RM-12 parent contracts are prepared with independent Astra design
review clarifications incorporated. RM-10 and RM-13 contracts were also prepared
and reviewed; no implementation began ahead of dependencies.
Historical counts below describe
earlier checkpoints. Do not execute application tests on the host as a workaround.
Preserve all existing strategy/review documents.

Historical RM-10B first integrated checkpoint passed lint/format and 105 focused tests, with
7 failures. Known corrections cover expired handoff takeover, failed-pending
enqueue rejection, and old fixture/error oracles. Independent Astra additionally
identified shadow identity validation, shadow failed-handoff cleanup replay and
terminal recovery cleanup gaps. These are now closed by B-runtime-04, which
passed 959 unit / 102 admin tests and independent Astra source/runtime review.
Parent preserved pre-B runtime, failed fixtures and exact tested source packets.
RM-14's independent preparation is also captured in RM-14-CONTRACT.md.

Historical RM-11A first checkpoint passed lint/format and 190 focused tests / 21 subtests,
with seven failures. Transition/legacy fixtures, conservative failure labeling,
partial usage preservation and Dynamo reclaim-versus-renew ownership were
corrected in A-runtime-03. Independent test review also strengthened deterministic winner-order,
boundedness, privacy and aggregate-counter oracles. The corrected source received
its own runtime checkpoint there: 977 tests and independent Astra PASS. R06 is
accepted. Subsequent B-runtime-05 passed 1014 unit and 102 admin tests with
independent Astra acceptance, closing R07 and RM-11.

## September 14 evening manual recovery

The user requested another resumption. At 19:56 JST the bounded Docker API probe
returned OK. The owned container was stopped; parent started only that container
and verified networks={}, mounts=[], vscode user, cap-drop ALL/no-new-privileges.
Pinned dependencies and provider caches remained available. No new provisioning,
credential access or real provider calls were needed.

RM-04 passed 190 unit tests, package 8 tests/14 subtests and final smoke twice
after scoped persistence, local storage echo and fixture corrections. Independent
Astra accepted runtime-02. RM-09A passed final 871 backend tests and independent
Astra accepted A-runtime-03. Its pending purchase/idempotency finding is resolved.

RM-09B introduced authoritative current subscription retrieval and atomic event
deduplication/revision updates. B-runtime-01 freezes eight files against accepted A
with 886 canonical tests passing. Independent review found three issues. Parent's
earlier claim that A lacked subscription_data metadata was incorrect: frozen A
proves it was present. The associated absence test was a bad oracle, now being
replaced alongside identity and real concurrent-handler coverage corrections.

B-runtime-03 supersedes that historical checkpoint: all three findings closed,
891 canonical backend tests passed, independent Astra accepted B. C-source-01
has conservative finite entitlement and explicit provider wiring. Initial C
tests exposed ten legacy fixture failures; independent review identified a saved
mock-session cross-mode replay issue, and parent identified mock activation
recovery. Terra is correcting C; neither C nor RM-09 as a whole is accepted yet.

The consumed 04:15 heartbeat remains PAUSED. No new time was scheduled. All earlier
runtime receipts remain historical and are not attributed to newer source versions.

## September 14 04:15 continuation

Actual clock confirmed 04:15:30 JST, so this was the eligible invocation. No other
implementation or review owner was active. The bounded read-only Docker API probe
returned no bytes and timed out after 10.010 seconds (exit 28). No tests ran and
no application source changed. No daemon/user container was stopped or restarted.

RM-04 source-02 and RM-09A source-03 source/diff hashes still match their frozen
manifests; git diff --check passed. Accepted counts remain seven tasks / thirteen
findings. The remaining runtime gates and subsequent narrow review are unchanged.
Do not repeat source-only billing review or start dependent B/C work in place of
the missing container evidence. Docker engine recovery requires user attention;
no further automatic continuation has been scheduled and no reset was consumed.

## September 13 completed runtime checkpoints

Dedicated container `untangle-remediation-mrxkdp53` ran these checks with networks={},
mounts=[], UID1000, cap-drop ALL and no-new-privileges. Dependencies were prepared;
Docker was available for these receipts, before the later engine timeout.
ENV-01 source-manifest correction passed independent
review and 8 regressions. Backend collection corrections passed static review.
After separately preparing hash-verified public tokenizer data, backend unit tests
passed; the latest RM-09A checkpoint has 857 tests, 6 skipped, 33 subtests.
Extension unit tests passed 188, package tests passed 8 tests/14 subtests, and
managed-Chromium smoke passed. RM-03 account-switch fixes are accepted. RM-04
independent review found a legacy-key panel selection writer. Its scoped correction
and real UI regression passed static re-review; their runtime checks remain pending.
RM-07 passed 119 deployment-policy tests, workflow security/online tests and lint,
then offline Lambda build and 2 real arm64 package tests. The build required adding
missing secret_resolver.py to its existing source allowlist. Independent Astra
review accepted the correction and remaining build gate. No deployment occurred.
RM-08 helper corrections passed independent review and 845 backend tests. Separate
public dependency preparation supplied the hash-verified locked Linux provider,
as recorded in RM-08-CONTRACT.md. Native provider guards passed all 11 cases;
infra:validate passed dev and prod. No lockfile changed. The small native fixture
and set-equality correction passed independent Astra review; RM-08 is accepted.

The prior automation file is absent and the older 17:30 slot passed during this
manual run. The user subsequently authorized the new September 14 04:15
continuation recorded above; it does not revive the older reservations.

## Recovery chronology and historical continuation reservations

September 13 manual recovery: the user explicitly restarted Docker and asked
work to continue. Default Docker socket access still fails, but an escalated
read-only listing now succeeds. A dedicated local container
`untangle-remediation-mrxkdp53` is preparing the pinned dependency/toolchain inputs
via the repository post-create workflow; old cached workspace inputs are absent.
Parent records this separate provisioning decision under the renewed request:
public locked dependencies only, no credentials, host mounts or Docker socket;
network is permitted for preparation and must be disconnected before tests.
The container uses vscode UID1000, cap-drop ALL and no-new-privileges. Source is a
filtered copy excluding secrets and local dependencies, refreshed after edits.
At that initial preparation checkpoint no runtime tests had run. Provision log:
`/private/tmp/untangle-remediation-mrxkdp53/provision.log`.

Recovery update: provisioning installed the pinned tools/dependencies/Chromium,
then its source-manifest guard rejected newly installed root node_modules. Parent
added that exact runtime directory to the exclusion contract and a Git/fallback
regression: canonical manifest RED 2 failed/6 passed; GREEN 8 passed, followed by
passing devcontainer:validate. ENV-01 evidence is independently reviewed by Terra.
The container network is now disconnected: networks={}, mounts=[], UID1000,
cap-drop ALL and no-new-privileges. Actual tests have begun. RM-07 deploy-policy
run: 109 passed, 10 failed because its fake-storage fixture directory is missing;
Terra owns that precise test correction. These are runtime failures, not Docker
blockers. RM-03 privacy corrections remain active on disjoint files.

The old automation TOML is absent at the previously recorded path. Its app view
renders a card but provides no model-visible current fields. This manual run is
active across the final 17:30 slot; do not create a duplicate or add another date.
No 12:00 execution is recorded in the available status/evidence. Earlier reservation
claims below are historical until current app state can be resolved.

Historical app confirmation: same automation ID `untangle-review-fixes-at-midnight` was ACTIVE with a simple
direct reservation for September 13, 2026 12:00 JST. At that eligible window's
start, advance it to the final authorized time: 17:30 JST.
Pause at 17:30 before that window's work, or when all work is accepted.
The later reservations depend on prior invocations advancing the heartbeat.
Consumed: September 13 01:00 JST (started 01:00:04 JST) and 06:30 JST (started
06:30:05 JST). The app confirmed the 12:00 update before implementation.
Reject duplicate 01:00/06:30 wakeups.

06:30 starting shared account usage: five-hour 9% / weekly 33%; no reset consumed.
Docker listing was checked once and failed with permission denied; no retries or
host test fallback. Required runtime evidence remains separate from source
authoring and independent static review. Fresh bounded Terra/high implementers
`rm03_regressions` and `rm07_regressions` finished disjoint test authoring and
released ownership. Independent Astra/high review of frozen resume-03 diffs by
`rm03_security_rereview` and `rm07_review` completed. The RM-07 follow-up
test correction is saved as resume-04. All ownership is released.

01:00 environment check: Docker listing again exited 1, permission denied.
No repeated retries or host test fallback. Starting shared account usage was
five-hour 21% / weekly 19%; no reset consumed. Source correction/review continues
under the renewed authorization; runtime acceptance remains blocked.

Scheduling correction: at September 12 21:00:33 JST, the multi-time rule
delivered an unexpected early wakeup. The cause is unverified. No implementation,
tests or agents were started and no future window was consumed. The app confirmed
replacement with the simple 01:00 rule and sequential continuation prompt.
Reject subsequent early/duplicate wakeups using actual JST time and this log.

## September 13 06:30 checkpoint and next actions

- RM-03 added deferred storage and gated browser regressions, then received
  independent Astra review. A High panel account-scope race remains at the
  learner-profile await and unowned cached preload; its smoke has worker/main-world,
  HTTP status, URL-normalization and gate-lifetime defects. Additional clearing,
  readiness/mount and replaced-login coverage remains. The exact next correction
  packet is resume-03/REVIEW.md. Do not call R10/R12/R13 resolved.
- RM-07 review confirms its three prior source corrections. It rejected the
  handwritten workflow test sequence. Terra then changed the harness to load
  actual workflow bodies, preserve environment/directories/arguments, remove fake
  mkdir, and assert failure reasons/drift. Resume-04 needs a narrow independent
  follow-up; do not repeat already-reviewed source absent drift.
- Both current manifests and parent whitespace checks passed. No canonical tests
  ran: Docker listing was denied once. No host workaround or credential use.
- Fully accepted remains 0/14 tasks and 0/27 findings. RM-04 and RM-08 through
  RM-14 are still unstarted (8 tasks/17 findings). [RM-08 contract](RM-08-CONTRACT.md)
  now records the exact permitted Terraform negative-test target and scope;
  its implementation waits for RM-07 static acceptance.
- Final shared usage reached five-hour 100% / weekly 47%. These
  are account-wide percentages, not task token counts; no reset consumed.
- At 12:00, record consumption and advance this same heartbeat to 17:30 before
  work. Recheck the container once. In parallel: assign the precise RM-03 privacy
  and test corrections to Terra, and ask Astra for the narrow RM-07 harness
  follow-up. If clean, advance RM-08 on disjoint files under its recorded scope.
  Freeze and independently review each correction; runtime gates still apply.
- Direct reservation for September 13 12:00 is confirmed. At that start reserve
  the final 17:30 window; pause at 17:30 before work. No added dates or resets.

## September 13 01:00 checkpoint and next actions (historical)

- RM-03 corrections are saved: per-login cryptographic identity, async account
  rechecks, document restoration guards, and stricter cache schema. Tests were
  expanded, including smoke cases, but the gated browser and deferred-storage
  regressions listed in resume-02/EVIDENCE remain unauthored. No re-review yet.
- RM-07 received independent Astra review and three correction categories were
  implemented: precise package object permissions, apply-only ordering assertions,
  and GET identity/encryption validation. The full fake-storage apply restoration
  harness and specified negative cases remain unauthored. No re-review yet.
- Both Terra implementers released ownership. Parent saved immutable resume-02
  diffs/manifests and passed whitespace/hash checks. No application runtime ran.
- Source-prepared tasks remain six; fully accepted tasks remain 0/14 and findings
  0/27. RM-04 and RM-08 through RM-14 remain unstarted (8 tasks/17 findings).
  Parent recorded [RM-09 preparation notes](RM-09-PREPARATION.md); they are not a
  completed billing contract or implementation.
- Final shared account usage reached five-hour 100% / weekly 31% at checkpoint.
  This is account-wide, not this task's token consumption. No reset consumed.
  Stop at this saved boundary; do not start another unit in this window.
- At 06:30, reject duplicates, advance the existing heartbeat to 12:00 before
  work, recheck the container once, then finish the two precise regression gaps
  using Terra on disjoint paths. Freeze and independently re-review before
  RM-04/RM-08. Do not repeat the original audit or all previously clean reviews.
- The same heartbeat already directly reserves September 13 06:30 JST. Preserve
  the later authorized 12:00/17:30 sequence; pause at the final window's start.

## September 12 checkpoint and next actions (historical)

- RM-06 newly has clean independent static review after a regression-harness
  correction. All canonical acceptance remains blocked by Docker access.
- RM-03 source and unit regressions are written; independent review requests four
  race fixes and stricter page_url validation. Its detailed REVIEW.md is the next
  implementation packet. Required browser/panel integration regressions are also
  missing. Do not count R10/R12/R13 as resolved.
- RM-07 source, focused tests and runbook are written; independent Astra security
  review is pending. Do not count R17 as resolved.
- Unstarted: RM-04, RM-08 through RM-14 (8 tasks / 17 findings).
- Previous RM-01/RM-02/RM-05 and new RM-06 represent six findings with historical
  clean static reviews, but shared-path source changes require combined validation.
  Fully accepted tasks/findings remain zero because no canonical runtime ran.
- Next 01:00 window: review RM-07's frozen record/package boundary with Astra;
  concurrently assign RM-03's documented corrections and missing regressions to
  Terra. Re-review corrections before source-dependent RM-04/RM-08 work. Continue
  through remaining tasks as capacity permits, preserving exact checkpoints.
- Current source manifests for shared paths: RM-03 supersedes RM-02 extension
  digests; RM-07 supersedes RM-06 deploy-workflow digest. Earlier diff/review
  artifacts remain immutable historical evidence. RM-01/RM-05 are unchanged.
- Latest observed shared account usage: five-hour 100%, weekly 16%. Five-hour
  reset is 2026-09-13 00:52:53 JST, before the first reservation. Exact per-task
  token consumption is unavailable; no reset credits consumed.
- Parent whitespace check passed. No host tests, external writes, commits or
  deployments. Default and escalated Docker listing failed despite matching
  socket ownership; no filesystem permission or runtime policy was weakened.

## 05:30 continuation decisions

The authorized continuation fired at 2026-09-11 05:30:16 JST. Docker access was
rechecked once: `docker ps --format '{{.ID}} {{.Names}}'` exited 1 with permission
denied at the local Docker socket. G0 and all runtime evidence remain blocked.
Midnight source and diff hashes were verified unchanged; no competing active
remediation owner was found. No host application execution or secret access.

Starting account usage: five-hour 8% used, weekly 95% used. These are shared
account percentages, not task token counts. Bound this continuation to the
independent RM-05 source unit and its Astra security review; defer larger
dependent changes because runtime prerequisites remain blocked and usage is
limited. This is preparatory work allowed by the earlier decision, not acceptance
of RM-01 or any dependent task. No additional run will be scheduled.

## Midnight execution decisions

Docker access rechecked once and failed with permission denied. G0 remains
blocked. No host test execution or credential access is permitted. Source-only
progress is allowed by PLAN; it does not satisfy acceptance dependencies.
After RM-01 source inspection, independent RM-02, RM-05 and RM-06 edits may be
prepared on disjoint files while canonical acceptance remains blocked by RM-01/G0.
This is preparatory work, not a waiver of tests or permission to implement
dependent persistence/security redesigns before their prerequisite acceptance.
Existing strategy/review documents remain untouched.

Actual account usage at 2026-09-11 00:03:56 JST: 55% of the five-hour window and
86% of the weekly window used. These are shared account percentages, not exact
task token counts. No reset credits consumed. Bound this midnight source-only
checkpoint to RM-01 and RM-02; defer further units to the authorized continuation
instead of accumulating larger unverified dependent changes.

## Midnight checkpoint (historical)

- Fully accepted: 0 of 14 tasks / 0 of 27 findings.
- Source prepared with clean independent static review: RM-01 (R04, R27),
  RM-02 (R09), covering three findings. Both still require runtime evidence.
- Not started: RM-03 through RM-14, covering the other 24 findings.
- No implementation commits created. HEAD remains the recorded baseline;
  both immutable diffs and source SHA-256 manifests are linked above.
- Source-only updates span ten files. Unrelated documentation remains preserved.
- If checks require corrections, freeze a new checkpoint rather than overwrite
  the reviewed evidence and have a distinct reviewer assess the resulting diff.
- Once RM-01/RM-02 acceptance is available, proceed in PLAN dependency order;
  RM-03 requires an Astra account/document/generation decision and security review.
- No further scheduling after the authorized 05:30 continuation. Report any
  remaining verification blockers instead of claiming completion.

Final account usage snapshot: five-hour window 100% used; weekly window 93%
used. The five-hour reset is `2026-09-10T20:00:30Z` (2026-09-11 05:00:30 JST),
before the reserved continuation. Percentages are account-wide and cannot be
attributed to this task alone. No reset credit was consumed. Source/evidence
hash verification and parent `git diff --check` passed at final checkpoint.

## Final 05:30 checkpoint

- Fully accepted: 0 of 14 tasks / 0 of 27 findings; runtime evidence is blocked.
- Source prepared with clean independent static review: RM-01 (R04/R27),
  RM-02 (R09), RM-05 (R15/R19), covering five findings.
- Not started: RM-03, RM-04, RM-06 through RM-14 (11 tasks / 22 findings).
- RM-05 fixes both Dynamo factory credential paths and configured session TTL;
  both Lambda entrypoints preserve the shared factories. Tests cover synthetic
  constructor arguments, wiring, persisted expiry, valid-before and expired-at
  behavior. No existing session records were rewritten.
- 18 implementation/test files now differ from baseline, including one new
  untracked test. No implementation commits, external writes or deployments.
- All current checkpoint source/diff hashes and `git diff --check` verified.
  RM-05 continuation-01 remains historical; continuation-02 is authoritative.
- Final shared account usage: five-hour 44% used; weekly 100% used. Exact
  per-task tokens are unavailable. No reset credits consumed.
- The authorized two execution windows are exhausted. No further automation
  was created or re-armed. Resume from this checkpoint when container access
  and usable account capacity are available.

## Duplicate wakeup disposition

At 2026-09-12 06:26:39 JST, the already-consumed 05:30 continuation prompt
arrived again. The saved final checkpoint confirmed that both authorized
execution windows had already run. No remediation, tests or agents were started.
The existing automation was still ACTIVE despite its single-run rule; the parent
set the same automation to PAUSED to prevent further duplicate wakeups. The app
confirmed the update. Task scope and implementation status remain unchanged.
