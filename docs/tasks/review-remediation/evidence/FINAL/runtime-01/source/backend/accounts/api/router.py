"""The HTTP surface of an account: sign in, subscribe, manage, cancel.

`app.include_router(build_accounts_router(get_accounts))` is the whole
integration, where `get_accounts` returns the host's container. Usage
summaries (`/billing/me`) are deliberately absent: what a plan allows is
the host's business, so the host builds that endpoint on top of
`container.describe_subscription()`.
"""

from __future__ import annotations

import html
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from accounts.api.dependencies import AccountsProvider, build_current_user_dependency
from accounts.container import AccountsContainer, read_bearer_token
from accounts.models import (
    AuthConfigResponse,
    AuthSessionResponse,
    CheckoutRequest,
    CheckoutResponse,
    PortalResponse,
    SsoLoginRequest,
    User,
)
from accounts.ports import BillingError, IdentityVerificationError

MAX_WEBHOOK_BODY_BYTES = 262_144


def _error_responses(
    error_model: type[Any] | None,
    *statuses: int,
) -> dict[int, dict[str, object]]:
    if error_model is None:
        return {}
    return {status: {"model": error_model} for status in statuses}


def build_accounts_router(
    provider: AccountsProvider,
    *,
    error_model: type[Any] | None = None,
    current_user_dependency: Any | None = None,
    billing_user_dependency: Any | None = None,
) -> APIRouter:
    router = APIRouter()
    current_user = current_user_dependency or build_current_user_dependency(provider)
    billing_user = billing_user_dependency or current_user

    @router.get(
        "/auth/config",
        response_model=AuthConfigResponse,
        operation_id="getAuthConfig",
    )
    def get_auth_config(
        accounts: AccountsContainer = Depends(provider),
    ) -> AuthConfigResponse:
        # Public: the client asks which sign-in flow to present.
        return accounts.auth_config()

    @router.post(
        "/auth/login",
        response_model=AuthSessionResponse,
        operation_id="createAuthSession",
        responses=_error_responses(error_model, 400, 401, 422),
    )
    def login(
        request: SsoLoginRequest,
        accounts: AccountsContainer = Depends(provider),
    ) -> AuthSessionResponse:
        try:
            return accounts.login(request.credential)
        except IdentityVerificationError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get(
        "/auth/me",
        response_model=User,
        operation_id="getCurrentUser",
        responses=_error_responses(error_model, 401),
    )
    def get_auth_me(user: User = Depends(current_user)) -> User:
        return user

    @router.post(
        "/auth/logout",
        operation_id="closeAuthSession",
        responses=_error_responses(error_model, 401),
    )
    def logout(
        user: User = Depends(current_user),
        authorization: str | None = Header(default=None),
        accounts: AccountsContainer = Depends(provider),
    ) -> dict[str, str]:
        accounts.logout(read_bearer_token(authorization))
        return {"status": "ok"}

    @router.post(
        "/billing/checkout",
        response_model=CheckoutResponse,
        operation_id="createBillingCheckout",
        responses=_error_responses(error_model, 400, 401, 403, 409, 422, 502),
    )
    def create_billing_checkout(
        request: CheckoutRequest,
        user: User = Depends(billing_user),
        accounts: AccountsContainer = Depends(provider),
    ) -> CheckoutResponse:
        try:
            session = accounts.start_checkout(user, request.plan)
        except BillingError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        return CheckoutResponse(url=session.url, activated=bool(session.activated_plan))

    @router.post(
        "/billing/portal",
        response_model=PortalResponse,
        operation_id="openBillingPortal",
        responses=_error_responses(error_model, 401, 403, 404, 502),
    )
    def create_billing_portal(
        user: User = Depends(billing_user),
        accounts: AccountsContainer = Depends(provider),
    ) -> PortalResponse:
        try:
            return PortalResponse(url=accounts.open_portal(user))
        except BillingError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @router.post(
        "/billing/webhook",
        operation_id="processBillingWebhook",
        responses=_error_responses(error_model, 400, 413, 500),
        openapi_extra={
            "x-max-body-bytes": MAX_WEBHOOK_BODY_BYTES,
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"type": "object", "additionalProperties": True},
                    },
                },
            },
        },
    )
    async def billing_webhook(
        request: Request,
        stripe_signature: str | None = Header(
            default=None,
            alias="Stripe-Signature",
        ),
        accounts: AccountsContainer = Depends(provider),
    ) -> dict[str, str]:
        # Unauthenticated by design: trust comes from the Stripe signature,
        # verified fail-closed inside the provider.
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > MAX_WEBHOOK_BODY_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Webhook payload is too large.",
                    )
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid Content-Length header",
                ) from exc

        payload = bytearray()
        async for chunk in request.stream():
            if len(payload) + len(chunk) > MAX_WEBHOOK_BODY_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail="Webhook payload is too large.",
                )
            payload.extend(chunk)
        try:
            result = accounts.handle_webhook(
                bytes(payload),
                stripe_signature,
            )
        except BillingError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        return {"status": result}

    @router.get(
        "/billing/done",
        response_class=HTMLResponse,
        operation_id="getBillingDonePage",
    )
    def billing_done(
        state: str = "success",
        accounts: AccountsContainer = Depends(provider),
    ) -> HTMLResponse:
        # Landing page after Checkout/Portal; the client picks the new plan
        # up on its next refresh.
        message = {
            "success": "Subscription updated. You can close this tab.",
            "cancel": "Checkout was cancelled. You can close this tab.",
            "portal": "Billing settings saved. You can close this tab.",
        }.get(state, "You can close this tab.")
        return HTMLResponse(
            "<html><body style='font-family: sans-serif; padding: 48px; text-align: center;'>"
            f"<h2>{html.escape(accounts.settings.app_name)}</h2>"
            f"<p>{message}</p></body></html>"
        )

    return router


def install_accounts_exception_handlers(app) -> None:
    """Map `BillingError` raised outside the router onto its status code.

    The router already handles its own; this covers hosts that call
    `container.start_checkout()` from their own endpoints.
    """

    @app.exception_handler(BillingError)
    async def _handle_billing_error(request, exc: BillingError):
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})
