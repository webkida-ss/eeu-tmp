"""The seams accounts is built on: identity, sessions, billing, storage.

Every concrete provider is chosen by configuration and injected at the
composition root (`accounts.container`). Nothing in this module imports a
concrete implementation, and nothing here knows about HTTP.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from accounts.models import IdentityClaims, User

# --- identity ---------------------------------------------------------------


class IdentityVerificationError(Exception):
    """Raised when an SSO credential cannot be verified."""


class IdentityProvider(Protocol):
    """Verifies an opaque sign-in credential and returns identity claims.

    The credential format is provider-specific: a Google ID token in
    production, a `mock:<email>` string in local development.
    """

    provider_name: str

    def verify(self, credential: str) -> IdentityClaims: ...


# --- sessions ---------------------------------------------------------------


class AuthService(Protocol):
    """Account records plus the bearer sessions issued against them.

    `login` is upsert-shaped: the first sign-in for an email creates the
    account, later ones reuse it. Implementations decide where that lives
    (JSON file, DynamoDB, memory).
    """

    def login(self, *, email: str, display_name: str | None = None) -> tuple[str, User]: ...

    def resolve_user(self, access_token: str) -> User | None: ...

    def logout(self, access_token: str) -> None: ...


# --- billing ----------------------------------------------------------------


class BillingError(Exception):
    """Billing operation failed (bad signature, unknown plan, upstream error)."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class CheckoutSession:
    url: str
    # Mock provider activates the plan immediately (no external checkout);
    # Stripe activates through the webhook after payment.
    activated_plan: str | None = None
    stripe_customer_id: str | None = None
    # Provider identifiers must remain explicitly named so a future provider
    # cannot accidentally reuse Stripe checkout state.
    stripe_checkout_session_id: str | None = None
    expires_at: int | None = None


@dataclass(frozen=True)
class HistoricalCheckout:
    """A provider-normalized hosted checkout found during recovery.

    The provider fills trusted identity fields only from its own metadata or
    client reference. An email match is deliberately separate because it is
    never enough to establish checkout ownership.
    """

    stripe_checkout_session_id: str
    url: str | None
    state: str
    user_id: str | None = None
    email: str | None = None
    stripe_customer_id: str | None = None
    metadata_user_id: str | None = None
    client_reference_id: str | None = None
    operation_id: str | None = None
    requested_plan: str | None = None
    price_id: str | None = None
    success_url: str | None = None
    cancel_url: str | None = None
    stripe_subscription_id: str | None = None
    subscription_status: str | None = None
    expires_at: int | None = None


@dataclass(frozen=True)
class CheckoutDiscovery:
    """Bounded, paginated, read-only provider history for one checkout start."""

    sessions: tuple[HistoricalCheckout, ...]
    # False means a page or retrieval failed before the provider proved that
    # discovery was exhaustive; callers must fail closed.
    complete: bool


@dataclass(frozen=True)
class SubscriptionEvent:
    """Provider-agnostic result of a verified webhook event."""

    kind: str  # "updated" | "deleted" | "ignored"
    user_id: str | None = None
    stripe_customer_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


class BillingProvider(Protocol):
    def create_checkout_session(
        self,
        user: User,
        plan_id: str,
        *,
        success_url: str,
        cancel_url: str,
        price_id: str,
        stripe_customer_id: str | None = None,
        customer_email: str,
        idempotency_key: str,
        operation_id: str,
    ) -> CheckoutSession: ...

    def checkout_price_id(self, plan_id: str) -> str: ...

    def discover_checkout_sessions(
        self, user: User, *, stripe_customer_id: str | None
    ) -> CheckoutDiscovery: ...

    def create_portal_session(self, stripe_customer_id: str, *, return_url: str) -> str: ...

    def parse_webhook_event(self, payload: bytes, signature: str | None) -> SubscriptionEvent: ...


class SubscriptionRepository(Protocol):
    """The user's current subscription entitlement.

    One record per user: {plan, status, stripe_customer_id,
    stripe_subscription_id, current_period_end, cancel_at}. Billing
    webhooks write it; every metered request reads it (no Stripe
    round-trips on the hot path).
    """

    def get(self, user_id: str) -> dict[str, Any] | None: ...

    def upsert(self, user_id: str, record: dict[str, Any]) -> dict[str, Any]: ...

    def compare_and_swap(
        self,
        user_id: str,
        record: dict[str, Any],
        *,
        expected_revision: int,
    ) -> dict[str, Any] | None: ...

    def find_user_by_customer(self, stripe_customer_id: str) -> str | None: ...
