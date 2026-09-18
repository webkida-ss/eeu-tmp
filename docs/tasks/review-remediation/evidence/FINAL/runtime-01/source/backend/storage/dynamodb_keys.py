from __future__ import annotations

import hashlib

from repositories.page_preload_repository import normalize_page_url

SK_USER = "USER"
SK_PROFILE = "PROFILE"
SK_SESSION = "SESSION"
SK_SUBSCRIPTION = "SUBSCRIPTION"
PRELOAD_SK_PREFIX = "PRELOAD#URL#"
PRELOAD_ID_SK_PREFIX = "PRELOAD#ID#"
PHRASE_SK_PREFIX = "PHRASE#"
USAGE_SK_PREFIX = "USAGE#"
USAGE_OPERATION_SK_PREFIX = "USAGE_OPERATION#"
USAGE_EVENT_SK_PREFIX = "USAGE_EVENT#"
USAGE_RESULT_SK_PREFIX = "USAGE_RESULT#"
USAGE_RESULT_TTL_ATTRIBUTE = "expires_at_epoch"
USAGE_EXECUTION_SK_PREFIX = "USAGE_EXECUTION#"


def email_pk(email: str) -> str:
    return f"EMAIL#{email}"


def user_pk(user_id: str) -> str:
    return f"USER#{user_id}"


def session_pk(token: str) -> str:
    return f"SESSION#{token}"


def preload_sk(page_url: str) -> str:
    normalized = normalize_page_url(page_url)
    url_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"{PRELOAD_SK_PREFIX}{url_hash}"


def preload_id_sk(preload_id: str) -> str:
    return f"{PRELOAD_ID_SK_PREFIX}{preload_id}"


def phrase_sk(phrase_id: str) -> str:
    return f"{PHRASE_SK_PREFIX}{phrase_id}"


def usage_sk(month: str) -> str:
    return f"{USAGE_SK_PREFIX}{month}"


def usage_operation_sk(operation_id: str) -> str:
    return f"{USAGE_OPERATION_SK_PREFIX}{operation_id}"


def usage_event_sk(operation_id: str, transition: str) -> str:
    return f"{USAGE_EVENT_SK_PREFIX}{operation_id}#{transition}"


def usage_result_sk(operation_id: str) -> str:
    return f"{USAGE_RESULT_SK_PREFIX}{operation_id}"


def usage_execution_sk(operation_id: str) -> str:
    return f"{USAGE_EXECUTION_SK_PREFIX}{operation_id}"


def stripe_customer_pk(stripe_customer_id: str) -> str:
    return f"STRIPE_CUSTOMER#{stripe_customer_id}"
