# RM-09 billing safety contract

Parent Astra implementation decision, September 13, 2026. This completes the
previous preparation notes. User authorized local implementation of all review
findings; this contract authorizes no Stripe calls, migrations of live records,
cancellations, refunds, credentials, deployments, or public API changes.
RM-05 is accepted. Implement three ordered, independently reviewed subunits.

## Shared repository boundary

Use a revision-based compare-and-swap operation on the subscription record.
Missing revision on legacy records is revision zero; every supported writer must
advance it. JSON uses json_list_lock across read/condition/write, memory uses a
critical section and deep copies, and Dynamo uses conditional transactions.
Pending operations must never replace entitlement fields read before a concurrent
webhook. Legacy upsert paths must preserve pending-operation ownership; a stale
writer cannot erase or reset its idempotency identity. Provider calls stay outside
repository locks; conflicts require a new read and explicit retry outcome.

Keep customer reverse-index ownership consistent in the same atomic boundary.
An index may be created only if absent or owned by the same user; remapping removes
an old index only under that same ownership condition. Duplicate historical
customer ownership fails safely. Never steal a customer mapping. Tests use two
repository instances sharing backing state, not only a single process-local lock.

## A: pending checkout ownership and ambiguous recovery (R01)

Persist a UUIDv7 operation identity before any provider creation. Retain its
immutable provider parameters: user reference, requested plan and price, return
URLs, email/customer choice, operation metadata, creation time, and stable
idempotency key. External session IDs use explicit provider-specific field names.
Competing requests for the same operation reuse its existing session; different
plans or return parameters return a conflict while it remains unresolved.

Persist a creation-attempt marker before the provider request. Retries inside a
conservative 23-hour interval use the identical saved parameters/key, including
provider errors and timeouts. Never clear the operation on an ambiguous response.
After the interval, do not repeat creation if the provider session is unknown:
read-only discovery may recover it by operation metadata, otherwise return a
reconciliation-required conflict. Local timeout/expiry is never proof of absence.
Store the returned session ID, URL, and provider expiry under operation/revision
conditions. A stale success cannot overwrite a newer operation or entitlement.

Before creating the first managed operation, reconcile historical hosted checkouts.
An empty local record/customer ID does not prove that no old checkout exists.
Use bounded, fully paginated read-only session discovery and match trusted user
reference/metadata, including old sessions created without a known customer ID.
Email-only matches are ambiguous, never proof of ownership. If the scan is partial,
provider lookup fails, ownership conflicts, or multiple open/nonterminal purchases
exist, fail closed without creating another session. Record an explicit safe
conflict; do not cancel, expire, or refund old provider objects automatically.

One compatible open historical session may be adopted and reused after validating
its user, plan/price, URLs and provider state. Completed sessions require current
subscription retrieval; complete does not imply settled payment. A new operation
is allowed only when every relevant prior session/subscription is proven terminal
(expired checkout with no subscription, or canceled/incomplete_expired
subscription), with no pending ambiguous creation. Unknown subscription statuses,
unpaid, paused, past_due, incomplete, active and trialing all block a second sale.
A provider timeout after a durable attempt cannot be cleared just because a later
history scan finds no session. This conservative result may require support.
Deployment preparation must retire old non-idempotent checkout writers before
exposing the new flow; local tests cannot establish mixed-version safety.

Tests: two concurrent starts through separate adapters; conflicting plans;
crashes before/after creation; stable retry parameters; unknown session after key
retention; one/multiple historical sessions with and without local customer IDs;
partial pagination; terminal and ambiguous recovery; webhook interleaving and
customer-index collision/remap. Stripe SDK is mocked. Existing checkout tests must
assert idempotency and retain RM-01's no-network guarantees.

## B: authoritative lifecycle reconciliation (R02)

Verified events carry provider event identity and resource/customer/user identity;
event timestamps are diagnostic only. Fetch current subscription state from the
provider instead of merging historical entitlement fields from the event body.
Validate fetched customer/subscription ownership and supported price/plan. Conflicting
live subscriptions or unknown ownership require reconciliation, never automatic
replacement of an unrelated user's or customer's record.

Read revision before retrieval and commit the validated snapshot with event
identity atomically. On conflict, fetch provider state again; do not retry the old
snapshot against a new revision. Bound retries and fail with a retryable outcome.
Record deduplication evidence atomically with the entitlement write. If retained
event history is bounded, replay outside that bound must still fetch authoritative
state; it cannot roll back current state from the old event payload. Checkout
completion links identities/pending operation only until an authoritative finite
subscription snapshot is validated. Deletion also reconciles current state; an
older active event cannot resurrect a canceled subscription.

Tests: deletion then stale active, upgrade then stale lower plan, duplicates,
equal-time events, delayed retrieval/CAS conflict, separate simultaneous handlers,
failed persistence and index ownership conflicts. Unknown or malformed provider
responses do not grant access. No timestamp-only ordering substitute.

Existing-record compatibility clarification: B must preserve A's exact checkout
request parameters, including the accepted A subscription_data.metadata fields
user_id, plan and checkout_operation_id for already persisted attempts. Compare
the complete SDK request against the hash-verified accepted A source. Do not change checkout creation parameters
as a shortcut for webhook ownership. A fetched metadata user ID, when present,
must match; when absent on legacy resources, validate the existing customer index
or a verified checkout-completion user reference together with matching resource
and customer identities. Conflicting index/reference/metadata ownership fails
closed. A bare unverified customer or email is not an ownership proof.

September 14 review correction: the earlier parent clarification incorrectly
described subscription_data as absent in A. A-runtime-01 proves it was present.
B-runtime-01 and B-compat-red remain historical evidence; their absence oracle
does not establish request compatibility and must be replaced.

Known paid plan and finite period are conditions for granting active/trialing
entitlement. They must not prevent authoritative revocation for a validated
terminal resource of the same owner/subscription when its plan/period is absent.
Such a snapshot cannot grant access or retain an old active status. Test actual
legacy shapes and same-key request arguments, not only newly normalized fixtures.

## C: finite real-provider entitlement and compatibility (R03)

Paid access requires a catalogued paid plan, active/trialing validated status and
a finite valid period end. Preserve the existing bounded renewal grace, never an
unbounded fallback. Reject missing/malformed/boolean/nonfinite periods and unknown
plans. Checkout metadata/payment completion alone must not activate paid access.

Persist explicit entitlement provenance. Intentional mock activation is allowed
only when the configured mock provider explicitly enables it; a persisted mock
marker alone cannot grant paid access after switching to Stripe. Real legacy
records with missing expiry fall back to Basic until authoritative reconciliation.
Existing valid finite Stripe records remain compatible. Apply the same resolver
through account descriptions and quota/entitlement consumers; do not fix only UI.
Tests cover legacy records, mocked activation, provider-mode transition, unknown
plan, malformed/endless expiry and completion without subsequent lifecycle events.

C composition decision: pass the configured billing-provider mode explicitly
from AccountsContainer.settings. A stored entitlement_provider=mock grants only
in explicitly configured mock mode; it cannot grant in Stripe mode even when
it contains a finite expiry. Valid finite legacy Stripe records without a marker
remain compatible; unrecognized provenance does not grant. Default low-level
resolver behavior is conservative, never an implicit mock exception.

Necessary C ownership includes services/entitlements.py, services/usage_meter.py,
deps.py, services/preloading.py, jobs/inline_runner.py and worker_handler.py,
plus their focused tests, to propagate the same configured mode through HTTP
and worker-created guards/meters. Preserve RM-02/RM-05 factory behavior. This
extends wiring only; preload reservation/accounting redesign remains RM-10–12.
Add provenance when mock activation or validated Stripe reconciliation writes
entitlement. Do not infer mock permission merely from activated_plan returned by
an arbitrary provider. Check activation persistence under A's revision boundary;
legacy upsert intentionally preserves pending state and is not a state-transition
API. Mock cancellation/retry/repeated checkout must not lose operation ownership
or silently activate a stale result. No real historical-operation cleanup.

C initial review clarification: pending operations must retain immutable provider
origin. A mock activation followed by a Stripe-mode checkout must not return the
saved mock success URL. Reject a known cross-mode operation with an explicit
reconciliation conflict; automatic historical cleanup/migration is outside this
unit. Preserve accepted A legacy real-provider retries and their SDK arguments.
If required, C may add provider origin to the existing immutable pending-field
checks in JSON, memory and Dynamo subscription adapters, with focused regressions;
do not otherwise redesign these accepted adapters. Missing legacy origin is not
permission to reinterpret known mock evidence as a real checkout.

## Evidence and implementation order

Scope follows PLAN.md RM-09 ownership. Internal ports/models/adapters may gain
small typed state/result structures; keep contracts/ public responses unchanged.
Subunit A must receive an independent Astra checkpoint before B, then B before C.
Each uses canonical test:backend:unit, lint:backend and format:backend:check in the
credential-free network-denied container. Fake Dynamo conditional transactions
are required; live Dynamo/Stripe are outside scope. Record unresolved historical
ambiguity explicitly. Parent accepts a subunit only after independent review and
canonical receipts; RM-09 completes only when A/B/C all satisfy this contract.

## Primary provider references

Stripe retains an idempotent result including failures and may prune keys after
at least 24 hours; reuse after pruning can create a new request. This motivates
the conservative local retry interval and durable ambiguous-operation marker.
[Stripe idempotency](https://docs.stripe.com/api/idempotent_requests).

Checkout listing is paginated; complete may still mean payment is processing,
while expired is terminal. Local discovery must not interpret an incomplete page
or local expiry as proof that no older purchase exists.
[Checkout session listing](https://docs.stripe.com/api/checkout/sessions/list).

Webhook delivery may be duplicated or out of order. Current-resource retrieval
plus local conditional persistence is the application decision for safe recovery.
[Stripe webhooks](https://docs.stripe.com/webhooks).
