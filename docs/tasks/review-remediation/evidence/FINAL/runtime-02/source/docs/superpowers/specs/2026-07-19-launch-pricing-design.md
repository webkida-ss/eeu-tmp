# Launch Pricing Design

## Status

Approved profitable pilot matrix. Do not create live Stripe products until
the active OpenAI model rate card is verified against the cost ceilings
below.

## Goal

Launch in Japan with three quota-only plans whose **worst-case AI cost
cannot erase contribution margin**. Price and quota are derived from
profit rules, not from growth optimism.

## Hard Profit Rules

1. **AI cost ceiling ≤ 30%** of (tax-exclusive revenue − Stripe fee).
2. **Visible articles × ¥8 ≤ AI cost ceiling** (P90 article cost planning).
3. **Residual after Stripe + AI ceiling ≥ 50%** of tax-exclusive revenue.
4. **Free-tier AI ceiling ≤ ¥30** (~USD 0.20).

Planning assumptions:

- Customer prices are tax-inclusive; consumption tax 10%.
- Stripe Japan domestic cards: 3.6% of the charged amount.
- FX planning rate: JPY 150 / USD.
- Article AI cost planning range: JPY 2–8; P90 planning uses JPY 8.
- Chat AI cost planning: about JPY 0.1.
- Infrastructure is low at pilot scale and is covered by the residual, not
  by shrinking the AI ceiling further.

## Recommended Plans

### Basic

- Price: JPY 0
- Article analyses: 3 per UTC calendar month
- Chats: 15 per UTC calendar month
- Sentences per article: 50
- Source-token ceiling per article: 12,000
- Hidden provider-cost ceiling: USD 0.20 per month (`200000` micro-USD)
- Role: complete product trial with minimal free-user cost exposure.

Check: 3 × ¥8 = ¥24 ≤ ¥30.

### Pro

- Price: JPY 1,480 per month, tax-inclusive
- Article analyses: 40 per UTC calendar month
- Chats: 400 per UTC calendar month
- Sentences per article: 150
- Source-token ceiling per article: 36,000
- Hidden provider-cost ceiling: USD 2.50 per month (`2500000` micro-USD)
- Role: default plan for weekday English reading.

Unit economics:

| Item | Amount |
| --- | ---: |
| Tax-exclusive revenue | ¥1,345 |
| Stripe 3.6% | ¥53 |
| Available after Stripe | ¥1,292 |
| AI cost ceiling | ¥375 (29% of available) |
| Residual | ¥917 (68% of tax-exclusive) |
| Articles × ¥8 | ¥320 ≤ ¥375 |

### Max

- Price: JPY 3,980 per month, tax-inclusive
- Article analyses: 120 per UTC calendar month
- Chats: 1,200 per UTC calendar month
- Sentences per article: 300
- Source-token ceiling per article: 72,000
- Hidden provider-cost ceiling: USD 7.00 per month (`7000000` micro-USD)
- Role: heavy daily / long-form / multi-language readers.

Unit economics:

| Item | Amount |
| --- | ---: |
| Tax-exclusive revenue | ¥3,618 |
| Stripe 3.6% | ¥143 |
| Available after Stripe | ¥3,475 |
| AI cost ceiling | ¥1,050 (30% of available) |
| Residual | ¥2,425 (67% of tax-exclusive) |
| Articles × ¥8 | ¥960 ≤ ¥1,050 |

All plans share the same features at launch. Max differs from Pro only by
quota. Do not add a premium model, queue priority, annual billing, trial,
or discount for the first cohort.

## Why This Replaces the Previous Pilot Matrix

The previous Pro at JPY 980 / 50 articles / USD 3 failed the profit rules:

- AI ceiling (~¥450) was about **52%** of post-Stripe available (~¥856).
- 50 × ¥8 = ¥400 nearly exhausted the ceiling before chats and long articles.
- Residual after the AI ceiling was too thin for AWS, support, refunds, and
  FX movement.

Raising Pro to JPY 1,480 and cutting the article allowance to 40 restores a
~68% residual while keeping Pro below full English-course apps
(roughly JPY 2,000–3,300/month). Max stays about 2.7× Pro on price with a
3× article allowance so the ladder stays explainable.

## Pilot Rules

- Offer one price per plan. Do not A/B test price in a 5–20 person cohort.
- Charge the real recurring price and exercise cancel / refund paths.
- Keep features identical across plans.
- Do not advertise pilot prices as permanently guaranteed.
- Reopen pricing only when measured cost invalidates a recorded assumption.

## Evidence Required Before Broad Public Promotion

- Active OpenAI model name and official input/output rates.
- P50 / P90 provider cost per successful article.
- Cost by sentence count and source-token count.
- Average and P90 chats per active user.
- Basic quota-hit rate and free→Pro conversion.
- Share of Pro / Max users hitting visible or hidden ceilings.
- Checkout, cancel, refund, and support rates.
- Tax treatment confirmed by a qualified professional.

## Decision Rules

- Keep this matrix if P90 monthly provider cost stays at or below the AI
  ceiling while users still reach first value.
- If the hidden ceiling blocks normal use before the visible quota, lower
  visible articles first; raise price only if conversion remains healthy.
- If P90 article cost rises above ¥8, shrink quotas or ceilings before
  cutting price.
- Do not return to Pro JPY 980 / 50 articles unless measured P90 article
  cost is low enough to satisfy all four hard rules.

## Configuration Mapping

```text
PLAN_BASIC_ARTICLES_PER_MONTH=3
PLAN_BASIC_CHATS_PER_MONTH=15
PLAN_BASIC_SENTENCES_PER_ARTICLE=50
PLAN_BASIC_SOURCE_TOKENS_PER_ARTICLE=12000
PLAN_BASIC_COST_MICRO_USD_PER_MONTH=200000

PLAN_PRO_ARTICLES_PER_MONTH=40
PLAN_PRO_CHATS_PER_MONTH=400
PLAN_PRO_SENTENCES_PER_ARTICLE=150
PLAN_PRO_SOURCE_TOKENS_PER_ARTICLE=36000
PLAN_PRO_COST_MICRO_USD_PER_MONTH=2500000

PLAN_MAX_ARTICLES_PER_MONTH=120
PLAN_MAX_CHATS_PER_MONTH=1200
PLAN_MAX_SENTENCES_PER_ARTICLE=300
PLAN_MAX_SOURCE_TOKENS_PER_ARTICLE=72000
PLAN_MAX_COST_MICRO_USD_PER_MONTH=7000000
```

Stripe test helper amounts: Pro `1480`, Max `3980` (JPY, tax-inclusive).

Raw token budgets remain migration and calibration fields only.
