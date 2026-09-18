#!/usr/bin/env python3
"""Validate environment-specific least-privilege AWS plan-role examples."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "docs" / "examples"
ENVIRONMENTS = ("dev", "prod")
REQUIRED_PLACEHOLDERS = {
    "ACCOUNT_ID",
    "PRIVATE_PLAN_BUCKET",
    "PLAN_KMS_KEY_ARN",
    "REGION",
    "STATE_BUCKET",
    "STATE_KMS_KEY_ARN",
}
SECRET_BEARING_ACTIONS = {
    "kms:Decrypt",
    "lambda:GetFunction",
    "lambda:GetFunctionConfiguration",
    "s3:GetObject",
    "s3:GetObjectVersion",
    "ssm:GetParameter",
}
ALLOWED_UNSCOPED_SIDS = {
    "CallerIdentityOnly",
    "RegionalAccountScopedUnscopableReads",
}
DENY_SID = "DenyInfrastructureMutationAndPlanDeletion"


class ValidationError(ValueError):
    """An unsafe example policy."""


def as_strings(value: Any, name: str) -> list[str]:
    values = [value] if isinstance(value, str) else value
    if (
        not isinstance(values, list)
        or not values
        or not all(isinstance(item, str) and item for item in values)
    ):
        raise ValidationError(f"{name} must be a non-empty string or string array")
    return values


def statement_by_sid(policy: dict[str, Any], sid: str) -> dict[str, Any]:
    matches = [statement for statement in policy["Statement"] if statement.get("Sid") == sid]
    if len(matches) != 1:
        raise ValidationError(f"Expected exactly one {sid} statement")
    return matches[0]


def validate_policy(environment: str) -> None:
    path = EXAMPLES / f"aws-plan-role-policy-{environment}.json"
    raw = path.read_text(encoding="utf-8")
    policy = json.loads(raw)
    if policy.get("Version") != "2012-10-17" or not isinstance(policy.get("Statement"), list):
        raise ValidationError(f"{path.name} is not an IAM policy object")
    missing_placeholders = sorted(
        placeholder for placeholder in REQUIRED_PLACEHOLDERS if placeholder not in raw
    )
    if missing_placeholders:
        raise ValidationError(f"{path.name} lacks placeholders: {missing_placeholders}")
    other = "prod" if environment == "dev" else "dev"
    forbidden_markers = (
        f"/reading-assistant/{other}/",
        f"english-{other}-reading-assistant",
        f"/english/{other}/reading-assistant/",
        f"/*/{other}/*/tfplan",
    )
    if any(marker in raw for marker in forbidden_markers):
        raise ValidationError(f"{path.name} contains a cross-environment marker")

    for statement in policy["Statement"]:
        if not isinstance(statement, dict):
            raise ValidationError("Policy statements must be objects")
        actions = as_strings(statement.get("Action"), "Action")
        resources = as_strings(statement.get("Resource"), "Resource")
        if statement.get("Effect") == "Allow":
            if any("*" in action for action in actions):
                raise ValidationError(f"{statement.get('Sid')} has wildcard Allow action")
            if SECRET_BEARING_ACTIONS.intersection(actions) and "*" in resources:
                raise ValidationError(f"{statement.get('Sid')} exposes secret-bearing resources")
            if "*" in resources:
                if statement.get("Sid") not in ALLOWED_UNSCOPED_SIDS:
                    raise ValidationError(f"{statement.get('Sid')} is unexpectedly unscoped")
                if statement.get("Sid") == "CallerIdentityOnly":
                    if actions != ["sts:GetCallerIdentity"]:
                        raise ValidationError("Caller identity statement is not exact")
                else:
                    condition = statement.get("Condition", {})
                    if condition.get("StringEquals") != {
                        "aws:RequestedRegion": "REGION"
                    } or condition.get("StringEqualsIfExists") != {
                        "aws:ResourceAccount": "ACCOUNT_ID"
                    }:
                        raise ValidationError("Unscopable reads lack region/account boundary")

    state_key = f"02_english/reading-assistant/{environment}/terraform.tfstate"
    list_state = statement_by_sid(policy, "ListOnlyEnvironmentStatePrefix")
    if list_state.get("Resource") != "arn:aws:s3:::STATE_BUCKET":
        raise ValidationError("State ListBucket is not bound to STATE_BUCKET")
    if list_state.get("Condition", {}).get("StringLike", {}).get("s3:prefix") != [
        state_key,
        f"{state_key}.*",
    ]:
        raise ValidationError("State ListBucket prefix is not exact")

    state_kms = statement_by_sid(policy, "DecryptOnlyEnvironmentState")
    if state_kms.get("Resource") != "STATE_KMS_KEY_ARN":
        raise ValidationError("State decrypt is not bound to STATE_KMS_KEY_ARN")
    if (
        state_kms.get("Condition", {}).get("StringEquals", {}).get("kms:ViaService")
        != "s3.REGION.amazonaws.com"
    ):
        raise ValidationError("State decrypt lacks exact S3 ViaService")
    expected_context = f"arn:aws:s3:::STATE_BUCKET/{state_key}*"
    if (
        state_kms.get("Condition", {}).get("StringLike", {}).get("kms:EncryptionContext:aws:s3:arn")
        != expected_context
    ):
        raise ValidationError("State decrypt lacks exact encryption context")

    preload_bucket = statement_by_sid(policy, f"ReadOnly{environment.title()}PreloadBucket")
    expected_preload_bucket = (
        f"arn:aws:s3:::english-{environment}-reading-assistant-preload-content-ACCOUNT_ID"
    )
    if preload_bucket.get("Resource") != expected_preload_bucket:
        raise ValidationError("Preload bucket read is not environment-bound")
    preload_actions = set(as_strings(preload_bucket.get("Action"), "Preload bucket Action"))
    if (
        "s3:GetEncryptionConfiguration" not in preload_actions
        or "s3:GetBucketEncryption" in preload_actions
    ):
        raise ValidationError(
            "Preload bucket encryption read must use s3:GetEncryptionConfiguration"
        )

    tagged_api = statement_by_sid(policy, f"ReadOnlyTagged{environment.title()}HttpApi")
    if tagged_api.get("Resource") != "arn:aws:apigateway:REGION::/apis/*" or tagged_api.get(
        "Condition", {}
    ).get("StringEquals") != {
        "aws:ResourceTag/Environment": environment,
        "aws:ResourceTag/Project": "english-reading-assistant",
    }:
        raise ValidationError(
            "HTTP API reads must require the provisioned Project and Environment tags"
        )

    plan_bucket_controls = statement_by_sid(policy, "InspectPrivatePlanBucketControls")
    if plan_bucket_controls.get("Resource") != "arn:aws:s3:::PRIVATE_PLAN_BUCKET" or set(
        as_strings(plan_bucket_controls.get("Action"), "Private plan bucket Action")
    ) != {"s3:GetEncryptionConfiguration", "s3:GetBucketVersioning"}:
        raise ValidationError(
            "Private plan bucket controls must use the exact encryption-read action"
        )

    write = statement_by_sid(
        policy,
        f"WriteOnlyRunDerivedEncrypted{environment.title()}PlanObject",
    )
    expected_objects = [
        f"arn:aws:s3:::PRIVATE_PLAN_BUCKET/terraform-plans/*/*/{environment}/*/tfplan",
        (
            "arn:aws:s3:::PRIVATE_PLAN_BUCKET/terraform-plans/"
            f"*/*/{environment}/*/reading-assistant-lambda.zip"
        ),
    ]
    if as_strings(write.get("Resource"), "Plan write Resource") != expected_objects:
        raise ValidationError("Plan write is not bound to the two exact run-derived objects")
    if write.get("Condition", {}).get("StringEquals") != {
        "s3:x-amz-server-side-encryption": "aws:kms",
        "s3:x-amz-server-side-encryption-aws-kms-key-id": "PLAN_KMS_KEY_ARN",
    }:
        raise ValidationError("Plan write lacks exact SSE-KMS requirements")
    plan_kms = statement_by_sid(
        policy,
        f"EncryptOnlyRunDerived{environment.title()}PlanObject",
    )
    if plan_kms.get("Resource") != "PLAN_KMS_KEY_ARN":
        raise ValidationError("Plan encryption is not bound to PLAN_KMS_KEY_ARN")
    if (
        plan_kms.get("Condition", {}).get("StringEquals")
        != {"kms:ViaService": "s3.REGION.amazonaws.com"}
        or plan_kms.get("Condition", {})
        .get("StringLike", {})
        .get("kms:EncryptionContext:aws:s3:arn")
        != expected_objects
    ):
        raise ValidationError("Plan encryption context is not bound to the two exact objects")

    deny = statement_by_sid(policy, DENY_SID)
    deny_actions = set(as_strings(deny.get("Action"), "Deny Action"))
    required_denials = {
        "iam:PassRole",
        "lambda:Update*",
        "s3:DeleteObject",
        "ssm:Put*",
    }
    if deny.get("Effect") != "Deny" or deny.get("Resource") != "*":
        raise ValidationError("Mutation deny must be account-wide")
    if not required_denials <= deny_actions:
        raise ValidationError("Mutation deny lacks required actions")


def validate_apply_plan_read_policy(environment: str) -> None:
    path = EXAMPLES / f"aws-apply-plan-read-policy-{environment}.json"
    raw = path.read_text(encoding="utf-8")
    policy = json.loads(raw)
    expected_objects = [
        f"arn:aws:s3:::PRIVATE_PLAN_BUCKET/terraform-plans/*/*/{environment}/*/tfplan",
        (
            "arn:aws:s3:::PRIVATE_PLAN_BUCKET/terraform-plans/"
            f"*/*/{environment}/*/reading-assistant-lambda.zip"
        ),
    ]
    other = "prod" if environment == "dev" else "dev"
    if f"/*/{other}/*/tfplan" in raw:
        raise ValidationError(f"{path.name} contains a cross-environment marker")
    read = statement_by_sid(policy, f"ReadOnlyVersioned{environment.title()}PlanObjects")
    if as_strings(read.get("Resource"), "Apply plan read Resource") != expected_objects or set(
        as_strings(read.get("Action"), "Apply plan read Action")
    ) != {"s3:GetObjectVersion", "s3:GetObjectVersionAttributes"}:
        raise ValidationError("Apply plan read is not versioned and environment-bound")
    decrypt = statement_by_sid(policy, f"DecryptOnly{environment.title()}PlanObjects")
    if decrypt.get("Action") != "kms:Decrypt" or decrypt.get("Resource") != "PLAN_KMS_KEY_ARN":
        raise ValidationError("Apply plan decrypt is not key-bound")
    condition = decrypt.get("Condition", {})
    if (
        condition.get("StringEquals", {}).get("kms:ViaService") != ("s3.REGION.amazonaws.com")
        or condition.get("StringLike", {}).get("kms:EncryptionContext:aws:s3:arn")
        != expected_objects
    ):
        raise ValidationError("Apply plan decrypt lacks exact S3 context")


def main() -> int:
    try:
        for unsafe_name in (
            "aws-apply-plan-read-policy.json",
            "aws-plan-role-policy.json",
        ):
            if (EXAMPLES / unsafe_name).exists():
                raise ValidationError(f"Unsafe generic example still exists: {unsafe_name}")
        for environment in ENVIRONMENTS:
            validate_policy(environment)
            validate_apply_plan_read_policy(environment)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        print(f"AWS plan policy validation failed: {error}", file=sys.stderr)
        return 1
    print("AWS dev and prod plan policies validated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
