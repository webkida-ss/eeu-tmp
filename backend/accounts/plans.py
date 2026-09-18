"""Which plans exist, and which one a subscription record currently grants.

Deliberately *not* where quota numbers live. How many articles, chats,
sessions or minutes a plan allows differs per application and belongs to
the host's entitlement layer; accounts only needs the plan identifiers so
Checkout can refuse to sell an unknown one, and the rule that turns a
stored subscription into an effective plan id.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# A subscription only entitles while Stripe considers it live.
ACTIVE_STATUSES = frozenset({"active", "trialing"})

# Grace period covering renewal-webhook delivery lag, so a subscriber is
# never locked out by a few minutes of Stripe latency.
_RENEWAL_GRACE_SECONDS = 86_400
_MAX_UNIX_TIMESTAMP = 253_402_300_799


@dataclass(frozen=True)
class PlanCatalog:
    """The plan identifiers a host application sells.

    `basic_plan_id` is the free tier every account falls back to; it is
    never sold through Checkout. `paid_plan_ids` are the ids Checkout
    accepts and that `STRIPE_PRICE_ID_<PLAN>` is read for.
    """

    basic_plan_id: str = "basic"
    paid_plan_ids: tuple[str, ...] = ("pro", "max")

    def __post_init__(self) -> None:
        if not self.basic_plan_id:
            raise ValueError("basic_plan_id is required.")
        if self.basic_plan_id in self.paid_plan_ids:
            raise ValueError("The basic plan cannot also be a paid plan.")

    @property
    def all_plan_ids(self) -> tuple[str, ...]:
        return (self.basic_plan_id, *self.paid_plan_ids)

    def is_paid(self, plan_id: str | None) -> bool:
        return plan_id in self.paid_plan_ids


def normalize_utc(moment: datetime) -> datetime:
    """Return an aware datetime in UTC and reject ambiguous naive values."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return moment.astimezone(UTC)


def resolve_plan_id(
    subscription: dict[str, Any] | None,
    catalog: PlanCatalog,
    now: datetime | None = None,
    *,
    provider_mode: str = "stripe",
) -> str:
    """The effective plan: the paid one while the subscription is live,
    otherwise the basic plan. Expiry is judged by current_period_end so a
    missed deletion webhook cannot grant service forever."""
    if not subscription:
        return catalog.basic_plan_id
    if subscription.get("status") not in ACTIVE_STATUSES:
        return catalog.basic_plan_id
    plan_id = subscription.get("plan")
    if not isinstance(plan_id, str) or not catalog.is_paid(plan_id):
        return catalog.basic_plan_id

    provenance = subscription.get("entitlement_provider")
    if provenance == "mock":
        return plan_id if provider_mode == "mock" else catalog.basic_plan_id
    if provenance not in (None, "stripe"):
        return catalog.basic_plan_id

    period_end = subscription.get("current_period_end")
    if (
        not isinstance(period_end, int)
        or isinstance(period_end, bool)
        or not 0 < period_end <= _MAX_UNIX_TIMESTAMP
    ):
        return catalog.basic_plan_id
    moment = normalize_utc(now or datetime.now(UTC))
    try:
        expires = datetime.fromtimestamp(period_end, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return catalog.basic_plan_id
    if (moment - expires).total_seconds() > _RENEWAL_GRACE_SECONDS:
        return catalog.basic_plan_id

    return plan_id
