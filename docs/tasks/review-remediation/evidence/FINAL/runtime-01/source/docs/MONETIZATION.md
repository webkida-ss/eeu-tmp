# Monetization Strategy

> Review update (2026-09-09): see the [strategy proposal](strategy/MONETIZATION_STRATEGY.md),
> [code and economics review](strategy/STRATEGY_REVIEW.md), and
> [implementation roadmap](strategy/MONETIZATION_ROADMAP.md). The review identifies
> corrections to the habit metric, vocabulary UX assumption, and Max profit-rule
> calculation below. Existing runtime prices are unchanged; the proposal is not
> authorization to launch or alter billing.

Companion to [BILLING.md](BILLING.md) (mechanics) — this doc covers *what to
sell on which plan and why*. Plans: `basic` (free) / `pro` / `max`.
The prices and limits below are approved for the paid pilot and remain subject
to evidence-based revision before broad public promotion (see §3).

## 1. Feature-to-plan matrix

Guiding rule: **gate what costs money, keep what builds habit free.**
Launch with quota-only differentiation because it is easy to explain and maps
directly to cost. Do not introduce plan-specific features during the pilot.

| Feature | Marginal cost | basic | pro | max | Rationale |
| --- | --- | --- | --- | --- | --- |
| Monthly price (tax-inclusive pilot) | — | JPY 0 | JPY 1,480 | JPY 3,980 | Priced so worst-case AI cost leaves ≥50% residual. |
| Article preload analysis | High (~JPY 2–8/article) | 3/mo | 40/mo | 120/mo | The core cost driver; quota is the paywall. |
| Sentences per article | Scales with above | 50 | 150 | 300 | Truncation on long articles is the built-in upsell. |
| Follow-up chat | Low (~JPY 0.1/msg) | 15/mo | 400/mo | 1,200/mo | Cheap but abusable; paid limits remain finite. |
| Selection analysis (cached) | Zero | Free | Free | Free | Answers from preload cache; keep unmetered. |
| Selection analysis (uncached) | Low–mid | Metered under provider-cost ceiling | ↑ | ↑ | Real cost; the hidden integer micro-USD ceiling covers it. |
| Word book (cross-article) | Zero | **Free, all plans** | — | — | The habit loop and switching cost. Never gate. |
| Per-word TTS / continuous read-aloud | Zero (browser TTS) | **Free** | — | — | Habit + accessibility; gating it buys nothing. |
| Highlighting, 10-language UI, level presets | Zero | **Free** | — | — | Table stakes; gating hurts activation. |

Explicitly **do not gate**: word book, TTS/read-aloud, highlighting, UI
languages, cached selection analysis. These are retention features — a free
user with a growing word book has a reason to return and eventually pay.

## 2. Conversion funnel

Already implemented: article quota errors (402 → upgrade), sentence-cap
truncation notice ("explained the first N of M sentences"), in-panel usage
meter, and the 80%-quota warning. These are the natural paywall moments — a
basic user reading regularly reaches the three-article cap quickly enough to
evaluate Pro.

Worth building later: a monthly recap email with articles read, words saved,
and sentences truncated by the cap. It requires email infrastructure and is
not part of the paid-pilot scope.

Skip for now: time-limited pro trials and discount campaigns — premature
before pricing is validated.

## 3. Pilot pricing and evidence

Use one price per plan for the 5–20-user paid pilot:

- Pro: JPY 1,480/month, tax-inclusive; 40 articles; AI ceiling USD 2.50.
- Max: JPY 3,980/month, tax-inclusive; 120 articles; AI ceiling USD 7.00.

These numbers are derived from hard profit rules: AI ceiling ≤ 30% of
post-Stripe available revenue, articles × ¥8 ≤ AI ceiling, and residual after
Stripe + AI ceiling ≥ 50% of tax-exclusive revenue. Pro remains below full
English-course apps (roughly JPY 2,000–3,300/month). Max sits near the top of
that band for heavy daily readers. Verify the active model's official rate
card before enabling enforcement.

Do not A/B test price in the small pilot. Measure real usage and revisit the
single coherent offer before broad public promotion.

Metrics to watch:

- **Activation**: % of sign-ups with a first preload within 24h.
- **Habit**: users with ≥3 preloads/week (the retention predictor).
- **Quota-hit rate**: % of basic users hitting the article cap or sentence
  truncation per month — the size of the convertible pool.
- **Conversion**: free→pro %, and time from first quota hit to upgrade.
- **Cost**: avg OpenAI cost per active user vs plan price (per tier).

## 4. max-plan justification

Who needs max: heavy daily readers (news professionals, exam crammers),
multi-language learners (10-language support multiplies volume), and users
who read long-form (300-sentence cap matters). It also serves as the price
anchor that makes Pro look inexpensive. At launch Max is about 2.7× Pro on
price and 3× on article allowance; it has no exclusive feature.

Later, not now: **annual discount** (~2 months free) once monthly churn is
measured — worth it if churn >5%/mo. **Team/per-seat** only if organic
signals appear (schools, corporate learning); requires seat management and
is a different product motion. Do not build speculatively.

## 5. Risks

- **Cost blowout**: long articles + expensive model days. Mitigated by the
  hidden monthly integer micro-USD provider-cost ceiling and per-article
  sentence caps. Keep cost ceilings and model rate cards env-tunable; alert
  when a user hits 80% of the active cost ceiling.
- **Multi-accounting**: free tier reset via new Google accounts. SSO raises
  friction but doesn't stop it; three articles/mo limits the exposure. Accept
  the residual risk and monitor signup spikes.
- **Churn drivers**: "read less this month" cancellations (seasonal usage),
  quota anxiety (users hoarding analyses), and model-quality regressions.
  Counter with the word book as accumulated value, rollover experiments if
  quota anxiety shows up in feedback, and eval-gated model changes.
- **Platform risk**: Chrome-only distribution; a Web Store policy change is
  existential. Keep the backend extension-agnostic (it already is).

## 6. Rollout

**Now** (before paid pilot)
- Instrument activation, habit, quota-hit, and provider-cost metrics.
- Measure real cost per article per tier; sanity-check the integer micro-USD
  provider-cost ceilings and model-specific rates.
- Deploy composite-meter storage, native TTL, and structured events in a
  **shadow** phase with `USAGE_RESERVATION_ENABLED=false`. Enable enforcement
  only after staging verifies concurrent reservations, idempotent replay,
  lease recovery, and pending-result repair.

**Next** (first paid cohort)
- Offer Pro at JPY 1,480 and Max at JPY 3,980 to every pilot participant.
- Verify purchase, cancellation, refund, and entitlement transitions.
- Review price and limits only if pilot evidence invalidates an assumption.

**Later** (post product-market signal)
- Publish a plan-comparison page and consider a monthly recap email.
- Consider annual discounts if churn warrants and priority processing under
  real load.
- Team plan only on organic demand; revisit quotas from usage percentiles.

The product meter is intentionally simple: customers see article/chat used,
pending, remaining, and the next **UTC calendar month** reset. The hidden cost
policy keeps raw tokens, model/rate data, and micro-USD out of the product UI.
Raw token totals are retained only for migration, calibration, and rollback;
they are not an active hard ceiling. With reservation enforcement enabled,
admission uses the hidden integer micro-USD ceiling from pinned model-specific
input/output rates.
Plan upgrades can raise a pinned snapshot during a month; a downgrade is
deferred so a customer never loses already granted capacity.

For operational recovery and the full threshold/configuration contract, see
[BILLING.md](BILLING.md). Pricing experiments must change plan environment
values and pinned rate-card versions together; they must not bypass the
reservation idempotency contract.
