"""Composition root: turns settings plus injected ports into one object.

`AccountsContainer` is the whole package's surface for a host application.
Transports call its methods — HTTP through `accounts.api`, but equally a
WebSocket handshake or a Lambda handler through `resolve_user` — so no
caller needs to know which provider or store is configured.
"""

from __future__ import annotations

from dataclasses import dataclass

from accounts.billing import MockBillingProvider, StripeBillingProvider
from accounts.identity import GoogleIdentityProvider, MockIdentityProvider
from accounts.models import (
    AuthConfigResponse,
    AuthSessionResponse,
    SubscriptionState,
    User,
)
from accounts.plans import PlanCatalog
from accounts.ports import (
    AuthService,
    BillingProvider,
    CheckoutSession,
    IdentityProvider,
    SubscriptionRepository,
)
from accounts.services import auth_flow, billing_flow
from accounts.settings import AccountsSettings
from accounts.storage import JsonEmailAuthService, JsonSubscriptionRepository

BEARER_PREFIX = "Bearer "


@dataclass(frozen=True)
class AccountsContainer:
    settings: AccountsSettings
    plans: PlanCatalog
    auth_service: AuthService
    identity_provider: IdentityProvider
    billing_provider: BillingProvider
    subscription_repository: SubscriptionRepository

    # --- authentication ---

    def auth_config(self) -> AuthConfigResponse:
        """Public: which sign-in flow a client should present."""
        return AuthConfigResponse(
            provider=self.settings.auth_provider,
            google_client_id=self.settings.google_oauth_client_id or None,
        )

    def login(self, credential: str) -> AuthSessionResponse:
        return auth_flow.login_with_identity(self.auth_service, self.identity_provider, credential)

    def resolve_user(self, access_token: str | None) -> User | None:
        """Resolve a raw access token. Transport-agnostic on purpose: a
        WebSocket handshake carries the token in its first frame, not in an
        Authorization header."""
        token = (access_token or "").strip()
        if not token:
            return None
        return self.auth_service.resolve_user(token)

    def resolve_bearer(self, authorization: str | None) -> User | None:
        return self.resolve_user(read_bearer_token(authorization))

    def logout(self, access_token: str | None) -> None:
        token = (access_token or "").strip()
        if token:
            self.auth_service.logout(token)

    # --- billing ---

    def start_checkout(self, user: User, plan_id: str) -> CheckoutSession:
        return billing_flow.start_checkout(
            self.subscription_repository,
            self.billing_provider,
            self.plans,
            user,
            plan_id,
            success_url=self.settings.billing_success_url,
            cancel_url=self.settings.billing_cancel_url,
        )

    def open_portal(self, user: User) -> str:
        return billing_flow.open_portal(
            self.subscription_repository,
            self.billing_provider,
            user,
            return_url=self.settings.billing_portal_return_url,
        )

    def handle_webhook(self, payload: bytes, signature: str | None) -> str:
        return billing_flow.handle_webhook(
            self.subscription_repository,
            self.billing_provider,
            payload,
            signature,
            plans=self.plans,
        )

    def describe_subscription(self, user_id: str) -> SubscriptionState:
        return billing_flow.describe_subscription(self.subscription_repository, self.plans, user_id)


def read_bearer_token(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith(BEARER_PREFIX):
        return None
    return authorization.removeprefix(BEARER_PREFIX).strip() or None


def build_accounts_container(
    settings: AccountsSettings | None = None,
    *,
    plans: PlanCatalog | None = None,
    auth_service: AuthService | None = None,
    identity_provider: IdentityProvider | None = None,
    billing_provider: BillingProvider | None = None,
    subscription_repository: SubscriptionRepository | None = None,
) -> AccountsContainer:
    """Build the container, defaulting every port from `settings`.

    Any port may be overridden: a host with its own datastore passes its
    `AuthService` / `SubscriptionRepository` implementations here and keeps
    the rest of the package untouched.
    """
    settings = settings or AccountsSettings()
    plans = plans or PlanCatalog()

    if identity_provider is None:
        identity_provider = (
            GoogleIdentityProvider(settings.google_oauth_client_id)
            if settings.auth_provider == "google"
            else MockIdentityProvider()
        )

    if billing_provider is None:
        billing_provider = (
            StripeBillingProvider(
                secret_key=settings.stripe_secret_key,
                webhook_secret=settings.stripe_webhook_secret,
                price_ids=dict(settings.stripe_price_ids),
            )
            if settings.billing_provider == "stripe"
            else MockBillingProvider(plans)
        )

    if auth_service is None:
        auth_service = JsonEmailAuthService(
            settings.users_path,
            settings.sessions_path,
            session_ttl_days=settings.session_ttl_days,
        )

    if subscription_repository is None:
        subscription_repository = JsonSubscriptionRepository(settings.subscriptions_path)

    return AccountsContainer(
        settings=settings,
        plans=plans,
        auth_service=auth_service,
        identity_provider=identity_provider,
        billing_provider=billing_provider,
        subscription_repository=subscription_repository,
    )
