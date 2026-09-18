# RM-09 preparation notes

September 13, 2026. Parent Astra source inspection only; no RM-09 implementation
or final contract approval. Dispatch the three ordered subunits only after the
complete contract required by PLAN is recorded.

## Confirmed code seams

`accounts/services/billing_flow.py` performs checkout without a persisted pending
record and merges webhook snapshots without atomicity. `StripeBillingProvider`
does not pass idempotency or retain the Checkout Session ID. Checkout completion
currently marks a plan active without its period. `resolve_plan_id` accepts an
active record without a period and does not validate the returned plan against
the catalog. Preserve intentional mock activation explicitly when tightening it.

All subscription adapters expose only get/upsert/customer lookup. JSON already has
`json_list_lock` available, but subscription writes do not use it. Dynamo writes
the subscription and customer reverse index separately. A new atomic operation
must preserve both ownership and index consistency, with conditional conflict
behavior tested across separate repository instances. In-memory copies must not
share newly added nested mutable pending-state objects.

## Provider facts checked

Stripe stores the first idempotent result, including server errors. Keys may be
pruned after at least 24 hours; reusing a pruned key can execute a new request.
Changed parameters are rejected while a key is retained. A local timeout must
therefore preserve the original operation and parameters; it cannot justify
creating a new checkout or assuming indefinite deduplication.
[Stripe idempotency reference](https://docs.stripe.com/api/idempotent_requests).

Checkout exposes its status, expiry, and subscription association. The list API
supports customer, status, subscription, and pagination filters; a complete
session can still have payment processing in progress. Local expiry alone is not
proof that payment did not complete.
[Retrieve Session](https://docs.stripe.com/api/checkout/sessions/retrieve),
[List Sessions](https://docs.stripe.com/api/checkout/sessions/list).

Webhook delivery can be duplicated or out of order; retrieving current resource
state is available. Retrieval still needs a conditional persistence boundary so
a delayed response cannot overwrite a newer committed reconciliation.
[Stripe webhook documentation](https://docs.stripe.com/webhooks).

## Decisions still required before implementation

- Persist a stable pending operation and immutable request parameters before the
  provider call; define expiry and ambiguous-response recovery beyond provider
  key retention without duplicate billing.
- Define historical checkout discovery, including old sessions with no locally
  stored customer/session ID. An empty local subscription record does not prove
  no older hosted checkout exists. Never silently cancel or refund historical
  purchases. Ambiguous historical state needs an explicit fail-safe outcome.
- Define revision-based subscription updates, customer-index ownership, event
  deduplication, and fresh retrieval after conditional-write conflicts. Event
  timestamps alone are insufficient, including equal-time events.
- Define finite real-provider entitlement and existing-record compatibility;
  checkout completion may link identity but must not establish unlimited access.

No SDK execution, provider access, source changes, or tests occurred for RM-09.
