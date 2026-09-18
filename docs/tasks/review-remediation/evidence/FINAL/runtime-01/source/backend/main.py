"""FastAPI adapter for the Untangle backend.

Thin by design: routes parse HTTP, delegate to the framework-free
services layer, and map domain errors onto HTTP responses. Swapping
this layer (e.g. for an AWS Lambda handler) must not require touching
schemas/, core/, or services/.
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

load_dotenv()

from accounts import User
from accounts.api import build_accounts_router, install_accounts_exception_handlers
from accounts.api.router import MAX_WEBHOOK_BODY_BYTES as MAX_WEBHOOK_BODY_BYTES
from config import (
    ADMIN_ALLOWED_ORIGIN,
    ADMIN_ENABLED,
    STORAGE_BACKEND,
    validate_admin_runtime,
)
from core.pipeline import PipelineError
from deps import (
    get_accounts,
    get_active_learner_user,
    get_admin_activity_repository,
    get_current_user,
    get_entitlement_guard,
    get_page_preload_repository,
    get_phrase_repository,
    get_preload_content_store,
    get_preload_job_runner,
    get_usage_meter,
)
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from generated.admin_models import CorrelationError
from jobs.runner import PreloadJobRunner
from middleware.correlation import CorrelationIdMiddleware
from middleware.cors import RouteCorsMiddleware
from repositories.admin_activity import AdminActivityRepository
from repositories.page_preload_repository import PagePreloadRepository
from repositories.phrase_repository import PhraseRepository
from schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    ApiError,
    BillingMeResponse,
    ChatRequest,
    ChatResponse,
    PagePreloadRequest,
    PagePreloadStatusResponse,
    PhraseCreateRequest,
    PhraseRecord,
    VocabularyBookResponse,
)
from services import reading
from services.entitlements import EntitlementError, EntitlementGuard, usage_summary
from services.usage_meter import UsageMeter
from storage.preload_content_store import PreloadContentStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

validate_admin_runtime(
    admin_enabled=ADMIN_ENABLED,
    storage_backend=STORAGE_BACKEND,
)


def error_responses(*statuses: int) -> dict[int, dict[str, object]]:
    # Every product route uses the active-learner dependency in both runtime modes.
    statuses = tuple(sorted(set(statuses) | {403}))
    return {
        status: {
            "model": ApiError,
            "description": {
                400: "Bad request",
                401: "Authentication failed",
                402: "Plan quota exceeded",
                403: "Account access forbidden",
                404: "Resource not found",
                409: "Conflict",
                413: "Request body too large",
                422: "Request validation failed",
                429: "Usage limit exceeded",
                500: "Internal server error",
                502: "Upstream provider failed",
            }[status],
        }
        for status in statuses
    }


ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:18765,http://127.0.0.1:18765",
    ).split(",")
    if origin.strip() and "*" not in origin.strip()
]
app = FastAPI(title="Untangle API")
app.add_middleware(
    RouteCorsMiddleware,
    learner_origins=ALLOWED_ORIGINS,
    admin_origin=ADMIN_ALLOWED_ORIGIN,
)
app.add_middleware(CorrelationIdMiddleware)
if ADMIN_ENABLED:
    from admin.router import router as admin_router

    app.include_router(admin_router)


@app.exception_handler(HTTPException)
async def handle_http_exception(request: Request, exc: HTTPException):
    if not (ADMIN_ENABLED and request.url.path.startswith("/admin/")):
        if (
            exc.status_code == 403
            and isinstance(exc.detail, dict)
            and exc.detail.get("code") == "account_suspended"
            and isinstance(exc.detail.get("message"), str)
        ):
            return JSONResponse(
                status_code=403,
                content={"detail": exc.detail["message"], "code": "account_suspended"},
                headers=exc.headers,
            )
        return await http_exception_handler(request, exc)

    error: tuple[str, str] | None = None
    if exc.status_code == 401:
        error = ("unauthenticated", "Authentication is required.")
    elif exc.status_code == 403 and isinstance(exc.detail, dict):
        code = exc.detail.get("code")
        message = exc.detail.get("message")
        if code in {"admin_forbidden", "account_suspended"} and isinstance(message, str):
            error = (code, message)
    if error is None:
        return await http_exception_handler(request, exc)

    body = CorrelationError(
        code=error[0],
        message=error[1],
        correlation_id=request.state.correlation_id,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=body.model_dump(mode="json"),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_exception(request: Request, exc: RequestValidationError):
    if not (ADMIN_ENABLED and request.url.path.startswith("/admin/")):
        return await request_validation_exception_handler(request, exc)
    return JSONResponse(
        status_code=422,
        content=CorrelationError(
            code="validation_error",
            message="The request is invalid.",
            correlation_id=request.state.correlation_id,
        ).model_dump(mode="json"),
    )


@app.exception_handler(PipelineError)
async def handle_pipeline_error(request, exc: PipelineError):
    # Domain errors carry a transport hint; this is the only place that
    # translates them into HTTP.
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


@app.exception_handler(EntitlementError)
async def handle_entitlement_error(request, exc: EntitlementError):
    # `code` lets the extension render a localized quota message.
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc), "code": exc.code})


install_accounts_exception_handlers(app)

# Sign-in and subscription management in full: /auth/config, /auth/login,
# /auth/me, /auth/logout, /billing/checkout, /billing/portal,
# /billing/webhook, /billing/done. What a plan *allows* stays here, in
# /billing/me below.
app.include_router(
    build_accounts_router(
        get_accounts,
        error_model=ApiError,
        current_user_dependency=get_current_user,
        billing_user_dependency=get_active_learner_user,
    )
)


@app.get("/health", operation_id="getHealth")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get(
    "/pages/preload",
    response_model=PagePreloadStatusResponse,
    operation_id="getPagePreload",
    responses=error_responses(401, 422),
)
def get_page_preload(
    page_url: str = Query(min_length=1),
    current_user: User = Depends(get_active_learner_user),
    repository: PagePreloadRepository = Depends(get_page_preload_repository),
) -> PagePreloadStatusResponse:
    return reading.get_preload_status(repository, current_user.id, page_url)


@app.post(
    "/pages/preload",
    response_model=PagePreloadStatusResponse,
    status_code=202,
    operation_id="createPagePreload",
    responses=error_responses(400, 401, 402, 409, 422, 429, 500),
)
def create_page_preload(
    request: PagePreloadRequest,
    current_user: User = Depends(get_active_learner_user),
    repository: PagePreloadRepository = Depends(get_page_preload_repository),
    job_runner: PreloadJobRunner = Depends(get_preload_job_runner),
    content_store: PreloadContentStore = Depends(get_preload_content_store),
    guard: EntitlementGuard = Depends(get_entitlement_guard),
    usage_meter: UsageMeter = Depends(get_usage_meter),
    admin_activity_repository: AdminActivityRepository | None = Depends(
        get_admin_activity_repository
    ),
) -> PagePreloadStatusResponse:
    # Fast submit: extraction runs synchronously (a bad-input 400 still
    # surfaces here), then the slow analysis is deferred to the job runner.
    # The client polls GET /pages/preload until the record is ready or failed.
    return reading.submit_preload(
        repository,
        job_runner,
        content_store,
        current_user.id,
        request,
        guard=guard,
        usage_meter=usage_meter,
        admin_activity_repository=admin_activity_repository,
    )


@app.get(
    "/vocabulary",
    response_model=VocabularyBookResponse,
    operation_id="getVocabularyBook",
    responses=error_responses(401),
)
def get_vocabulary_book(
    current_user: User = Depends(get_active_learner_user),
    repository: PagePreloadRepository = Depends(get_page_preload_repository),
) -> VocabularyBookResponse:
    return reading.build_vocabulary_book(repository, current_user.id)


@app.post(
    "/analyze",
    response_model=AnalyzeResponse,
    operation_id="analyzeText",
    responses=error_responses(400, 401, 402, 422, 429, 500),
)
def analyze(
    request: AnalyzeRequest,
    current_user: User = Depends(get_active_learner_user),
    repository: PagePreloadRepository = Depends(get_page_preload_repository),
    guard: EntitlementGuard = Depends(get_entitlement_guard),
    usage_meter: UsageMeter = Depends(get_usage_meter),
) -> AnalyzeResponse:
    return reading.analyze_selection(
        repository, current_user.id, request, guard=guard, usage_meter=usage_meter
    )


@app.post(
    "/chat",
    response_model=ChatResponse,
    operation_id="createChatReply",
    responses=error_responses(400, 401, 402, 422, 429, 500),
)
def chat(
    request: ChatRequest,
    current_user: User = Depends(get_active_learner_user),
    repository: PagePreloadRepository = Depends(get_page_preload_repository),
    guard: EntitlementGuard = Depends(get_entitlement_guard),
    usage_meter: UsageMeter = Depends(get_usage_meter),
    admin_activity_repository: AdminActivityRepository | None = Depends(
        get_admin_activity_repository
    ),
) -> ChatResponse:
    return reading.chat_reply(
        repository,
        current_user.id,
        request,
        guard=guard,
        usage_meter=usage_meter,
        admin_activity_repository=admin_activity_repository,
    )


@app.get(
    "/phrases",
    response_model=list[PhraseRecord],
    operation_id="listPhrases",
    responses=error_responses(401),
)
def list_phrases(
    current_user: User = Depends(get_active_learner_user),
    repository: PhraseRepository = Depends(get_phrase_repository),
) -> list[PhraseRecord]:
    return reading.list_phrases(repository, current_user.id)


@app.post(
    "/phrases",
    response_model=PhraseRecord,
    operation_id="createPhrase",
    responses=error_responses(401, 422),
)
def create_phrase(
    request: PhraseCreateRequest,
    current_user: User = Depends(get_active_learner_user),
    repository: PhraseRepository = Depends(get_phrase_repository),
) -> PhraseRecord:
    return reading.create_phrase(repository, current_user.id, request)


# Untangle's own half of billing: how much of the plan is left. The
# subscription itself (checkout, portal, webhooks) is served by the
# accounts router included above.
@app.get(
    "/billing/me",
    response_model=BillingMeResponse,
    operation_id="getBillingSummary",
    responses=error_responses(401),
)
def get_billing_me(
    guard: EntitlementGuard = Depends(get_entitlement_guard),
) -> BillingMeResponse:
    return BillingMeResponse(**usage_summary(guard))
