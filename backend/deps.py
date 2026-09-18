from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from accounts import (
    AccountsContainer,
    AuthService,
    SubscriptionRepository,
    User,
    build_accounts_container,
)
from accounts.api import build_current_user_dependency
from accounts.storage import JsonSubscriptionRepository
from auth.dynamodb_email_auth import DynamoEmailAuthService
from config import (
    ACCOUNTS_SETTINGS,
    ADMIN_ACTIVITY_PATH,
    ADMIN_CONTROL_PATH,
    ADMIN_ENABLED,
    AWS_REGION,
    JOB_RUNNER,
    PAGE_PRELOADS_PATH,
    PHRASES_PATH,
    PRELOAD_CONTENT_BUCKET,
    PRELOAD_CONTENT_DIR,
    PRELOAD_JOBS_QUEUE_URL,
    STORAGE_BACKEND,
    USAGE_PATH,
    USAGE_RESERVATION_ENABLED,
    USAGE_RESERVATION_TTL_SECONDS,
)
from core.plans import PLAN_CATALOG
from fastapi import Depends, HTTPException
from jobs.inline_runner import InlinePreloadJobRunner
from jobs.runner import PreloadJobRunner
from jobs.sqs_runner import SqsPreloadJobRunner
from repositories.admin_account_control import AdminAccountControlRepository
from repositories.admin_activity import AdminActivityRepository
from repositories.dynamodb_billing_repositories import (
    DynamoSubscriptionRepository,
    DynamoUsageRepository,
)
from repositories.dynamodb_page_preload_repository import DynamoPagePreloadRepository
from repositories.dynamodb_phrase_repository import DynamoPhraseRepository
from repositories.json_admin_account_control import JsonAdminAccountControlRepository
from repositories.json_admin_activity import JsonAdminActivityRepository
from repositories.json_session_repository import JsonSessionRepository
from repositories.page_preload_repository import JsonPagePreloadRepository, PagePreloadRepository
from repositories.phrase_repository import JsonPhraseRepository, PhraseRepository
from repositories.usage_repository import JsonUsageRepository, UsageRepository
from services.account_access import AccountSuspended, require_active_learner
from services.admin_accounts import AdminAccounts
from services.entitlements import EntitlementGuard, build_guard
from services.usage_meter import UsageMeter
from storage.dynamodb_store import DynamoDbStore
from storage.json_list_store import read_json_list
from storage.preload_content_store import (
    FilesystemPreloadContentStore,
    PreloadContentStore,
    S3PreloadContentStore,
)

_dynamodb_store: DynamoDbStore | None = None


def _get_dynamodb_store() -> DynamoDbStore:
    global _dynamodb_store
    if _dynamodb_store is None:
        _dynamodb_store = DynamoDbStore()
    return _dynamodb_store


def _create_auth_service(
    *,
    store: DynamoDbStore | None = None,
    clock: Callable[[], datetime] | None = None,
) -> AuthService | None:
    # None means "let accounts use its bundled JSON store", so the shared
    # package keeps owning its own local-development default.
    if STORAGE_BACKEND == "dynamodb":
        return DynamoEmailAuthService(
            store if store is not None else _get_dynamodb_store(),
            session_ttl_days=ACCOUNTS_SETTINGS.session_ttl_days,
            clock=clock,
        )
    return None


def _create_page_preload_repository() -> PagePreloadRepository:
    if STORAGE_BACKEND == "dynamodb":
        return DynamoPagePreloadRepository(_get_dynamodb_store())
    return JsonPagePreloadRepository(PAGE_PRELOADS_PATH)


def _create_phrase_repository() -> PhraseRepository:
    if STORAGE_BACKEND == "dynamodb":
        return DynamoPhraseRepository(_get_dynamodb_store())
    return JsonPhraseRepository(PHRASES_PATH)


def _create_usage_repository() -> UsageRepository:
    if STORAGE_BACKEND == "dynamodb":
        return DynamoUsageRepository(_get_dynamodb_store())
    return JsonUsageRepository(USAGE_PATH)


def _create_subscription_repository() -> SubscriptionRepository:
    if STORAGE_BACKEND == "dynamodb":
        return DynamoSubscriptionRepository(_get_dynamodb_store())
    return JsonSubscriptionRepository(ACCOUNTS_SETTINGS.subscriptions_path)


def _create_admin_activity_repository() -> AdminActivityRepository | None:
    if STORAGE_BACKEND == "dynamodb":
        return None
    return JsonAdminActivityRepository(ADMIN_ACTIVITY_PATH)


def _create_admin_account_control_repository() -> AdminAccountControlRepository | None:
    if STORAGE_BACKEND == "dynamodb":
        return None
    return JsonAdminAccountControlRepository(ADMIN_CONTROL_PATH)


def _create_session_repository() -> JsonSessionRepository | None:
    if STORAGE_BACKEND == "dynamodb":
        return None
    return JsonSessionRepository(ACCOUNTS_SETTINGS.sessions_path)


def _json_user_exists(user_id: str) -> bool:
    return any(
        record.get("id") == user_id for record in read_json_list(ACCOUNTS_SETTINGS.users_path)
    )


def _create_preload_content_store() -> PreloadContentStore:
    # Independent of STORAGE_BACKEND: a bucket name selects S3, otherwise the
    # filesystem store is used (see config.py PRELOAD_CONTENT_BUCKET).
    if PRELOAD_CONTENT_BUCKET:
        return S3PreloadContentStore(PRELOAD_CONTENT_BUCKET, region_name=AWS_REGION)
    return FilesystemPreloadContentStore(PRELOAD_CONTENT_DIR)


_page_preload_repository: PagePreloadRepository = _create_page_preload_repository()
_phrase_repository: PhraseRepository = _create_phrase_repository()
_usage_repository: UsageRepository = _create_usage_repository()
_subscription_repository: SubscriptionRepository = _create_subscription_repository()
_admin_activity_repository = _create_admin_activity_repository()
_admin_account_control_repository = _create_admin_account_control_repository()
_session_repository = _create_session_repository()
_admin_accounts = (
    AdminAccounts(
        _admin_account_control_repository,
        _session_repository,
        user_exists=_json_user_exists,
    )
    if _admin_account_control_repository is not None and _session_repository is not None
    else None
)
_preload_content_store: PreloadContentStore = _create_preload_content_store()

# Sign-in and subscriptions come from the shared `accounts` package: it
# picks the identity/billing providers from configuration, while Untangle
# only supplies the two stores that live in its own DynamoDB table.
_accounts: AccountsContainer = build_accounts_container(
    ACCOUNTS_SETTINGS,
    plans=PLAN_CATALOG,
    auth_service=_create_auth_service(),
    subscription_repository=_subscription_repository,
)


def _create_preload_job_runner() -> PreloadJobRunner:
    if JOB_RUNNER == "sqs":
        return SqsPreloadJobRunner(PRELOAD_JOBS_QUEUE_URL, region_name=AWS_REGION)
    return InlinePreloadJobRunner(
        _page_preload_repository,
        _subscription_repository,
        _usage_repository,
        _preload_content_store,
        _admin_activity_repository,
        billing_provider_mode=_accounts.settings.billing_provider,
    )


_preload_job_runner: PreloadJobRunner = _create_preload_job_runner()


def get_accounts() -> AccountsContainer:
    """Sign-in and subscriptions. Overriding this one dependency replaces
    the whole accounts stack, which is how the tests do it."""
    return _accounts


def get_page_preload_repository() -> PagePreloadRepository:
    return _page_preload_repository


def get_phrase_repository() -> PhraseRepository:
    return _phrase_repository


def get_usage_repository() -> UsageRepository:
    return _usage_repository


def get_subscription_repository() -> SubscriptionRepository:
    return _subscription_repository


def get_admin_activity_repository() -> AdminActivityRepository | None:
    return _admin_activity_repository


def get_admin_account_control_repository() -> AdminAccountControlRepository | None:
    return _admin_account_control_repository


def get_session_repository() -> JsonSessionRepository | None:
    return _session_repository


def get_admin_accounts() -> AdminAccounts | None:
    return _admin_accounts


def get_preload_job_runner() -> PreloadJobRunner:
    return _preload_job_runner


def get_preload_content_store() -> PreloadContentStore:
    return _preload_content_store


# Bearer-token authentication is the shared package's concern; Untangle's
# own endpoints just depend on the resulting User. Resolving the container
# through get_accounts (rather than closing over it) keeps the whole
# accounts stack replaceable with one dependency override.
get_current_user = build_current_user_dependency(get_accounts)


def get_active_learner_user(
    current_user: User = Depends(get_current_user),
    account_repository: AdminAccountControlRepository | None = Depends(
        get_admin_account_control_repository
    ),
) -> User:
    if account_repository is None:
        if ADMIN_ENABLED:
            raise RuntimeError("Account-control repository is required when admin is enabled.")
        return current_user
    try:
        require_active_learner(current_user.id, account_repository)
    except AccountSuspended as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return current_user


def get_entitlement_guard(
    current_user: User = Depends(get_active_learner_user),
    subscription_repository: SubscriptionRepository = Depends(get_subscription_repository),
    usage_repository: UsageRepository = Depends(get_usage_repository),
    accounts: AccountsContainer = Depends(get_accounts),
) -> EntitlementGuard:
    return build_guard(
        subscription_repository,
        usage_repository,
        current_user.id,
        provider_mode=accounts.settings.billing_provider,
    )


def get_usage_meter(
    current_user: User = Depends(get_active_learner_user),
    subscription_repository: SubscriptionRepository = Depends(get_subscription_repository),
    usage_repository: UsageRepository = Depends(get_usage_repository),
    accounts: AccountsContainer = Depends(get_accounts),
) -> UsageMeter:
    return UsageMeter(
        subscription_repository,
        usage_repository,
        current_user.id,
        reservation_enabled=USAGE_RESERVATION_ENABLED,
        reservation_ttl_seconds=USAGE_RESERVATION_TTL_SECONDS,
        provider_mode=accounts.settings.billing_provider,
    )
