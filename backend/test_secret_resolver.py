from __future__ import annotations

from unittest.mock import patch

import secret_resolver


def test_resolve_runtime_secrets_keeps_existing_env(monkeypatch) -> None:
    secret_resolver._get_ssm_parameter.cache_clear()
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    monkeypatch.setenv(
        "OPENAI_API_KEY_SSM_PARAMETER", "/english/dev/reading-assistant/OPENAI_API_KEY"
    )
    with patch.object(secret_resolver, "_get_ssm_parameter", return_value="from-ssm") as fetch:
        secret_resolver.resolve_runtime_secrets()
    assert fetch.call_count == 0
    assert secret_resolver.os.getenv("OPENAI_API_KEY") == "from-env"


def test_resolve_runtime_secrets_loads_ssm_when_env_empty(monkeypatch) -> None:
    secret_resolver._get_ssm_parameter.cache_clear()
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.setenv(
        "STRIPE_SECRET_KEY_SSM_PARAMETER", "/english/dev/reading-assistant/STRIPE_SECRET_KEY"
    )
    with patch.object(secret_resolver, "_get_ssm_parameter", return_value="sk_test_loaded"):
        secret_resolver.resolve_runtime_secrets()
    assert secret_resolver.os.getenv("STRIPE_SECRET_KEY") == "sk_test_loaded"


def test_resolve_runtime_secrets_treats_placeholder_as_unset(monkeypatch) -> None:
    secret_resolver._get_ssm_parameter.cache_clear()
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "REPLACE_ME")
    monkeypatch.setenv(
        "STRIPE_WEBHOOK_SECRET_SSM_PARAMETER",
        "/english/dev/reading-assistant/STRIPE_WEBHOOK_SECRET",
    )
    with patch.object(secret_resolver, "_get_ssm_parameter", return_value="REPLACE_ME"):
        secret_resolver.resolve_runtime_secrets()
    assert not secret_resolver.os.getenv("STRIPE_WEBHOOK_SECRET")
