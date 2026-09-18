"""Plan entitlement checks and monthly usage metering.

Untangle's half of the plan story: `accounts` decides *which* plan a
subscription grants, this module decides what that plan lets you do
(articles, chats, tokens). Framework-free. Handlers build an
EntitlementGuard per request and pass it to the metered use cases; the
guard enforces the plan's quotas with the monthly token budget as a hidden
double-check, and records consumption after successful requests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from accounts import SubscriptionRepository
from accounts.plans import normalize_utc
from accounts.plans import resolve_plan_id as _resolve_plan_id
from core.plans import BASIC_PLAN_ID, PLAN_CATALOG, PlanLimits, get_plan_limits
from repositories.usage_repository import UsageRepository


class EntitlementError(Exception):
    """A plan limit blocks the request.

    `code` is a stable machine-readable identifier the extension maps onto
    a localized message; `status_code` is the transport hint (402 = upgrade
    solves it, 429 = hard monthly ceiling).
    """

    def __init__(self, message: str, *, code: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def current_month(now: datetime | None = None) -> str:
    moment = normalize_utc(now or datetime.now(UTC))
    return moment.strftime("%Y-%m")


def resolve_plan_id(
    subscription: dict[str, Any] | None,
    now: datetime | None = None,
    *,
    provider_mode: str = "stripe",
) -> str:
    """The effective plan for a stored subscription record.

    The rule itself (active status, period expiry, renewal grace) is
    billing-generic and lives in `accounts`; this wrapper binds it to
    Untangle's plan catalog so callers keep a two-argument signature.
    """
    return _resolve_plan_id(subscription, PLAN_CATALOG, now, provider_mode=provider_mode)


@dataclass
class EntitlementGuard:
    plan: PlanLimits
    usage_repository: UsageRepository
    user_id: str
    month: str
    subscription: dict[str, Any] | None = None

    def _usage(self) -> dict[str, Any]:
        return self.usage_repository.get_month(self.user_id, self.month)

    def _check_token_budget(self, usage: dict[str, Any]) -> None:
        if int(usage.get("tokens") or 0) >= self.plan.tokens_per_month:
            raise EntitlementError(
                "Monthly usage limit reached.",
                code="token_budget_exceeded",
                status_code=429,
            )

    def check_article(self) -> None:
        usage = self._usage()
        self._check_token_budget(usage)
        if int(usage.get("articles") or 0) >= self.plan.articles_per_month:
            raise EntitlementError(
                f"Monthly article limit reached ({self.plan.articles_per_month}).",
                code="article_quota_exceeded",
                status_code=402,
            )

    def check_chat(self) -> None:
        usage = self._usage()
        self._check_token_budget(usage)
        if int(usage.get("chats") or 0) >= self.plan.chats_per_month:
            raise EntitlementError(
                f"Monthly chat limit reached ({self.plan.chats_per_month}).",
                code="chat_quota_exceeded",
                status_code=402,
            )

    def check_tokens(self) -> None:
        self._check_token_budget(self._usage())

    # Consumption is recorded after the request succeeds, so a failed
    # analysis never burns quota. The check→record window is racy under
    # parallel requests by the same user; acceptable at this scale.
    def record_article(self, *, tokens: int = 0) -> None:
        self.usage_repository.add(self.user_id, self.month, articles=1, tokens=tokens)

    def record_chat(self, *, tokens: int = 0) -> None:
        self.usage_repository.add(self.user_id, self.month, chats=1, tokens=tokens)

    def record_tokens(self, tokens: int) -> None:
        if tokens > 0:
            self.usage_repository.add(self.user_id, self.month, tokens=tokens)


def build_guard(
    subscription_repository: SubscriptionRepository,
    usage_repository: UsageRepository,
    user_id: str,
    now: datetime | None = None,
    *,
    provider_mode: str = "stripe",
) -> EntitlementGuard:
    subscription = subscription_repository.get(user_id)
    plan_id = resolve_plan_id(subscription, now, provider_mode=provider_mode)
    return EntitlementGuard(
        plan=get_plan_limits(plan_id),
        usage_repository=usage_repository,
        user_id=user_id,
        month=current_month(now),
        subscription=subscription,
    )


def usage_summary(guard: EntitlementGuard) -> dict[str, Any]:
    usage = guard.usage_repository.get_month(guard.user_id, guard.month)
    has_snapshot = bool(usage.get("plan_id"))
    quota_plan_id = str(usage.get("plan_id") or guard.plan.plan_id)
    quota_plan = get_plan_limits(quota_plan_id)
    articles_used = int(
        usage.get("committed_articles") if has_snapshot else usage.get("articles") or 0
    )
    chats_used = int(usage.get("committed_chats") if has_snapshot else usage.get("chats") or 0)
    articles_pending = int(usage.get("reserved_articles") or 0)
    chats_pending = int(usage.get("reserved_chats") or 0)
    article_limit_snapshot = usage.get("article_limit")
    chat_limit_snapshot = usage.get("chat_limit")
    articles_limit = int(
        guard.plan.articles_per_month
        if not has_snapshot or article_limit_snapshot is None
        else article_limit_snapshot
    )
    chats_limit = int(
        guard.plan.chats_per_month
        if not has_snapshot or chat_limit_snapshot is None
        else chat_limit_snapshot
    )
    warnings: list[str] = []
    if _at_warning_threshold(articles_used + articles_pending, articles_limit):
        warnings.append("article_quota_approaching")
    if _at_warning_threshold(chats_used + chats_pending, chats_limit):
        warnings.append("chat_quota_approaching")

    # A paid plan with a scheduled cancellation shows when it will end
    # (Stripe cancel_at; the plan stays active until then).
    plan_ends_at = None
    if guard.plan.plan_id != BASIC_PLAN_ID and guard.subscription:
        plan_ends_at = guard.subscription.get("cancel_at")

    return {
        "plan": guard.plan.plan_id,
        "quota_plan": quota_plan_id,
        "month": guard.month,
        "articles_used": articles_used,
        "articles_pending": articles_pending,
        "articles_limit": articles_limit,
        "articles_remaining": max(0, articles_limit - articles_used - articles_pending),
        "chats_used": chats_used,
        "chats_pending": chats_pending,
        "chats_limit": chats_limit,
        "chats_remaining": max(0, chats_limit - chats_used - chats_pending),
        "reset_at": _reset_at(guard.month),
        "sentences_per_article": int(
            usage.get("sentences_per_article") or quota_plan.sentences_per_article
        ),
        "source_tokens_per_article": int(
            usage.get("source_tokens_per_article") or quota_plan.source_tokens_per_article
        ),
        "plan_ends_at": plan_ends_at,
        "warning_codes": warnings,
    }


def _at_warning_threshold(used_and_pending: int, limit: int) -> bool:
    return limit > 0 and used_and_pending * 100 >= limit * 80


def _reset_at(month: str) -> str:
    year, month_number = (int(part) for part in month.split("-", 1))
    if month_number == 12:
        reset = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        reset = datetime(year, month_number + 1, 1, tzinfo=UTC)
    return reset.isoformat()
