from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
WORKFLOWS = sorted((*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")))
CI = WORKFLOW_DIR / "reading-assistant-ci.yml"
NIGHTLY = WORKFLOW_DIR / "nightly-automation.yml"
OPTIONAL = WORKFLOW_DIR / "optional-pr-browser-smoke.yml"
CODEQL = WORKFLOW_DIR / "codeql.yml"
INTAKE = WORKFLOW_DIR / "agent-intake.yml"
DEPLOY = WORKFLOW_DIR / "deploy-reading-assistant.yml"
DYNAMODB_DIGEST = (
    "amazon/dynamodb-local@sha256:d89f8fcc6b1a39cb35976c248ed42a28c66ae00dc043099210f5571e42648ab4"
)
ACTION_PROVENANCE = ROOT / "scripts" / "tool-locks" / "github-actions" / "provenance.json"


def workflow_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_every_workflow_action_is_immutable_and_documented() -> None:
    assert WORKFLOWS
    for workflow in WORKFLOWS:
        text = workflow_text(workflow)
        uses = re.findall(r"^\s*uses:\s*([^\s#]+)(?:\s+#\s*(.+))?$", text, re.MULTILINE)
        for reference, comment in uses:
            assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", reference), (
                workflow.name,
                reference,
            )
            assert comment and re.search(r"\bv\d", comment), (
                workflow.name,
                reference,
            )


def test_reviewed_action_refs_use_peeled_commit_provenance() -> None:
    fixture = json.loads(ACTION_PROVENANCE.read_text(encoding="utf-8"))
    reviewed = fixture["reviewed_refs"]
    observed: dict[str, str] = {}
    for workflow in WORKFLOWS:
        for reference, comment in re.findall(
            r"^\s*uses:\s*([^\s#]+)(?:\s+#\s*(.+))?$",
            workflow_text(workflow),
            re.MULTILINE,
        ):
            action, sha = reference.rsplit("@", 1)
            version = re.search(r"\bv\d+(?:\.\d+)*", comment or "")
            if version:
                observed[f"{action}@{version.group()}"] = sha

    assert reviewed
    for action_ref, provenance in reviewed.items():
        commit_sha = provenance["commit_sha"]
        peeled_commit_sha = provenance["peeled_commit_sha"]
        tag_ref_sha = provenance["tag_ref_sha"]
        assert re.fullmatch(r"[0-9a-f]{40}", commit_sha)
        assert re.fullmatch(r"[0-9a-f]{40}", peeled_commit_sha)
        assert re.fullmatch(r"[0-9a-f]{40}", tag_ref_sha)
        assert commit_sha == peeled_commit_sha
        assert observed[action_ref] == peeled_commit_sha
        if provenance["tag_type"] == "annotated":
            assert provenance["annotated_tag_object_sha"] == tag_ref_sha
            assert peeled_commit_sha != tag_ref_sha
            assert observed[action_ref] != tag_ref_sha
        else:
            assert provenance["tag_type"] == "lightweight"
            assert peeled_commit_sha == tag_ref_sha


def test_every_pinned_action_has_repository_provenance() -> None:
    fixture = json.loads(ACTION_PROVENANCE.read_text(encoding="utf-8"))
    provenance = fixture["pinned_commits"]
    observed: set[str] = set()
    for workflow in WORKFLOWS:
        for reference in re.findall(
            r"^\s*uses:\s*([^\s#]+)", workflow_text(workflow), re.MULTILINE
        ):
            observed.add(reference)

    assert set(provenance) == observed
    for reference, metadata in provenance.items():
        assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", reference)
        assert metadata["source"].startswith("https://github.com/")
        assert metadata["review_basis"] in {
            "reviewed tag provenance",
            "existing pinned repository workflow",
        }


def test_workflows_avoid_privileged_pr_trigger_and_default_to_read_only() -> None:
    for workflow in WORKFLOWS:
        text = workflow_text(workflow)
        assert "pull_request_target" not in text, workflow.name
        assert re.search(r"(?m)^permissions:\n  contents: read$", text), workflow.name

    issue_writers = [path.name for path in WORKFLOWS if "issues: write" in workflow_text(path)]
    assert issue_writers == [NIGHTLY.name]
    nightly = workflow_text(NIGHTLY)
    assert nightly.count("issues: write") == 1
    assert re.search(
        r"(?ms)^  notify:.*?^    permissions:\n"
        r"      contents: read\n      issues: write$",
        nightly,
    )


def test_every_checkout_disables_persisted_credentials() -> None:
    for workflow in WORKFLOWS:
        text = workflow_text(workflow)
        checkouts = list(re.finditer(r"actions/checkout@", text))
        for checkout in checkouts:
            end = text.find("\n      - ", checkout.end())
            block = text[checkout.start() : end if end != -1 else len(text)]
            assert "persist-credentials: false" in block, workflow.name


def test_dispatch_inputs_enter_actor_gates_through_quoted_environment_variables() -> None:
    intake = workflow_text(INTAKE)
    deploy = workflow_text(DEPLOY)

    assert "ISSUE_NUMBER: ${{ inputs.issue_number }}" in intake
    assert '--issue-number "${ISSUE_NUMBER}"' in intake

    for input_name, environment_name, option_name in (
        ("environment", "DEPLOY_ENVIRONMENT", "environment"),
        ("operation", "DEPLOY_OPERATION", "operation"),
        (
            "production_confirmation",
            "PRODUCTION_CONFIRMATION",
            "production-confirmation",
        ),
    ):
        assert f"{environment_name}: ${{{{ inputs.{input_name} }}}}" in deploy
        assert f'--{option_name} "${{{environment_name}}}"' in deploy

    for workflow in (intake, deploy):
        gate_scripts = re.findall(
            r"(?ms)^      - name: Gate .*?^        run: \|\n(.*?)(?=^      - |\Z)",
            workflow,
        )
        assert gate_scripts
        assert all("${{" not in script for script in gate_scripts)


def test_required_ci_uses_tasks_and_retains_lambda_artifact() -> None:
    text = workflow_text(CI)
    for task in (
        "setup:backend",
        "setup:extension",
        "deps:backend:check",
        "format:backend:check",
        "lint:backend",
        "api:check",
        "build:lambda",
        "test:backend:integration",
        "test:backend:coverage",
        "test:extension:coverage",
        "test:extension:automation:static",
        "infra:lock:check",
        "infra:validate",
    ):
        assert f"./scripts/bootstrap.sh --exec task {task}" in text
    assert DYNAMODB_DIGEST in text
    assert "backend/dist/reading-assistant-lambda.zip" in text
    assert "if-no-files-found: error" in text
    assert re.search(r"(?ms)name: Upload Lambda package.*?retention-days: 14", text)
    assert text.index("task setup:backend") < text.index("task deps:backend:check")
    assert text.index("task deps:backend:check") < text.index("task format:backend:check")
    taskfile = (ROOT / "Taskfile.yaml").read_text(encoding="utf-8")
    assert "npm ci --ignore-scripts --prefix extension" in taskfile
    assert text.index("task setup:extension") < text.index("task test:extension:coverage")
    run_commands = "\n".join(match.group(1) for match in re.finditer(r"(?m)^\s*run:\s*(.+)$", text))
    assert not re.search(
        r"\b(?:pytest|node --test|terraform (?:fmt|init|validate))\b",
        run_commands,
    )
    agent_job = re.search(r"(?ms)^  agent-config:.*?(?=^  [a-z][\w-]+:|\Z)", text)
    assert agent_job
    assert "task setup:agents" in agent_job.group()
    assert "task setup:backend" not in agent_job.group()
    taskfile = (ROOT / "Taskfile.yaml").read_text(encoding="utf-8")
    assert "python3 -m unittest backend.test_agent_configuration" in taskfile


def test_all_uploaded_artifacts_have_fourteen_day_retention() -> None:
    for workflow in WORKFLOWS:
        text = workflow_text(workflow)
        starts = [match.start() for match in re.finditer(r"actions/upload-artifact@", text)]
        for index, start in enumerate(starts):
            end = starts[index + 1] if index + 1 < len(starts) else len(text)
            assert "retention-days: 14" in text[start:end], workflow.name


def test_nightly_runs_non_skipping_service_and_browser_lifecycle() -> None:
    text = workflow_text(NIGHTLY)
    assert "schedule:" in text and "workflow_dispatch:" in text
    assert "group: nightly-automation" in text
    assert "cancel-in-progress: false" in text
    assert DYNAMODB_DIGEST in text
    assert "DYNAMODB_INTEGRATION_ENDPOINT: http://localhost:8000" in text
    for task in (
        "setup",
        "setup:browser",
        "test:backend:integration",
        "test:extension:smoke",
        "test:extension:automation:lifecycle",
    ):
        assert f"./scripts/bootstrap.sh --exec task {task}" in text
    assert "if: failure()" in text
    assert "nightly-playwright-${{ github.run_id }}-${{ github.run_attempt }}" in text


def test_nightly_issue_is_deduplicated_and_has_safe_body() -> None:
    text = workflow_text(NIGHTLY)
    marker = "<!-- untangle-nightly-automation -->"
    assert "github.rest.issues.listForRepo" in text
    assert "issue.title === title" in text
    assert marker in text
    assert 'issue.user?.login === "github-actions[bot]"' in text
    assert "issue.body?.includes(marker)" in text
    assert "github.rest.issues.update" in text
    assert "github.rest.issues.create" in text
    assert 'state: "closed"' in text
    assert "matches.length > 1" in text
    assert "reconciling #${issue.number} only" in text
    assert 'return left.state === "open" ? -1 : 1' in text
    assert "return left.number - right.number" in text
    assert "context.runId" in text
    assert "Status: ${result}" in text
    assert "This issue intentionally contains no workflow logs." in text
    for untrusted_source in (
        "context.payload.issue",
        "context.payload.pull_request",
        "steps.",
        "needs.nightly-tests.outputs",
    ):
        assert untrusted_source not in text


def test_optional_browser_run_requires_trusted_label_actor_and_association() -> None:
    text = workflow_text(OPTIONAL)
    assert "pull_request:" in text
    assert "workflow_dispatch:" in text
    assert "types:\n      - labeled" in text
    assert "github.event.label.name == 'run-browser-smoke'" in text
    assert "TRUSTED_BROWSER_AUTOMATION_ACTOR_IDS" in text
    assert "github.actor_id" in text
    assert '["OWNER","MEMBER","COLLABORATOR"]' in text
    assert "github.event.pull_request.author_association" in text
    assert "persist-credentials: false" in text
    assert "${{ secrets." not in text
    assert "issues: write" not in text
    assert "test:extension:smoke" in text
    assert "if: failure()" in text


def test_codeql_covers_python_and_javascript_with_generated_paths_ignored() -> None:
    text = workflow_text(CODEQL)
    config = workflow_text(ROOT / ".github" / "codeql" / "codeql-config.yml")
    assert "push:" in text and "pull_request:" in text and "schedule:" in text
    assert "security-events: write" in text
    assert "\n          - python\n" in text
    assert "\n          - javascript-typescript\n" in text
    assert "github/codeql-action/init@" in text
    assert "github/codeql-action/analyze@" in text
    for ignored in ("backend/generated/**", "extension/generated/**", "output/**"):
        assert ignored in config


def test_dependabot_covers_all_managed_dependency_ecosystems() -> None:
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    updates = config["updates"]
    assert {entry["package-ecosystem"] for entry in updates} == {
        "npm",
        "pip",
        "github-actions",
    }
    for entry in updates:
        assert entry["schedule"]["interval"] == "monthly"
        assert entry["open-pull-requests-limit"] <= 2
        assert entry["groups"]

    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "Dependabot cannot run" in contributing
    assert "task deps:backend:lock" in contributing
    assert "task deps:backend:check" in contributing


def test_templates_and_setup_contracts_are_valid() -> None:
    issue_dir = ROOT / ".github" / "ISSUE_TEMPLATE"
    config = yaml.safe_load((issue_dir / "config.yml").read_text(encoding="utf-8"))
    assert config["blank_issues_enabled"] is False
    for filename in ("bug.yml", "automation-failure.yml"):
        template = yaml.safe_load((issue_dir / filename).read_text(encoding="utf-8"))
        assert template["name"]
        assert template["description"]
        assert template["body"]

    pull_request_template = (ROOT / ".github" / "pull_request_template.md").read_text(
        encoding="utf-8"
    )
    for heading in (
        "Summary",
        "Verification",
        "Security and privacy",
        "API schema",
        "Deployment",
        "Agent evidence",
    ):
        assert f"## {heading}" in pull_request_template


def test_actionlint_bootstrap_and_node_runtime_are_pinned() -> None:
    installer = (ROOT / "scripts" / "install-actionlint.sh").read_text(encoding="utf-8")
    lock_lines = (
        (ROOT / "scripts" / "tool-locks" / "actionlint" / "checksums.tsv")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert 'readonly VERSION="1.7.12"' in installer
    assert "Archive checksum mismatch" in installer
    assert installer.index("Archive checksum mismatch") < installer.index(
        '"${TEMP_DIR}/actionlint" -version'
    )
    assert len(lock_lines) == 5
    assert all(
        re.fullmatch(r"[0-9a-f]{64}", field)
        for line in lock_lines[1:]
        for field in line.split("\t")[2:]
    )

    assert 'readonly NODE_VERSION="22.23.1"' in (ROOT / "scripts" / "bootstrap.sh").read_text(
        encoding="utf-8"
    )
    assert 'node = "22.23.1"' in (ROOT / "mise.toml").read_text(encoding="utf-8")
