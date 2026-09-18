from config import ADMIN_ENABLED
from main import app

EXPECTED_OPERATION_IDS = {
    ("GET", "/health"): "getHealth",
    ("GET", "/auth/config"): "getAuthConfig",
    ("POST", "/auth/login"): "createAuthSession",
    ("GET", "/auth/me"): "getCurrentUser",
    ("POST", "/auth/logout"): "closeAuthSession",
    ("GET", "/pages/preload"): "getPagePreload",
    ("POST", "/pages/preload"): "createPagePreload",
    ("GET", "/vocabulary"): "getVocabularyBook",
    ("POST", "/analyze"): "analyzeText",
    ("POST", "/chat"): "createChatReply",
    ("GET", "/phrases"): "listPhrases",
    ("POST", "/phrases"): "createPhrase",
    ("GET", "/billing/me"): "getBillingSummary",
    ("POST", "/billing/checkout"): "createBillingCheckout",
    ("POST", "/billing/portal"): "openBillingPortal",
    ("POST", "/billing/webhook"): "processBillingWebhook",
    ("GET", "/billing/done"): "getBillingDonePage",
}


def runtime_operation_ids():
    document = app.openapi()
    return {
        (method.upper(), path): operation["operationId"]
        for path, path_item in document["paths"].items()
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
    }


def test_operation_ids_are_explicit_unique_and_stable():
    actual = runtime_operation_ids()
    expected = dict(EXPECTED_OPERATION_IDS)
    if ADMIN_ENABLED:
        expected[("GET", "/admin/v1/session")] = "getAdminSession"
    assert actual == expected
    assert len(set(actual.values())) == len(expected)


def test_repeated_openapi_generation_keeps_operation_ids_stable():
    first = runtime_operation_ids()
    app.openapi_schema = None
    second = runtime_operation_ids()
    assert second == first
