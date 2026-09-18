from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "schema"))
import schema_tasks  # noqa: E402
from schema_tasks import SchemaError, validate_exceptions  # noqa: E402

TOOLS_ROOT = Path(os.environ.get("REPOSITORY_TOOLS_DIR", ROOT / ".tools"))
OASDIFF = TOOLS_ROOT / "oasdiff" / "1.23.0" / "bin" / "oasdiff"
INSTALLER = ROOT / "scripts" / "install-oasdiff.sh"


def test_runtime_contract_filters_only_explicit_admin_feature():
    bundle = schema_tasks.redocly_bundle()
    disabled = schema_tasks.contract_for_runtime(bundle, admin_enabled=False)
    enabled = schema_tasks.contract_for_runtime(bundle, admin_enabled=True)
    assert "/admin/v1/session" not in disabled["paths"]
    assert "/admin/v1/session" in enabled["paths"]
    assert set(disabled["paths"]) == set(enabled["paths"]) - {"/admin/v1/session"}
    assert "AdminSession" not in disabled["components"]["schemas"]
    assert "ApiError" in disabled["components"]["schemas"]


def test_runtime_contract_rejects_unknown_feature():
    bundle = schema_tasks.redocly_bundle()
    bundle["paths"]["/health"]["get"]["x-runtime-feature"] = "unknown"
    with pytest.raises(SchemaError, match="runtime feature"):
        schema_tasks.contract_for_runtime(bundle, admin_enabled=False)


def test_runtime_contract_rejects_feature_on_learner_operation():
    bundle = schema_tasks.redocly_bundle()
    bundle["paths"]["/health"]["get"]["x-runtime-feature"] = "admin"
    with pytest.raises(SchemaError, match="runtime feature"):
        schema_tasks.contract_for_runtime(bundle, admin_enabled=False)


def test_runtime_contract_rejects_unmarked_admin_operation():
    bundle = schema_tasks.redocly_bundle()
    del bundle["paths"]["/admin/v1/session"]["get"]["x-runtime-feature"]
    with pytest.raises(SchemaError, match="runtime feature"):
        schema_tasks.contract_for_runtime(bundle, admin_enabled=False)


def test_runtime_contract_rejects_unknown_mode(monkeypatch):
    monkeypatch.setenv("ADMIN_ENABLED", "typo")
    with pytest.raises(SchemaError, match="ADMIN_ENABLED"):
        schema_tasks.runtime_admin_enabled()


def test_admin_models_are_part_of_canonical_drift_gate():
    assert schema_tasks.GENERATED["backend/generated/admin_models.py"] == (
        ROOT / "backend/generated/admin_models.py"
    )


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def commit(repository: Path, message: str) -> None:
    git(repository, "add", ".")
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Contract Test",
            "-c",
            "user.email=contract@example.test",
            "commit",
            "-m",
            message,
        ],
        cwd=repository,
        check=True,
        text=True,
        capture_output=True,
    )


def initialize_repository(path: Path) -> None:
    path.mkdir()
    git(path, "init", "-b", "main")
    (path / "README.md").write_text("initial\n", encoding="utf-8")
    commit(path, "initial")


def add_contract(repository: Path) -> None:
    contract = repository / "contracts" / "openapi"
    contract.mkdir(parents=True)
    (contract / "openapi.yaml").write_text(
        "openapi: 3.1.0\ninfo: {title: test, version: '1'}\npaths: {}\n",
        encoding="utf-8",
    )
    commit(repository, "add canonical contract")


def write_spec(path: Path, *, include_name: bool) -> None:
    properties = {"id": {"type": "string"}}
    required = ["id"]
    if include_name:
        properties["name"] = {"type": "string"}
        required.append("name")
    document = {
        "openapi": "3.1.0",
        "info": {"title": "Synthetic", "version": "1"},
        "paths": {
            "/items": {
                "get": {
                    "operationId": "listItems",
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": properties,
                                        "required": required,
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
    }
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def test_checksum_pinned_oasdiff_detects_synthetic_breaking_change(tmp_path):
    subprocess.run([str(INSTALLER), "--verify"], cwd=ROOT, check=True)
    base = tmp_path / "base.yaml"
    revision = tmp_path / "revision.yaml"
    write_spec(base, include_name=True)
    write_spec(revision, include_name=False)
    result = subprocess.run(
        [
            str(OASDIFF),
            "breaking",
            str(base),
            str(revision),
            "--allow-external-refs=false",
            "--fail-on",
            "ERR",
        ],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "required" in (result.stdout + result.stderr).lower()


def test_generator_supports_singular_success_response_example():
    bundle = schema_tasks.redocly_bundle()
    media = bundle["paths"]["/health"]["get"]["responses"]["200"]["content"]["application/json"]
    value = media.pop("examples")["happy"]["value"]
    media["example"] = value
    generated = schema_tasks.generated_outputs(bundle)
    document = __import__("json").loads(generated["backend/generated/openapi-contract-cases.json"])
    health_cases = [case for case in document["cases"] if case["operationId"] == "getHealth"]
    assert health_cases == [
        {
            "auth": "anonymous",
            "caseId": "response-200-application-json-example",
            "caseKind": "success",
            "exampleName": "example",
            "expectedMediaType": "application/json",
            "expectedStatus": 200,
            "invoke": True,
            "method": "GET",
            "mode": "generic",
            "operationId": "getHealth",
            "parameters": {},
            "path": "/health",
            "requestBody": None,
            "requestMediaType": None,
            "responseExample": {"status": "ok"},
            "setup": "none",
        }
    ]


def test_operation_validation_allows_additive_operation():
    bundle = schema_tasks.redocly_bundle()
    operation = {
        "operationId": "getNewResource",
        "responses": {
            "200": {
                "description": "ok",
                "content": {
                    "application/json": {
                        "example": {"status": "ok"},
                        "schema": {"type": "object"},
                    }
                },
            }
        },
        "security": [],
        "x-contract-test": {
            "mode": "generic",
            "owner": "backend",
            "auth": "anonymous",
            "setup": "none",
        },
    }
    bundle["paths"]["/new-resource"] = {"get": operation}
    operation_map = schema_tasks.validate_operation_ids(bundle)
    assert operation_map["getNewResource"] == ("get", "/new-resource")


@pytest.mark.parametrize(
    "operation_id",
    ["class", "await", "yield", "arguments", "eval", "1invalid", "bad-name"],
)
def test_operation_validation_rejects_unsafe_javascript_symbols(operation_id):
    bundle = schema_tasks.redocly_bundle()
    bundle["paths"]["/health"]["get"]["operationId"] = operation_id
    with pytest.raises(SchemaError, match="operationId|ECMAScript"):
        schema_tasks.validate_operation_ids(bundle)


@pytest.mark.parametrize(
    "hostile_ref",
    [
        "https://attacker.invalid/schema.yaml",
        "/etc/passwd",
        "../outside.yaml",
        "components/../../outside.yaml",
    ],
)
def test_redocly_preflight_rejects_hostile_refs_before_invocation(
    tmp_path, monkeypatch, hostile_ref
):
    contract = tmp_path / "contracts" / "openapi"
    contract.mkdir(parents=True)
    source = contract / "openapi.yaml"
    source.write_text(
        yaml.safe_dump(
            {
                "openapi": "3.1.0",
                "info": {"title": "test", "version": "1"},
                "paths": {"/x": {"$ref": hostile_ref}},
            }
        ),
        encoding="utf-8",
    )
    calls = []
    monkeypatch.setattr(schema_tasks, "run", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(SchemaError, match="(?i)reference|ref"):
        schema_tasks.redocly_bundle(source)
    assert calls == []


def test_runtime_drift_detects_webhook_body_limit_mismatch(tmp_path):
    bundle = schema_tasks.redocly_bundle()
    bundle["paths"]["/billing/webhook"]["post"]["x-max-body-bytes"] += 1
    report = tmp_path / "normalization.json"
    with pytest.raises(SchemaError, match="x-max-body-bytes"):
        schema_tasks.check_runtime_drift(bundle, report_path=report)
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["status"] == "failed"
    assert data["canonical"]["paths"]["/billing/webhook"]["post"]["x-max-body-bytes"] == 262145


def test_webhook_runtime_limit_matches_canonical_contract():
    from main import MAX_WEBHOOK_BODY_BYTES

    bundle = schema_tasks.redocly_bundle()
    assert bundle["paths"]["/billing/webhook"]["post"]["x-max-body-bytes"] == MAX_WEBHOOK_BODY_BYTES


def test_manual_contract_metadata_rejects_stale_pytest_node():
    bundle = schema_tasks.redocly_bundle()
    bundle["paths"]["/auth/login"]["post"]["x-contract-test"]["test"] = (
        "backend/test_openapi_manual_contract.py::test_missing_node"
    )
    with pytest.raises(SchemaError, match="collected pytest node"):
        schema_tasks.validate_contract_metadata(bundle)


def test_exact_finding_fingerprint_waives_only_one_same_category_finding():
    findings = [
        {
            "id": "response-required-property-removed",
            "text": "removed required property `name`",
            "level": 3,
            "operation": "GET",
            "operationId": "listItems",
            "path": "/items",
            "section": "paths",
            "property": "responses.200.schema.required.name",
            "baseSource": {"file": "/tmp/a.yaml", "line": 10, "column": 3},
        },
        {
            "id": "response-required-property-removed",
            "text": "removed required property `description`",
            "level": 3,
            "operation": "GET",
            "operationId": "listItems",
            "path": "/items",
            "section": "paths",
            "property": "responses.200.schema.required.description",
            "baseSource": {"file": "/tmp/a.yaml", "line": 20, "column": 3},
        },
    ]
    first_fingerprint = schema_tasks.finding_fingerprint(findings[0])
    exceptions = [
        {
            "id": "waive-name-only",
            "kind": "compatibility",
            "owner": "api",
            "reason": "Approved synthetic rollout.",
            "approval": "ADR-test",
            "expires": "2099-01-01",
            "fingerprint": first_fingerprint,
            "operationId": "listItems",
            "property": "responses.200.schema.required.name",
            "consumers": ["extension"],
            "rollout": "synthetic",
            "monitoring": "synthetic",
            "rollback": "synthetic",
        }
    ]
    with pytest.raises(SchemaError, match="unapproved"):
        schema_tasks.apply_compatibility_exceptions(findings, exceptions)
    assert schema_tasks.finding_fingerprint(findings[1]) != first_fingerprint


def test_exact_compatibility_exception_schema_is_validated(tmp_path):
    entry = {
        "id": "waive-one-finding",
        "kind": "compatibility",
        "owner": "api",
        "reason": "Approved synthetic rollout.",
        "approval": "ADR-test",
        "expires": "2099-01-01",
        "fingerprint": f"sha256:{'a' * 64}",
        "operationId": "listItems",
        "property": "responses.200.schema.required.name",
        "consumers": ["extension"],
        "rollout": "synthetic",
        "monitoring": "synthetic",
        "rollback": "synthetic",
    }
    path = tmp_path / "exceptions.yaml"
    path.write_text(
        yaml.safe_dump({"version": 1, "exceptions": [entry]}, sort_keys=False),
        encoding="utf-8",
    )
    assert validate_exceptions(path) == [entry]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("operationId", "getOtherItems"),
        ("property", "responses.200.schema.required.other"),
    ],
)
def test_compatibility_exception_review_identity_must_match_finding(field, value):
    finding = {
        "id": "response-required-property-removed",
        "operationId": "listItems",
        "property": "responses.200.schema.required.name",
        "path": "/items",
    }
    exception = {
        "id": "waive-name-only",
        "kind": "compatibility",
        "owner": "api",
        "reason": "Approved synthetic rollout.",
        "approval": "ADR-test",
        "expires": "2099-01-01",
        "fingerprint": schema_tasks.finding_fingerprint(finding),
        "operationId": "listItems",
        "property": "responses.200.schema.required.name",
        "consumers": ["extension"],
        "rollout": "synthetic",
        "monitoring": "synthetic",
        "rollback": "synthetic",
    }
    exception[field] = value
    with pytest.raises(SchemaError, match="review identity"):
        schema_tasks.apply_compatibility_exceptions([finding], [exception])


@pytest.mark.parametrize("context", ["bootstrap", "compatibility check"])
def test_all_compatibility_modes_reject_unused_exception(context):
    with pytest.raises(SchemaError, match=f"{context}.*unused"):
        schema_tasks.reject_unused_compatibility_exceptions(
            [{"id": "unused", "kind": "compatibility"}],
            context=context,
        )


def test_oasdiff_raw_and_normalized_reports_are_separate_and_sanitized(tmp_path):
    raw = '[{"id":"changed","operationId":"listItems","property":"name"}]\n'
    finding = json.loads(raw)[0]
    schema_tasks.write_oasdiff_reports(
        raw_report=raw,
        findings=[finding],
        status="failed",
        base_label="abc123",
        applied=set(),
        report_dir=tmp_path,
    )
    assert (tmp_path / "oasdiff.json").read_text(encoding="utf-8") == raw
    normalized = json.loads((tmp_path / "oasdiff-normalized.json").read_text(encoding="utf-8"))
    assert normalized["findings"][0]["fingerprint"] == schema_tasks.finding_fingerprint(finding)
    assert normalized["findings"][0]["reviewOperationId"] == "listItems"
    assert normalized["findings"][0]["reviewProperty"] == "name"
    assert str(ROOT) not in json.dumps(normalized)


def test_schema_reports_are_deterministic_and_path_sanitized(tmp_path):
    bundle = schema_tasks.redocly_bundle()
    report_dir = tmp_path / "schema"
    schema_tasks.write_check_reports(bundle, report_dir=report_dir)
    first = {path.name: path.read_bytes() for path in report_dir.iterdir()}
    schema_tasks.write_check_reports(bundle, report_dir=report_dir)
    second = {path.name: path.read_bytes() for path in report_dir.iterdir()}
    assert first == second
    assert {
        "normalization.json",
        "operation-map.json",
        "route-security.json",
    }.issubset(first)
    route_security = json.loads(first["route-security.json"])
    assert route_security["appliedExceptions"] == []
    for content in first.values():
        assert str(ROOT).encode() not in content


@pytest.mark.parametrize(
    "entry",
    [
        {
            "id": "broad",
            "kind": "compatibility",
            "owner": "api",
            "reason": "Synthetic invalid broad exception.",
            "operationId": "listItems",
            "property": "*",
            "approval": "ADR-test",
            "expires": "2099-01-01",
            "consumers": ["extension"],
            "rollout": "test",
            "monitoring": "test",
            "rollback": "test",
        },
        {
            "id": "expired",
            "kind": "compatibility",
            "owner": "api",
            "reason": "Synthetic expired exception.",
            "operationId": "listItems",
            "property": "responses.200",
            "approval": "ADR-test",
            "expires": "2000-01-01",
            "consumers": ["extension"],
            "rollout": "test",
            "monitoring": "test",
            "rollback": "test",
        },
    ],
    ids=["broad", "expired"],
)
def test_invalid_or_expired_compatibility_exception_fails_closed(tmp_path, entry):
    path = tmp_path / "exceptions.yaml"
    path.write_text(
        yaml.safe_dump({"version": 1, "exceptions": [entry]}, sort_keys=False),
        encoding="utf-8",
    )
    with pytest.raises(SchemaError):
        validate_exceptions(path)


def test_oasdiff_installer_rejects_bad_checksum_before_replacement(tmp_path):
    archive = tmp_path / "oasdiff.tar.gz"
    archive.write_bytes(b"not a trusted release archive")
    before = OASDIFF.read_bytes()
    result = subprocess.run(
        [str(INSTALLER), "--archive", str(archive)],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr.lower()
    assert OASDIFF.read_bytes() == before


def test_oasdiff_installer_ignores_hostile_path(tmp_path):
    hostile = tmp_path / "bin"
    hostile.mkdir()
    fake_shasum = hostile / "shasum"
    fake_shasum.write_text("#!/bin/sh\necho attacker\n", encoding="utf-8")
    fake_shasum.chmod(0o755)
    result = subprocess.run(
        [str(INSTALLER), "--verify"],
        cwd=ROOT,
        check=False,
        env={**os.environ, "PATH": f"{hostile}:{os.environ['PATH']}", "BASH_ENV": str(fake_shasum)},
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


def test_compatibility_base_classifies_true_first_contract(tmp_path):
    repository = tmp_path / "repository"
    initialize_repository(repository)
    git(repository, "switch", "-c", "feature")
    state = schema_tasks.classify_compatibility_base(
        repository=repository,
        head="HEAD",
        configured_ref="main",
    )
    assert state.mode == "bootstrap"
    assert state.base_ref == "main"


def test_compatibility_base_detects_established_contract(tmp_path):
    repository = tmp_path / "repository"
    initialize_repository(repository)
    add_contract(repository)
    git(repository, "switch", "-c", "feature")
    state = schema_tasks.classify_compatibility_base(
        repository=repository,
        head="HEAD",
        configured_ref="main",
    )
    assert state.mode == "compare"


def test_compatibility_base_rejects_stale_branch_when_base_tip_has_schema(tmp_path):
    repository = tmp_path / "repository"
    initialize_repository(repository)
    git(repository, "switch", "-c", "feature")
    git(repository, "switch", "main")
    add_contract(repository)
    git(repository, "switch", "feature")
    with pytest.raises(SchemaError, match="stale branch"):
        schema_tasks.classify_compatibility_base(
            repository=repository,
            head="HEAD",
            configured_ref="main",
        )


def test_compatibility_base_rejects_missing_configured_ref(tmp_path):
    repository = tmp_path / "repository"
    initialize_repository(repository)
    with pytest.raises(SchemaError, match="SCHEMA_BASE_REF"):
        schema_tasks.classify_compatibility_base(
            repository=repository,
            head="HEAD",
            configured_ref="origin/missing",
        )


def test_compatibility_base_rejects_shallow_history_without_merge_base(tmp_path):
    source = tmp_path / "source"
    initialize_repository(source)
    git(source, "switch", "-c", "feature")
    (source / "feature.txt").write_text("feature\n", encoding="utf-8")
    commit(source, "feature")
    git(source, "switch", "main")
    (source / "main.txt").write_text("main\n", encoding="utf-8")
    commit(source, "main")

    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "--depth=1", "--branch", "feature", f"file://{source}", str(shallow)],
        check=True,
        text=True,
        capture_output=True,
    )
    git(shallow, "fetch", "--depth=1", "origin", "main:refs/remotes/origin/main")
    with pytest.raises(SchemaError, match="shallow|merge base"):
        schema_tasks.classify_compatibility_base(
            repository=shallow,
            head="HEAD",
            configured_ref="origin/main",
        )


def test_zero_baseline_rejects_schema_introduction_head(tmp_path):
    repository = tmp_path / "repository"
    initialize_repository(repository)
    add_contract(repository)
    with pytest.raises(SchemaError, match="All-zero.*remote/default branch.*pull request"):
        schema_tasks.classify_compatibility_base(
            repository=repository,
            head="HEAD",
            baseline_sha="0" * 40,
        )


def test_zero_baseline_rejects_later_commit(tmp_path):
    repository = tmp_path / "repository"
    initialize_repository(repository)
    add_contract(repository)
    (repository / "later.txt").write_text("later\n", encoding="utf-8")
    commit(repository, "later change")
    with pytest.raises(SchemaError, match="All-zero.*manually approved"):
        schema_tasks.classify_compatibility_base(
            repository=repository,
            head="HEAD",
            baseline_sha="0" * 40,
        )


def test_zero_baseline_rejects_deleted_and_recreated_schema(tmp_path):
    repository = tmp_path / "repository"
    initialize_repository(repository)
    add_contract(repository)
    (repository / "contracts" / "openapi" / "openapi.yaml").unlink()
    commit(repository, "delete canonical contract")
    (repository / "contracts" / "openapi" / "openapi.yaml").write_text(
        "openapi: 3.1.0\ninfo: {title: test, version: '2'}\npaths: {}\n",
        encoding="utf-8",
    )
    commit(repository, "recreate canonical contract")
    with pytest.raises(SchemaError, match="All-zero.*manually approved"):
        schema_tasks.classify_compatibility_base(
            repository=repository,
            head="HEAD",
            baseline_sha="0" * 40,
        )


def test_zero_baseline_rejects_shallow_or_missing_history(tmp_path):
    source = tmp_path / "source"
    initialize_repository(source)
    add_contract(source)
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "--depth=1", f"file://{source}", str(shallow)],
        check=True,
        text=True,
        capture_output=True,
    )
    with pytest.raises(SchemaError, match="All-zero.*manually approved"):
        schema_tasks.classify_compatibility_base(
            repository=shallow,
            head="HEAD",
            baseline_sha="0" * 40,
        )
    with pytest.raises(SchemaError, match="All-zero.*manually approved"):
        schema_tasks.classify_compatibility_base(
            repository=source,
            head="refs/heads/missing",
            baseline_sha="0" * 40,
        )


def test_zero_baseline_does_not_inspect_repository_history(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        schema_tasks,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    with pytest.raises(SchemaError, match="All-zero"):
        schema_tasks.classify_compatibility_base(
            repository=tmp_path / "missing",
            head="HEAD",
            baseline_sha="0" * 40,
        )
    assert calls == []


def test_nonzero_trusted_base_supports_first_schema_introduction(tmp_path):
    repository = tmp_path / "repository"
    initialize_repository(repository)
    trusted_base = git(repository, "rev-parse", "HEAD")
    add_contract(repository)
    state = schema_tasks.classify_compatibility_base(
        repository=repository,
        head="HEAD",
        configured_ref=trusted_base,
        baseline_sha=trusted_base,
    )
    assert state.mode == "bootstrap"
    assert state.merge_base == trusted_base
