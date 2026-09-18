"""Stripe billing provider: hosted Checkout + Customer Portal + webhooks.

Card data never touches this backend. Entitlements are driven by verified
webhook events only; signature verification fails closed. The stripe
package is imported lazily so environments running BILLING_PROVIDER=mock
do not need it installed.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from accounts.models import User
from accounts.ports import (
    BillingError,
    CheckoutDiscovery,
    CheckoutSession,
    HistoricalCheckout,
    SubscriptionEvent,
)

logger = logging.getLogger("accounts.billing")


def _is_stripe_customer_id(value: str | None) -> bool:
    # Records written by the mock provider carry "mock_customer_..." ids;
    # switching BILLING_PROVIDER to stripe must not send those to Stripe.
    return bool(value and value.startswith("cus_"))


_ACTIVE_SUBSCRIPTION_EVENTS = frozenset(
    {"customer.subscription.created", "customer.subscription.updated"}
)


def _import_stripe():
    try:
        import stripe
    except ImportError as exc:  # pragma: no cover - environment specific
        raise BillingError(
            "The stripe package is required when BILLING_PROVIDER=stripe. "
            "Install it with: pip install stripe",
            status_code=500,
        ) from exc
    return stripe


class StripeBillingProvider:
    def __init__(
        self,
        *,
        secret_key: str,
        webhook_secret: str,
        price_ids: dict[str, str],
    ) -> None:
        if not secret_key:
            raise ValueError("STRIPE_SECRET_KEY is required when BILLING_PROVIDER=stripe.")
        self._secret_key = secret_key
        self._webhook_secret = webhook_secret
        # plan_id -> Stripe price id, and the reverse for webhook resolution.
        self._price_ids = {plan: price for plan, price in price_ids.items() if price}
        self._plan_by_price = {price: plan for plan, price in self._price_ids.items()}

    def _client(self):
        stripe = _import_stripe()
        stripe.api_key = self._secret_key
        return stripe

    def checkout_price_id(self, plan_id: str) -> str:
        price_id = self._price_ids.get(plan_id)
        if not price_id:
            raise BillingError(
                f"No Stripe price is configured for plan '{plan_id}'. "
                f"Set STRIPE_PRICE_ID_{plan_id.upper()}."
            )
        return price_id

    def create_checkout_session(
        self,
        user: User,
        plan_id: str,
        *,
        success_url: str,
        cancel_url: str,
        stripe_customer_id: str | None = None,
        customer_email: str,
        idempotency_key: str,
        operation_id: str,
    ) -> CheckoutSession:
        price_id = self.checkout_price_id(plan_id)

        stripe = self._client()
        try:
            params: dict[str, Any] = {
                "mode": "subscription",
                "line_items": [{"price": price_id, "quantity": 1}],
                "success_url": success_url,
                "cancel_url": cancel_url,
                "client_reference_id": user.id,
                "subscription_data": {
                    "metadata": {
                        "user_id": user.id,
                        "plan": plan_id,
                        "checkout_operation_id": operation_id,
                    }
                },
                "metadata": {
                    "user_id": user.id,
                    "plan": plan_id,
                    "checkout_operation_id": operation_id,
                },
            }
            if _is_stripe_customer_id(stripe_customer_id):
                params["customer"] = stripe_customer_id
            else:
                params["customer_email"] = customer_email
            session = stripe.checkout.Session.create(**params, idempotency_key=idempotency_key)
        except BillingError:
            raise
        except Exception as exc:
            raise BillingError(f"Stripe checkout failed: {exc}", status_code=502) from exc

        return CheckoutSession(
            url=session.url,
            stripe_checkout_session_id=getattr(session, "id", None),
            expires_at=getattr(session, "expires_at", None),
        )

    def discover_checkout_sessions(
        self, user: User, *, stripe_customer_id: str | None
    ) -> CheckoutDiscovery:
        """Read bounded paginated history without treating a missing page as empty."""
        stripe = self._client()
        sessions: list[HistoricalCheckout] = []
        starting_after: str | None = None
        max_pages = 20
        try:
            for _page in range(max_pages):
                params: dict[str, Any] = {
                    "limit": 100,
                    "expand": ["data.line_items"],
                }
                if starting_after:
                    params["starting_after"] = starting_after
                page = stripe.checkout.Session.list(**params)
                data = list(self._value(page, "data") or [])
                for session in data:
                    sessions.append(self._historical_checkout(stripe, session))
                if not self._value(page, "has_more"):
                    return CheckoutDiscovery(sessions=tuple(sessions), complete=True)
                if not data:
                    return CheckoutDiscovery(sessions=tuple(sessions), complete=False)
                starting_after = self._value(data[-1], "id")
                if not starting_after:
                    return CheckoutDiscovery(sessions=tuple(sessions), complete=False)
        except BillingError:
            raise
        except Exception as exc:
            raise BillingError("Stripe checkout history lookup failed.", status_code=502) from exc
        return CheckoutDiscovery(sessions=tuple(sessions), complete=False)

    def _historical_checkout(self, stripe: Any, session: Any) -> HistoricalCheckout:
        metadata = self._value(session, "metadata") or {}
        customer_details = self._value(session, "customer_details") or {}
        line_items = self._value(session, "line_items") or {}
        items = self._value(line_items, "data") or []
        first_item = items[0] if items else {}
        price = self._value(first_item, "price") or {}
        subscription_id = self._value(session, "subscription")
        subscription_status = None
        if self._value(session, "status") == "complete" and subscription_id:
            subscription = stripe.Subscription.retrieve(subscription_id)
            subscription_status = self._value(subscription, "status")
        return HistoricalCheckout(
            stripe_checkout_session_id=str(self._value(session, "id") or ""),
            url=self._value(session, "url"),
            state=str(self._value(session, "status") or "unknown"),
            user_id=(
                self._value(metadata, "user_id") or self._value(session, "client_reference_id")
            ),
            email=self._value(customer_details, "email") or self._value(session, "customer_email"),
            stripe_customer_id=self._value(session, "customer"),
            metadata_user_id=self._value(metadata, "user_id"),
            client_reference_id=self._value(session, "client_reference_id"),
            operation_id=self._value(metadata, "checkout_operation_id"),
            requested_plan=self._value(metadata, "plan"),
            price_id=self._value(price, "id"),
            success_url=self._value(session, "success_url"),
            cancel_url=self._value(session, "cancel_url"),
            stripe_subscription_id=subscription_id,
            subscription_status=subscription_status,
            expires_at=self._value(session, "expires_at"),
        )

    @staticmethod
    def _value(value: Any, field: str) -> Any:
        if isinstance(value, dict):
            return value.get(field)
        return getattr(value, field, None)

    def create_portal_session(self, stripe_customer_id: str, *, return_url: str) -> str:
        if not _is_stripe_customer_id(stripe_customer_id):
            raise BillingError("No Stripe subscription found for this account.", status_code=404)
        stripe = self._client()
        try:
            session = stripe.billing_portal.Session.create(
                customer=stripe_customer_id,
                return_url=return_url,
            )
        except Exception as exc:
            raise BillingError(f"Stripe portal failed: {exc}", status_code=502) from exc
        return session.url

    def parse_webhook_event(self, payload: bytes, signature: str | None) -> SubscriptionEvent:
        stripe = self._client()
        if not self._webhook_secret:
            raise BillingError("STRIPE_WEBHOOK_SECRET is not configured.", status_code=500)
        if not signature:
            raise BillingError("Missing Stripe-Signature header.", status_code=400)

        try:
            stripe.Webhook.construct_event(payload, signature, self._webhook_secret)
        except Exception as exc:
            # Fail closed: any verification problem rejects the event.
            raise BillingError(f"Webhook signature verification failed: {exc}") from exc

        # construct_event verified the signature; read the payload as plain
        # JSON (StripeObject's attribute-style access varies across SDK
        # versions).
        event = json.loads(payload.decode("utf-8"))
        kind = event["type"]
        obj = event["data"]["object"]

        if kind == "checkout.session.completed":
            # Delayed-notification payment methods complete the session
            # before funds settle; entitlement then waits for the
            # customer.subscription.* events.
            if obj.get("payment_status") not in (None, "paid"):
                logger.info(
                    "checkout completed but unpaid (payment_status=%s)", obj.get("payment_status")
                )
                return SubscriptionEvent(kind="ignored")
            # Links the user to the Stripe customer; the plan/period details
            # arrive via customer.subscription.* events.
            return SubscriptionEvent(
                kind="updated",
                user_id=obj.get("client_reference_id")
                or (obj.get("metadata") or {}).get("user_id"),
                stripe_customer_id=obj.get("customer"),
                data={
                    "plan": (obj.get("metadata") or {}).get("plan"),
                    "status": "active",
                    "stripe_subscription_id": obj.get("subscription"),
                },
            )

        if kind in _ACTIVE_SUBSCRIPTION_EVENTS or kind == "customer.subscription.deleted":
            items = (obj.get("items") or {}).get("data") or []
            price_id = items[0]["price"]["id"] if items else None
            # API versions from 2025 (basil) moved current_period_end from
            # the subscription onto its items.
            period_end = obj.get("current_period_end")
            if period_end is None and items:
                period_end = items[0].get("current_period_end")
            return SubscriptionEvent(
                kind="deleted" if kind == "customer.subscription.deleted" else "updated",
                user_id=(obj.get("metadata") or {}).get("user_id"),
                stripe_customer_id=obj.get("customer"),
                data={
                    "plan": self._plan_by_price.get(price_id),
                    "status": obj.get("status"),
                    "stripe_subscription_id": obj.get("id"),
                    "current_period_end": period_end,
                    # None is meaningful here: a resumed subscription clears
                    # its scheduled cancellation.
                    "cancel_at": obj.get("cancel_at"),
                },
            )

        logger.info("ignoring stripe event type=%s", kind)
        return SubscriptionEvent(kind="ignored")
