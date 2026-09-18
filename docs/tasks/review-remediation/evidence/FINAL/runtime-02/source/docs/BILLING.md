# Billing & Plans

## Plan design

Three tiers — `basic` (free), `pro`, `max` — differentiated purely by
quota. Features are identical on every plan; `max` is a large but finite
allowance, never unlimited.

| Limit | basic | pro | max |
| --- | --- | --- | --- |
| Monthly price (tax-inclusive pilot) | JPY 0 | JPY 1,480 | JPY 3,980 |
| Article analyses / month | 3 | 40 | 120 |
| Chats / month | 15 | 400 | 1,200 |
| Sentences analyzed per article | 50 | 150 | 300 |
| Raw tokens / month (migration/calibration only) | 200k | 3M | 10M |
| Provider cost / month (micro-USD, hidden) | 200,000 | 2,500,000 | 7,000,000 |

These prices and limits satisfy the launch profit rules in
`docs/superpowers/specs/2026-07-19-launch-pricing-design.md`: AI cost ceiling
≤ 30% of post-Stripe available revenue, and articles × ¥8 cannot exceed the
ceiling. They are the paid-pilot offer, not a permanent public price
guarantee. Every limit is an environment variable (`PLAN_<TIER>_<LIMIT>`, see
`.env.example`). Verify the active OpenAI rate card before enabling usage
reservation enforcement or live Stripe products.

Design decisions:

- **Two visible meters** (articles + chats per month). Selection analysis
  (`/analyze`) answers from the preload cache for free; a cache miss calls
  OpenAI and therefore counts against the hidden monthly provider-cost ceiling (no
  article/chat charge).
- **Per-article sentence cap** — separate from the monthly count. Long
  articles are analyzed up to the cap (graceful truncation): the panel
  meta line shows "explained the first N of M sentences", which doubles
  as the upgrade prompt. Requests are never rejected for length.
- **Monthly provider-cost ceiling.** When reservation enforcement is enabled,
  the active hidden monthly hard cost ceiling is integer micro-USD calculated
  from model-specific input/output rates. If the ceiling is exhausted the
  request fails even when article quota remains. Raw token totals are retained
  only for migration, calibration, and rollback; they are not the active hard
  ceiling.
- Quota errors carry a machine-readable `code`
  (`article_quota_exceeded` / `chat_quota_exceeded` /
  `token_budget_exceeded`); the extension maps codes onto localized
  messages. 402 means "upgrading solves it"; the legacy
  `token_budget_exceeded` name may represent the active hidden cost ceiling.
- With `USAGE_RESERVATION_ENABLED=true`, each operation atomically reserves
  its visible meter and estimated provider cost before dispatch. Success
  finalizes actual usage; a known pre-dispatch failure releases it. Uncertain
  post-dispatch failures settle conservatively. The switch remains **off by
  default** until staging concurrency verification is complete.

## Composite usage-meter contract

The composite meter reserves articles/chats and estimated provider cost in
one atomic transaction. This prevents concurrent requests from independently
passing visible and cost checks. Article and chat counters are visible; raw
tokens, model names, rates, rate-card versions, and micro-USD values follow the
**hidden cost policy** and never appear in client responses or UI.
Raw token totals are retained only for migration, calibration, and rollback.
With reservation enforcement enabled, admission and settlement use the integer
micro-USD ceiling derived from the pinned model-specific input/output rates.

Quota periods are **UTC calendar months** (`YYYY-MM`), resetting at 00:00 UTC
on day one. Each operation and audit event persists the exact **tokenizer
encoding** used for source-token accounting alongside the model, rate-card
version, and rates. This makes accounting reproducible across configuration
changes. This metadata remains hidden from the billing API and UI. A month's
first reservation creates a **pinned snapshot** of plan limits. Upgrades may
ratchet the snapshot upward immediately. A downgrade never reduces the active
month's allowance and takes effect in the next month.

Every retriable command requires a stable operation ID and canonical payload
hash. **Idempotency** means a replay with the same ID and hash returns the
original transition/result; reuse with a different hash fails with 409.

### Thresholds and configuration

- Visible warning threshold: article or chat `used + pending >= 80%`.
- `PLAN_<TIER>_{ARTICLES_PER_MONTH,CHATS_PER_MONTH,SENTENCES_PER_ARTICLE,
  SOURCE_TOKENS_PER_ARTICLE,COST_MICRO_USD_PER_MONTH,TOKENS_PER_MONTH}`:
  plan settings. `COST_MICRO_USD_PER_MONTH` is the active hidden hard ceiling
  under reservation enforcement; `TOKENS_PER_MONTH` is retained only for
  migration, calibration, and rollback.
- `OPENAI_TOKEN_ENCODING`, `OPENAI_RATE_CARD_VERSION`,
  `OPENAI_MODEL_{INPUT,OUTPUT}_MICRO_USD_PER_MILLION`: pinned estimation
  inputs. Missing pricing fails closed when reservations are enabled.
- `USAGE_RESERVATION_ENABLED=false`: rollout switch; enable only after the
  staging parallel-request suite passes.
- `USAGE_RESERVATION_TTL_SECONDS=900`: reservation lease.
- `SYNC_EXECUTION_LEASE_SECONDS=120`, `SYNC_EXECUTION_WAIT_SECONDS=2`:
  execution ownership and duplicate-request wait.
- `PRELOAD_WORKER_LEASE_SECONDS=900`: async preload worker ownership lease;
  heartbeats extend it, and another worker may reclaim it after expiry.
- `OPENAI_MAX_INPUT_TOKENS_PER_CALL=128000`: maximum input-plus-reserved-output
  envelope for one provider call (valid range `1..1000000`), preventing an
  oversized call before dispatch.
- `MAX_SENTENCE_SPLIT_AGENT_TURNS=2`: default fallback sentence-splitting turns per chunk (configurable up to 8); reservations cover every configured turn at maximum completion output
  ceiling per chunk (valid range `1..8`), bounding retries and provider cost.
- `SYNC_RESULT_TTL_SECONDS=86400`, `SYNC_RESULT_MAX_BYTES=65536`,
  `SYNC_RESULT_CLEANUP_BATCH_SIZE=100`: private replay retention and bounds.
  DynamoDB native TTL uses numeric `expires_at_epoch`.

### Failure, lease recovery, and operations

Reservations are released only when provider dispatch is known not to have
happened. After dispatch, actual usage is finalized when known; otherwise the
estimate is finalized conservatively. Expired reservations are reclaimed
lazily. An expired execution lease may be claimed by a retry, which repairs a
persisted pending result before returning it. Preload records in
`ready_pending_usage` or `failed_pending_usage` are similarly repaired without
re-dispatch.

Structured events are `usage_reserve_blocked`, `usage_reserved`,
`usage_finalized`, `usage_finalize_blocked`, `usage_finalization_error`,
`usage_released`, `usage_reclaimed`, `execution_lease_recovered`, and
`pending_result_repaired`. Shadow mode additionally emits
`usage_shadow_observed`. `usage_finalize_blocked` records an expected quota
denial during settlement, including only the operation ID, meter, and stable
error type. `usage_finalization_error` is emitted at error level immediately
before an unexpected settlement failure is re-raised; it contains the
operation ID and exception type, never the exception message.
`usage_shadow_observed` contains the meter, outcome, estimated and actual
micro-USD, input/output/total token classes, model, rate-card version, and
tokenizer encoding. Events never include source text, auth tokens, payload
hashes, exception messages, or private replay results.

Operational recovery: first inspect these events by operation ID. Retry the
same operation ID only with the identical payload. Allow an active lease to
expire before recovery; do not delete counters manually. If a pending preload
cannot self-repair, preserve its operation record, quarantine the job, and
reconcile via the repository transition API. Use point-in-time recovery for
accidental table mutations.

Rollout uses a **shadow migration**. With
`USAGE_RESERVATION_ENABLED=false`, article, chat, and uncached selection
analysis provider calls are calibrated without creating reservations,
blocking on the composite meter, or writing composite counters. Existing
legacy quota checks remain authoritative and successful calls increment those
legacy counters exactly once. Cached selection analysis emits no shadow event
because it dispatches no provider request. A successful call emits its
observed usage. Its actual micro-USD cost is also accumulated in a hidden
compatibility total so enabling enforcement mid-month does not reset the cost
allowance. Raw compatibility totals and committed admission totals are kept
aligned across enforcement rollback and re-enablement. A failure after
dispatch emits a `conservative_failure` outcome and uses at least the
pre-dispatch estimate as actual cost; a known
pre-dispatch failure is marked `failed_before_dispatch`. Deploy schema, TTL,
and logs in this mode, verify replay, failure, and concurrency tests in
staging, then set the rollout switch true. Roll back by switching enforcement
off, not by deleting usage data.

## Architecture

Subscriptions live in the shared `accounts` package (see
`backend/accounts/README.md`), which the `realtime` application embeds too.
Following the AUTH_PROVIDER pattern, `BILLING_PROVIDER=mock|stripe` picks a
`BillingProvider` (accounts/ports.py) injected via DI.

- `accounts/billing/mock_billing.py` — local development. Checkout
  "succeeds" instantly and the plan activates without payment.
- `accounts/billing/stripe_billing.py` — hosted Stripe Checkout + Customer
  Portal. Card data never touches the backend. Webhook signatures are
  verified fail-closed; entitlements change only through verified events,
  matched against the stored subscription id so stale duplicates cannot
  cancel an active plan.
- **Plan changes**: Checkout is only for users without an active paid
  subscription (a second Checkout would create a second subscription and
  double-bill — the server rejects it with 409). Subscribers up/downgrade
  and cancel through the Customer Portal.
- `accounts/services/billing_flow.py` — checkout/portal/webhook use cases.
- `accounts/plans.py` — `PlanCatalog` (which plan ids exist) and
  `resolve_plan_id` (is the subscription still live).
- `services/entitlements.py` — Untangle's quota guard: what a resolved
  plan actually allows (framework-free, works under FastAPI or a Lambda
  handler). The shared package never learns these numbers.
- `repositories/usage_repository.py` and the DynamoDB subscription
  adapter — JSON and DynamoDB implementations following STORAGE_BACKEND;
  the JSON subscription store ships with `accounts`.

Endpoints: `POST /billing/checkout`, `POST /billing/portal`,
`POST /billing/webhook` (unauthenticated, signature-verified), and
`GET /billing/done` (post-checkout landing page) come from the accounts
router. `GET /billing/me` stays in main.py because remaining quota is
Untangle's own concept.

Entitlement records live per user: `{plan, status, stripe_customer_id,
stripe_subscription_id, current_period_end}`. The hot path reads only
this record (no Stripe API calls). A subscription counts as active when
`status ∈ {active, trialing}` and `current_period_end` has not passed
(with one day of grace for renewal-webhook lag), so a missed deletion
webhook cannot grant service forever.

## Local development (mock)

The default. Sign in, open the settings tab, press "Upgrade to pro" —
the plan switches instantly and the usage line updates.

## Stripe test mode

1. `stripe login` (once; CLI keys expire after ~90 days).
2. Create the approved recurring pilot prices once:
   `python scripts/create_stripe_prices.py` (uses the CLI's test key), or
   create two monthly prices in the dashboard.
3. In `.env`: `BILLING_PROVIDER=stripe`, `STRIPE_SECRET_KEY=sk_test_...`,
   `STRIPE_PRICE_ID_PRO=price_...`, `STRIPE_PRICE_ID_MAX=price_...`.
4. Forward webhooks and copy the printed `whsec_...` into
   `STRIPE_WEBHOOK_SECRET`:
   `stripe listen --forward-to localhost:18765/billing/webhook`
5. Restart uvicorn (env vars are not hot-reloaded). Upgrade from the
   extension using test card `4242 4242 4242 4242`.

Checkout sessions carry `client_reference_id` and subscription metadata
`user_id`, so webhook events map back to the user; later events also
resolve via the stored `stripe_customer_id`.

## Production notes (AWS/Lambda later)

- The webhook endpoint must be publicly reachable; point the Stripe
  webhook destination at the deployed URL and set the real
  `STRIPE_WEBHOOK_SECRET`.
- Usage counters use atomic `UpdateItem ADD`, safe under concurrent
  Lambda instances.
- Prices: create live counterparts only after verifying the active model rate
  card and pilot assumptions; keep the live price ids in environment
  configuration.
