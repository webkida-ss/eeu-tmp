"""Subscription plan definitions and their usage limits.

Framework-free. Defaults match the approved paid-pilot plan and remain
overridable via environment variables, so evidence-based tuning never
requires a code change. `max` is deliberately finite: it is a large
allowance, not an unlimited plan.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from accounts import PlanCatalog

BASIC_PLAN_ID = "basic"
PAID_PLAN_IDS = ("pro", "max")

# What `accounts` needs to know about plans: the identifiers, nothing more.
# The quota numbers below are Untangle's own business and stay out of the
# shared package.
PLAN_CATALOG = PlanCatalog(basic_plan_id=BASIC_PLAN_ID, paid_plan_ids=PAID_PLAN_IDS)


@dataclass(frozen=True)
class PlanLimits:
    plan_id: str
    articles_per_month: int
    chats_per_month: int
    # Per-article analysis cap; long articles are analyzed up to this many
    # sentences (graceful truncation, surfaced in the panel).
    sentences_per_article: int
    # Internal per-article source-size and monthly model-cost safety limits.
    source_tokens_per_article: int
    cost_micro_usd_per_month: int
    # Hidden monthly safety valve on OpenAI usage, double-checking the
    # article/chat quotas against abnormal consumption patterns.
    tokens_per_month: int


def _limit(name: str, default: int) -> int:
    return max(1, int(os.getenv(name, str(default))))


def load_plans() -> dict[str, PlanLimits]:
    return {
        "basic": PlanLimits(
            plan_id="basic",
            articles_per_month=_limit("PLAN_BASIC_ARTICLES_PER_MONTH", 3),
            chats_per_month=_limit("PLAN_BASIC_CHATS_PER_MONTH", 15),
            sentences_per_article=_limit("PLAN_BASIC_SENTENCES_PER_ARTICLE", 50),
            source_tokens_per_article=_limit("PLAN_BASIC_SOURCE_TOKENS_PER_ARTICLE", 12_000),
            cost_micro_usd_per_month=_limit("PLAN_BASIC_COST_MICRO_USD_PER_MONTH", 200_000),
            tokens_per_month=_limit("PLAN_BASIC_TOKENS_PER_MONTH", 200_000),
        ),
        "pro": PlanLimits(
            plan_id="pro",
            articles_per_month=_limit("PLAN_PRO_ARTICLES_PER_MONTH", 40),
            chats_per_month=_limit("PLAN_PRO_CHATS_PER_MONTH", 400),
            sentences_per_article=_limit("PLAN_PRO_SENTENCES_PER_ARTICLE", 150),
            source_tokens_per_article=_limit("PLAN_PRO_SOURCE_TOKENS_PER_ARTICLE", 36_000),
            cost_micro_usd_per_month=_limit("PLAN_PRO_COST_MICRO_USD_PER_MONTH", 2_500_000),
            tokens_per_month=_limit("PLAN_PRO_TOKENS_PER_MONTH", 3_000_000),
        ),
        "max": PlanLimits(
            plan_id="max",
            articles_per_month=_limit("PLAN_MAX_ARTICLES_PER_MONTH", 120),
            chats_per_month=_limit("PLAN_MAX_CHATS_PER_MONTH", 1_200),
            sentences_per_article=_limit("PLAN_MAX_SENTENCES_PER_ARTICLE", 300),
            source_tokens_per_article=_limit("PLAN_MAX_SOURCE_TOKENS_PER_ARTICLE", 72_000),
            cost_micro_usd_per_month=_limit("PLAN_MAX_COST_MICRO_USD_PER_MONTH", 7_000_000),
            tokens_per_month=_limit("PLAN_MAX_TOKENS_PER_MONTH", 10_000_000),
        ),
    }


PLANS = load_plans()


def get_plan_limits(plan_id: str | None) -> PlanLimits:
    return PLANS.get(plan_id or BASIC_PLAN_ID, PLANS[BASIC_PLAN_ID])
