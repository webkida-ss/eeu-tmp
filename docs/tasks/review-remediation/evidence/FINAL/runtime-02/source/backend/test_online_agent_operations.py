from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
INTAKE_WORKFLOW = ROOT / ".github" / "workflows" / "agent-intake.yml"
DEPLOY_WORKFLOW = ROOT / ".github" / "workflows" / "deploy-reading-assistant.yml"
ROLE_NAMES = {
    "planner",
    "implementer",
    "test-runner",
    "ci-investigator",
    "correctness-reviewer",
    "security-reviewer",
    "release-preparer",
}
SKILL_NAMES = {
    "online-task-intake",
    "ci-failure-triage",
    "pr-evidence-preparation",
    "release-preparation",
}


def workflow_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def workflow_step(workflow: Path, step_name: str) -> dict:
    parsed = yaml.safe_load(workflow_text(workflow))
    for job in parsed["jobs"].values():
        for step in job.get("steps", []):
            if step.get("name") == step_name:
                return {
                    **step,
                    "env": {
                        **job.get("env", {}),
                        **step.get("env", {}),
                    },
                }
    raise AssertionError(f"Missing workflow step: {step_name}")


def assert_rejected_actor_cannot_execute_dispatch_input(
    workflow: Path,
    step_name: str,
    input_environment_name: str,
    temp_path: Path,
) -> None:
    step = workflow_step(workflow, step_name)
    environment = step["env"]
    sentinel = temp_path / f"{workflow.stem}-{input_environment_name}-sentinel"
    network_blocker = temp_path / f"network-blocker-{sentinel.name}-{step_name.split()[1]}"
    network_blocker.mkdir()
    (network_blocker / "sitecustomize.py").write_text(
        """
import socket

_original_socket = socket.socket


def deny_network(*args, **kwargs):
    raise RuntimeError("network access disabled by regression harness")


class NetworkDisabledSocket(_original_socket):
    def connect(self, address):
        deny_network(address)

    def connect_ex(self, address):
        deny_network(address)


socket.socket = NetworkDisabledSocket
socket.create_connection = deny_network
socket.getaddrinfo = deny_network
""".lstrip(),
        encoding="utf-8",
    )
    hostile_input = (
        f'$(touch "{sentinel}") "quoted"\n; touch "{sentinel}"; `touch "{sentinel}"` && :'
    )
    command_environment = {
        **os.environ,
        **environment,
        "GITHUB_TOKEN": "synthetic-test-token",
        "GITHUB_OUTPUT": str(temp_path / "github-output"),
        "PLAN_PREFIX": "terraform-plans",
        "PYTHONPATH": f"{network_blocker}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
        "TRUSTED_AGENT_ACTOR_IDS": "456",
        "TRUSTED_DEPLOY_ACTOR_IDS": "456",
        "POLICY_ACTOR_ID": "999",
        "POLICY_REPOSITORY": "owner/repository",
        "POLICY_GIT_REF": "refs/heads/main",
        "POLICY_WORKFLOW_REF": (
            f"owner/repository/.github/workflows/{workflow.name}@refs/heads/main"
        ),
        "POLICY_CHECKED_OUT_SHA": "a" * 40,
        "POLICY_RUN_ID": "100",
        "POLICY_RUN_ATTEMPT": "1",
        "POLICY_REF_PROTECTED": "true",
        "DEPLOY_ENVIRONMENT": "dev",
        "DEPLOY_OPERATION": "plan",
        input_environment_name: hostile_input,
    }

    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", step["run"]],
        cwd=ROOT,
        env=command_environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode != 0
    assert not sentinel.exists()
    failure = f"{result.stdout}\n{result.stderr}".lower()
    assert "request actor id is not trusted" in failure, failure
    assert "network access disabled by regression harness" not in failure


def test_shared_roles_have_least_authority_and_separation_contracts() -> None:
    source_dir = ROOT / ".rulesync" / "subagents"
    assert {path.stem for path in source_dir.glob("*.md")} == ROLE_NAMES
    for role in ROLE_NAMES:
        text = (source_dir / f"{role}.md").read_text(encoding="utf-8")
        normalized = " ".join(text.lower().split())
        for required in (
            "least authority",
            "task evidence",
            "untrusted",
            "prompt injection",
            "secret",
            "external write",
            "blocker",
            "handoff",
            "english",
        ):
            assert required in normalized, (role, required)

    implementer = " ".join(workflow_text(source_dir / "implementer.md").lower().split())
    reviewer = " ".join(workflow_text(source_dir / "correctness-reviewer.md").lower().split())
    security = " ".join(workflow_text(source_dir / "security-reviewer.md").lower().split())
    release = " ".join(workflow_text(source_dir / "release-preparer.md").lower().split())
    assert "must not approve" in implementer and "must not release" in implementer
    assert "must not mutate" in reviewer and "read-only" in reviewer
    assert "authentication" in security and "billing" in security and "infrastructure" in security
    assert "runtime read-only" in release
    assert "release plan and proposed evidence content" in release
    assert "explicit human approval" in release


def test_online_operation_skills_are_focused_and_do_not_duplicate_verify_or_reload() -> None:
    skill_root = ROOT / ".rulesync" / "skills"
    observed = {path.parent.name for path in skill_root.glob("*/SKILL.md")}
    assert SKILL_NAMES <= observed
    for name in SKILL_NAMES:
        text = workflow_text(skill_root / name / "SKILL.md")
        normalized = " ".join(text.split())
        assert "untrusted" in normalized.lower()
        assert "Task evidence" in normalized
        assert "external write" in normalized.lower()
        assert "verify-agents" not in text
        assert "reload extension" not in text.lower()


def test_roles_and_skills_are_generated_for_cursor_claude_and_codex() -> None:
    for directory, suffix in (
        (ROOT / ".cursor" / "agents", ".md"),
        (ROOT / ".claude" / "agents", ".md"),
        (ROOT / ".codex" / "agents", ".toml"),
    ):
        assert {path.stem for path in directory.glob(f"*{suffix}")} == ROLE_NAMES
        for role in ROLE_NAMES:
            text = workflow_text(directory / f"{role}{suffix}").lower()
            assert "least authority" in text
            assert "handoff" in text

    for directory in (
        ROOT / ".cursor" / "skills",
        ROOT / ".claude" / "skills",
        ROOT / ".agents" / "skills",
    ):
        for skill in SKILL_NAMES:
            assert (directory / skill / "SKILL.md").is_file()


def test_agent_issue_form_captures_scope_risk_and_tests_without_secret_fields() -> None:
    form = yaml.safe_load(workflow_text(ROOT / ".github" / "ISSUE_TEMPLATE" / "agent-task.yml"))
    ids = {entry.get("id") for entry in form["body"]}
    assert {
        "goal",
        "acceptance_criteria",
        "allowed_scope",
        "prohibited_scope",
        "risk_level",
        "test_expectations",
    } <= ids
    text = json.dumps(form).lower()
    for forbidden in ("password", "api key", "access token", "private key"):
        assert forbidden not in text
    assert form["labels"] == []


def test_manual_intake_workflow_is_read_only_pinned_and_never_checks_out_issue_ref() -> None:
    text = workflow_text(INTAKE_WORKFLOW)
    assert "workflow_dispatch:" in text
    assert re.search(r"(?m)^permissions:\n  contents: read\n  issues: read$", text)
    assert "TRUSTED_AGENT_ACTOR_IDS" in text
    assert "github.actor_id" in text
    assert "pull_request_target" not in text
    assert "${{ secrets." not in text
    assert "issues: write" not in text
    assert "contents: write" not in text
    assert "pull-requests: write" not in text
    assert "labels" not in text.lower()
    assert "ref: ${{ github.event.repository.default_branch }}" in text
    assert "persist-credentials: false" in text
    assert "validate_agent_intake.py" in text
    for reference, comment in re.findall(
        r"^\s*uses:\s*([^\s#]+)(?:\s+#\s*(.+))?$", text, re.MULTILINE
    ):
        assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", reference)
        assert comment and re.search(r"\bv\d", comment)


def test_rejected_actor_keeps_all_dispatch_inputs_literal(tmp_path: Path) -> None:
    assert_rejected_actor_cannot_execute_dispatch_input(
        INTAKE_WORKFLOW,
        "Gate identity and fetch minimal issue metadata",
        "ISSUE_NUMBER",
        tmp_path,
    )
    for input_environment_name in (
        "DEPLOY_ENVIRONMENT",
        "DEPLOY_OPERATION",
        "PRODUCTION_CONFIRMATION",
    ):
        for step_name in (
            "Gate dev actor, branch, roles, storage, and operation",
            "Gate prod actor, branch, roles, storage, and operation",
        ):
            assert_rejected_actor_cannot_execute_dispatch_input(
                DEPLOY_WORKFLOW,
                step_name,
                input_environment_name,
                tmp_path,
            )


def test_deploy_defaults_to_plan_and_production_apply_is_explicit_and_gated() -> None:
    text = workflow_text(DEPLOY_WORKFLOW)
    parsed = yaml.safe_load(text)
    inputs = parsed[True]["workflow_dispatch"]["inputs"]
    assert inputs["operation"]["default"] == "plan"
    assert set(inputs["operation"]["options"]) == {"plan", "apply"}
    assert inputs["production_confirmation"]["default"] == ""
    assert "plan_only" not in inputs
    assert re.search(r"(?m)^permissions:\n  contents: read$", text)
    assert text.count("id-token: write") == 2
    assert "inputs.operation == 'apply'" in text
    assert "inputs.production_confirmation" in text
    assert "environment: ${{ inputs.environment }}" in text
    assert "release-evidence-" in text
    assert "retention-days: 14" in text
    assert "terraform apply -input=false -auto-approve tfplan" in text


def test_online_operations_docs_cover_security_operation_and_external_blockers() -> None:
    operations = workflow_text(ROOT / "docs" / "ONLINE_AGENT_OPERATIONS.md").lower()
    release = workflow_text(ROOT / "docs" / "RELEASE_RUNBOOK.md").lower()
    drafts = workflow_text(ROOT / "docs" / "CURSOR_AUTOMATION_DRAFTS.md").lower()
    for required in (
        "immutable actor id",
        "prompt injection",
        "permission matrix",
        "audit log",
        "cost",
        "timeout",
        "incident stop switch",
        "rollback",
        "local fallback",
        "no git remote",
        "codeowners",
        "trusted actor ids",
        "github environments",
        "oidc",
        "cursor compute",
    ):
        assert required in operations
    for required in ("plan", "evidence", "approval", "deploy", "smoke", "rollback"):
        assert required in release
    for draft in (
        "trusted issue intake",
        "ci failure triage",
        "scheduled dependency maintenance",
    ):
        assert draft in drafts
    assert "external activation pending" in drafts
    assert "production always requires explicit human approval" in release
