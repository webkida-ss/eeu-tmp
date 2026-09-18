"""Billing use cases: start checkout, open the portal, apply webhooks.

Framework-free. The provider (mock/stripe) does the money part; this layer
owns the subscription records that the host's entitlement layer reads.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from core.ids import generate_uuid7

from accounts.models import SubscriptionState, User
from accounts.plans import PlanCatalog, resolve_plan_id
from accounts.ports import (
    BillingError,
    BillingProvider,
    CheckoutDiscovery,
    CheckoutSession,
    HistoricalCheckout,
    SubscriptionRepository,
)

logger = logging.getLogger("accounts.billing")

_CHECKOUT_KEY_RETENTION_SECONDS = 23 * 60 * 60
_TERMINAL_SUBSCRIPTION_STATUSES = frozenset({"canceled", "incomplete_expired"})


def _record_revision(record: dict[str, Any] | None) -> int:
    value = (record or {}).get("revision", 0)
    return value if isinstance(value, int) and value >= 0 else 0


def _now_epoch() -> int:
    return int(datetime.now(UTC).timestamp())


def _pending_matches(pending: dict[str, Any], requested: dict[str, Any]) -> bool:
    return all(pending.get(field) == value for field, value in requested.items())


def _pending_request_matches(
    pending: dict[str, Any],
    user: User,
    plan_id: str,
    success_url: str,
    cancel_url: str,
) -> bool:
    return (
        pending.get("user_id") == user.id
        and pending.get("requested_plan") == plan_id
        and pending.get("success_url") == success_url
        and pending.get("cancel_url") == cancel_url
    )


def _session_from_pending(pending: dict[str, Any]) -> CheckoutSession | None:
    url = pending.get("url")
    if not isinstance(url, str) or not url:
        return None
    return CheckoutSession(
        url=url,
        stripe_checkout_session_id=pending.get("stripe_checkout_session_id"),
        expires_at=pending.get("expires_at"),
    )


def _safe_checkout_conflict(message: str) -> BillingError:
    return BillingError(message, status_code=409)


def _historical_checkout_is_compatible(
    checkout: HistoricalCheckout,
    parameters: dict[str, Any],
    *,
    operation_id: str | None,
    checkout_session_id: str | None,
) -> bool:
    identities = {
        value
        for value in (checkout.user_id, checkout.metadata_user_id, checkout.client_reference_id)
        if value
    }
    return (
        identities == {parameters["user_id"]}
        and checkout.requested_plan == parameters["requested_plan"]
        and checkout.price_id == parameters["price_id"]
        and checkout.success_url == parameters["success_url"]
        and checkout.cancel_url == parameters["cancel_url"]
        and (operation_id is None or checkout.operation_id == operation_id)
        and (
            checkout_session_id is None
            or checkout.stripe_checkout_session_id == checkout_session_id
        )
        and bool(checkout.url)
    )


def _recover_historical_checkout(
    discovery: CheckoutDiscovery,
    user: User,
    parameters: dict[str, Any],
    *,
    operation_id: str | None = None,
    checkout_session_id: str | None = None,
) -> HistoricalCheckout | None:
    """Return one reusable trusted session, otherwise fail closed.

    Discovery is provider read-only. A partial page, an email-only candidate,
    an unknown state, or more than one nonterminal purchase is ambiguity, not
    evidence that a new sale is safe.
    """
    if not discovery.complete:
        raise _safe_checkout_conflict("Checkout history is incomplete; reconciliation is required.")

    relevant: list[HistoricalCheckout] = []
    normalized_email = user.email.strip().lower()
    for checkout in discovery.sessions:
        identities = {
            value
            for value in (checkout.user_id, checkout.metadata_user_id, checkout.client_reference_id)
            if value
        }
        if len(identities) > 1:
            raise _safe_checkout_conflict(
                "Checkout identity evidence disagrees; reconciliation is required."
            )
        known_customer_id = parameters["stripe_customer_id"]
        if known_customer_id:
            if checkout.stripe_customer_id == known_customer_id and identities != {user.id}:
                raise _safe_checkout_conflict(
                    "Known customer ownership is ambiguous; reconciliation is required."
                )
            if checkout.stripe_customer_id != known_customer_id and identities == {user.id}:
                raise _safe_checkout_conflict(
                    "Checkout customer ownership conflicts; reconciliation is required."
                )
        if identities == {user.id}:
            relevant.append(checkout)
        elif checkout.email and checkout.email.strip().lower() == normalized_email:
            raise _safe_checkout_conflict(
                "Checkout history has an email-only ownership match; reconciliation is required."
            )

    if checkout_session_id is not None:
        matching_sessions = [
            checkout
            for checkout in relevant
            if checkout.stripe_checkout_session_id == checkout_session_id
        ]
        if len(matching_sessions) != 1:
            raise _safe_checkout_conflict(
                "The saved checkout session is not discoverable; reconciliation is required."
            )

    reusable: list[HistoricalCheckout] = []
    if operation_id is not None and (
        not any(checkout.operation_id == operation_id for checkout in relevant)
        or (checkout_session_id is not None and matching_sessions[0].operation_id != operation_id)
    ):
        raise _safe_checkout_conflict(
            "The saved checkout operation is not discoverable; reconciliation is required."
        )
    for checkout in relevant:
        if checkout.state == "open":
            reusable.append(checkout)
            continue
        if checkout.state == "expired":
            if checkout.stripe_subscription_id and (
                checkout.subscription_status not in _TERMINAL_SUBSCRIPTION_STATUSES
            ):
                raise _safe_checkout_conflict(
                    "Historical checkout requires subscription reconciliation."
                )
            continue
        if checkout.state == "complete":
            if checkout.subscription_status not in _TERMINAL_SUBSCRIPTION_STATUSES:
                raise _safe_checkout_conflict(
                    "Completed checkout requires subscription reconciliation."
                )
            continue
        raise _safe_checkout_conflict(
            "Historical checkout has an unknown state; reconciliation is required."
        )

    if len(reusable) != 1:
        if len(reusable) > 1:
            raise _safe_checkout_conflict("Multiple open checkouts require reconciliation.")
        return None
    if not _historical_checkout_is_compatible(
        reusable[0],
        parameters,
        operation_id=operation_id,
        checkout_session_id=checkout_session_id,
    ):
        raise _safe_checkout_conflict("An incompatible open checkout requires reconciliation.")
    return reusable[0]


def _discover_or_conflict(
    provider: BillingProvider,
    user: User,
    stripe_customer_id: str | None,
    parameters: dict[str, Any],
    *,
    operation_id: str | None = None,
    checkout_session_id: str | None = None,
) -> HistoricalCheckout | None:
    try:
        discovery = provider.discover_checkout_sessions(user, stripe_customer_id=stripe_customer_id)
    except Exception as exc:
        logger.warning("checkout history lookup failed user=%s", user.id)
        raise _safe_checkout_conflict(
            "Checkout history is unavailable; reconciliation is required."
        ) from exc
    return _recover_historical_checkout(
        discovery,
        user,
        parameters,
        operation_id=operation_id,
        checkout_session_id=checkout_session_id,
    )


def _persist_pending(
    subscription_repository: SubscriptionRepository,
    user_id: str,
    current: dict[str, Any],
    pending: dict[str, Any],
) -> dict[str, Any] | None:
    candidate = {**current, "pending_checkout": pending}
    return subscription_repository.compare_and_swap(
        user_id,
        candidate,
        expected_revision=_record_revision(current),
    )


def start_checkout(
    subscription_repository: SubscriptionRepository,
    provider: BillingProvider,
    plans: PlanCatalog,
    user: User,
    plan_id: str,
    *,
    success_url: str,
    cancel_url: str,
) -> CheckoutSession:
    if not plans.is_paid(plan_id):
        raise BillingError(f"Unknown paid plan: {plan_id}")

    for _attempt in range(4):
        existing = subscription_repository.get(user.id) or {}

        # Stripe Checkout always creates a NEW subscription; running it for a
        # user who already has an active paid plan would double-bill. Plan
        # changes for subscribers go through the customer portal instead.
        if resolve_plan_id(existing, plans) != plans.basic_plan_id:
            raise _safe_checkout_conflict(
                "An active subscription already exists. Use the billing portal to change plans."
            )

        customer_id = existing.get("stripe_customer_id")
        pending = existing.get("pending_checkout")
        if isinstance(pending, dict) and pending.get("state") == "terminal":
            pending = None
        if isinstance(pending, dict):
            if not _pending_request_matches(pending, user, plan_id, success_url, cancel_url):
                raise _safe_checkout_conflict("A different checkout operation is already pending.")
            immutable_parameters = {
                field: pending.get(field)
                for field in (
                    "user_id",
                    "requested_plan",
                    "price_id",
                    "success_url",
                    "cancel_url",
                    "stripe_customer_id",
                    "customer_choice",
                    "email",
                )
            }
            customer_id = immutable_parameters["stripe_customer_id"]
            stored_session = _session_from_pending(pending)
            if stored_session is not None and pending.get("state") in {"created", "adopted"}:
                reconciliation_operation_id = pending.get("operation_id")
                reconciliation_session_id = pending.get("stripe_checkout_session_id")
                if pending.get("state") == "adopted":
                    reconciliation_operation_id = pending.get("historical_operation_id")
                    reconciliation_session_id = pending.get("historical_checkout_session_id")
                if not isinstance(reconciliation_session_id, str):
                    raise _safe_checkout_conflict(
                        "A saved checkout lacks durable session evidence; "
                        "reconciliation is required."
                    )
                reconciled = _discover_or_conflict(
                    provider,
                    user,
                    customer_id,
                    immutable_parameters,
                    operation_id=(
                        reconciliation_operation_id
                        if isinstance(reconciliation_operation_id, str)
                        else None
                    ),
                    checkout_session_id=reconciliation_session_id,
                )
                if reconciled is not None:
                    return stored_session
                terminal_pending = {
                    **pending,
                    "state": "terminal",
                    "terminal_proof": {"reconciled_at": _now_epoch()},
                }
                if (
                    _persist_pending(subscription_repository, user.id, existing, terminal_pending)
                    is None
                ):
                    continue
                continue
            if stored_session is not None:
                return stored_session
            attempted_at = pending.get("creation_attempted_at")
            if (
                isinstance(attempted_at, int)
                and _now_epoch() - attempted_at >= _CHECKOUT_KEY_RETENTION_SECONDS
            ):
                adopted = _discover_or_conflict(
                    provider,
                    user,
                    customer_id,
                    immutable_parameters,
                    operation_id=pending.get("operation_id"),
                )
                if adopted is None:
                    raise _safe_checkout_conflict(
                        "The earlier checkout attempt is ambiguous; reconciliation is required."
                    )
                updated_pending = {
                    **pending,
                    "state": "adopted",
                    "historical_operation_id": adopted.operation_id,
                    "historical_checkout_session_id": adopted.stripe_checkout_session_id,
                    "stripe_checkout_session_id": adopted.stripe_checkout_session_id,
                    "url": adopted.url,
                    "expires_at": adopted.expires_at,
                }
                persisted = _persist_pending(
                    subscription_repository, user.id, existing, updated_pending
                )
                if persisted is None:
                    continue
                return _session_from_pending(updated_pending)  # type: ignore[return-value]
        else:
            price_id = provider.checkout_price_id(plan_id)
            immutable_parameters = {
                "user_id": user.id,
                "requested_plan": plan_id,
                "price_id": price_id,
                "success_url": success_url,
                "cancel_url": cancel_url,
                "stripe_customer_id": customer_id,
                "customer_choice": "customer" if customer_id else "email",
                "email": user.email,
            }
            adopted = _discover_or_conflict(provider, user, customer_id, immutable_parameters)
            operation_id = generate_uuid7()
            pending = {
                **immutable_parameters,
                "operation_id": operation_id,
                "operation_metadata": {
                    "operation_id": operation_id,
                    "user_id": user.id,
                    "plan": plan_id,
                },
                "idempotency_key": generate_uuid7(),
                "created_at": _now_epoch(),
                "state": "reserved",
            }
            if adopted is not None:
                pending.update(
                    {
                        "state": "adopted",
                        "historical_operation_id": adopted.operation_id,
                        "historical_checkout_session_id": adopted.stripe_checkout_session_id,
                        "stripe_checkout_session_id": adopted.stripe_checkout_session_id,
                        "url": adopted.url,
                        "expires_at": adopted.expires_at,
                    }
                )
            persisted = _persist_pending(subscription_repository, user.id, existing, pending)
            if persisted is None:
                continue
            if adopted is not None:
                return _session_from_pending(pending)  # type: ignore[return-value]

        # Persist the marker before external I/O. It intentionally remains
        # after timeout/error so local failure cannot be misread as absence.
        current = subscription_repository.get(user.id) or {}
        current_pending = current.get("pending_checkout")
        if not isinstance(current_pending, dict):
            continue
        if not _pending_matches(current_pending, immutable_parameters):
            raise _safe_checkout_conflict("A different checkout operation is already pending.")
        stored_session = _session_from_pending(current_pending)
        if stored_session is not None:
            return stored_session
        attempted_pending = {
            **current_pending,
            "state": "attempted",
            "creation_attempted_at": current_pending.get("creation_attempted_at") or _now_epoch(),
        }
        persisted = _persist_pending(subscription_repository, user.id, current, attempted_pending)
        if persisted is None:
            continue

        # Provider I/O is deliberately outside repository locks. Every retry
        # carries the durable operation identity and identical parameters.
        session = provider.create_checkout_session(
            user,
            attempted_pending["requested_plan"],
            success_url=attempted_pending["success_url"],
            cancel_url=attempted_pending["cancel_url"],
            price_id=attempted_pending["price_id"],
            stripe_customer_id=attempted_pending["stripe_customer_id"],
            customer_email=attempted_pending["email"],
            idempotency_key=attempted_pending["idempotency_key"],
            operation_id=attempted_pending["operation_id"],
        )
        latest = subscription_repository.get(user.id) or {}
        latest_pending = latest.get("pending_checkout")
        if not isinstance(latest_pending, dict) or latest_pending.get(
            "operation_id"
        ) != attempted_pending.get("operation_id"):
            replacement = (
                _session_from_pending(latest_pending) if isinstance(latest_pending, dict) else None
            )
            if replacement is not None:
                return replacement
            raise _safe_checkout_conflict("Checkout ownership changed; reconciliation is required.")
        completed_pending = {
            **latest_pending,
            "state": "created",
            "stripe_checkout_session_id": session.stripe_checkout_session_id,
            "url": session.url,
            "expires_at": session.expires_at,
        }
        persisted = _persist_pending(subscription_repository, user.id, latest, completed_pending)
        if persisted is None:
            continue

        # The mock provider has no external checkout: the plan activates now.
        if session.activated_plan:
            activated = subscription_repository.get(user.id) or {}
            activated_pending = activated.get("pending_checkout")
            if isinstance(activated_pending, dict) and activated_pending.get(
                "operation_id"
            ) == completed_pending.get("operation_id"):
                activated_pending = {**activated_pending, "state": "activated"}
            subscription_repository.upsert(
                user.id,
                {
                    **activated,
                    "pending_checkout": activated_pending,
                    "plan": session.activated_plan,
                    "status": "active",
                    "stripe_customer_id": session.stripe_customer_id
                    or activated.get("stripe_customer_id"),
                    "current_period_end": None,
                },
            )
        return session

    raise _safe_checkout_conflict("Checkout ownership changed repeatedly; retry later.")


def open_portal(
    subscription_repository: SubscriptionRepository,
    provider: BillingProvider,
    user: User,
    *,
    return_url: str,
) -> str:
    record = subscription_repository.get(user.id)
    customer_id = (record or {}).get("stripe_customer_id")
    if not customer_id:
        raise BillingError("No subscription found for this account.", status_code=404)
    return provider.create_portal_session(customer_id, return_url=return_url)


def handle_webhook(
    subscription_repository: SubscriptionRepository,
    provider: BillingProvider,
    payload: bytes,
    signature: str | None,
) -> str:
    event = provider.parse_webhook_event(payload, signature)
    if event.kind == "ignored":
        return "ignored"

    user_id = event.user_id or subscription_repository.find_user_by_customer(
        event.stripe_customer_id or ""
    )
    if not user_id:
        # Unmatched events are acknowledged (2xx) so Stripe stops retrying;
        # the log line is the trail for manual reconciliation.
        logger.warning(
            "billing webhook could not be matched to a user (customer=%s)",
            event.stripe_customer_id,
        )
        return "unmatched"

    existing = subscription_repository.get(user_id) or {}

    # Events for a different subscription than the one on record (stale
    # duplicates, dashboard experiments) must not cancel or mutate the
    # active entitlement. A different-id event only wins when it represents
    # a live subscription (e.g. re-subscribing after a cancellation).
    known_id = existing.get("stripe_subscription_id")
    event_id = event.data.get("stripe_subscription_id")
    if known_id and event_id and known_id != event_id:
        if event.kind == "deleted" or event.data.get("status") not in ("active", "trialing"):
            logger.info(
                "billing webhook ignored: subscription mismatch user=%s known=%s event=%s",
                user_id,
                known_id,
                event_id,
            )
            return "ignored_mismatch"

    merged: dict[str, Any] = {
        **existing,
        "stripe_customer_id": event.stripe_customer_id or existing.get("stripe_customer_id"),
    }

    if event.kind == "deleted":
        merged["status"] = "canceled"
    else:
        for field in ("plan", "status", "stripe_subscription_id", "current_period_end"):
            value = event.data.get(field)
            if value is not None:
                merged[field] = value
        # Scheduled cancellation: None clears it (the user resumed the
        # subscription in the portal), so it is written unconditionally on
        # subscription updates that carry the field.
        if "cancel_at" in event.data:
            merged["cancel_at"] = event.data.get("cancel_at")

    subscription_repository.upsert(user_id, merged)
    logger.info(
        "billing webhook applied user=%s kind=%s plan=%s status=%s",
        user_id,
        event.kind,
        merged.get("plan"),
        merged.get("status"),
    )
    return "applied"


def describe_subscription(
    subscription_repository: SubscriptionRepository,
    plans: PlanCatalog,
    user_id: str,
) -> SubscriptionState:
    """The billing facts a host needs to build its own usage view.

    Stops at "which plan, until when" on purpose — quotas belong to the
    host's entitlement layer, not to this package.
    """
    record = subscription_repository.get(user_id) or {}
    plan_id = resolve_plan_id(record, plans)
    return SubscriptionState(
        plan=plan_id,
        status=record.get("status"),
        # A scheduled cancellation only matters while a paid plan is live.
        cancel_at=record.get("cancel_at") if plans.is_paid(plan_id) else None,
        current_period_end=record.get("current_period_end"),
        has_billing_account=bool(record.get("stripe_customer_id")),
    )
