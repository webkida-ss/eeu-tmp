from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "reading-assistant-ci.yml"
DEPLOY_WORKFLOW = ROOT / ".github" / "workflows" / "deploy-reading-assistant.yml"
sys.path.insert(0, str(ROOT / "scripts" / "schema"))
import schema_tasks  # noqa: E402


@pytest.mark.parametrize("workflow", [WORKFLOW, DEPLOY_WORKFLOW], ids=lambda path: path.name)
def test_all_workflow_actions_are_pinned_to_full_commit_shas(workflow):
    text = workflow.read_text(encoding="utf-8")
    uses = re.findall(r"^\s*uses:\s*([^\s#]+)(?:\s+#\s*(.+))?$", text, re.MULTILINE)
    assert uses
    for reference, comment in uses:
        assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", reference), reference
        assert comment and re.search(r"\bv\d", comment), reference


def test_workflow_selects_event_specific_compatibility_baseline():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "github.event.before" in text
    assert "github.event.pull_request.base.sha" in text
    assert "0000000000000000000000000000000000000000" in text
    assert "workflow_dispatch:" in text
    assert "inputs.trusted_base_sha" in text
    assert "vars.SCHEMA_COMPATIBILITY_BASE_SHA" not in text
    assert "SCHEMA_BASE_SHA=HEAD" not in text


def test_ci_builds_and_validates_lambda_through_canonical_task():
    text = WORKFLOW.read_text(encoding="utf-8")
    canonical_command = "run: ./scripts/bootstrap.sh --exec task build:lambda"

    assert text.count(canonical_command) == 1
    assert "backend/scripts/build_lambda.sh" not in text
    assert "backend/test_lambda_package.py" not in text
    assert "--ignore=backend/test_lambda_package.py" not in text
    assert "--ignore-glob" not in text


def test_push_baseline_classifier_never_uses_current_head():
    assert (
        schema_tasks.select_compatibility_baseline(
            event_name="push",
            before_sha="1" * 40,
            pull_request_base_sha="",
        )
        == "1" * 40
    )
    assert (
        schema_tasks.select_compatibility_baseline(
            event_name="pull_request",
            before_sha="2" * 40,
            pull_request_base_sha="3" * 40,
        )
        == "3" * 40
    )
    with pytest.raises(ValueError, match="All-zero"):
        schema_tasks.select_compatibility_baseline(
            event_name="push",
            before_sha="0" * 40,
            pull_request_base_sha="",
        )
    with pytest.raises(ValueError):
        schema_tasks.select_compatibility_baseline(
            event_name="push",
            before_sha="HEAD",
            pull_request_base_sha="",
        )


def test_deploy_workflow_supplies_state_bucket_at_init() -> None:
    text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    assert "vars.TERRAFORM_STATE_BUCKET" in text
    assert text.count('-backend-config="bucket=${TERRAFORM_STATE_BUCKET}"') == 2
    assert "task secrets:check" not in text


def test_backend_tf_does_not_pin_a_bucket_name() -> None:
    for environment in ("dev", "prod"):
        text = (ROOT / "infra" / "envs" / environment / "backend.tf").read_text(
            encoding="utf-8"
        )
        assert re.search(r"(?m)^\s*bucket\s*=", text) is None
        assert "replace-with-state-bucket" not in text
