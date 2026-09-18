"""Data carried across the accounts boundary.

Pydantic models because they double as the HTTP contract in
`accounts.api`; nothing here knows about FastAPI itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field


class User(BaseModel):
    """A signed-in account, as every host application sees it."""

    id: str
    email: str
    display_name: str


@dataclass(frozen=True)
class IdentityClaims:
    """Verified identity returned by an identity provider."""

    email: str
    display_name: str
    subject: str


class AuthSessionResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    user: User


class SsoLoginRequest(BaseModel):
    # Provider-specific sign-in credential: a Google ID token in production,
    # or a "mock:<email>" string with the mock provider in development.
    credential: str = Field(min_length=1, max_length=4096)


class AuthConfigResponse(BaseModel):
    """Public description of the sign-in flow the server expects.

    Clients fetch this before rendering a login screen, so switching
    AUTH_PROVIDER never requires shipping a new client build.
    """

    provider: str
    google_client_id: str | None = None


class CheckoutRequest(BaseModel):
    # Validated against the host's PlanCatalog in the service layer rather
    # than by a hard-coded pattern, so adding a plan stays a config change.
    plan: str = Field(min_length=1, max_length=64)


class CheckoutResponse(BaseModel):
    url: str
    # True with the mock provider: the plan is already active, no external
    # checkout page needs to be visited.
    activated: bool = False


class PortalResponse(BaseModel):
    url: str


class SubscriptionState(BaseModel):
    """The billing facts a host application needs to build its own view.

    Deliberately stops at "which plan, until when": what that plan allows
    is the host's business, not this package's.
    """

    plan: str
    status: str | None = None
    # Unix timestamp of a scheduled cancellation (the plan stays active
    # until then); None when no cancellation is pending.
    cancel_at: int | None = None
    current_period_end: int | None = None
    has_billing_account: bool = False
