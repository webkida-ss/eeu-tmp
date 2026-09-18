"""Configuration for the accounts package.

Plain dataclass + `os.getenv` rather than pydantic-settings, so the package
imposes no settings library on its host. `from_env` is a convenience; a
host that keeps configuration elsewhere can construct `AccountsSettings`
directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from accounts.plans import PlanCatalog

DEFAULT_SESSION_TTL_DAYS = 30


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class AccountsSettings:
    # Shown on the post-checkout landing page.
    app_name: str = "App"

    # "mock" (local development, no external dependency) or "google"
    # (verifies Google ID tokens; needs google-auth + a client id).
    auth_provider: str = "mock"
    google_oauth_client_id: str = ""
    session_ttl_days: int = DEFAULT_SESSION_TTL_DAYS

    # "mock" (plans activate instantly without payment) or "stripe"
    # (hosted Checkout + Customer Portal + signature-verified webhooks).
    billing_provider: str = "mock"
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    # plan id -> Stripe price id.
    stripe_price_ids: dict[str, str] = field(default_factory=dict)

    billing_success_url: str = "http://localhost:8000/billing/done?state=success"
    billing_cancel_url: str = "http://localhost:8000/billing/done?state=cancel"
    billing_portal_return_url: str = "http://localhost:8000/billing/done?state=portal"

    # Used only by the bundled JSON reference storage.
    users_path: Path = Path("data/auth_users.json")
    sessions_path: Path = Path("data/auth_sessions.json")
    subscriptions_path: Path = Path("data/subscriptions.json")

    @classmethod
    def from_env(
        cls,
        plans: PlanCatalog,
        *,
        app_name: str = "App",
        data_dir: Path | None = None,
        default_api_base_url: str = "http://localhost:8000",
    ) -> AccountsSettings:
        api_base = (_env("API_BASE_URL", default_api_base_url) or default_api_base_url).rstrip("/")
        directory = data_dir or Path("data")
        return cls(
            app_name=app_name,
            auth_provider=_env("AUTH_PROVIDER", "mock").lower(),
            google_oauth_client_id=_env("GOOGLE_OAUTH_CLIENT_ID"),
            session_ttl_days=max(
                1, int(_env("AUTH_SESSION_TTL_DAYS", str(DEFAULT_SESSION_TTL_DAYS)))
            ),
            billing_provider=_env("BILLING_PROVIDER", "mock").lower(),
            stripe_secret_key=_env("STRIPE_SECRET_KEY"),
            stripe_webhook_secret=_env("STRIPE_WEBHOOK_SECRET"),
            stripe_price_ids={
                plan_id: _env(f"STRIPE_PRICE_ID_{plan_id.upper()}")
                for plan_id in plans.paid_plan_ids
            },
            billing_success_url=_env(
                "BILLING_SUCCESS_URL", f"{api_base}/billing/done?state=success"
            ),
            billing_cancel_url=_env("BILLING_CANCEL_URL", f"{api_base}/billing/done?state=cancel"),
            billing_portal_return_url=_env(
                "BILLING_PORTAL_RETURN_URL", f"{api_base}/billing/done?state=portal"
            ),
            users_path=directory / "auth_users.json",
            sessions_path=directory / "auth_sessions.json",
            subscriptions_path=directory / "subscriptions.json",
        )
