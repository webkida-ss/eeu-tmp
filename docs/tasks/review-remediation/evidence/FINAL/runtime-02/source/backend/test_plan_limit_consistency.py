"""Guard the backend plan defaults against Terraform environment drift."""

from __future__ import annotations

import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from core.plans import load_plans

ROOT = Path(__file__).resolve().parents[1]
PLAN_FIELDS = (
    "articles_per_month",
    "chats_per_month",
    "sentences_per_article",
    "source_tokens_per_article",
    "cost_micro_usd_per_month",
    "tokens_per_month",
)
TERRAFORM_FIELDS = tuple(field.upper() for field in PLAN_FIELDS)
EXPECTED_LIMITS = {
    "basic": (3, 15, 50, 12_000, 200_000, 200_000),
    "pro": (40, 400, 150, 36_000, 2_500_000, 3_000_000),
    "max": (120, 1_200, 300, 72_000, 7_000_000, 10_000_000),
}


def _terraform_plan_defaults(path: Path) -> dict[str, tuple[int, ...]]:
    """Read the literal PLAN_* defaults from a Terraform variable block."""
    source = path.read_text(encoding="utf-8")
    block_match = re.search(
        r'^variable "usage_pricing_and_plan_environment" \{(?P<body>.*?)(?=^variable |\Z)',
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    if block_match is None:
        raise AssertionError(f"usage_pricing_and_plan_environment block missing in {path}")

    values: dict[str, int] = {}
    for key, raw_value in re.findall(
        r'^\s*(PLAN_[A-Z0-9_]+)\s*=\s*"([^\"]*)"\s*$',
        block_match.group("body"),
        flags=re.MULTILINE,
    ):
        if key in values:
            raise AssertionError(f"duplicate Terraform plan key {key} in {path}")
        try:
            values[key] = int(raw_value)
        except ValueError as exc:
            raise AssertionError(f"non-integer Terraform plan value {key}={raw_value!r}") from exc

    expected_keys = {
        f"PLAN_{plan.upper()}_{field.upper()}"
        for plan in EXPECTED_LIMITS
        for field in TERRAFORM_FIELDS
    }
    assert set(values) == expected_keys, f"unexpected Terraform plan keys in {path}"

    return {
        plan: tuple(values[f"PLAN_{plan.upper()}_{field}"] for field in TERRAFORM_FIELDS)
        for plan in EXPECTED_LIMITS
    }


def test_backend_and_terraform_plan_defaults_are_identical() -> None:
    with patch.dict(os.environ, {}, clear=True):
        loaded_plans = load_plans()
        backend_limits = {
            plan: tuple(getattr(loaded_plans[plan], field) for field in PLAN_FIELDS)
            for plan in EXPECTED_LIMITS
        }

    assert backend_limits == EXPECTED_LIMITS
    for environment in ("dev", "prod"):
        assert (
            _terraform_plan_defaults(
                ROOT / "infra" / "envs" / environment / "variables.tf",
            )
            == EXPECTED_LIMITS
        )
    assert (
        _terraform_plan_defaults(
            ROOT / "infra" / "modules" / "reading-assistant-api" / "variables.tf",
        )
        == EXPECTED_LIMITS
    )


def test_malformed_backend_plan_override_is_rejected() -> None:
    with patch.dict(os.environ, {"PLAN_BASIC_ARTICLES_PER_MONTH": "not-an-integer"}, clear=True):
        with pytest.raises(ValueError):
            load_plans()


def _terraform_fixture(tmp_path: Path, entries: str) -> Path:
    path = tmp_path / "variables.tf"
    path.write_text(
        f'variable "usage_pricing_and_plan_environment" {{\n  default = {{\n{entries}  }}\n}}\n',
        encoding="utf-8",
    )
    return path


def test_terraform_plan_defaults_reject_missing_key(tmp_path: Path) -> None:
    entries = '    PLAN_BASIC_ARTICLES_PER_MONTH = "3"\n'
    with pytest.raises(AssertionError, match="unexpected Terraform plan keys"):
        _terraform_plan_defaults(_terraform_fixture(tmp_path, entries))


def test_terraform_plan_defaults_reject_duplicate_key(tmp_path: Path) -> None:
    entries = '    PLAN_BASIC_ARTICLES_PER_MONTH = "3"\n    PLAN_BASIC_ARTICLES_PER_MONTH = "3"\n'
    with pytest.raises(AssertionError, match="duplicate Terraform plan key"):
        _terraform_plan_defaults(_terraform_fixture(tmp_path, entries))


def test_terraform_plan_defaults_reject_unknown_plan_key(tmp_path: Path) -> None:
    entries = '    PLAN_ENTERPRISE_ARTICLES_PER_MONTH = "999"\n'
    with pytest.raises(AssertionError, match="unexpected Terraform plan keys"):
        _terraform_plan_defaults(_terraform_fixture(tmp_path, entries))


def test_terraform_plan_defaults_reject_malformed_value(tmp_path: Path) -> None:
    entries = '    PLAN_BASIC_ARTICLES_PER_MONTH = "three"\n'
    with pytest.raises(AssertionError, match="non-integer Terraform plan value"):
        _terraform_plan_defaults(_terraform_fixture(tmp_path, entries))
