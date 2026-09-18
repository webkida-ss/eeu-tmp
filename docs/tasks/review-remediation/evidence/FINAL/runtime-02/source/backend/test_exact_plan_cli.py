from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "exact_plan_policy.py"
COMMIT = "a" * 40
PLAN_ROLE = "arn:aws:iam::123456789012:role/untangle-plan"
APPLY_ROLE = "arn:aws:iam::123456789012:role/untangle-apply"
KMS_ARN = "arn:aws:kms:ap-northeast-1:123456789012:key/example"
WORKFLOW_REF = "owner/repository/.github/workflows/deploy-reading-assistant.yml@refs/heads/main"
CLASSIFICATION_COUNT_KEYS = (
    "drift_count",
    "high_risk_drift_count",
    "high_risk_resource_count",
    "output_count",
    "replacement_path_count",
    "resource_count",
    "sensitive_output_count",
    "sensitive_path_count",
)
PACKAGE_DESTINATION = "backend/dist/reading-assistant-lambda.zip"


class GitHubHandler(BaseHTTPRequestHandler):
    requests: list[str] = []

    def do_GET(self) -> None:  # noqa: N802
        type(self).requests.append(self.path)
        payloads = {
            "/repos/owner/repository": {
                "full_name": "owner/repository",
                "fork": False,
                "default_branch": "main",
            },
            "/repos/owner/repository/commits/main": {"sha": COMMIT},
        }
        payload = payloads.get(self.path)
        if payload is None:
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture
def github_api() -> str:
    GitHubHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), GitHubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def run_cli(
    args: list[str], *, api_url: str | None = None, cwd: Path = ROOT
) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "GITHUB_TOKEN": "test-token",
    }
    if api_url:
        environment["GITHUB_API_URL"] = api_url
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def gate_args(output: Path, **overrides: str) -> list[str]:
    values = {
        "trusted-actor-ids": "123,456",
        "actor-id": "123",
        "repository": "owner/repository",
        "git-ref": "refs/heads/main",
        "workflow-ref": WORKFLOW_REF,
        "checked-out-sha": COMMIT,
        "run-id": "100",
        "run-attempt": "2",
        "ref-protected": "true",
        "environment": "prod",
        "operation": "apply",
        "production-confirmation": f"APPLY-PROD-{COMMIT}",
        "plan-role-arn": PLAN_ROLE,
        "apply-role-arn": APPLY_ROLE,
        "bucket": "private-plan-bucket",
        "prefix": "terraform-plans",
        "kms-key-arn": KMS_ARN,
        "github-output": str(output),
    }
    values.update(overrides)
    result = ["gate-deploy"]
    for key, value in values.items():
        result.extend((f"--{key}", value))
    return result


def identity_args(*, apply_role: str = APPLY_ROLE) -> list[str]:
    return [
        "--bucket",
        "private-plan-bucket",
        "--prefix",
        "terraform-plans",
        "--run-id",
        "100",
        "--run-attempt",
        "2",
        "--environment",
        "prod",
        "--commit-sha",
        COMMIT,
        "--workflow-ref",
        WORKFLOW_REF,
        "--kms-key-arn",
        KMS_ARN,
        "--apply-role-arn",
        apply_role,
    ]


def parse_outputs(path: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if line
    )


def classification_args(values: dict[str, str]) -> list[str]:
    result = [
        "--classification-sha256",
        values["classification_sha256"],
        "--presentation-limits-sha256",
        values["presentation_limits_sha256"],
        "--review-summary-sha256",
        values["review_summary_sha256"],
    ]
    for key in CLASSIFICATION_COUNT_KEYS:
        result.extend((f"--{key.replace('_', '-')}", values[key]))
    return result


def bounded_classification_values() -> dict[str, str]:
    presentation_limits_sha256 = hashlib.sha256(
        json.dumps(
            {
                "max_emit_outputs": 100,
                "max_emit_resources": 32,
                "max_path_depth": 16,
                "max_paths_per_change": 24,
                "max_scan_items": 1_000,
                "max_summary_bytes": 65_536,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return {
        "classification_sha256": hashlib.sha256(b"classification").hexdigest(),
        "presentation_limits_sha256": presentation_limits_sha256,
        "review_summary_sha256": hashlib.sha256(b"summary").hexdigest(),
        "drift_count": "0",
        "high_risk_drift_count": "0",
        "high_risk_resource_count": "0",
        "output_count": "0",
        "replacement_path_count": "0",
        "resource_count": "1",
        "sensitive_output_count": "0",
        "sensitive_path_count": "0",
    }


def expected_record_digest(values: dict[str, str]) -> str:
    binding = {
        "apply_role_arn": values["apply_role_arn"],
        "apply_role_digest": values["apply_role_digest"],
        "bucket": "private-plan-bucket",
        "commit_sha": COMMIT,
        "digest": values["plan_digest"],
        "environment": "prod",
        "key": values["plan_key"],
        "kms_key_arn": KMS_ARN,
        "run_attempt": "2",
        "run_id": "100",
        "version_id": values["plan_version_id"],
        "classification_sha256": values["classification_sha256"],
        "presentation_limits_sha256": values["presentation_limits_sha256"],
        "review_summary_sha256": values["review_summary_sha256"],
    }
    package_keys = {
        "package_key",
        "package_version_id",
        "package_digest",
        "package_destination",
    }
    if package_keys.intersection(values):
        assert package_keys.issubset(values)
        binding["package"] = {
            "destination": values["package_destination"],
            "digest": values["package_digest"],
            "key": values["package_key"],
            "version_id": values["package_version_id"],
        }
    binding.update({key: int(values[key]) for key in CLASSIFICATION_COUNT_KEYS})
    return hashlib.sha256(
        json.dumps(binding, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


class FakeVersionedS3:
    """A version-aware, local stand-in for the apply job's S3 API calls."""

    def __init__(self) -> None:
        self.objects: dict[str, dict[str, object]] = {}

    def add_object(
        self,
        *,
        bucket: str,
        key: str,
        version_id: str,
        body: bytes,
        metadata: dict[str, str],
        destination: str,
        get_response: dict[str, object] | None = None,
        head_response: dict[str, object] | None = None,
    ) -> None:
        response = {
            "VersionId": version_id,
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": KMS_ARN,
            "Metadata": metadata,
        }
        self.objects["\0".join((bucket, key, version_id))] = {
            "body": base64.b64encode(body).decode("ascii"),
            "destination": destination,
            "get_response": get_response or response,
            "head_response": head_response or response,
        }

    def install_cli(self, tmp_path: Path) -> Path:
        tmp_path.mkdir(parents=True, exist_ok=True)
        store = tmp_path / "fake-versioned-s3.json"
        store.write_text(json.dumps(self.objects), encoding="utf-8")
        executable = tmp_path / "bin" / "aws"
        executable.parent.mkdir(parents=True)
        executable.write_text(
            """#!/usr/bin/env python3
import base64
import json
import os
import sys
from pathlib import Path


def option(arguments, name):
    try:
        return arguments[arguments.index(name) + 1]
    except (ValueError, IndexError) as error:
        raise SystemExit(f"missing {name}") from error


arguments = sys.argv[1:]
if len(arguments) < 2 or arguments[0] != "s3api" or arguments[1] not in {
    "head-object", "get-object"
}:
    raise SystemExit("unexpected fake AWS operation")
operation = arguments[1]
bucket = option(arguments, "--bucket")
key = option(arguments, "--key")
version_id = option(arguments, "--version-id")
store = json.loads(Path(os.environ["FAKE_VERSIONED_S3"]).read_text(encoding="utf-8"))
item = store.get("\\0".join((bucket, key, version_id)))
if item is None:
    raise SystemExit("requested object version is absent from fake S3")
if operation == "get-object":
    destination = Path(arguments[-1])
    if destination.as_posix() != item["destination"]:
        raise SystemExit("fake S3 rejected a non-workflow download destination")
    destination.write_bytes(base64.b64decode(item["body"]))
    response = item["get_response"]
else:
    response = item["head_response"]
print(json.dumps(response))
""",
            encoding="utf-8",
        )
        executable.chmod(0o755)
        return executable.parent


def package_metadata(values: dict[str, str]) -> dict[str, str]:
    metadata = {
        "apply-role-sha256": values["apply_role_digest"],
        "commit-sha": COMMIT,
        "environment": "prod",
        "plan-sha256": values["plan_digest"],
        "run-attempt": "2",
        "run-id": "100",
        "workflow-ref-sha256": hashlib.sha256(WORKFLOW_REF.encode()).hexdigest(),
        "classification-sha256": values["classification_sha256"],
        "presentation-limits-sha256": values["presentation_limits_sha256"],
        "review-summary-sha256": values["review_summary_sha256"],
    }
    metadata.update({key.replace("_", "-"): values[key] for key in CLASSIFICATION_COUNT_KEYS})
    return metadata


def remove_option_and_value(command: list[str], option: str) -> list[str]:
    position = command.index(option)
    return command[:position] + command[position + 2 :]


def test_fake_versioned_s3_rejects_unknown_operations_and_object_versions(tmp_path: Path) -> None:
    storage = FakeVersionedS3()
    storage.add_object(
        bucket="private-plan-bucket",
        key="terraform-plans/100/2/prod/exact/tfplan",
        version_id="exact-version",
        body=b"exact plan",
        metadata={},
        destination="infra/envs/prod/tfplan",
    )
    aws_bin = storage.install_cli(tmp_path)
    environment = {**os.environ, "FAKE_VERSIONED_S3": str(tmp_path / "fake-versioned-s3.json")}
    unexpected = subprocess.run(
        [str(aws_bin / "aws"), "s3api", "put-object"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert unexpected.returncode != 0
    assert "unexpected fake AWS operation" in unexpected.stderr
    missing_version = subprocess.run(
        [
            str(aws_bin / "aws"),
            "s3api",
            "head-object",
            "--bucket",
            "private-plan-bucket",
            "--key",
            "terraform-plans/100/2/prod/exact/tfplan",
            "--version-id",
            "other-version",
        ],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert missing_version.returncode != 0
    assert "requested object version is absent" in missing_version.stderr


def test_workflow_exact_plan_cli_chain_succeeds_end_to_end(tmp_path: Path, github_api: str) -> None:
    gate_output = tmp_path / "gate-output"
    gate = run_cli(gate_args(gate_output), api_url=github_api)
    assert gate.returncode == 0, gate.stderr
    gate_values = parse_outputs(gate_output)
    assert gate_values["commit_sha"] == COMMIT
    assert gate_values["plan_role_arn"] == PLAN_ROLE
    assert gate_values["apply_role_arn"] == APPLY_ROLE
    assert gate_values["apply_role_digest"] == hashlib.sha256(APPLY_ROLE.encode()).hexdigest()

    versioning = tmp_path / "versioning.json"
    encryption = tmp_path / "encryption.json"
    versioning.write_text('{"Status":"Enabled"}', encoding="utf-8")
    encryption.write_text(
        json.dumps(
            {
                "ServerSideEncryptionConfiguration": {
                    "Rules": [
                        {
                            "ApplyServerSideEncryptionByDefault": {
                                "SSEAlgorithm": "aws:kms",
                                "KMSMasterKeyID": KMS_ARN,
                            }
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    storage = run_cli(
        [
            "verify-storage",
            "--versioning-response",
            str(versioning),
            "--encryption-response",
            str(encryption),
            "--kms-key-arn",
            KMS_ARN,
        ]
    )
    assert storage.returncode == 0, storage.stderr

    plan = tmp_path / "tfplan"
    plan.write_bytes(b"opaque exact plan")
    package = tmp_path / PACKAGE_DESTINATION
    package.parent.mkdir(parents=True)
    package.write_bytes(b"approved Lambda package")
    plan_json = tmp_path / "tfplan.json"
    plan_json.write_text(
        json.dumps({"resource_changes": [minimal_change(0)]}),
        encoding="utf-8",
    )
    summary = tmp_path / "summary.json"
    classification = tmp_path / "classification.json"
    summarized = run_cli(
        [
            "summarize-plan",
            "--input",
            str(plan_json),
            "--output",
            str(summary),
            "--classification-output",
            str(classification),
        ]
    )
    assert summarized.returncode == 0, summarized.stderr
    descriptor = tmp_path / "descriptor.json"
    descriptor_output = tmp_path / "descriptor-output"
    describe = run_cli(
        [
            "describe",
            *identity_args(),
            "--plan-file",
            str(plan),
            "--package-file",
            str(package),
            "--classification",
            str(classification),
            "--output",
            str(descriptor),
            "--github-output",
            str(descriptor_output),
        ]
    )
    assert describe.returncode == 0, describe.stderr
    descriptor_data = json.loads(descriptor.read_text(encoding="utf-8"))

    upload = tmp_path / "put-object.json"
    upload.write_text('{"VersionId":"version-1"}', encoding="utf-8")
    package_upload = tmp_path / "put-package.json"
    package_upload.write_text('{"VersionId":"package-version-1"}', encoding="utf-8")
    record = tmp_path / "record.json"
    record_output = tmp_path / "record-output"
    recorded = run_cli(
        [
            "record-version",
            "--descriptor",
            str(descriptor),
            "--upload-response",
            str(upload),
            "--package-upload-response",
            str(package_upload),
            "--output",
            str(record),
            "--github-output",
            str(record_output),
        ]
    )
    assert recorded.returncode == 0, recorded.stderr
    values = parse_outputs(record_output)

    asserted = run_cli(
        [
            "assert-record",
            *identity_args(apply_role=values["apply_role_arn"]),
            "--key",
            values["plan_key"],
            "--version-id",
            values["plan_version_id"],
            "--digest",
            values["plan_digest"],
            "--apply-role-digest",
            values["apply_role_digest"],
            "--record-digest",
            values["plan_record_digest"],
            "--require-package",
            "--package-key",
            values["package_key"],
            "--package-version-id",
            values["package_version_id"],
            "--package-digest",
            values["package_digest"],
            "--package-destination",
            values["package_destination"],
            *classification_args(values),
        ]
    )
    assert asserted.returncode == 0, asserted.stderr

    head = tmp_path / "head.json"
    get = tmp_path / "get.json"
    head.write_text(
        json.dumps(
            {
                "VersionId": "version-1",
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": KMS_ARN,
                "Metadata": descriptor_data["metadata"],
            }
        ),
        encoding="utf-8",
    )
    get.write_text(
        json.dumps(
            {
                "VersionId": "version-1",
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": KMS_ARN,
                "Metadata": descriptor_data["metadata"],
            }
        ),
        encoding="utf-8",
    )
    package_head = tmp_path / "package-head.json"
    package_get = tmp_path / "package-get.json"
    package_head.write_text(
        json.dumps(
            {
                "VersionId": values["package_version_id"],
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": KMS_ARN,
                "Metadata": {
                    **descriptor_data["metadata"],
                    "package-sha256": values["package_digest"],
                },
            }
        ),
        encoding="utf-8",
    )
    package_get.write_text(
        json.dumps(
            {
                "VersionId": values["package_version_id"],
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": KMS_ARN,
                "Metadata": {
                    **descriptor_data["metadata"],
                    "package-sha256": values["package_digest"],
                },
            }
        ),
        encoding="utf-8",
    )
    verified = run_cli(
        [
            "verify-download",
            *identity_args(apply_role=values["apply_role_arn"]),
            "--key",
            values["plan_key"],
            "--version-id",
            values["plan_version_id"],
            "--digest",
            values["plan_digest"],
            "--apply-role-digest",
            values["apply_role_digest"],
            "--record-digest",
            values["plan_record_digest"],
            "--require-package",
            "--package-key",
            values["package_key"],
            "--package-version-id",
            values["package_version_id"],
            "--package-digest",
            values["package_digest"],
            "--package-destination",
            values["package_destination"],
            *classification_args(values),
            "--head-response",
            str(head),
            "--get-response",
            str(get),
            "--plan-file",
            str(plan),
            "--package-head-response",
            str(package_head),
            "--package-get-response",
            str(package_get),
            "--package-file",
            PACKAGE_DESTINATION,
        ],
        cwd=tmp_path,
    )
    assert verified.returncode == 0, verified.stderr
    classification_verified = run_cli(
        [
            "verify-classification",
            "--input",
            str(plan_json),
            *classification_args(values),
        ]
    )
    assert classification_verified.returncode == 0, classification_verified.stderr


@pytest.mark.parametrize(
    "override",
    [
        {"actor-id": "999"},
        {"trusted-actor-ids": "123, 456"},
        {"git-ref": "refs/heads/feature"},
        {"ref-protected": "false"},
        {"checked-out-sha": "b" * 40},
        {"apply-role-arn": PLAN_ROLE},
        {"production-confirmation": "APPLY-PROD-wrong"},
        {"bucket": ""},
        {"kms-key-arn": ""},
    ],
)
def test_gate_deploy_cli_fails_closed(
    tmp_path: Path, github_api: str, override: dict[str, str]
) -> None:
    result = run_cli(gate_args(tmp_path / "output", **override), api_url=github_api)
    assert result.returncode != 0
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("plan_key", "attacker/tfplan"),
        ("plan_version_id", "bad/version"),
        ("plan_digest", "0" * 64),
        ("apply_role_arn", "arn:aws:iam::123456789012:role/conflicting"),
        ("apply_role_digest", "0" * 64),
        ("classification_sha256", "0" * 64),
        ("resource_count", "2"),
    ],
)
def test_apply_cli_rejects_conflicting_record_values(
    tmp_path: Path, field: str, bad_value: str
) -> None:
    plan = tmp_path / "tfplan"
    plan.write_bytes(b"opaque exact plan")
    digest = hashlib.sha256(plan.read_bytes()).hexdigest()
    values = {
        "plan_key": f"terraform-plans/100/2/prod/{COMMIT}/tfplan",
        "plan_version_id": "version-1",
        "plan_digest": digest,
        "apply_role_arn": APPLY_ROLE,
        "apply_role_digest": hashlib.sha256(APPLY_ROLE.encode()).hexdigest(),
        **bounded_classification_values(),
    }
    values["plan_record_digest"] = expected_record_digest(values)
    values[field] = bad_value
    result = run_cli(
        [
            "assert-record",
            *identity_args(apply_role=values["apply_role_arn"]),
            "--key",
            values["plan_key"],
            "--version-id",
            values["plan_version_id"],
            "--digest",
            values["plan_digest"],
            "--apply-role-digest",
            values["apply_role_digest"],
            "--record-digest",
            values["plan_record_digest"],
            *classification_args(values),
        ]
    )
    assert result.returncode != 0


@pytest.mark.parametrize(
    "tamper",
    [
        "head-version",
        "encryption",
        "kms-key",
        "metadata",
        "download-version",
        "get-encryption",
        "get-kms-key",
        "get-metadata",
        "plan-body",
    ],
)
def test_verify_download_cli_rejects_s3_kms_and_toctou_failures(
    tmp_path: Path, tamper: str
) -> None:
    plan = tmp_path / "tfplan"
    plan.write_bytes(b"opaque exact plan")
    values = {
        "plan_key": f"terraform-plans/100/2/prod/{COMMIT}/tfplan",
        "plan_version_id": "version-1",
        "plan_digest": hashlib.sha256(plan.read_bytes()).hexdigest(),
        "apply_role_arn": APPLY_ROLE,
        "apply_role_digest": hashlib.sha256(APPLY_ROLE.encode()).hexdigest(),
        **bounded_classification_values(),
    }
    values["plan_record_digest"] = expected_record_digest(values)
    metadata = {
        "apply-role-sha256": values["apply_role_digest"],
        "commit-sha": COMMIT,
        "environment": "prod",
        "plan-sha256": values["plan_digest"],
        "run-attempt": "2",
        "run-id": "100",
        "workflow-ref-sha256": hashlib.sha256(WORKFLOW_REF.encode()).hexdigest(),
        "classification-sha256": values["classification_sha256"],
        "presentation-limits-sha256": values["presentation_limits_sha256"],
        "review-summary-sha256": values["review_summary_sha256"],
    }
    metadata.update({key.replace("_", "-"): values[key] for key in CLASSIFICATION_COUNT_KEYS})
    head_data = {
        "VersionId": values["plan_version_id"],
        "ServerSideEncryption": "aws:kms",
        "SSEKMSKeyId": KMS_ARN,
        "Metadata": metadata,
    }
    get_data = {
        "VersionId": values["plan_version_id"],
        "ServerSideEncryption": "aws:kms",
        "SSEKMSKeyId": KMS_ARN,
        "Metadata": metadata,
    }
    if tamper == "head-version":
        head_data["VersionId"] = "version-2"
    elif tamper == "encryption":
        head_data["ServerSideEncryption"] = "AES256"
    elif tamper == "kms-key":
        head_data["SSEKMSKeyId"] = "arn:aws:kms:ap-northeast-1:123456789012:key/other"
    elif tamper == "metadata":
        metadata["commit-sha"] = "b" * 40
    elif tamper == "download-version":
        get_data["VersionId"] = "version-2"
    elif tamper == "get-encryption":
        get_data["ServerSideEncryption"] = "AES256"
    elif tamper == "get-kms-key":
        get_data["SSEKMSKeyId"] = "arn:aws:kms:ap-northeast-1:123456789012:key/other"
    elif tamper == "get-metadata":
        get_data["Metadata"] = {"commit-sha": "b" * 40}
    elif tamper == "plan-body":
        plan.write_bytes(b"replaced after download")

    head = tmp_path / "head.json"
    get = tmp_path / "get.json"
    head.write_text(json.dumps(head_data), encoding="utf-8")
    get.write_text(json.dumps(get_data), encoding="utf-8")
    result = run_cli(
        [
            "verify-download",
            *identity_args(),
            "--key",
            values["plan_key"],
            "--version-id",
            values["plan_version_id"],
            "--digest",
            values["plan_digest"],
            "--apply-role-digest",
            values["apply_role_digest"],
            "--record-digest",
            values["plan_record_digest"],
            *classification_args(values),
            "--head-response",
            str(head),
            "--get-response",
            str(get),
            "--plan-file",
            str(plan),
        ]
    )
    assert result.returncode != 0
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("tamper", ["versioning", "kms-key"])
def test_storage_cli_fails_closed_for_fake_s3_and_kms(tmp_path: Path, tamper: str) -> None:
    versioning = {"Status": "Enabled"}
    kms = KMS_ARN
    if tamper == "versioning":
        versioning["Status"] = "Suspended"
    else:
        kms = "arn:aws:kms:ap-northeast-1:123456789012:key/other"
    encryption = {
        "ServerSideEncryptionConfiguration": {
            "Rules": [
                {
                    "ApplyServerSideEncryptionByDefault": {
                        "SSEAlgorithm": "aws:kms",
                        "KMSMasterKeyID": kms,
                    }
                }
            ]
        }
    }
    versioning_path = tmp_path / "versioning.json"
    encryption_path = tmp_path / "encryption.json"
    versioning_path.write_text(json.dumps(versioning), encoding="utf-8")
    encryption_path.write_text(json.dumps(encryption), encoding="utf-8")
    result = run_cli(
        [
            "verify-storage",
            "--versioning-response",
            str(versioning_path),
            "--encryption-response",
            str(encryption_path),
            "--kms-key-arn",
            KMS_ARN,
        ]
    )
    assert result.returncode != 0
    assert "Traceback" not in result.stderr


def test_apply_workflow_uses_only_plan_role_output() -> None:
    workflow = (ROOT / ".github/workflows/deploy-reading-assistant.yml").read_text(encoding="utf-8")
    plan, apply = workflow.split("\n  apply:", 1)
    assert "vars.AWS_PLAN_ROLE_ARN_DEV" in plan
    assert "vars.AWS_PLAN_ROLE_ARN_PROD" in plan
    assert "vars.AWS_APPLY_ROLE_ARN_DEV" in plan
    assert "vars.AWS_APPLY_ROLE_ARN_PROD" in plan
    assert "vars.AWS_PLAN_ROLE_ARN }}" not in workflow
    assert "vars.AWS_APPLY_ROLE_ARN }}" not in workflow
    assert (
        "role-to-assume: ${{ steps.gate-dev.outputs.plan_role_arn || "
        "steps.gate-prod.outputs.plan_role_arn }}"
    ) in plan
    assert "role-to-assume: ${{ needs.plan.outputs.apply_role_arn }}" in apply
    assert "vars.AWS_APPLY_ROLE_ARN" not in apply


def apply_binding_values(
    tmp_path: Path, terraform_plan: dict[str, object]
) -> tuple[dict[str, str], bytes, bytes, Path]:
    plan_bytes = b"opaque exact plan"
    package_bytes = b"approved Lambda package"
    plan_json = tmp_path / "terraform-plan.json"
    classification = tmp_path / "classification.json"
    plan_json.write_text(json.dumps(terraform_plan), encoding="utf-8")
    summarized = run_cli(
        [
            "summarize-plan",
            "--input",
            str(plan_json),
            "--output",
            str(tmp_path / "summary.json"),
            "--classification-output",
            str(classification),
        ]
    )
    assert summarized.returncode == 0, summarized.stderr
    classification_data = json.loads(classification.read_text(encoding="utf-8"))
    values = {
        "plan_key": f"terraform-plans/100/2/prod/{COMMIT}/tfplan",
        "plan_version_id": "plan-version-1",
        "plan_digest": hashlib.sha256(plan_bytes).hexdigest(),
        "apply_role_arn": APPLY_ROLE,
        "apply_role_digest": hashlib.sha256(APPLY_ROLE.encode()).hexdigest(),
        "package_key": f"terraform-plans/100/2/prod/{COMMIT}/reading-assistant-lambda.zip",
        "package_version_id": "package-version-1",
        "package_digest": hashlib.sha256(package_bytes).hexdigest(),
        "package_destination": PACKAGE_DESTINATION,
        **{
            key: str(classification_data[key])
            for key in (
                "classification_sha256",
                "presentation_limits_sha256",
                "review_summary_sha256",
                *CLASSIFICATION_COUNT_KEYS,
            )
        },
    }
    values["plan_record_digest"] = expected_record_digest(values)
    return values, plan_bytes, package_bytes, plan_json


def install_fake_terraform(tmp_path: Path) -> Path:
    executable = tmp_path / "bin" / "terraform"
    executable.parent.mkdir(parents=True)
    executable.write_text(
        """#!/usr/bin/env python3
import os
import sys
from pathlib import Path

arguments = sys.argv[1:]
if arguments == [
    "init",
    "-input=false",
    "-backend-config=bucket=private-state-bucket",
]:
    raise SystemExit(0)
if arguments == ["show", "-json", "tfplan"]:
    sys.stdout.write(Path(os.environ["FAKE_TERRAFORM_PLAN"]).read_text(encoding="utf-8"))
    raise SystemExit(0)
if arguments == ["apply", "-input=false", "-auto-approve", "tfplan"]:
    Path(os.environ["APPLY_SENTINEL"]).touch()
    raise SystemExit(0)
raise SystemExit("unexpected fake Terraform operation")
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable.parent


APPLY_RUN_STEP_NAMES = (
    "Reject arbitrary plan identity before AWS access",
    "Download exact object version and metadata",
    "Verify exact version metadata environment commit and digest",
    "Terraform init",
    "Verify complete plan classification before apply",
    "Apply exact previously reviewed plan",
)


def load_apply_run_steps() -> list[dict[str, object]]:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/deploy-reading-assistant.yml").read_text(encoding="utf-8")
    )
    assert isinstance(workflow, dict)
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    apply_job = jobs.get("apply")
    assert isinstance(apply_job, dict)
    steps = apply_job.get("steps")
    assert isinstance(steps, list)
    selected = [
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") in APPLY_RUN_STEP_NAMES
    ]
    assert tuple(step.get("name") for step in selected) == APPLY_RUN_STEP_NAMES
    assert all(isinstance(step.get("run"), str) for step in selected)
    return selected


def assert_apply_run_steps_are_complete(steps: list[dict[str, object]]) -> None:
    names = tuple(step.get("name") for step in steps)
    assert names == APPLY_RUN_STEP_NAMES, "apply verification steps changed order or are absent"
    assert all(isinstance(step.get("run"), str) for step in steps)
    download = steps[1]["run"]
    assert isinstance(download, str)
    assert download.count("--version-id") == 4, "download must request every exact object version"


def test_apply_workflow_drift_cannot_remove_versions_or_verification_steps() -> None:
    steps = load_apply_run_steps()
    changed_download = [dict(step) for step in steps]
    download = changed_download[1]["run"]
    assert isinstance(download, str)
    changed_download[1]["run"] = download.replace(
        '--version-id "${{ needs.plan.outputs.plan_version_id }}"', ""
    )
    with pytest.raises(AssertionError, match="exact object version"):
        assert_apply_run_steps_are_complete(changed_download)

    removed_verification = [step for step in steps if step["name"] != APPLY_RUN_STEP_NAMES[2]]
    with pytest.raises(AssertionError, match="changed order or are absent"):
        assert_apply_run_steps_are_complete(removed_verification)

    moved_verification = list(steps)
    moved_verification[2], moved_verification[3] = moved_verification[3], moved_verification[2]
    with pytest.raises(AssertionError, match="changed order or are absent"):
        assert_apply_run_steps_are_complete(moved_verification)


def substitute_apply_expressions(value: str, expressions: dict[str, str]) -> str:
    rendered = value
    for expression, replacement in expressions.items():
        rendered = rendered.replace(expression, replacement)
    assert "${{" not in rendered, f"unmapped workflow expression: {rendered}"
    return rendered


def run_apply_restoration(
    *,
    tmp_path: Path,
    values: dict[str, str],
    storage: FakeVersionedS3,
    terraform_plan: Path,
    steps: list[dict[str, object]] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    apply_workspace = tmp_path / "empty-apply-workspace"
    runner_temp = tmp_path / "runner-temp"
    sentinel = tmp_path / "apply-sentinel"
    apply_workspace.mkdir()
    runner_temp.mkdir()
    assert not any(apply_workspace.iterdir())
    aws_bin = storage.install_cli(tmp_path / "fake-aws")
    terraform_bin = install_fake_terraform(tmp_path / "fake-terraform")
    (apply_workspace / "scripts").symlink_to(ROOT / "scripts", target_is_directory=True)
    (apply_workspace / "infra" / "envs" / "prod").mkdir(parents=True)
    selected_steps = steps or load_apply_run_steps()
    assert_apply_run_steps_are_complete(selected_steps)
    expressions = {
        "${{ needs.plan.outputs.plan_bucket }}": "private-plan-bucket",
        "${{ needs.plan.outputs.plan_key }}": values["plan_key"],
        "${{ needs.plan.outputs.plan_version_id }}": values["plan_version_id"],
        "${{ needs.plan.outputs.package_key }}": values["package_key"],
        "${{ needs.plan.outputs.package_version_id }}": values["package_version_id"],
        "${{ needs.plan.outputs.commit_sha }}": COMMIT,
        "${{ needs.plan.outputs.plan_kms_key_arn }}": KMS_ARN,
        "${{ needs.plan.outputs.apply_role_arn }}": values["apply_role_arn"],
        "${{ needs.plan.outputs.plan_digest }}": values["plan_digest"],
        "${{ needs.plan.outputs.apply_role_digest }}": values["apply_role_digest"],
        "${{ needs.plan.outputs.plan_record_digest }}": values["plan_record_digest"],
        "${{ needs.plan.outputs.package_digest }}": values["package_digest"],
        "${{ needs.plan.outputs.package_destination }}": values["package_destination"],
        "${{ needs.plan.outputs.classification_sha256 }}": values["classification_sha256"],
        "${{ needs.plan.outputs.presentation_limits_sha256 }}": values[
            "presentation_limits_sha256"
        ],
        "${{ needs.plan.outputs.review_summary_sha256 }}": values["review_summary_sha256"],
        **{
            f"${{{{ needs.plan.outputs.{key} }}}}": values[key] for key in CLASSIFICATION_COUNT_KEYS
        },
        "${{ github.run_id }}": "100",
        "${{ github.run_attempt }}": "2",
        "${{ inputs.environment }}": "prod",
        "${{ github.workflow_ref }}": WORKFLOW_REF,
        "${{ vars.TERRAFORM_STATE_BUCKET }}": "private-state-bucket",
    }
    environment = {
        **os.environ,
        "APPLY_SENTINEL": str(sentinel),
        "FAKE_TERRAFORM_PLAN": str(terraform_plan),
        "FAKE_VERSIONED_S3": str(tmp_path / "fake-aws" / "fake-versioned-s3.json"),
        "PATH": f"{aws_bin}{os.pathsep}{terraform_bin}{os.pathsep}{os.environ['PATH']}",
        "PLAN_PREFIX": "terraform-plans",
        "PYTHONPATH": str(ROOT),
        "RUNNER_TEMP": str(runner_temp),
        "TERRAFORM_STATE_BUCKET": "private-state-bucket",
    }
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    for step in selected_steps:
        run = step["run"]
        assert isinstance(run, str)
        working_directory = step.get("working-directory", ".")
        assert isinstance(working_directory, str)
        rendered_directory = substitute_apply_expressions(working_directory, expressions)
        assert rendered_directory in {".", "infra/envs/prod"}
        step_environment = dict(environment)
        raw_step_environment = step.get("env", {})
        assert isinstance(raw_step_environment, dict)
        for name, raw_value in raw_step_environment.items():
            assert isinstance(name, str) and isinstance(raw_value, str)
            step_environment[name] = substitute_apply_expressions(raw_value, expressions)
        completed = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", substitute_apply_expressions(run, expressions)],
            cwd=apply_workspace / rendered_directory,
            env=step_environment,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            break
    return completed, apply_workspace, sentinel


@pytest.mark.parametrize(
    "tamper",
    [
        "none",
        "missing-package",
        "corrupt-package",
        "package-head-metadata",
        "package-get-version",
        "package-get-encryption",
        "package-get-kms-key",
        "package-get-metadata",
        "first-lambda-hash",
        "second-lambda-hash",
    ],
)
def test_apply_job_restores_only_the_verified_plan_bound_package(
    tmp_path: Path, tamper: str
) -> None:
    package_bytes = b"approved Lambda package"
    package_digest = hashlib.sha256(package_bytes).hexdigest()
    source_hash = base64.b64encode(bytes.fromhex(package_digest)).decode("ascii")
    lambda_hashes = [source_hash, source_hash]
    if tamper == "first-lambda-hash":
        lambda_hashes[0] = base64.b64encode(bytes.fromhex("0" * 64)).decode("ascii")
    elif tamper == "second-lambda-hash":
        lambda_hashes[1] = base64.b64encode(bytes.fromhex("0" * 64)).decode("ascii")
    terraform_plan = {
        "resource_changes": [
            {
                "address": f"aws_lambda_function.test[{index}]",
                "type": "aws_lambda_function",
                "change": {
                    "actions": ["update"],
                    "after": {"source_code_hash": value},
                },
            }
            for index, value in enumerate(lambda_hashes)
        ]
    }
    values, plan_bytes, package_bytes, terraform_plan_path = apply_binding_values(
        tmp_path, terraform_plan
    )
    storage = FakeVersionedS3()
    plan_metadata = package_metadata(values)
    package_object_metadata = {
        **plan_metadata,
        "package-sha256": values["package_digest"],
    }
    storage.add_object(
        bucket="private-plan-bucket",
        key=values["plan_key"],
        version_id=values["plan_version_id"],
        body=plan_bytes,
        metadata=plan_metadata,
        destination="infra/envs/prod/tfplan",
    )
    if tamper != "missing-package":
        package_head = {
            "VersionId": values["package_version_id"],
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": KMS_ARN,
            "Metadata": package_object_metadata,
        }
        package_get = dict(package_head)
        if tamper == "package-head-metadata":
            package_head["Metadata"] = {"commit-sha": COMMIT}
        elif tamper == "package-get-version":
            package_get["VersionId"] = "other-package-version"
        elif tamper == "package-get-encryption":
            package_get["ServerSideEncryption"] = "AES256"
        elif tamper == "package-get-kms-key":
            package_get["SSEKMSKeyId"] = "arn:aws:kms:ap-northeast-1:123456789012:key/other"
        elif tamper == "package-get-metadata":
            package_get["Metadata"] = {"commit-sha": COMMIT}
        storage.add_object(
            bucket="private-plan-bucket",
            key=values["package_key"],
            version_id=values["package_version_id"],
            body=(b"corrupted Lambda package" if tamper == "corrupt-package" else package_bytes),
            metadata=package_object_metadata,
            destination=PACKAGE_DESTINATION,
            head_response=package_head,
            get_response=package_get,
        )

    completed, apply_workspace, sentinel = run_apply_restoration(
        tmp_path=tmp_path,
        values=values,
        storage=storage,
        terraform_plan=terraform_plan_path,
    )
    package_path = apply_workspace / PACKAGE_DESTINATION
    if tamper == "none":
        assert completed.returncode == 0, completed.stderr
        assert package_path.read_bytes() == package_bytes
        assert sentinel.exists()
    else:
        assert completed.returncode != 0
        expected_rejection = {
            "missing-package": "requested object version is absent from fake S3",
            "corrupt-package": "Downloaded package digest does not match",
            "package-head-metadata": "Package object metadata or encryption is invalid",
            "package-get-version": "Downloaded package version does not match",
            "package-get-encryption": "Downloaded package metadata or encryption is invalid",
            "package-get-kms-key": "Downloaded package metadata or encryption is invalid",
            "package-get-metadata": "Downloaded package metadata or encryption is invalid",
            "first-lambda-hash": "Approved plan Lambda source hashes do not match the package",
            "second-lambda-hash": "Approved plan Lambda source hashes do not match the package",
        }
        assert expected_rejection[tamper] in completed.stderr
        assert not sentinel.exists()


def test_apply_restores_and_verifies_the_plan_bound_lambda_package() -> None:
    workflow = (ROOT / ".github/workflows/deploy-reading-assistant.yml").read_text(encoding="utf-8")
    assert "Store exact encrypted versioned Lambda package" in workflow
    assert "steps.record.outputs.package_version_id" in workflow
    assert "Download exact object version and metadata" in workflow
    assert "--require-package" in workflow
    assert "--package-head-response" in workflow
    assert "mkdir -p backend/dist" in workflow
    assert "test -s backend/dist/reading-assistant-lambda.zip" not in workflow
    assert "verify-lambda-package" in workflow
    apply = workflow.split("\n  apply:", 1)[1]
    assert apply.index("--package-head-response") < apply.index("Terraform init")
    assert apply.count("--require-package") == 2
    assert workflow.index("verify-lambda-package") < workflow.index(
        "Apply exact previously reviewed plan"
    )


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("package_key", "terraform-plans/100/2/prod/" + COMMIT + "/swapped.zip"),
        ("package_version_id", "package-version-2"),
        ("package_digest", "0" * 64),
        ("package_destination", "arbitrary/package.zip"),
        ("package_destination", ""),
    ],
)
def test_strict_package_record_rejects_missing_or_swapped_binding(
    tmp_path: Path, field: str, bad_value: str
) -> None:
    plan = tmp_path / "tfplan"
    plan.write_bytes(b"opaque exact plan")
    package = tmp_path / "reading-assistant-lambda.zip"
    package.write_bytes(b"approved Lambda package")
    values = {
        "plan_key": f"terraform-plans/100/2/prod/{COMMIT}/tfplan",
        "plan_version_id": "version-1",
        "plan_digest": hashlib.sha256(plan.read_bytes()).hexdigest(),
        "apply_role_arn": APPLY_ROLE,
        "apply_role_digest": hashlib.sha256(APPLY_ROLE.encode()).hexdigest(),
        "package_key": f"terraform-plans/100/2/prod/{COMMIT}/reading-assistant-lambda.zip",
        "package_version_id": "package-version-1",
        "package_digest": hashlib.sha256(package.read_bytes()).hexdigest(),
        "package_destination": PACKAGE_DESTINATION,
        **bounded_classification_values(),
    }
    values["plan_record_digest"] = expected_record_digest(values)
    values[field] = bad_value
    command = [
        "assert-record",
        *identity_args(),
        "--key",
        values["plan_key"],
        "--version-id",
        values["plan_version_id"],
        "--digest",
        values["plan_digest"],
        "--apply-role-digest",
        values["apply_role_digest"],
        "--record-digest",
        values["plan_record_digest"],
        "--require-package",
        "--package-key",
        values["package_key"],
        "--package-version-id",
        values["package_version_id"],
        "--package-digest",
        values["package_digest"],
        "--package-destination",
        values["package_destination"],
        *classification_args(values),
    ]
    rejected = run_cli(command)
    assert rejected.returncode != 0

    missing_complete = command[: command.index("--package-key")]
    missing_complete.extend(classification_args(values))
    complete_rejection = run_cli(missing_complete)
    assert complete_rejection.returncode != 0
    assert "Package record binding is required" in complete_rejection.stderr

    missing_partial = remove_option_and_value(command, "--package-key")
    partial_rejection = run_cli(missing_partial)
    assert partial_rejection.returncode != 0
    assert "Package record binding is incomplete" in partial_rejection.stderr


def test_record_version_rejects_a_package_descriptor_without_upload_evidence(
    tmp_path: Path,
) -> None:
    terraform_plan = {"resource_changes": [minimal_change(0)]}
    values, plan_bytes, package_bytes, _ = apply_binding_values(tmp_path, terraform_plan)
    plan = tmp_path / "tfplan"
    package = tmp_path / "reading-assistant-lambda.zip"
    descriptor = tmp_path / "descriptor.json"
    plan.write_bytes(plan_bytes)
    package.write_bytes(package_bytes)
    classification = tmp_path / "classification.json"
    summarized = run_cli(
        [
            "summarize-plan",
            "--input",
            str(tmp_path / "terraform-plan.json"),
            "--output",
            str(tmp_path / "summary-for-descriptor.json"),
            "--classification-output",
            str(classification),
        ]
    )
    assert summarized.returncode == 0, summarized.stderr
    described = run_cli(
        [
            "describe",
            *identity_args(),
            "--plan-file",
            str(plan),
            "--package-file",
            str(package),
            "--classification",
            str(classification),
            "--output",
            str(descriptor),
        ]
    )
    assert described.returncode == 0, described.stderr
    upload = tmp_path / "plan-upload.json"
    upload.write_text(json.dumps({"VersionId": values["plan_version_id"]}), encoding="utf-8")
    rejected = run_cli(
        [
            "record-version",
            "--descriptor",
            str(descriptor),
            "--upload-response",
            str(upload),
            "--output",
            str(tmp_path / "record.json"),
            "--github-output",
            str(tmp_path / "record-output"),
        ]
    )
    assert rejected.returncode != 0
    assert "Package descriptor requires an upload response" in rejected.stderr


def test_lambda_package_verification_requires_two_matching_plan_hashes(tmp_path: Path) -> None:
    package = tmp_path / "reading-assistant-lambda.zip"
    package.write_bytes(b"approved package")
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    source_hash = base64.b64encode(bytes.fromhex(digest)).decode("ascii")
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "resource_changes": [
                    {
                        "type": "aws_lambda_function",
                        "change": {"after": {"source_code_hash": source_hash}},
                    },
                    {
                        "type": "aws_lambda_function",
                        "change": {"after": {"source_code_hash": source_hash}},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    command = [
        "verify-lambda-package",
        "--plan",
        str(plan),
        "--package-file",
        str(package),
        "--package-digest",
        digest,
    ]
    result = run_cli(command)
    assert result.returncode == 0, result.stderr
    plan.write_text(json.dumps({"resource_changes": []}), encoding="utf-8")
    rejected = run_cli(command)
    assert rejected.returncode != 0


def test_plan_summary_cli_is_private_bounded_and_operationally_useful(
    tmp_path: Path,
) -> None:
    plan_json = tmp_path / "plan.json"
    summary = tmp_path / "summary.json"
    sensitive_values = [
        "person@example.com",
        "123456789.apps.googleusercontent.com",
        "price_123456789",
        "sk-proj-supersecretvalue",
        "https://private.example/path",
        '{"PRIVATE_ENV":"arbitrary-value"}',
        "arn:aws:iam::123456789012:role/escalated-admin",
        "0.0.0.0/0",
    ]
    plan = {
        "resource_changes": [
            {
                "address": "module.api.aws_iam_role_policy.lambda",
                "type": "aws_iam_role_policy",
                "action_reason": "replace_because_cannot_update",
                "change": {
                    "actions": ["delete", "create"],
                    "before": {"policy": {"Statement": [{"Action": ["s3:GetObject"]}]}},
                    "after": {
                        "policy": {
                            "Statement": [
                                {
                                    "Action": ["*"],
                                    "Credential": "sk-proj-supersecretvalue",
                                }
                            ]
                        },
                    },
                    "before_sensitive": {"policy": False},
                    "after_sensitive": {"policy": True},
                    "replace_paths": [["policy"]],
                },
            },
            {
                "address": "module.api.aws_security_group_rule.ingress",
                "type": "aws_security_group_rule",
                "change": {
                    "actions": ["update"],
                    "before": {"cidr_blocks": ["10.0.0.0/8"], "type": "ingress"},
                    "after": {"cidr_blocks": ["0.0.0.0/0"], "type": "ingress"},
                },
            },
            {
                "address": ('module.api.aws_lambda_function.backend["person@example.com"]'),
                "type": "aws_lambda_function",
                "change": {
                    "actions": ["update"],
                    "before": {
                        "role": "arn:aws:iam::123456789012:role/old",
                        "environment": {"variables": {"API_KEY": "old"}},
                        "reserved_concurrent_executions": 5,
                    },
                    "after": {
                        "role": sensitive_values[-2],
                        "environment": {
                            "variables": {
                                "API_KEY": "sk-proj-supersecretvalue",
                                "OAUTH_CLIENT": sensitive_values[1],
                                "sk-proj-supersecretvalue": "embedded",
                            }
                        },
                        "reserved_concurrent_executions": 100,
                    },
                    "after_sensitive": {
                        "environment": {
                            "variables": {
                                "API_KEY": True,
                                "OAUTH_CLIENT": True,
                            }
                        }
                    },
                },
            },
            {
                "address": "module.api.aws_apigatewayv2_api.this",
                "type": "aws_apigatewayv2_api",
                "change": {
                    "actions": ["update"],
                    "before": {
                        "cors_configuration": {"allow_origins": ["https://old.private.example"]}
                    },
                    "after": {
                        "cors_configuration": {"allow_origins": ["https://new.private.example"]}
                    },
                },
            },
            {
                "address": "module.data.aws_kms_key.content",
                "type": "aws_kms_key",
                "change": {
                    "actions": ["update"],
                    "before": {"enable_key_rotation": True},
                    "after": {"enable_key_rotation": False},
                },
            },
        ],
        "resource_drift": [
            {
                "address": "module.data.aws_s3_bucket_public_access_block.preload",
                "type": "aws_s3_bucket_public_access_block",
                "change": {
                    "actions": ["update"],
                    "before": {"block_public_acls": True},
                    "after": {"block_public_acls": False},
                },
            }
        ],
        "output_changes": {
            "api_url": {
                "actions": ["update"],
                "before": "https://old.private.example",
                "after": "https://new.private.example",
                "after_sensitive": False,
            },
            "oauth_client": {
                "actions": ["update"],
                "before": sensitive_values[1],
                "after": "other.apps.googleusercontent.com",
                "after_sensitive": True,
            },
        },
    }
    plan_json.write_text(json.dumps(plan), encoding="utf-8")
    result = run_cli(
        [
            "summarize-plan",
            "--input",
            str(plan_json),
            "--output",
            str(summary),
        ]
    )
    assert result.returncode == 0, result.stderr
    combined = result.stdout + summary.read_text(encoding="utf-8")
    for value in sensitive_values:
        assert value not in combined
    parsed = json.loads(summary.read_text(encoding="utf-8"))
    assert parsed["action_counts"] == {"delete+create": 1, "update": 4}
    assert parsed["high_risk"] is True
    assert set(parsed["high_risk_categories"]) >= {
        "identity_and_access",
        "public_network_exposure",
        "lambda_execution",
        "api_auth_cors",
        "encryption_and_key_controls",
        "storage_public_access",
    }
    resources = {item["address"]: item for item in parsed["resource_changes"]}
    iam = resources["module.api.aws_iam_role_policy.lambda"]
    assert iam["replace_paths"] == ["policy"]
    assert iam["replacement_reason"] == "replace_because_cannot_update"
    assert {"path": "policy.Statement[0].Action[0]", "sensitive": True} in iam["changed_paths"]
    network = resources["module.api.aws_security_group_rule.ingress"]
    assert {"path": "cidr_blocks[0]", "sensitive": False} in network["changed_paths"]
    lambda_change = resources['module.api.aws_lambda_function.backend["<key>"]']
    assert {"path": "role", "sensitive": False} in lambda_change["changed_paths"]
    assert {
        "path": "environment.variables.API_KEY",
        "sensitive": True,
    } in lambda_change["changed_paths"]
    assert {
        "path": "reserved_concurrent_executions",
        "sensitive": False,
    } in lambda_change["changed_paths"]
    assert parsed["resource_drift"][0]["address"].endswith(
        "aws_s3_bucket_public_access_block.preload"
    )
    assert parsed["resource_drift"][0]["changed_paths"] == [
        {"path": "block_public_acls", "sensitive": False}
    ]
    outputs = {item["name"]: item for item in parsed["output_changes"]}
    assert outputs["api_url"] == {
        "actions": ["update"],
        "name": "api_url",
        "sensitive": False,
    }
    assert outputs["oauth_client"]["sensitive"] is True
    assert parsed["truncation"]["truncated"] is False
    assert re.fullmatch(r"[0-9a-f]{64}", parsed["truncation"]["source_sha256"])


def test_plan_summary_truncates_deterministically_with_source_hash(
    tmp_path: Path,
) -> None:
    plan = {
        "resource_changes": [
            {
                "address": f'module.bulk.aws_lambda_function.item["secret-{index}"]',
                "type": "aws_lambda_function",
                "change": {
                    "actions": ["update"],
                    "before": {f"attribute_{item}": "before" for item in range(100)},
                    "after": {f"attribute_{item}": "after" for item in range(100)},
                },
            }
            for index in range(500)
        ]
    }
    plan_json = tmp_path / "large-plan.json"
    summary = tmp_path / "summary.json"
    classification = tmp_path / "classification.json"
    plan_json.write_text(json.dumps(plan), encoding="utf-8")
    result = run_cli(
        [
            "summarize-plan",
            "--input",
            str(plan_json),
            "--output",
            str(summary),
            "--classification-output",
            str(classification),
        ]
    )
    assert result.returncode != 0
    assert "truncat" in result.stderr.lower()
    assert not summary.exists()
    assert not classification.exists()


def minimal_change(
    index: int,
    *,
    resource_type: str = "aws_dynamodb_table",
    before: dict | None = None,
    after: dict | None = None,
    replace_paths: list[list[str]] | None = None,
) -> dict:
    return {
        "address": f"module.stack.{resource_type}.item_{index}",
        "type": resource_type,
        "change": {
            "actions": ["update"],
            "before": before or {"value": "before"},
            "after": after or {"value": "after"},
            "replace_paths": replace_paths or [],
        },
    }


@pytest.mark.parametrize(
    ("case", "plan", "expected_category"),
    [
        (
            "high-risk-33rd-resource",
            {
                "resource_changes": [
                    *[minimal_change(index) for index in range(32)],
                    minimal_change(
                        32,
                        resource_type="aws_iam_role_policy",
                        before={"policy": "limited"},
                        after={"policy": "admin"},
                    ),
                ]
            },
            "identity_and_access",
        ),
        (
            "high-risk-25th-path",
            {
                "resource_changes": [
                    minimal_change(
                        0,
                        resource_type="aws_lambda_function",
                        before={f"attribute_{index:02d}": "before" for index in range(25)},
                        after={
                            **{f"attribute_{index:02d}": "after" for index in range(24)},
                            "zz_role": "admin-role",
                        },
                    )
                ]
            },
            "lambda_execution",
        ),
        (
            "late-drift",
            {
                "resource_drift": [
                    *[minimal_change(index) for index in range(32)],
                    minimal_change(
                        32,
                        resource_type="aws_security_group_rule",
                        before={"cidr_blocks": ["10.0.0.0/8"]},
                        after={"cidr_blocks": ["0.0.0.0/0"]},
                    ),
                ]
            },
            "public_network_exposure",
        ),
        (
            "late-output",
            {
                "output_changes": {
                    **{
                        f"output_{index:03d}": {
                            "actions": ["update"],
                            "before": "before",
                            "after": "after",
                        }
                        for index in range(100)
                    },
                    "zz_sensitive_output": {
                        "actions": ["update"],
                        "before": "secret-before",
                        "after": "secret-after",
                        "after_sensitive": True,
                    },
                }
            },
            None,
        ),
        (
            "late-replacement-path",
            {
                "resource_changes": [
                    minimal_change(
                        0,
                        replace_paths=[
                            *[[f"attribute_{index:02d}"] for index in range(24)],
                            ["zz_role"],
                        ],
                    )
                ]
            },
            None,
        ),
    ],
)
def test_late_or_truncated_plan_evidence_is_classified_then_rejected(
    tmp_path: Path,
    case: str,
    plan: dict,
    expected_category: str | None,
) -> None:
    plan_json = tmp_path / f"{case}.json"
    classification = tmp_path / f"{case}-classification.json"
    summary = tmp_path / f"{case}-summary.json"
    plan_json.write_text(json.dumps(plan), encoding="utf-8")
    classified = run_cli(
        [
            "classify-plan",
            "--input",
            str(plan_json),
            "--output",
            str(classification),
        ]
    )
    assert classified.returncode == 0, classified.stderr
    complete = json.loads(classification.read_text(encoding="utf-8"))
    if expected_category:
        assert expected_category in complete["high_risk_categories"]
    if case == "late-output":
        assert complete["output_count"] == 101
        assert complete["sensitive_output_count"] == 1
    if case == "late-replacement-path":
        assert complete["replacement_path_count"] == 25
    blocked = run_cli(
        [
            "summarize-plan",
            "--input",
            str(plan_json),
            "--output",
            str(summary),
            "--classification-output",
            str(tmp_path / "blocked-classification.json"),
        ]
    )
    assert blocked.returncode != 0
    assert "truncat" in blocked.stderr.lower()
    assert not summary.exists()


def test_workflow_cannot_upload_or_apply_after_summary_rejection() -> None:
    workflow = (ROOT / ".github/workflows/deploy-reading-assistant.yml").read_text(encoding="utf-8")
    assert workflow.index("summarize-plan") < workflow.index("Store exact encrypted versioned plan")
    assert "continue-on-error: true" not in workflow


def test_apply_rejects_reclassified_downloaded_plan(tmp_path: Path) -> None:
    reviewed = tmp_path / "reviewed.json"
    changed = tmp_path / "changed.json"
    classification = tmp_path / "classification.json"
    reviewed.write_text(
        json.dumps({"resource_changes": [minimal_change(0)]}),
        encoding="utf-8",
    )
    changed.write_text(
        json.dumps(
            {
                "resource_changes": [
                    minimal_change(
                        0,
                        resource_type="aws_iam_role_policy",
                        before={"policy": "limited"},
                        after={"policy": "admin"},
                    )
                ]
            }
        ),
        encoding="utf-8",
    )
    classified = run_cli(
        [
            "summarize-plan",
            "--input",
            str(reviewed),
            "--output",
            str(tmp_path / "reviewed-summary.json"),
            "--classification-output",
            str(classification),
        ]
    )
    assert classified.returncode == 0, classified.stderr
    expected = {
        key: str(value)
        for key, value in json.loads(classification.read_text(encoding="utf-8")).items()
        if key
        in {
            "classification_sha256",
            "presentation_limits_sha256",
            "review_summary_sha256",
        }
        or key in CLASSIFICATION_COUNT_KEYS
    }
    result = run_cli(
        [
            "verify-classification",
            "--input",
            str(changed),
            *classification_args(expected),
        ]
    )
    assert result.returncode != 0
    assert "classification does not match" in result.stderr


def test_descriptor_rejects_unattested_classification(tmp_path: Path) -> None:
    plan_json = tmp_path / "plan.json"
    plan_json.write_text(
        json.dumps({"resource_changes": [minimal_change(0)]}),
        encoding="utf-8",
    )
    classification = tmp_path / "classification.json"
    classified = run_cli(
        [
            "classify-plan",
            "--input",
            str(plan_json),
            "--output",
            str(classification),
        ]
    )
    assert classified.returncode == 0, classified.stderr
    binary = tmp_path / "tfplan"
    binary.write_bytes(b"opaque plan")
    result = run_cli(
        [
            "describe",
            *identity_args(),
            "--plan-file",
            str(binary),
            "--classification",
            str(classification),
            "--output",
            str(tmp_path / "descriptor.json"),
        ]
    )
    assert result.returncode != 0
    assert "bounded-review attestation" in result.stderr


def test_oversized_summary_is_rejected_without_count_truncation(
    tmp_path: Path,
) -> None:
    plan = {
        "resource_changes": [
            minimal_change(
                resource_index,
                before={
                    f"attribute_{path_index:02d}_{'x' * 44}": "before" for path_index in range(24)
                },
                after={
                    f"attribute_{path_index:02d}_{'x' * 44}": "after" for path_index in range(24)
                },
            )
            for resource_index in range(32)
        ]
    }
    plan_json = tmp_path / "oversized.json"
    summary = tmp_path / "summary.json"
    plan_json.write_text(json.dumps(plan), encoding="utf-8")
    result = run_cli(
        [
            "summarize-plan",
            "--input",
            str(plan_json),
            "--output",
            str(summary),
            "--classification-output",
            str(tmp_path / "classification.json"),
        ]
    )
    assert result.returncode != 0
    assert "summary_size" in result.stderr
    assert not summary.exists()


def test_failure_summary_cli_never_logs_raw_stderr(tmp_path: Path) -> None:
    raw = tmp_path / "stderr"
    secrets = (
        "person@example.com sk-proj-supersecretvalue "
        "https://private.example password=hunter2 "
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdef"
    )
    raw.write_text(secrets, encoding="utf-8")
    result = run_cli(
        [
            "summarize-failure",
            "--input",
            str(raw),
            "--command",
            "terraform-plan",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert "terraform-plan failed" in result.stdout
    assert "details withheld" in result.stdout
    for token in secrets.split():
        assert token not in result.stdout


def test_workflow_never_logs_raw_plan_or_terraform_stderr() -> None:
    workflow = (ROOT / ".github/workflows/deploy-reading-assistant.yml").read_text(encoding="utf-8")
    assert "terraform plan" in workflow
    assert '2> "${RUNNER_TEMP}/terraform-plan.stderr"' in workflow
    assert '2> "${RUNNER_TEMP}/terraform-show.stderr"' in workflow
    assert "summarize-failure" in workflow
    assert "summarize-plan" in workflow
    assert "plan.raw.txt" not in workflow
    assert "cat " not in workflow


def test_privacy_bearing_terraform_variables_are_sensitive() -> None:
    expected = {
        "infra/envs/dev/variables.tf": {
            "google_oauth_client_id",
            "stripe_price_id_pro",
            "stripe_price_id_max",
            "app_extra_environment",
            "alert_email",
        },
        "infra/envs/prod/variables.tf": {
            "google_oauth_client_id",
            "stripe_price_id_pro",
            "stripe_price_id_max",
            "app_extra_environment",
            "alert_email",
        },
        "infra/modules/reading-assistant-api/variables.tf": {
            "google_oauth_client_id",
            "stripe_price_id_pro",
            "stripe_price_id_max",
            "extra_environment",
        },
        "infra/modules/reading-assistant-alerting/variables.tf": {"alert_email"},
    }
    for relative_path, names in expected.items():
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        for name in names:
            start = text.index(f'variable "{name}" {{')
            next_variable = text.find('\nvariable "', start + 1)
            block = text[start : next_variable if next_variable >= 0 else len(text)]
            assert "sensitive" in block
            assert "= true" in block
