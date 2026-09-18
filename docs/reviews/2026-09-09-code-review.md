# Current implementation review — 2026-09-09

Status: both planned static-review rounds completed on 2026-09-10.
27 retained findings; application fixes and runtime verification are not completed.

## Review contract and status

User authorized current-code review, with volume/usage-based scheduling and a
single continuation five hours later if needed. No application fixes requested.
Baseline and reviewed source: `3c4fae5d2c03e6592ebd1f51debf5c798294a476`.
This is the sole initial commit, so this is a snapshot audit, not a change review.
The working tree's strategy documents are excluded from implementation findings.

Two rounds are planned. Round 1 covers core customer/product paths; round 2
covers administration, deployment and supporting boundaries. The source inventory
contains about 74,000 lines across backend, extension, contracts, scripts, CI and
infrastructure, including tests and generated content. This is a scope estimate,
not a claim that every line has been reviewed. No exhaustive audit or release
approval is implied by a completed round.

At planning time, account usage reported 3% of the five-hour window and 47% of
the weekly window consumed. These are shared usage percentages, not per-task
token totals. Exact token consumption was not exposed. Splitting was based on
review volume and complexity, not an assertion that the quota was exhausted. At the end of round 1, the
five-hour window reported 100% and the weekly window 62%. This is an account-wide
change from 3%/47%, not an exact attribution to this review. No usage-reset
credit was consumed. The second round remains appropriate for both scope and
available usage.

## Method and verification limits

Three independent correctness reviewers examined billing/auth, usage/preload,
and extension runtime, respectively. A separate security reviewer assessed
billing, identity and browser data-boundary concerns. The parent checked source
paths, cross-layer effects and reported findings. Reviewers made no edits and
ran no tests. Applicable sources include AGENTS.md, docs/BILLING.md, the usage
ADR and OpenAPI contracts; speculative code smells and planned feature gaps
are not reported as implementation bugs.

No canonical runtime check has run in this review. Access to the Docker socket
failed with permission denied, including an approved read-only retry, so the
credential-free, network-denied dev-container execution path was unavailable.
The parent did not fall back to executing potentially networked tests on the
host. R04 below specifically identifies such a test. Findings are static
execution-path analyses; proposed regression scenarios are not passing tests.
Documentation link/whitespace checks are separate from runtime validation.

## Findings: contract and behavior

### R01 — P1: Multiple pending checkouts can create duplicate subscriptions

Source: [billing_flow.py](../../backend/accounts/services/billing_flow.py), lines
37–54; [stripe_billing.py](../../backend/accounts/billing/stripe_billing.py), line 96.
A Basic user can open two Checkout sessions before either webhook creates an
active entitlement. Both pass the check and can create paid subscriptions,
while the application stores only one subscription reference. The documented
already-paid guard does not prevent this in-flight case.

Correction: atomically reserve/reuse a pending checkout per account, with stable
provider idempotency and defined completion/expiry behavior. Regression: overlap
two starts and complete both previously opened sessions; ensure there is only
one billable subscription. Existing tests cover an already-active subscriber.

### R02 — P1: Out-of-order events roll subscription state backward

Source: [billing_flow.py](../../backend/accounts/services/billing_flow.py), lines
114–144. The mismatch guard only handles selected events with a different
subscription ID. A stale `active` event for the same subscription can follow a
deletion and restore access; a stale Pro update can follow Max and remove the
purchased plan. Event identity/order are not retained and updates lack a
concurrency-safe reconciliation boundary.

Correction: reconcile validated lifecycle events with authoritative state and
persist safe deduplication/concurrency handling. A timestamp-only rule is not
necessarily sufficient for simultaneous provider events. Regression: deletion
then older active event, upgrade then older plan event, duplicate deliveries,
and simultaneous handlers. Existing stale-ID tests do not cover these cases.

### R03 — P2: Checkout completion can grant paid access without expiry

Source: [stripe_billing.py](../../backend/accounts/billing/stripe_billing.py),
lines 148–157; [plans.py](../../backend/accounts/plans.py), lines 70–80.
Completion marks the plan active without a period end, and absent expiry is
accepted indefinitely. If lifecycle events are missed or misconfigured,
checkout alone bypasses the documented finite-period safeguard.

Correction: link checkout identifiers first and activate only with a validated
subscription snapshot containing a finite period. Keep intentional mock behavior
separate. Regression: completion without any later lifecycle event must not
leave permanently paid entitlement.

### R05 — P1: Initial preload submissions can overwrite ongoing work

Source: [preloading.py](../../backend/services/preloading.py), lines 417–420;
[JSON adapter](../../backend/repositories/page_preload_repository.py), lines
119–156; [Dynamo adapter](../../backend/repositories/dynamodb_page_preload_repository.py),
lines 74–94. Two simultaneous submissions with the same operation ID can both
pass earlier lookups and receive the same reservation. A delayed submitter then
unconditionally saves its initial record after the first worker has started or
finished, replacing its lease/result with processing state. Atomic usage
reservation does not make initial record creation atomic.

Correction: create-if-absent with submission ownership and return/recover the
winner's record. Regression: pause the second submission after its lookup,
finish or start the first worker, then resume the second save. Sequential replay
coverage does not establish safety for this interleaving.

### R06 — P2: Private-result expiry deletes unsettled cost evidence

Source: [usage_repository.py](../../backend/repositories/usage_repository.py),
lines 717–734 and 575–606;
[Dynamo usage adapter](../../backend/repositories/dynamodb_billing_repositories.py),
lines 278–281 and 434–458. After dispatch and a crash before settlement, the
only result/dispatch marker can expire. On a later visit beyond the retention
window, reclaim treats missing evidence as no dispatch and releases already
incurred cost and visible usage. Dynamo native TTL can remove that evidence too.

Correction: separate durable settlement evidence from private response retention;
never allow response TTL to erase the sole proof of dispatch. Regression:
dispatch, crash before settlement, advance past both result and reservation TTL,
then reclaim using both adapters. Existing tests cover the expirations separately.

### R07 — P2: Shadow-mode success can become permanently unmetered

Source: [preloading.py](../../backend/services/preloading.py), lines 1202–1216,
1284–1292 and 629–641. With reservation enforcement disabled, `ready` is published
before article/tokens and shadow cost are recorded. A crash or write error in
between leaves a successful result, while a retry returns early for `ready`
and never repairs the missing usage. Cost can also be lost between the separate
article and shadow writes.

Correction: persist pending usage and settle idempotently by operation before
publishing final readiness. Regression: inject failures at each publication and
settlement boundary and replay the worker; count each real operation once.

### R08 — P2: Downgrade truncates below the retained allowance

Source: [preloading.py](../../backend/services/preloading.py), lines 210–216;
[usage_repository.py](../../backend/repositories/usage_repository.py), lines
783–807; [entitlements.py](../../backend/services/entitlements.py), lines 126–182.
Content preparation uses the current subscription's processing caps, while
billing retains the month's higher snapshot. A mid-month downgrade can therefore
show a 150-sentence allowance but process only Basic's 50 sentences.

Correction: resolve effective retained sentence/source caps before preparation
and cost estimation. Regression: earn a Pro snapshot, downgrade in the same
month, submit a longer article and compare advertised with actual caps.

### R09 — P1: The normal preload start calls an undefined worker helper

Source: [background.js](../../extension/background.js), lines 779 and 834;
[content.js](../../extension/content.js), line 285;
[eslint.config.js](../../extension/eslint.config.js), line 125.
`updatePreloadJob` exists only in the isolated content-script context, not in
any worker import. Toolbar/panel `START_PRELOAD` calls it before POST and the
error handler calls it again, so fresh starts fail with `ReferenceError`.
Declaring the identifier as an ESLint global masks the missing runtime binding.

Correction: put the helper in a module imported by both contexts. Regression:
exercise the actual signed-in `START_PRELOAD` worker handler from extraction
through submission, with local mocks. Existing tests call `createPagePreload`
directly or intercept `CREATE_PAGE_PRELOAD`, bypassing this start path.

### R10 — P1: Navigation can deliver article data to another origin

Source: [background.js](../../extension/background.js), lines 821–824;
[content.js](../../extension/content.js), lines 940–952 and 2181–2182.
The worker sends completion to a tab ID without validating its current document.
If article A is replaced by page B during analysis, B accepts A's result and
publishes it under B's reading session. More seriously, the receiver persists
the full preload in B's page-origin sessionStorage, readable by B's scripts.
This can disclose A's analyzed content to an unrelated site. Security review
raised this from a wrong-page P2 to a cross-origin P1. The normal start-path
reproduction also requires R09 to be fixed; the completion/receiver boundary is
still independently unsafe.

Correction: bind delivery to the originating document and validate page identity
before any rendering/storage; keep extension results outside page-origin storage.
Regression: navigate a tab across origins between submit and completion and
assert that B receives/stores none of A's data.

### R11 — P2: Different article panels overwrite a global reading session

Source: [panel-ui.js](../../extension/panel-ui.js), lines 1858–1867 and 1686–1705;
[content.js](../../extension/content.js), lines 271–280. Each panel reacts to an
unrelated article's session event by hydrating its own cached preload back into
the same global storage key. Switching the key away clears the previous page's
anchors/selection state. Two open article panels can therefore erase each
other's state and generate repeated writes. An infinite loop is not claimed
as runtime-verified.

Correction: scope reading state by account and page/tab, and avoid writes in
response to unrelated storage events. Regression: two independent panels and
content scripts with interleaved storage notifications retain their own state.

## Findings: repository standards and test safety

### R04 — P2: A service-free test invokes the real Stripe client

Source: [test_billing.py](../../backend/test_billing.py), lines 439–455;
[Taskfile.yaml](../../Taskfile.yaml), line 259. The mock-customer-ID checkout test
uses a dummy key but does not stub Stripe Session.create. It can initiate real
HTTP attempts/retries; accepting a generic 502 does not test the desired
customer-ID behavior. This violates the repository service-free test rule.

Correction: stub the SDK call, assert request parameters and return a deterministic
session. Run the corrected test with network denied. It was not executed here.

## Additional security findings

### R12 — P2: Page-controlled storage can fabricate trusted analysis

Source: [content.js](../../extension/content.js), lines 2186–2189 and 428–432.
A visited page can populate `era_preload_data:<normalized URL>` in its own
sessionStorage. Restoration accepts that object when it has nonempty sentences
and promotes it to extension reading state. Thus a page can replace analysis
with fabricated content. No script execution or server authorization bypass is
claimed; the demonstrated boundary failure is analysis integrity.

Correction: store server responses only in extension-owned, account/page-scoped
storage with schema validation. Regression: seed a forged page-origin cache and
verify it is never promoted to trusted extension data.

### R13 — P2: Account changes retain another user's reading data

Source: [settings.js](../../extension/settings.js), lines 410–411;
[background.js](../../extension/background.js), lines 931–943;
[content.js](../../extension/content.js), lines 414–432. Logout clears only
authSession and neither purges user-unscoped reading caches nor invalidates
pending work. Another user in the same browser profile can restore the previous
user's personalized article analysis; restoration does not match an owner.

Correction: scope caches by authenticated user, clear visible state on logout,
and invalidate in-flight operations using an account generation. Regression:
A logs out while cached/in-flight data exists, B signs in, and neither completed
nor subsequently arriving A data becomes available as B's reading state.

### R14 — P2: Concurrent first logins can split one account into two identities

Source: [dynamodb_email_auth.py](../../backend/auth/dynamodb_email_auth.py), lines
35–47. Email lookup, unique index and profile creation are independent writes.
Two first logins can both see no user, create different IDs and obtain valid
sessions. The last email-index write wins, so later sign-in loses access to the
other identity's data/subscription, and free quotas can be duplicated.

Correction: transactionally create the unique email mapping/profile with a
condition, then have losing requests resolve the winning identity. Regression:
interleave two first logins and assert one persistent user and consistent
sessions. This is not an upstream identity-verification bypass finding.

## Round 1 conclusion and priority

Round 1 static review is complete: 14 findings, 5 P1 and 9 P2. Correctness and
security reviewers independently confirmed R01 and the signed-event/expiry
concerns. Security review escalated the cross-origin effect of R10; R12–R14
are additional boundary findings. No separate style-only defects were retained.
R04 is the standards/test-safety finding; the other 13 concern behavior or
security. Lack of runtime evidence is a verification limitation, not an extra bug.

Address activation failure R09 and disclosure R10 before user trials; reconcile
R01–R03 before charging; repair metering/idempotency R05–R08 before relying on
cost guarantees. Existing code is unchanged and fixes are not authorized by
this review report. A future fix needs focused regression tests and independent
review. No full-codebase completion claim is made until round 2 coverage is
reported, and even then untested paths must remain explicit.

## Round 2 handoff

The next reviewer should read this report first and avoid repeating completed
searches. Review source at the fixed baseline, or explicitly record any later
source drift before changing the scope. Inspect:

- Admin routes/dependencies/auth, account suspension, activity repositories,
  JSON/Dynamo runtime support and data isolation; `backend/admin/**`, admin
  services/repositories and tests, middleware and related OpenAPI schemas.
- Identity persistence/concurrency not exhausted by round 1, especially
  `backend/auth/dynamodb_email_auth.py` and session lifetime/ownership.
- `infra/**` source (exclude secrets/state/tfvars), `.github/workflows/**`,
  deployment/online-intake policy scripts and focused tests.
- Bootstrap, dev-container setup, generated-contract integration and release
  packaging (`extension/scripts/build_release.py`), without running providers.
- Unreviewed model/parser internals and storage/job/worker boundaries in
  `backend/core/pipeline.py`, `backend/jobs/**`, `backend/storage/**` and worker
  entrypoints. Review critical paths first and disclose residual coverage.

Retain IDs R01 onward; append findings and mark any disconfirmed item explicitly.
Do not implement fixes or turn the follow-up into recurring monitoring. Use the
same bounded read-only reviewers and preserve existing strategy document edits.
If canonical checks remain unavailable, report the limitation rather than
substitute real providers or host execution that violates repository constraints.

## Scheduling status

A single follow-up was proposed for 2026-09-09 18:08:26 UTC, equivalent to
2026-09-10 03:08:26 Asia/Tokyo, five hours after the recorded planning time.
Automatic creation was not confirmed: interval creation could not express the
single future run, and automated approval rejected the two-count and unanchored
clock alternatives. The tool accepted an exact anchored, single-run suggestion
and rendered an automation approval card. User confirmation in that card is
still required; this report does not claim an active reservation exists.

## Round 2 — completed 2026-09-10

The user requested completion of the remaining review, with a continuation at
2026-09-11 00:00 Asia/Tokyo only if unfinished. HEAD still matches the fixed
baseline; application source remains unchanged. Three bounded independent
reviewers covered administration/security, delivery/security and the remaining
pipeline/storage paths. The parent covered bootstrap, release packaging,
dev-container setup and contract-generation integration, and checked the findings
against source. The planned second-round static review is complete, so the
conditional midnight continuation is unnecessary and was not created.

### R15 — P1: Lambda's transaction client drops the temporary session token

Source: [dynamodb_store.py](../../backend/storage/dynamodb_store.py), lines
32–42 and 53–60; [lambda_handler.py](../../backend/lambda_handler.py), line 28;
[worker_handler.py](../../backend/worker_handler.py), line 39.
Both Lambda entrypoints override the DynamoDB resource factory to use the default
credential chain, but the separate transaction client still receives explicit
access/secret keys without the temporary session token. Resource reads/writes
can succeed while transactions fail authentication. Ordinary preload creation
uses transactional writes, so the defect is not limited to enabling reservation
enforcement. The delivery/security reviewer independently confirmed this path.

Correction: use the default credential chain for both factories outside Local,
keeping dummy credentials exclusive to DynamoDB Local. Regression: inspect both
client constructor paths with fake role credentials and a stubbed SDK; ensure
no temporary token is dropped and no live provider is called.

### R16 — P1: Workflow input executes before the actor gate

Source: [deployment workflow](../../.github/workflows/deploy-reading-assistant.yml),
lines 115 and 146; [intake workflow](../../.github/workflows/agent-intake.yml),
line 51. Free-form dispatch input is interpolated directly into double-quoted
shell source. Command substitution in a submitted value executes before Python
checks the actor allowlist or validates the input. A user able to dispatch the
workflow but outside the custom allowlist can therefore execute runner code
before denial. The step already holds GITHUB_TOKEN, and the plan job has OIDC
capability. This does not independently bypass the protected apply Environment.

Correction: pass all free-form inputs through step environment variables and
expand quoted shell variables. Regression: hostile input remains literal and
cannot execute even when the actor is rejected. Do not test this by dispatching
a real workflow; use an isolated, credential-free harness.

### R17 — P1: Apply lacks the Lambda ZIP referenced by the approved plan

Source: [deployment workflow](../../.github/workflows/deploy-reading-assistant.yml),
lines 154–156, 345, 421 and 515;
[API module](../../infra/modules/reading-assistant-api/main.tf), lines 156 and 334;
[production variables](../../infra/envs/prod/variables.tf), line 4 (dev equivalent).
The plan runner builds a local Lambda ZIP, but the fresh apply runner receives
only the saved Terraform plan. Both Lambda resources still refer to the
untracked local ZIP. A function creation/code update cannot upload that missing
file and may fail after unrelated infrastructure changes have completed.

Correction: preserve the exact built ZIP as an immutable artifact, bind its
digest to release evidence and verify/restore it before apply, or use a versioned
S3 code artifact. Do not rebuild a potentially different ZIP after approval.
Regression: simulate a fresh apply workspace with no inherited build directory
and verify all plan-referenced artifact bytes and digests before any apply.

### R18 — P2: Concurrent session writes can resurrect a logged-out token

Source: [json_auth.py](../../backend/accounts/storage/json_auth.py), lines 92–130;
[json_session_repository.py](../../backend/repositories/json_session_repository.py),
lines 37–43. A login reads a list containing token A, A's logout removes it, and
the login writes its stale list plus its new token. A becomes valid again after
a successful logout. Expiry cleanup has the same stale-write risk; the admin
revocation lock cannot protect against normal auth writers that never acquire it.
Suspension still blocks learner access, but the restored token can survive
reactivation. This concerns the supported JSON runtime.

Correction: share one lock boundary across creation, logout, cleanup and bulk
revocation, without nested independent flock acquisition. Regression: pause
login after reading, complete logout, resume login and verify A stays invalid.

### R19 — P2: Dynamo authentication ignores the configured session lifetime

Source: [deps.py](../../backend/deps.py), lines 74–75;
[dynamodb_email_auth.py](../../backend/auth/dynamodb_email_auth.py), lines 26–28;
[account settings](../../backend/accounts/settings.py), lines 67–69.
With DynamoDB storage and AUTH_SESSION_TTL_DAYS=1, the adapter is constructed
without the configured TTL and retains its 30-day default. Tokens can remain
usable 29 days beyond the requested lifetime; JSON correctly honors the setting.

Correction: pass ACCOUNTS_SETTINGS.session_ttl_days into the Dynamo adapter.
Regression: build the adapter through the composition root with a fake store and
clock, checking persisted expiry and rejection after the configured boundary.

### R20 — P2: Activity deduplication is not scoped to the account

Source: [admin_activity service](../../backend/services/admin_activity.py),
lines 45–47; [JSON activity](../../backend/repositories/json_admin_activity.py),
lines 84–89; [memory activity](../../backend/repositories/memory_admin_activity.py),
lines 19–24. Two accounts can submit the same valid operation UUID and terminal
status. Their usage records are user-scoped, but activity source identity omits
the user. The second append returns the first account's event, suppressing the
second account's actual operation from administrative history. A caller with
multiple accounts can deliberately exploit this telemetry collision. It does
not bypass the separate billing meter or prove data is returned to that caller.

Correction: deduplicate by (user_id, source_id) in both adapters. Regression:
cross-user identical operation/status retains two events; same-user replay one.

### R21 — P2: A successful fallback hides an earlier uncertain provider cost

Source: [pipeline.py](../../backend/core/pipeline.py), lines 557–564 and
1647–1665; [reading_support.py](../../backend/services/reading_support.py),
lines 49–53. If the one-shot splitter times out after dispatch, then fallback
and subsequent analysis succeed, the failed request never marks tally usage
incomplete. Later positive token counts and missing_usage=false cause settlement
to omit the uncertain first call. This differs from the crash/TTL paths R06/R07.

Correction: retain incomplete-usage evidence for every uncertain dispatched
failure across later successful calls, and settle conservatively. Regression:
a stubbed first call fails after dispatch and the fallback succeeds; final
settlement must account for the uncertain call rather than only good responses.

### R22 — P2: A global splitter cap truncates Max below its plan allowance

Source: [pipeline.py](../../backend/core/pipeline.py), lines 1313, 1637 and
1676–1682. A Max article with 250 distinct short sentences fitting one
14,000-character chunk has an outer 300-sentence limit, but the inner finalizer
and coarse reconciliation draft cap at MAX_SENTENCES, default 200. Even a
correct 250-sentence response loses the final 50. This is independent of R08's
downgrade mismatch; it happens while Max remains active.

Correction: propagate the effective cap through helpers or cap only the final
merge. Regression: a single chunk exceeding 200 sentences retains up to the
300-sentence plan allowance. Reservation-sizing coverage does not test output.

### R23 — P2: Concurrent phrase saves lose acknowledged data

Source: [phrase_repository.py](../../backend/repositories/phrase_repository.py),
lines 22–28; [main.py](../../backend/main.py), lines 333–338. Two POSTs can read
the same JSON list, prepend different phrases and both return success, while
the final write removes the other's phrase. The shared file also permits
collisions between different users. Atomic replacement prevents a partial file,
not a lost read-modify-write update.

Correction: hold the existing json_list_lock for the whole operation. Regression:
interleave saves through two repository instances and verify both records remain
under the proper owners. Scope is the supported JSON storage adapter.

### R24 — P2: The plan-role template grants the wrong encryption-read action

Source: [dev policy](../examples/aws-plan-role-policy-dev.json), line 185;
[prod policy](../examples/aws-plan-role-policy-prod.json), line 185;
[deployment workflow](../../.github/workflows/deploy-reading-assistant.yml),
line 177. The templates grant s3:GetBucketEncryption, but the invoked general
purpose bucket API requires s3:GetEncryptionConfiguration. Using these templates
can fail IAM policy validation or leave the storage-readiness check unauthorized.
The required permission was checked against the
[official AWS API reference](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetBucketEncryption.html)
on 2026-09-10. No live IAM configuration was inspected.

Correction: use the valid action in both templates and test the API-to-permission
mapping; existing structural policy assertions do not validate action names.

### R25 — P2: API read-role tag conditions do not match provisioned resources

Source: [dev policy](../examples/aws-plan-role-policy-dev.json), line 141;
[prod policy](../examples/aws-plan-role-policy-prod.json), line 141;
[dev provider](../../infra/envs/dev/versions.tf), line 17 and prod equivalent.
The API Gateway read condition requires Project=english, while the Terraform
provider applies Project=english-reading-assistant. Once the API exists, refresh
under this role cannot satisfy the tag condition and subsequent plans fail.

Correction: align the condition to the actual project tag and test consistency
between provider tags and policy templates. This reports repository configuration,
not a verified defect in any separately managed live IAM role.

### R26 — P2: Environment overlays bypass production provider validation

Source: [API environment merge](../../infra/modules/reading-assistant-api/main.tf),
lines 48–52; [module variables](../../infra/modules/reading-assistant-api/variables.tf),
lines 137–165; [account container](../../backend/accounts/container.py),
lines 128–143. The extra environment map and unrestricted pricing map are merged
after the validated base providers. They can set AUTH_PROVIDER or BILLING_PROVIDER
to mock even though production typed variables require real providers. Such a
configuration passes the typed guard and deploys mock identity/payment behavior.
This requires configuration access; it is not a public request exploit.

Correction: reserve provider/security keys in every overlay and enforce production
invariants against the final merged environment. Regression: attempt mock
provider overrides through each map and require validation failure before apply.

### R27 — P2: Shell activation adds a nonexistent tool shim directory

Source: [bootstrap.sh](../../scripts/bootstrap.sh), lines 24–26 and 307;
[dev-container configuration](../../.devcontainer/devcontainer.json), line 34.
The bootstrap exports MISE_DATA_DIR under mise/data, but its non-exported shim
variable and --env PATH point to mise/shims. Normal installation creates
mise/data/shims. The parent observed that actual directory in this checkout and
no sibling mise/shims; the dev-container PATH already uses the correct location.
A clean shell following the documented activation instructions cannot resolve
the pinned tools, or resolves unrelated system versions instead. --exec is not
affected. The delivery reviewer independently confirmed the source mismatch;
[official mise directories](https://mise.jdx.dev/directories.html) corroborate
the layout (accessed 2026-09-10).

Correction: derive the emitted shim path from the configured data directory and
keep bootstrap/dev-container activation consistent. Regression: check activation
from a clean PATH after installation, without relying on globally installed tools.

## Final coverage and disposition

| Area | Evidence reviewed in round 2 | Result |
| --- | --- | --- |
| Administration and identity | Admin routes/dependencies, CORS/correlation, suspension, control/audit storage, session and activity adapters, settings, contracts and test source | R18–R20; no additional demonstrated admin privilege escalation |
| Infrastructure and CI | Terraform modules/composition, workflow entrypoints, exact-plan gates/classification, intake sanitization, policy templates and relevant test assertions | R16–R17, R24–R26; external enforcement not verified |
| Remaining runtime | Parsing/splitting, provider dispatch/tally, jobs/worker, storage, reading projections and phrase persistence | R15, R21–R23; complete parser/provider behavior not runtime-validated |
| Local tooling and packaging | Bootstrap and installers, dev-container setup/manifest protection, Lambda builder, extension ZIP allowlist/dependency/URL validation, package smoke, API generation/drift/security checks | R27; no further concrete package/contract defect retained in these inspected paths |

Total retained findings: **27 (8 P1, 19 P2)** across both rounds. Round 2 added
**13 (3 P1, 10 P2)**. Two security reviewers plus one correctness reviewer supplied
the second-round findings; parent source checks and cross-review confirmations
are noted above. This is a completed risk-focused static review of the planned
scope, not a guarantee that every line or possible execution is defect-free.

Fix order: R09/R10 for first-use safety; R15–R17 for runtime/delivery viability;
R01–R03 for charging correctness; then cost/allowance, session integrity and
persistence defects. R24–R27 must be resolved before relying on their respective
release/local workflows. Each fix should have the focused regression specified
above and an independent review; no implementation change occurred here.

Canonical tests remain unexecuted: the Docker socket again returned permission
denied on 2026-09-10. Production-like AWS refresh/SSM behavior, live OIDC and
protected Environment enforcement, actual browser behavior and provider responses
remain validation limitations. No credentials, secret stores or production
accounts were inspected. These are not deferred static-review tasks that justify
another scheduled run of the same inspection; they need the appropriate isolated
runtime or separately authorized integration work.

Usage observations for round 2: five-hour/weekly account windows started at
5%/63% consumed and later reported 100%/78%. Exact per-task token counts are not
available; these shared windows cannot establish this task's isolated usage.
No reset credit was consumed. Despite the high reported usage, the assigned
reviewers finished and the report was consolidated in this turn. The prior
five-hour suggestion is historical; no new midnight automation was needed.
