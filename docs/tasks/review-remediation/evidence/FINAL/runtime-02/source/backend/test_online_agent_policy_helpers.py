from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tomllib
from fnmatch import fnmatchcase
from pathlib import Path

import pytest
import yaml

from scripts.exact_plan_policy import (
    PlanIdentity,
    PolicyError,
    download_verified_plan,
    redact_plan_text,
    upload_exact_plan,
    validate_role_separation,
)
from scripts.online_agent_policy import (
    authorize_actor,
    fetch_intake_payload,
    parse_actor_allowlist,
)
from scripts.validate_agent_intake import sanitize_payload

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / ".github" / "workflows" / "deploy-reading-assistant.yml"
INTAKE = ROOT / ".github" / "workflows" / "agent-intake.yml"
READ_ONLY_ROLES = {
    "planner",
    "ci-investigator",
    "correctness-reviewer",
    "security-reviewer",
    "test-runner",
    "release-preparer",
}
MUTATING_ROLES = {"implementer"}


class FakeGitHubApi:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get(self, path: str) -> dict:
        self.calls.append(path)
        if path == "/repos/owner/repository":
            return {
                "full_name": "owner/repository",
                "fork": False,
                "default_branch": "main",
            }
        if path == "/repos/owner/repository/commits/main":
            return {"sha": "a" * 40}
        if path == "/repos/owner/repository/issues/42":
            return {
                "number": 42,
                "title": "Bounded task",
                "body": (
                    "### Goal\n\nImprove reader safety.\n\n"
                    "### Acceptance criteria\n\nNo regression.\n\n"
                    "### Allowed scope\n\nscripts and tests\n\n"
                    "### Prohibited scope\n\nNo deploy.\n\n"
                    "### Risk level\n\nmedium\n\n"
                    "### Test expectations\n\ntask check"
                ),
                "state": "open",
                "user": {"id": 456},
            }
        raise AssertionError(f"Unexpected API path: {path}")


class FakeVersionedS3:
    def __init__(self) -> None:
        self.versions: dict[tuple[str, str, str], dict] = {}
        self.counter = 0

    def put_object(self, **kwargs) -> dict:
        self.counter += 1
        version_id = f"version-{self.counter}"
        self.versions[(kwargs["Bucket"], kwargs["Key"], version_id)] = dict(kwargs)
        return {"VersionId": version_id}

    def head_object(self, **kwargs) -> dict:
        item = self.versions[(kwargs["Bucket"], kwargs["Key"], kwargs["VersionId"])]
        return {
            "VersionId": kwargs["VersionId"],
            "Metadata": item["Metadata"],
            "ServerSideEncryption": item["ServerSideEncryption"],
            "SSEKMSKeyId": item["SSEKMSKeyId"],
        }

    def get_object(self, **kwargs) -> dict:
        item = self.versions[(kwargs["Bucket"], kwargs["Key"], kwargs["VersionId"])]
        return {"VersionId": kwargs["VersionId"], "Body": item["Body"]}


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "123,",
        ",123",
        "123,,456",
        "123, 456",
        " 123",
        "+123",
        "-123",
        "１２３",
        "123;456",
        "123\n456",
        "0",
        "001",
    ],
)
def test_actor_allowlist_parser_is_strict_ascii_csv(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_actor_allowlist(raw)


def test_actor_allowlist_requires_exact_match() -> None:
    assert parse_actor_allowlist("123,456") == ("123", "456")
    assert authorize_actor("123,456", "123") == "123"
    with pytest.raises(ValueError):
        authorize_actor("123,456", "12")


@pytest.mark.parametrize(
    ("allowlist", "actor"),
    [
        ("123, 456", "123"),
        ("123,456", "999"),
        ("１２３", "１２３"),
    ],
)
def test_invalid_or_untrusted_actor_causes_no_api_call(allowlist: str, actor: str) -> None:
    api = FakeGitHubApi()
    with pytest.raises(ValueError):
        fetch_intake_payload(
            api_get=api.get,
            trusted_actor_ids=allowlist,
            actor_id=actor,
            repository="owner/repository",
            issue_number="42",
            git_ref="refs/heads/main",
            workflow_ref=("owner/repository/.github/workflows/agent-intake.yml@refs/heads/main"),
            workflow_path=".github/workflows/agent-intake.yml",
            checked_out_sha="a" * 40,
            run_id="100",
            run_attempt="1",
        )
    assert api.calls == []


def test_unprotected_ref_causes_no_api_call() -> None:
    api = FakeGitHubApi()
    with pytest.raises(ValueError, match="protected"):
        fetch_intake_payload(
            api_get=api.get,
            trusted_actor_ids="123",
            actor_id="123",
            repository="owner/repository",
            issue_number="42",
            git_ref="refs/heads/main",
            workflow_ref=("owner/repository/.github/workflows/agent-intake.yml@refs/heads/main"),
            workflow_path=".github/workflows/agent-intake.yml",
            checked_out_sha="a" * 40,
            run_id="100",
            run_attempt="1",
            ref_protected="false",
        )
    assert api.calls == []


def test_non_default_workflow_ref_never_fetches_issue() -> None:
    api = FakeGitHubApi()
    with pytest.raises(ValueError, match="default branch"):
        fetch_intake_payload(
            api_get=api.get,
            trusted_actor_ids="123",
            actor_id="123",
            repository="owner/repository",
            issue_number="42",
            git_ref="refs/heads/feature",
            workflow_ref=("owner/repository/.github/workflows/agent-intake.yml@refs/heads/feature"),
            workflow_path=".github/workflows/agent-intake.yml",
            checked_out_sha="a" * 40,
            run_id="100",
            run_attempt="1",
        )
    assert "/repos/owner/repository/issues/42" not in api.calls


def test_intake_fetches_issue_only_after_identity_and_default_branch_gate() -> None:
    api = FakeGitHubApi()
    payload = fetch_intake_payload(
        api_get=api.get,
        trusted_actor_ids="123,456",
        actor_id="123",
        repository="owner/repository",
        issue_number="42",
        git_ref="refs/heads/main",
        workflow_ref=("owner/repository/.github/workflows/agent-intake.yml@refs/heads/main"),
        workflow_path=".github/workflows/agent-intake.yml",
        checked_out_sha="a" * 40,
        run_id="100",
        run_attempt="2",
    )
    assert api.calls[-1] == "/repos/owner/repository/issues/42"
    assert payload["request"]["default_branch_commit"] == "a" * 40
    assert payload["request"]["workflow_ref"].endswith("@refs/heads/main")
    assert payload["request"]["run_attempt"] == "2"


def test_sanitized_intake_contains_hashes_and_neutralized_selected_fields_only() -> None:
    api = FakeGitHubApi()
    payload = fetch_intake_payload(
        api_get=api.get,
        trusted_actor_ids="123",
        actor_id="123",
        repository="owner/repository",
        issue_number="42",
        git_ref="refs/heads/main",
        workflow_ref=("owner/repository/.github/workflows/agent-intake.yml@refs/heads/main"),
        workflow_path=".github/workflows/agent-intake.yml",
        checked_out_sha="a" * 40,
        run_id="100",
        run_attempt="1",
    )
    artifact = sanitize_payload(payload)
    serialized = json.dumps(artifact, sort_keys=True)
    assert payload["issue"]["body"] not in serialized
    assert (
        artifact["untrusted_issue"]["body_sha256"]
        == hashlib.sha256(payload["issue"]["body"].encode()).hexdigest()
    )
    assert set(artifact["untrusted_issue"]["fields"]) == {
        "acceptance_criteria",
        "allowed_scope",
        "goal",
        "prohibited_scope",
        "risk_level",
        "test_expectations",
    }
    for value in artifact["untrusted_issue"]["fields"].values():
        assert not re.search(r"[<>{}\[\]()`*_!#@]|https?://|```", value)


@pytest.mark.parametrize(
    "secret",
    [
        "-----BEGIN PRIVATE KEY-----",
        "AKIAIOSFODNN7EXAMPLE",
        "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "sk-proj-abcdefghijklmnopqrstuvwxyz",
        "Bearer abcdefghijklmnopqrstuvwxyz",
        "password=hunter2",
        "${{ secrets.PRODUCTION_TOKEN }}",
    ],
)
def test_sanitizer_rejects_common_secret_patterns(secret: str) -> None:
    api = FakeGitHubApi()
    payload = fetch_intake_payload(
        api_get=api.get,
        trusted_actor_ids="123",
        actor_id="123",
        repository="owner/repository",
        issue_number="42",
        git_ref="refs/heads/main",
        workflow_ref=("owner/repository/.github/workflows/agent-intake.yml@refs/heads/main"),
        workflow_path=".github/workflows/agent-intake.yml",
        checked_out_sha="a" * 40,
        run_id="100",
        run_attempt="1",
    )
    payload["issue"]["body"] += f"\n\n### Goal\n\n{secret}"
    with pytest.raises(ValueError, match="secret"):
        sanitize_payload(payload)


@pytest.mark.parametrize(
    "secret",
    [
        "ｐａｓｓｗｏｒｄ＝hunter2",
        "pass\u200bword=hunter2",
        "password\u202e=hunter2",
        "pa\u0301ssword=hunter2",
        "p a s s w o r d = hunter2",
        "pаssword=hunter2",
        "postgresql://reader:private@db.internal/app",
        "ｍｏｎｇｏｄｂ：／／reader：private＠db.internal/app",
        "ｇｈｐ＿abcdefghijklmnopqrstuvwxyz0123456789",
        "-----ＢＥＧＩＮ ＰＲＩＶＡＴＥ ＫＥＹ-----",
        "A7vQ2mZ9xL4cR8tY1pW6nK3sD5fH0jB+",
    ],
)
def test_sanitizer_rejects_canonicalized_obfuscated_credentials(secret: str) -> None:
    api = FakeGitHubApi()
    payload = fetch_intake_payload(
        api_get=api.get,
        trusted_actor_ids="123",
        actor_id="123",
        repository="owner/repository",
        issue_number="42",
        git_ref="refs/heads/main",
        workflow_ref=("owner/repository/.github/workflows/agent-intake.yml@refs/heads/main"),
        workflow_path=".github/workflows/agent-intake.yml",
        checked_out_sha="a" * 40,
        run_id="100",
        run_attempt="1",
    )
    payload["issue"]["body"] = payload["issue"]["body"].replace("Improve reader safety.", secret)
    with pytest.raises(ValueError):
        sanitize_payload(payload)


def test_rejected_intake_cli_writes_no_artifacts(tmp_path: Path) -> None:
    api = FakeGitHubApi()
    payload = fetch_intake_payload(
        api_get=api.get,
        trusted_actor_ids="123",
        actor_id="123",
        repository="owner/repository",
        issue_number="42",
        git_ref="refs/heads/main",
        workflow_ref=("owner/repository/.github/workflows/agent-intake.yml@refs/heads/main"),
        workflow_path=".github/workflows/agent-intake.yml",
        checked_out_sha="a" * 40,
        run_id="100",
        run_attempt="1",
    )
    payload["issue"]["body"] = payload["issue"]["body"].replace(
        "Improve reader safety.", "password\u202e=hunter2"
    )
    raw = tmp_path / "raw.json"
    outputs = [tmp_path / "intake.json", tmp_path / "intake.txt", tmp_path / "provenance.json"]
    raw.write_text(json.dumps(payload), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "validate_agent_intake.py"),
            "--input",
            str(raw),
            "--json-output",
            str(outputs[0]),
            "--text-output",
            str(outputs[1]),
            "--provenance-output",
            str(outputs[2]),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert all(not output.exists() for output in outputs)
    assert "hunter2" not in result.stdout + result.stderr


def test_hostile_markup_links_images_and_fences_are_not_active_in_artifact() -> None:
    api = FakeGitHubApi()
    payload = fetch_intake_payload(
        api_get=api.get,
        trusted_actor_ids="123",
        actor_id="123",
        repository="owner/repository",
        issue_number="42",
        git_ref="refs/heads/main",
        workflow_ref=("owner/repository/.github/workflows/agent-intake.yml@refs/heads/main"),
        workflow_path=".github/workflows/agent-intake.yml",
        checked_out_sha="a" * 40,
        run_id="100",
        run_attempt="1",
    )
    payload["issue"]["body"] = (
        "### Goal\n\n<script>run()</script> ![x](https://evil.invalid/a.png) "
        "[click](https://evil.invalid) ```sh\nrm -rf /\n```\n\n"
        "### Acceptance criteria\n\n> @owner **approve**\n\n"
        "### Allowed scope\n\nscripts\n\n"
        "### Prohibited scope\n\nexternal writes\n\n"
        "### Risk level\n\nmedium\n\n"
        "### Test expectations\n\ntask check"
    )
    artifact = sanitize_payload(payload)
    serialized = json.dumps(artifact)
    assert "evil.invalid" not in serialized
    assert "<script>" not in serialized
    assert "```" not in serialized
    assert "@owner" not in serialized


def test_intake_cli_deletes_raw_and_hashes_sanitized_artifacts(tmp_path: Path) -> None:
    api = FakeGitHubApi()
    payload = fetch_intake_payload(
        api_get=api.get,
        trusted_actor_ids="123",
        actor_id="123",
        repository="owner/repository",
        issue_number="42",
        git_ref="refs/heads/main",
        workflow_ref=("owner/repository/.github/workflows/agent-intake.yml@refs/heads/main"),
        workflow_path=".github/workflows/agent-intake.yml",
        checked_out_sha="a" * 40,
        run_id="100",
        run_attempt="1",
    )
    raw = tmp_path / "raw.json"
    artifact = tmp_path / "intake.json"
    text = tmp_path / "intake.txt"
    provenance = tmp_path / "provenance.json"
    raw.write_text(json.dumps(payload), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "validate_agent_intake.py"),
            "--input",
            str(raw),
            "--json-output",
            str(artifact),
            "--text-output",
            str(text),
            "--provenance-output",
            str(provenance),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not raw.exists()
    manifest = json.loads(provenance.read_text(encoding="utf-8"))
    assert manifest["workflow_ref"].endswith("@refs/heads/main")
    assert manifest["run_id"] == "100"
    assert manifest["run_attempt"] == "1"
    assert manifest["default_branch_commit"] == "a" * 40
    assert manifest["artifacts"]["intake.json"] == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert manifest["artifacts"]["intake.txt"] == hashlib.sha256(text.read_bytes()).hexdigest()
    assert payload["issue"]["body"] not in artifact.read_text(encoding="utf-8")
    assert "http" not in text.read_text(encoding="utf-8").lower()


def plan_identity() -> PlanIdentity:
    return PlanIdentity.create(
        bucket="private-plan-bucket",
        prefix="terraform-plans",
        run_id="100",
        run_attempt="2",
        environment="prod",
        commit_sha="a" * 40,
        workflow_ref=(
            "owner/repository/.github/workflows/deploy-reading-assistant.yml@refs/heads/main"
        ),
        kms_key_arn="arn:aws:kms:ap-northeast-1:123456789012:key/example",
        apply_role_arn="arn:aws:iam::123456789012:role/untangle-apply",
    )


def test_exact_plan_version_digest_and_metadata_survive_newer_version() -> None:
    store = FakeVersionedS3()
    identity = plan_identity()
    first = upload_exact_plan(store, identity, b"first exact plan")
    second = upload_exact_plan(store, identity, b"newer plan")
    assert first.version_id != second.version_id
    downloaded = download_verified_plan(store, identity, first)
    assert downloaded == b"first exact plan"
    assert first.digest == hashlib.sha256(downloaded).hexdigest()
    assert first.key == (f"terraform-plans/100/2/prod/{'a' * 40}/tfplan")


def test_exact_plan_rejects_tampered_metadata_digest_and_arbitrary_key() -> None:
    store = FakeVersionedS3()
    identity = plan_identity()
    record = upload_exact_plan(store, identity, b"exact plan")
    stored = store.versions[(record.bucket, record.key, record.version_id)]
    stored["Metadata"]["commit-sha"] = "b" * 40
    with pytest.raises(PolicyError, match="metadata"):
        download_verified_plan(store, identity, record)

    clean_store = FakeVersionedS3()
    clean_record = upload_exact_plan(clean_store, identity, b"exact plan")
    arbitrary = clean_record._replace(key="attacker/supplied/tfplan")
    with pytest.raises(PolicyError, match="key"):
        download_verified_plan(clean_store, identity, arbitrary)


def test_plan_redaction_masks_values_and_rejects_private_keys() -> None:
    redacted = redact_plan_text(
        '+ token = "super-secret"\n'
        '+ password = "hunter2"\n'
        '+ endpoint = "https://example.invalid/path"\n'
    )
    assert "super-secret" not in redacted
    assert "hunter2" not in redacted
    assert "https://example.invalid" not in redacted
    with pytest.raises(PolicyError, match="private key"):
        redact_plan_text("-----BEGIN PRIVATE KEY-----")


def test_plan_and_apply_roles_must_be_distinct() -> None:
    plan = "arn:aws:iam::123456789012:role/untangle-plan"
    apply = "arn:aws:iam::123456789012:role/untangle-apply"
    validate_role_separation(plan, apply)
    with pytest.raises(PolicyError, match="distinct"):
        validate_role_separation(plan, plan)


def load_plan_policy(environment: str) -> dict:
    return json.loads(
        (ROOT / "docs" / "examples" / f"aws-plan-role-policy-{environment}.json").read_text(
            encoding="utf-8"
        )
    )


def resources_for_action(policy: dict, action: str) -> list[str]:
    resources: list[str] = []
    for statement in policy["Statement"]:
        actions = statement["Action"]
        actions = [actions] if isinstance(actions, str) else actions
        if statement["Effect"] != "Allow" or action not in actions:
            continue
        values = statement["Resource"]
        resources.extend([values] if isinstance(values, str) else values)
    return resources


def policy_resource_matches(policy: dict, action: str, resource: str) -> bool:
    return any(fnmatchcase(resource, pattern) for pattern in resources_for_action(policy, action))


def test_environment_plan_policies_are_structurally_least_privilege() -> None:
    secret_bearing_actions = {
        "s3:GetObject",
        "s3:GetObjectVersion",
        "lambda:GetFunction",
        "lambda:GetFunctionConfiguration",
        "ssm:GetParameter",
        "kms:Decrypt",
    }
    for environment in ("dev", "prod"):
        policy = load_plan_policy(environment)
        statements = policy["Statement"]
        assert policy["Version"] == "2012-10-17"
        for statement in statements:
            actions = statement["Action"]
            actions = [actions] if isinstance(actions, str) else actions
            if statement["Effect"] == "Allow":
                assert all("*" not in action for action in actions)
                if secret_bearing_actions.intersection(actions):
                    assert statement["Resource"] != "*"
            else:
                assert statement["Sid"] == "DenyInfrastructureMutationAndPlanDeletion"
                assert statement["Resource"] == "*"

        state_key = f"02_english/reading-assistant/{environment}/terraform.tfstate"
        state_resources = resources_for_action(policy, "s3:GetObject")
        assert f"arn:aws:s3:::STATE_BUCKET/{state_key}" in state_resources
        assert not any(
            f"/reading-assistant/{'prod' if environment == 'dev' else 'dev'}/" in resource
            for resource in state_resources
        )
        list_statement = next(
            statement
            for statement in statements
            if statement["Sid"] == "ListOnlyEnvironmentStatePrefix"
        )
        assert list_statement["Resource"] == "arn:aws:s3:::STATE_BUCKET"
        assert list_statement["Condition"]["StringLike"]["s3:prefix"] == [
            state_key,
            f"{state_key}.*",
        ]
        plan_resource = resources_for_action(policy, "s3:PutObject")
        expected_plan_objects = [
            f"arn:aws:s3:::PRIVATE_PLAN_BUCKET/terraform-plans/*/*/{environment}/*/tfplan",
            (
                "arn:aws:s3:::PRIVATE_PLAN_BUCKET/terraform-plans/"
                f"*/*/{environment}/*/reading-assistant-lambda.zip"
            ),
        ]
        assert plan_resource == expected_plan_objects
        preload_bucket = next(
            statement
            for statement in statements
            if statement["Sid"] == f"ReadOnly{environment.title()}PreloadBucket"
        )
        preload_actions = preload_bucket["Action"]
        assert "s3:GetEncryptionConfiguration" in preload_actions
        assert "s3:GetBucketEncryption" not in preload_actions
        assert preload_bucket["Resource"] == (
            f"arn:aws:s3:::english-{environment}-reading-assistant-preload-content-ACCOUNT_ID"
        )
        tagged_api = next(
            statement
            for statement in statements
            if statement["Sid"] == f"ReadOnlyTagged{environment.title()}HttpApi"
        )
        assert tagged_api["Condition"]["StringEquals"] == {
            "aws:ResourceTag/Environment": environment,
            "aws:ResourceTag/Project": "english-reading-assistant",
        }
        plan_bucket_controls = next(
            statement
            for statement in statements
            if statement["Sid"] == "InspectPrivatePlanBucketControls"
        )
        assert plan_bucket_controls["Action"] == [
            "s3:GetEncryptionConfiguration",
            "s3:GetBucketVersioning",
        ]
        plan_kms = next(
            statement
            for statement in statements
            if statement["Sid"] == f"EncryptOnlyRunDerived{environment.title()}PlanObject"
        )
        assert (
            plan_kms["Condition"]["StringLike"]["kms:EncryptionContext:aws:s3:arn"]
            == expected_plan_objects
        )
        kms = next(
            statement
            for statement in statements
            if statement["Sid"] == "DecryptOnlyEnvironmentState"
        )
        assert kms["Resource"] == "STATE_KMS_KEY_ARN"
        assert kms["Condition"]["StringEquals"]["kms:ViaService"] == ("s3.REGION.amazonaws.com")
        assert (
            kms["Condition"]["StringLike"]["kms:EncryptionContext:aws:s3:arn"]
            == f"arn:aws:s3:::STATE_BUCKET/{state_key}*"
        )
        deny_actions = next(
            statement["Action"] for statement in statements if statement["Effect"] == "Deny"
        )
        assert "iam:PassRole" in deny_actions
        assert "lambda:Update*" in deny_actions
        assert "s3:DeleteObject" in deny_actions
        assert resources_for_action(policy, "ssm:GetParameter") == []


def test_dev_and_prod_plan_policies_deny_cross_environment_resources() -> None:
    dev = load_plan_policy("dev")
    prod = load_plan_policy("prod")
    resource_pairs = [
        (
            "s3:GetObject",
            "arn:aws:s3:::STATE_BUCKET/02_english/reading-assistant/{env}/terraform.tfstate",
        ),
        (
            "lambda:GetFunctionConfiguration",
            "arn:aws:lambda:REGION:ACCOUNT_ID:function:english-{env}-reading-assistant-api",
        ),
        (
            "dynamodb:DescribeTable",
            "arn:aws:dynamodb:REGION:ACCOUNT_ID:table/english-{env}-reading-assistant",
        ),
    ]
    for action, template in resource_pairs:
        assert policy_resource_matches(dev, action, template.format(env="dev"))
        assert not policy_resource_matches(dev, action, template.format(env="prod"))
        assert policy_resource_matches(prod, action, template.format(env="prod"))
        assert not policy_resource_matches(prod, action, template.format(env="dev"))


def test_plan_policy_validation_script_accepts_only_split_templates() -> None:
    assert not (ROOT / "docs" / "examples" / "aws-plan-role-policy.json").exists()
    assert not (ROOT / "docs" / "examples" / "aws-apply-plan-read-policy.json").exists()
    for environment in ("dev", "prod"):
        apply_policy = json.loads(
            (
                ROOT / "docs" / "examples" / f"aws-apply-plan-read-policy-{environment}.json"
            ).read_text(encoding="utf-8")
        )
        resources = resources_for_action(apply_policy, "s3:GetObjectVersion")
        expected_objects = [
            f"arn:aws:s3:::PRIVATE_PLAN_BUCKET/terraform-plans/*/*/{environment}/*/tfplan",
            (
                "arn:aws:s3:::PRIVATE_PLAN_BUCKET/terraform-plans/"
                f"*/*/{environment}/*/reading-assistant-lambda.zip"
            ),
        ]
        assert resources == expected_objects
        decrypt = next(
            statement
            for statement in apply_policy["Statement"]
            if statement["Sid"] == f"DecryptOnly{environment.title()}PlanObjects"
        )
        assert (
            decrypt["Condition"]["StringLike"]["kms:EncryptionContext:aws:s3:arn"]
            == expected_objects
        )
        other = "prod" if environment == "dev" else "dev"
        assert not policy_resource_matches(
            apply_policy,
            "s3:GetObjectVersion",
            (f"arn:aws:s3:::PRIVATE_PLAN_BUCKET/terraform-plans/100/1/{other}/{'a' * 40}/tfplan"),
        )
        assert policy_resource_matches(
            apply_policy,
            "s3:GetObjectVersion",
            (
                "arn:aws:s3:::PRIVATE_PLAN_BUCKET/terraform-plans/100/1/"
                f"{environment}/{'a' * 40}/reading-assistant-lambda.zip"
            ),
        )
        assert not policy_resource_matches(
            apply_policy,
            "s3:GetObjectVersion",
            (
                "arn:aws:s3:::PRIVATE_PLAN_BUCKET/terraform-plans/100/1/"
                f"{other}/{'a' * 40}/reading-assistant-lambda.zip"
            ),
        )
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "validate_aws_plan_policies.py"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "dev and prod plan policies validated" in result.stdout


def parse_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    _, raw, _ = text.split("---", 2)
    return yaml.safe_load(raw)


def test_generated_read_only_role_runtime_permissions_are_parsed() -> None:
    denied = {"Bash", "Write", "Edit", "WebFetch", "WebSearch", "Task", "mcp__*"}
    for role in READ_ONLY_ROLES:
        cursor = parse_frontmatter(ROOT / ".cursor" / "agents" / f"{role}.md")
        claude = parse_frontmatter(ROOT / ".claude" / "agents" / f"{role}.md")
        codex = tomllib.loads(
            (ROOT / ".codex" / "agents" / f"{role}.toml").read_text(encoding="utf-8")
        )
        assert cursor["readonly"] is True
        assert set(claude["tools"]) == {"Read", "Grep", "Glob"}
        assert denied <= set(claude["disallowedTools"])
        assert codex["sandbox_mode"] == "read-only"


def test_generated_mutating_roles_have_bounded_claude_and_codex_permissions() -> None:
    for role in MUTATING_ROLES:
        claude = parse_frontmatter(ROOT / ".claude" / "agents" / f"{role}.md")
        codex = tomllib.loads(
            (ROOT / ".codex" / "agents" / f"{role}.toml").read_text(encoding="utf-8")
        )
        assert "WebFetch" in claude["disallowedTools"]
        assert "WebSearch" in claude["disallowedTools"]
        assert "mcp__*" in claude["disallowedTools"]
        assert codex["sandbox_mode"] == "workspace-write"
        assert "deploy" not in {tool.lower() for tool in claude["tools"]}


def test_read_only_test_and_release_roles_delegate_execution_to_parent() -> None:
    for role in ("test-runner", "release-preparer"):
        text = (ROOT / ".rulesync" / "subagents" / f"{role}.md").read_text(encoding="utf-8")
        normalized = " ".join(text.lower().split())
        assert "parent" in normalized
        assert "immutable" in normalized
        assert "credential-free dev container" in normalized


def test_deploy_workflow_is_exact_plan_two_job_flow_without_replan() -> None:
    text = DEPLOY.read_text(encoding="utf-8")
    parsed = yaml.safe_load(text)
    assert set(parsed["jobs"]) == {"plan", "apply"}
    assert parsed["jobs"]["apply"]["needs"] == "plan"
    assert text.count("id-token: write") == 2
    plan_block, apply_block = text.split("\n  apply:", 1)
    assert "vars.AWS_PLAN_ROLE_ARN_DEV" in plan_block
    assert "vars.AWS_PLAN_ROLE_ARN_PROD" in plan_block
    assert "vars.AWS_APPLY_ROLE_ARN_DEV" in plan_block
    assert "vars.AWS_APPLY_ROLE_ARN_PROD" in plan_block
    assert "role-to-assume: ${{ vars.AWS_PLAN_ROLE_ARN }}" not in plan_block
    assert "role-to-assume: ${{ vars.AWS_APPLY_ROLE_ARN }}" not in plan_block
    assert "role-to-assume: ${{ needs.plan.outputs.apply_role_arn }}" in apply_block
    assert "vars.AWS_APPLY_ROLE_ARN" not in apply_block
    assert "terraform plan" in plan_block
    assert "terraform plan" not in apply_block
    assert "summarize-plan" in plan_block
    assert "plan.raw.txt" not in text
    assert "terraform apply -input=false -auto-approve tfplan" in apply_block
    assert "version-id" in apply_block
    assert "needs.plan.outputs.plan_version_id" in apply_block
    assert "ref: ${{ needs.plan.outputs.commit_sha }}" in apply_block
    assert "environment: ${{ inputs.environment }}" in apply_block
    assert "AWS_DEPLOY_ROLE_ARN" not in text


def test_intake_workflow_uses_single_python_gate_before_issue_fetch() -> None:
    text = INTAKE.read_text(encoding="utf-8")
    assert "Validate immutable requesting actor" not in text
    assert "github.rest.issues" not in text
    assert "online_agent_policy.py intake" in text
    assert "ref: ${{ github.event.repository.default_branch }}" in text
    assert text.index("online_agent_policy.py intake") < text.index("validate_agent_intake.py")


def trust_allows(policy: dict, *, action: str, audience: str, subject: str) -> bool:
    return any(
        statement["Effect"] == "Allow"
        and statement["Action"] == action
        and statement["Condition"]["StringEquals"]["token.actions.githubusercontent.com:aud"]
        == audience
        and statement["Condition"]["StringEquals"]["token.actions.githubusercontent.com:sub"]
        == subject
        for statement in policy["Statement"]
    )


def test_split_oidc_trust_policies_reject_cross_role_and_wrong_contexts() -> None:
    policies = {
        name: json.loads(
            (ROOT / "docs" / "examples" / f"aws-{name}-oidc-trust-policy.json").read_text(
                encoding="utf-8"
            )
        )
        for name in ("plan", "apply-dev", "apply-prod")
    }
    subjects = {
        name: policy["Statement"][0]["Condition"]["StringEquals"][
            "token.actions.githubusercontent.com:sub"
        ]
        for name, policy in policies.items()
    }
    action = "sts:AssumeRoleWithWebIdentity"
    for name, policy in policies.items():
        assert len(policy["Statement"]) == 1
        assert trust_allows(
            policy,
            action=action,
            audience="sts.amazonaws.com",
            subject=subjects[name],
        )
        for other_name, other_subject in subjects.items():
            if other_name != name:
                assert not trust_allows(
                    policy,
                    action=action,
                    audience="sts.amazonaws.com",
                    subject=other_subject,
                )
        assert not trust_allows(
            policy,
            action="sts:AssumeRole",
            audience="sts.amazonaws.com",
            subject=subjects[name],
        )
        assert not trust_allows(
            policy,
            action=action,
            audience="wrong.example",
            subject=subjects[name],
        )
        for wrong in (
            subjects[name].replace("OWNER/REPOSITORY", "ATTACKER/FORK", 1),
            subjects[name].replace("refs/heads/main", "refs/heads/feature"),
        ):
            assert not trust_allows(
                policy,
                action=action,
                audience="sts.amazonaws.com",
                subject=wrong,
            )

    assert "environment:dev" not in subjects["plan"]
    assert "environment:prod" not in subjects["plan"]
    assert "environment:dev" in subjects["apply-dev"]
    assert "environment:prod" in subjects["apply-prod"]


def test_external_self_review_requirements_are_machine_readable() -> None:
    setup = (ROOT / "docs" / "GITHUB_SETUP.md").read_text(encoding="utf-8").lower()
    assert "prevent self-review" in setup
    assert "required reviewers" in setup
