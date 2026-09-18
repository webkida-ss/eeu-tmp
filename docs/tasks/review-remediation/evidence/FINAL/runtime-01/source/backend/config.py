from __future__ import annotations

import os
from pathlib import Path

from accounts import AccountsSettings
from core.plans import PLAN_CATALOG
from secret_resolver import resolve_runtime_secrets

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
PHRASES_PATH = DATA_DIR / "phrases.json"
PAGE_PRELOADS_PATH = DATA_DIR / "page_preloads.json"
ADMIN_ACTIVITY_PATH = DATA_DIR / "admin_activity.json"
ADMIN_CONTROL_PATH = DATA_DIR / "admin_control.json"

STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "json").strip().lower()
ADMIN_ENABLED = os.getenv("ADMIN_ENABLED", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ADMIN_EMAILS = tuple(
    email.strip().lower() for email in os.getenv("ADMIN_EMAILS", "").split(",") if email.strip()
)
ADMIN_ALLOWED_ORIGIN = (
    os.getenv("ADMIN_ALLOWED_ORIGIN", "http://localhost:3000").strip() or "http://localhost:3000"
)
USAGE_PATH = DATA_DIR / "usage.json"


def validate_admin_runtime(*, admin_enabled: bool, storage_backend: str) -> None:
    if admin_enabled and storage_backend.strip().lower() != "json":
        raise RuntimeError("Admin runtime requires STORAGE_BACKEND=json when ADMIN_ENABLED is true")


# Preload job runner: "inline" (local development, the analysis runs on a
# background thread inside the same process) or "sqs" (the API enqueues a
# job onto SQS and a separate worker Lambda runs it, so the analysis is not
# bound by API Gateway's 30-second integration cap).
JOB_RUNNER = os.getenv("JOB_RUNNER", "inline").strip().lower()
PRELOAD_JOBS_QUEUE_URL = os.getenv("PRELOAD_JOBS_QUEUE_URL", "").strip()

# Transient store for a preloaded article's raw extracted text (a submit ->
# worker handoff payload, kept out of the DynamoDB record). Selection is
# independent of STORAGE_BACKEND: if PRELOAD_CONTENT_BUCKET is set the S3
# store is used, otherwise the filesystem store writes under
# PRELOAD_CONTENT_DIR (default DATA_DIR/preload_content). This lets local
# development run against DynamoDB Local while still using the filesystem
# content store.
PRELOAD_CONTENT_BUCKET = os.getenv("PRELOAD_CONTENT_BUCKET", "").strip()
_preload_content_dir = os.getenv("PRELOAD_CONTENT_DIR", "").strip()
PRELOAD_CONTENT_DIR = (
    Path(_preload_content_dir) if _preload_content_dir else DATA_DIR / "preload_content"
)

# Sign-in and subscriptions are configured entirely by the shared
# `accounts` package: AUTH_PROVIDER, GOOGLE_OAUTH_CLIENT_ID,
# BILLING_PROVIDER, STRIPE_*, and the Checkout/Portal return URLs are read
# there. See accounts/README.md for the full variable list.
resolve_runtime_secrets()
ACCOUNTS_SETTINGS = AccountsSettings.from_env(
    PLAN_CATALOG,
    app_name="Untangle",
    data_dir=DATA_DIR,
    default_api_base_url="http://localhost:18765",
)

READING_ASSISTANT_DYNAMODB_TABLE_NAME = os.getenv(
    "READING_ASSISTANT_DYNAMODB_TABLE_NAME",
    "english-local-reading-assistant",
)
DYNAMODB_ENDPOINT = os.getenv("DYNAMODB_ENDPOINT", "").strip() or None
AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "dummy")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "dummy")

# Token estimation and model pricing. Rates intentionally have no defaults:
# an unconfigured or unknown model must fail closed instead of being free.
OPENAI_TOKEN_ENCODING = os.getenv("OPENAI_TOKEN_ENCODING", "o200k_base").strip()
OPENAI_RATE_CARD_VERSION = os.getenv("OPENAI_RATE_CARD_VERSION", "").strip()
OPENAI_MODEL_INPUT_MICRO_USD_PER_MILLION = os.getenv(
    "OPENAI_MODEL_INPUT_MICRO_USD_PER_MILLION", ""
).strip()
OPENAI_MODEL_OUTPUT_MICRO_USD_PER_MILLION = os.getenv(
    "OPENAI_MODEL_OUTPUT_MICRO_USD_PER_MILLION", ""
).strip()

# Additive usage-reservation rollout. Keep enforcement disabled until staging
# concurrency verification is complete; compatibility guards remain active.
USAGE_RESERVATION_ENABLED = os.getenv("USAGE_RESERVATION_ENABLED", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
USAGE_RESERVATION_TTL_SECONDS = max(1, int(os.getenv("USAGE_RESERVATION_TTL_SECONDS", "900")))
