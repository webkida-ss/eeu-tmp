# Plan Usage Metering Design

## Goal

Enforce Free (`basic`), Pro, and Max allowances without exposing implementation-level token accounting to learners, while preventing long inputs, concurrent requests, retries, and model price differences from producing unbounded AI cost.

## Meter model

The product uses several complementary meters rather than one compound credit:

- **Articles per UTC month**: visible hard quota.
- **Chats per UTC month**: visible hard quota.
- **Sentences per article**: visible soft cap; analysis truncates instead of rejecting the article.
- **Source tokens per article**: internal soft cap; article text is tokenized before AI work and truncated at sentence boundaries.
- **AI cost per UTC month**: hidden hard ceiling in integer micro-USD, calculated from the resolved model's reported input and output tokens.

Cached selection analysis, the vocabulary book, and browser TTS remain unmetered.

## Configurable thresholds

Every threshold is environment-driven:

- `PLAN_<TIER>_ARTICLES_PER_MONTH`
- `PLAN_<TIER>_CHATS_PER_MONTH`
- `PLAN_<TIER>_SENTENCES_PER_ARTICLE`
- `PLAN_<TIER>_SOURCE_TOKENS_PER_ARTICLE`
- `PLAN_<TIER>_COST_MICRO_USD_PER_MONTH`
- `OPENAI_TOKEN_ENCODING`
- `OPENAI_RATE_CARD_VERSION`
- `OPENAI_MODEL_INPUT_MICRO_USD_PER_MILLION`
- `OPENAI_MODEL_OUTPUT_MICRO_USD_PER_MILLION`
- `USAGE_RESERVATION_TTL_SECONDS`
- `PRELOAD_WORKER_LEASE_SECONDS`

Defaults are provisional and documented in `.env.example`; changing them requires no code change.

## Cost accounting

`UsageTally` records model, input tokens, output tokens, total tokens, estimated input tokens, and calculated micro-USD. Monetary arithmetic uses integers only:

```text
input_cost = ceil(input_tokens × input_rate_micro_usd_per_million / 1,000,000)
output_cost = ceil(output_tokens × output_rate_micro_usd_per_million / 1,000,000)
actual_cost = input_cost + output_cost
```

The rate-card version and raw token counts are retained with finalized usage events. Unknown model pricing fails closed before dispatch when reservation enforcement is enabled. During default-off shadow rollout, unavailable pricing is reported as `pricing_available=false` without claiming a zero monetary cost, and AI remains available.

Before each metered operation, the service reserves a conservative estimate based on actual prompt/chunk size, every configured fallback-agent turn, each call's maximum completion output, tool/framing growth, and a 25% safety margin. The default is two fallback turns per chunk and deployments may configure up to eight; reservation and runtime use the same configured count. Finalization replaces the estimate with provider-reported actual cost; already-incurred overage is committed and blocks future reservations. A known failure releases the visible allowance and unused reservation. An ambiguous provider dispatch does not silently erase estimated cost.

## Usage state

The usage subsystem stores:

1. **Monthly aggregate** keyed by user and `YYYY-MM`, containing committed and reserved article, chat, and cost counters plus snapshotted limits.
2. **Operation record** keyed by UUID v7, containing payload hash, pinned period, plan/rate-card snapshots, reservation values, state (`reserved`, `finalized`, `released`), expiry, and result reference.
3. **Append-only events** for reserve, finalize, and release transitions.

Admission checks `committed + reserved + requested` against the monthly snapshot. Reusing an operation ID with another payload returns conflict; retrying the same payload returns the recorded state and never reserves twice.

Production DynamoDB writes that change aggregate, operation, and event state use transactional conditional writes. The JSON implementation provides equivalent process-local semantics for development and tests.

## Plan and period policy

- Usage periods are UTC calendar months.
- The first reservation snapshots the effective plan and numeric limits for that month.
- Upgrades may only increase the current month's snapshot.
- Downgrades and cancellations apply to the next UTC-month snapshot.
- The reservation's period remains pinned through asynchronous completion, including month rollover.
- `/billing/me` reports current billing plan, quota plan, committed and pending visible usage, remaining quota, reset time, sentence/source-token limits, and 80% warnings. Hidden cost values are not returned.

## Article input control

Article text is tokenized before AI dispatch. Both sentence and source-token caps are applied at sentence boundaries. The earlier limit wins. Selection is an order-preserving prefix: processing stops before the first complete sentence that would exceed either cap, and later sentences are not skipped into the result. The response records detected versus analyzed sentences and source tokens so truncation is explainable.

Every pipeline batch also stays within a configurable/model-safe input envelope. Parallel batches reserve hidden cost before dispatch, so their combined estimates cannot exceed the user's monthly ceiling.

## Request flows

### Preload

1. Extract and tokenize the article.
2. Apply sentence and source-token caps.
3. Reserve one article and estimated cost using `preload_id` as operation identity.
4. Persist the pinned period, operation ID, payload hash, limits, and rate-card version with the preload and SQS message.
5. Worker claims a renewable/reclaimable lease.
6. Worker performs AI calls and captures actual usage.
7. Ready publication, usage finalization, operation transition, and audit event are committed atomically or recoverably as one logical transition.
8. Known failure releases article reservation; retry is idempotent.

### Chat

The extension sends a UUID v7 request ID. The backend reserves one chat and estimated cost, executes the model, then finalizes. Failure releases the chat. A completed retry returns the stored response without calling the model again.

### Selection analysis

Cached analysis bypasses usage reservation. A cache miss reserves hidden cost only and follows the same idempotent settlement.

## Recovery and observability

- Preload `running` ownership uses lease ID, expiry, and attempt count; an expired lease is reclaimable.
- Expired reservations are lazily reconciled before the user's next reservation. A scheduled global sweeper is deferred.
- `ready + reserved` finalizes on retry instead of returning early.
- Enqueue failures release their reservation and mark the preload failed.
- Structured metrics cover rejected reservations, reserve/finalize/release, estimated versus actual cost, lease recovery, stale reservations, and usage-finalization errors.

## Compatibility and rollout

- Existing usage rows remain readable; missing new fields default to zero and initialize a snapshot lazily.
- Existing error codes remain stable, including `token_budget_exceeded`, even though the internal ceiling becomes monetary.
- Roll out additively: capture token classes and shadow cost first, then enable reservation enforcement through `USAGE_RESERVATION_ENABLED`.
- Persist hidden shadow cost totals and keep raw visible counters aligned with committed counters so enforcement can be enabled, rolled back, and re-enabled without resetting or undercounting the current month.
- Keep raw monthly tokens during migration for rollback and calibration.

## Verification

Tests must prove:

- Exact boundary enforcement under concurrent reservations.
- No double charge under duplicate request/SQS delivery.
- Correct reserve/finalize/release and non-negative counters.
- Cost calculation for input/output rates and unknown-model failure.
- Long-sentence and long-article token truncation.
- Pinned-period finalization over month rollover.
- Upgrade ratcheting and deferred downgrade.
- Enforcement enable/rollback/re-enable reconciliation for visible usage and shadow cost.
- Worker lease recovery and `ready + reserved` repair.
- Cached selection remains free.
- Billing API pending/remaining/warnings contract.
