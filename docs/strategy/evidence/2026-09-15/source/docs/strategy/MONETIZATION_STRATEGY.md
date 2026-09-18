# Monetization and market-entry strategy

Date: 2026-09-09. Status: recommended decision proposal, not a launch approval.
Code baseline: `3c4fae5d2c03e6592ebd1f51debf5c798294a476`.
The [September 15 implementation checkpoint](IMPLEMENTATION_STATUS.md) records
completed reliability remediation and separates it from remaining product and
commercial validation. Market and cost scenarios below retain their original date.

## Recommendation

Focus first on Japanese-speaking engineers and adjacent product professionals
who already read public English technical articles in desktop Chrome and want
to understand the English, not merely obtain a Japanese translation. Sell
continuity of real reading with contextual explanations. Make Pro at JPY 1,480
per month the primary offer to validate; keep Basic as a bounded evaluation
and Max as an available heavy-use option. Do not change production pricing as
part of this proposal. Resolve the Max cost-rule violation before charging.

This is the best current hypothesis given product fit and a small-team
execution constraint, not an empirically proven optimal market. No production
revenue, audience, conversion, retention, cost distribution, or interviews were
available. Assume one full-time engineer and a founder with about five hours
per week for research and distribution; revise the roadmap if capacity differs.

Read the [code and strategy review](STRATEGY_REVIEW.md),
[implementation roadmap](MONETIZATION_ROADMAP.md), and
[primary-source competitor research](../research/2026-09-09-reading-market.md).
Existing [billing mechanics](../BILLING.md) remain authoritative for behavior.
This proposal revises strategic assumptions in [MONETIZATION.md](../MONETIZATION.md),
but does not supersede approved prices or release requirements.

## Customer and value proposition

| Segment | Hypothesized need and fit | Decision |
| --- | --- | --- |
| Japanese engineers/product professionals reading public English articles weekly | Recurring real material, desktop workflow, interest in nuance and syntax | First cohort; validate willingness to pay |
| General English beginners | Need curated material and more teaching scaffolding | Defer; current arbitrary-page workflow may overwhelm |
| Exam learners | Clear motivation, but exam content and outcomes missing | Interview only if initial niche fails |
| Readers seeking instant translation only | Low reason to pay for explanation | Do not optimize acquisition for this audience |
| Schools and enterprises | Seats, procurement, privacy controls, reporting needed | Defer until repeated unsolicited demand |

Job story: when a sentence in an article blocks my understanding, explain its
structure and meaning in place so I can continue reading and revisit it later.
Initial copy concept: “Understand the English behind the translation, on the
article you already want to read.” Localize public copy into Japanese in a
later implementation task; repository documents stay English.

Demonstrate an original or licensed technical paragraph, a difficult sentence,
a contextual explanation, and return to reading in a 45–60 second recording.
Do not claim proven learning gains, time savings, universal site compatibility,
or confidential-workplace suitability. Test those outcomes before advertising.
The current cross-article vocabulary promise needs implementation repair.

Competitive alternatives include free translation, general-purpose chat, and
established reading/learning tools. Contextual AI explanation is a positioning
hypothesis rather than a durable moat. The practical differentiators to earn
are reliable page integration, useful explanations on technical prose, quick
first value, and accessible accumulated learning material. See the linked
research for verified competitor features and pricing caveats.

## Offer and monetization

Keep quota-only feature parity for the first cohort: Basic 3 articles/15 chats,
Pro 40/400, Max 120/1,200 per UTC month; sentence caps remain 50/150/300.
Keep existing cached explanations and vocabulary accessible without a paid
plan. Display price, limits, billing cadence, cancellation, and reset timing
before checkout. Explain service limits without exposing model/token internals.

Pro is the default recommendation, not a preselected payment. Max should be
visible in a comparison but need not occupy equal promotional space. Offer it
only after its economics pass; if they do not, postpone Max sales rather than
silently reducing a purchased allowance. No annual plan, lifetime deal,
referral system, premium model, or team billing in the first experiment.

Basic is an evaluation allowance, not enough new analyses for a daily habit.
Use a cached, original sample to show value before spending the allowance;
let users then try their own public article. Do not raise free allowances
until cost and activation data justify it. A return visit can reuse an already
analyzed article without requiring a new paid AI operation. Confirm the replay
and access behavior in implementation tests rather than assume it.

Upgrade prompts should follow demonstrated value or a clearly explained limit.
An opaque cost block while visible quota remains is a trust failure to measure,
not a conversion tactic. Do not automatically tell a Max user to upgrade when
no higher plan exists. Give support and reset information with honest limits. Before any paid pilot,
validate delivery of advertised allowances under supported workloads or disclose
additional restrictions before checkout in understandable customer-facing units.
A hidden budget and a message after rejection do not satisfy this gate; if an
honest offer cannot yet be supported, postpone charging.

## Economics and constraints

Planning only: 10% tax-inclusive price treatment, JPY 150/USD, domestic card
Payments fee 3.6%, plus a 0.7% Billing allowance. Stripe currently lists these
Payments and pay-as-you-go Billing rates; actual account terms, extra services,
refund costs, and tax treatment need confirmation. Sources accessed 2026-09-09:
[Payments](https://stripe.com/jp/payments) and
[Billing](https://stripe.com/jp/billing/pricing).

Use `net = price / 1.10`, `fees = price * 0.043`,
`AI = USD ceiling * FX`, and `residual = net - fees - AI`.
Residual is before infrastructure, support, refunds, acquisition, and fixed
costs. It is not profit or a measured gross margin.

| Plan | Price | Net revenue | Fee allowance | AI ceiling at 150 | Residual | AI / (net - fees) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Pro | 1,480 | 1,345.45 | 63.64 | 375 | 906.81 | 29.26% |
| Max | 3,980 | 3,618.18 | 171.14 | 1,050 | 2,397.04 | 30.46% |

Max violates the documented 30% rule, even using only the original 3.6% fee
(30.22%). Rounding it to 30% hid the violation. At JPY 180/USD, Pro and Max
reach 35.11% and 36.55% under the revised fee assumption. At JPY 150/USD,
allowable ceilings for this rule are at most USD 2.564 and USD 6.894; at 180,
USD 2.136 and USD 5.745. These are computed boundaries, not proposed deployed
settings. Freeze actual model/rates and choose a conservative FX budget before
approving any price/ceiling revision. Preserve existing subscription promises.

The existing cost assumptions also imply Max articles plus chats cost
`120 * 8 + 1200 * 0.1 = JPY 1,080`, exceeding its JPY 1,050 ceiling before
uncached selections. Pro gives JPY 360 against 375, leaving very little buffer.
Multiplying per-article P90 by count is a stress scenario, not a measured P90
monthly bill. Measure the joint workload, retries, failures and cache misses.
The ceiling bounds spending only when calibrated enforcement actually runs;
repository defaults alone cannot prove live protection.

Contribution planning: provisionally reserve JPY 200 per paid user-month for
variable infrastructure/support/refunds. Pro then leaves about JPY 707 at
FX 150. With 100 paid Pro users and 1,000 free users consuming the full JPY 30
free ceiling, this becomes about JPY 40,700/month before fixed costs and
acquisition. It is a sensitivity example, not a revenue forecast.

Illustrative Pro revenue goals require 68 subscribers for JPY 100,000 monthly
gross billings and 338 for JPY 500,000. Neither is take-home income. With that
JPY 707 contribution, a provisional three-month CAC payback cap is about
JPY 2,120 per payer before free-tier burden. At 5% activated-to-paid conversion,
that allows only about JPY 106 per activated user; actual allowable spend is
lower after free usage and founder acquisition time. Do not buy broad ads now.
Do not estimate LTV as margin divided by churn before cohorts stabilize.

## Acquisition plan

Start with one audience and one reusable demonstration. Founder-led interviews
and participation in relevant engineering/English-reading communities precede
SEO or paid media. These are proposed activities; no outreach or publication
is authorized by creating this document.

| Experiment | Deliverable and effort budget | Evidence and decision |
| --- | --- | --- |
| Problem interviews | 10 qualified readers; 5 founder hours in week 1 | Ask for last actual reading obstacle, current workaround, frequency, and prior spending; seek 6 recurring-problem accounts, otherwise revise segment |
| Demonstration | One original article, one short video, one concise landing page; 4 founder hours | In 10 sessions, at least 7 explain the value accurately and 6 reach value unaided; improve onboarding if not |
| First cohort | Invite up to 20 qualified evaluators through permitted personal/community contacts; no paid incentives | At least 5 genuine recurring-price payers within 30 days is a directional signal; record numerator/denominator and objections |
| Content distribution | Two useful technical-English breakdowns over 4 weeks, each linking to the same demo | Track qualified activations and retained payers per founder hour; discontinue channels attracting translation-only users |
| Expansion | A second comparable cohort after fixes | Require renewal and contribution evidence before increasing spend |

These small-sample cutoffs are management triggers, not statistical proof or
industry benchmarks. Avoid changing price, acquisition audience and onboarding
simultaneously. If users value the outcome but never return, fix retention; if
retained users do not pay, investigate alternatives and willingness to pay.
If there is no recurring problem, change the niche before building more tools.

Landing-page structure: specific use case → in-place demo → supported workflow
and limitations → free evaluation → Pro/Max comparison → privacy/support and
cancellation. Link to official store installation when available. Use an
optional self-reported acquisition source or a coarse campaign code; never
infer source by collecting browsing history. Organic content is not free:
include founder time in channel economics. Do not solicit incentivized reviews.

## Measurement and pilot decisions

North-star candidate: weekly returning readers who use an explanation on at
least two distinct days, including cached revisits. This measures engagement,
not demonstrated learning. Use optional feedback to validate understanding.

| Metric | Exact initial definition |
| --- | --- |
| Activation within 24h | Among new signed-in users whose full 24h elapsed, those with first own-article explanation rendered within 24h / all users in that same cohort; report sample demo separately |
| D7 return | Among activated users observed through day 13, those with an explanation rendered during days 7–13 / all users in that same cohort |
| Paid conversion by day 30 | Among activated users with full 30-day observation, those with first verified paid subscription within 30 days / all users in that same cohort; exclude mock/test/internal accounts |
| Checkout completion | Among unique checkout attempts with full 24h observation, those yielding verified entitlement within 24h / all attempts in that same cohort; report later settlement separately |
| Paid renewal | Successfully renewed subscriptions by scheduled renewal + 7 days / all subscribers whose scheduled renewal + 7 days elapsed, including advance cancellations as nonrenewals; separate first/second renewal, cancellation and failed collection |
| Unexpected limit block | Paid active users blocked by hidden cost with visible capacity remaining / paid active users; also count affected operations |
| Cost and contribution | All provider attempts including failures, infrastructure, fees, refunds and support; report missing cost as unknown and segment by plan |

Minimal new product events: first run, sign-in completed, sample viewed,
explanation rendered (new/cached), word revisited, upgrade viewed, checkout
started. Use existing terminal activity for server completion/error/cost where
possible. Entitlement activation/renewal comes from verified billing events,
not a success-page view. Deduplicate retries with stable event/source identity;
new persisted `id` fields use UUID v7. No article text, full URL, prompt, email,
credentials or model pricing in product analytics. Propose 90-day event
retention, deletion on account deletion and coarse aggregate retention; finalize
with the data policy. Do not copy operational model/cost fields to client events.

At day 30 inspect counts, recordings/feedback and cost, not just percentages.
At days 60–90 seek two renewal opportunities for the earliest cohort. A
provisional expansion gate is at least 10 matured first-renewal opportunities and at least
70% first renewal, with advance cancellations counted as nonrenewals and a fixed
seven-day settlement window. Report second renewal separately as it matures.
Also require positive measured contribution including free acquisition burden,
and no unexplained premature blocks. If the sample is smaller, keep the pilot
bounded. Passing this gate permits a larger experiment, not a claim of PMF.

## Deferred options and triggers

- Annual billing: only after multiple mature monthly cohorts show recurring
  value; high churn alone is a reason to investigate, not to lock users in.
- Review scheduling/export: build only if users revisit saved material and
  repeatedly ask for a better workflow; first repair basic cross-article access.
- Teams: interview organizations after at least three independent inbound
  requests; do not treat ten supported UI languages as ten validated markets.
- One-off packs: consider only if retained users prefer occasional bursts;
  assess metering complexity and unit economics before adding a second model.
- Large admin UI, mobile expansion and premium models: defer behind activation,
  reliability, transparent allowances and retention.

Open inputs for the founder: reachable audience, current live users/revenue,
monthly income goal, weekly capacity, budget, and acceptable support load.
These would refine priority and runway; the present plan can start with a
code-level measurement and onboarding design without inventing those inputs.
