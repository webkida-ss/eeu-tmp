"""Shared account foundation: sign-in (Google / mock) and subscriptions (Stripe / mock).

Kept byte-identical across the webkida applications so it can later be
lifted out into a standalone distribution without touching call sites.
See README.md in this directory for the rules that keep it extractable.

Typical wiring::

    from accounts import AccountsSettings, PlanCatalog, build_accounts_container
    from accounts.api import build_accounts_router

    PLANS = PlanCatalog(basic_plan_id="basic", paid_plan_ids=("pro", "max"))
    accounts = build_accounts_container(
        AccountsSettings.from_env(PLANS, app_name="My App"), plans=PLANS
    )
    app.include_router(build_accounts_router(accounts))

`accounts.api` is imported separately on purpose: it is the only module
that requires FastAPI.
"""

from accounts.container import (
    AccountsContainer,
    build_accounts_container,
    read_bearer_token,
)
from accounts.models import (
    AuthConfigResponse,
    AuthSessionResponse,
    CheckoutRequest,
    CheckoutResponse,
    IdentityClaims,
    PortalResponse,
    SsoLoginRequest,
    SubscriptionState,
    User,
)
from accounts.plans import PlanCatalog, resolve_plan_id
from accounts.ports import (
    AuthService,
    BillingError,
    BillingProvider,
    CheckoutSession,
    IdentityProvider,
    IdentityVerificationError,
    SubscriptionEvent,
    SubscriptionRepository,
)
from accounts.settings import AccountsSettings

__all__ = [
    "AccountsContainer",
    "AccountsSettings",
    "AuthConfigResponse",
    "AuthService",
    "AuthSessionResponse",
    "BillingError",
    "BillingProvider",
    "CheckoutRequest",
    "CheckoutResponse",
    "CheckoutSession",
    "IdentityClaims",
    "IdentityProvider",
    "IdentityVerificationError",
    "PlanCatalog",
    "PortalResponse",
    "SsoLoginRequest",
    "SubscriptionEvent",
    "SubscriptionRepository",
    "SubscriptionState",
    "User",
    "build_accounts_container",
    "read_bearer_token",
    "resolve_plan_id",
]
