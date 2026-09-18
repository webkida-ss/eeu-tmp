#!/usr/bin/env python3
"""Exact Terraform plan identity, redaction, and version verification helpers."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

try:
    from scripts.online_agent_policy import (
        GitHubApi,
        OnlinePolicyError,
        require_positive_ascii,
        require_sha,
        validate_default_branch_context,
        validate_pre_api_context,
    )
except ModuleNotFoundError:
    from online_agent_policy import (  # type: ignore[no-redef]
        GitHubApi,
        OnlinePolicyError,
        require_positive_ascii,
        require_sha,
        validate_default_branch_context,
        validate_pre_api_context,
    )

ENVIRONMENTS = {"dev", "prod"}
BUCKET_RE = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", re.ASCII)
PREFIX_RE = re.compile(r"[A-Za-z0-9!_.*'()/=-]+", re.ASCII)
VERSION_RE = re.compile(r"[A-Za-z0-9._=+-]{1,1024}", re.ASCII)
ROLE_ARN_RE = re.compile(r"arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]+", re.ASCII)
KMS_ARN_RE = re.compile(r"arn:aws:kms:[a-z0-9-]+:[0-9]{12}:key/[A-Za-z0-9-]+", re.ASCII)
SENSITIVE_KEY_RE = re.compile(r"(?i)(password|secret|token|api[_-]?key|credential|private[_-]?key)")
PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
URL_RE = re.compile(r"https?://[^\s\"']+", re.IGNORECASE)
QUOTED_ASSIGNMENT_RE = re.compile(
    r'(?P<prefix>\b(?P<key>[A-Za-z0-9_.-]+)\s*=\s*)"(?P<value>[^"]*)"'
)
MAX_PLAN_JSON_BYTES = 20 * 1024 * 1024
MAX_SCAN_ITEMS = 1_000
MAX_EMIT_RESOURCES = 32
MAX_EMIT_OUTPUTS = 100
MAX_PATHS_PER_CHANGE = 24
MAX_PATH_DEPTH = 16
MAX_SUMMARY_BYTES = 65_536
MISSING = object()
PRIVACY_BEARING_IDENTIFIER_RE = re.compile(
    r"(?i)(?:"
    r"(?:gh[pousr]|sk-(?:proj-)?|rk_live_|pk_live_)[A-Za-z0-9_-]{12,}"
    r"|(?:https?://|www\.)"
    r"|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    r"|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."
    r")"
)
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
CANONICAL_PACKAGE_DESTINATION = "backend/dist/reading-assistant-lambda.zip"
PRESENTATION_LIMITS_SHA256 = hashlib.sha256(
    json.dumps(
        {
            "max_emit_outputs": MAX_EMIT_OUTPUTS,
            "max_emit_resources": MAX_EMIT_RESOURCES,
            "max_path_depth": MAX_PATH_DEPTH,
            "max_paths_per_change": MAX_PATHS_PER_CHANGE,
            "max_scan_items": MAX_SCAN_ITEMS,
            "max_summary_bytes": MAX_SUMMARY_BYTES,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
).hexdigest()


class PolicyError(ValueError):
    """An exact-plan policy violation."""


@dataclass(frozen=True)
class PlanIdentity:
    bucket: str
    prefix: str
    run_id: str
    run_attempt: str
    environment: str
    commit_sha: str
    workflow_ref: str
    kms_key_arn: str
    apply_role_arn: str
    key: str

    @classmethod
    def create(
        cls,
        *,
        bucket: str,
        prefix: str,
        run_id: str,
        run_attempt: str,
        environment: str,
        commit_sha: str,
        workflow_ref: str,
        kms_key_arn: str,
        apply_role_arn: str,
    ) -> PlanIdentity:
        if not BUCKET_RE.fullmatch(bucket):
            raise PolicyError("Plan bucket name is invalid")
        if not prefix or not PREFIX_RE.fullmatch(prefix) or ".." in prefix.split("/"):
            raise PolicyError("Plan object prefix is invalid")
        require_positive_ascii(run_id, "Run ID")
        require_positive_ascii(run_attempt, "Run attempt")
        if environment not in ENVIRONMENTS:
            raise PolicyError("Environment must be dev or prod")
        require_sha(commit_sha, "Plan commit")
        if not re.fullmatch(
            r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/"
            r"\.github/workflows/deploy-reading-assistant\.yml@"
            r"refs/heads/[A-Za-z0-9._/-]+",
            workflow_ref,
        ):
            raise PolicyError("Deploy workflow ref must be the protected default branch")
        if not KMS_ARN_RE.fullmatch(kms_key_arn):
            raise PolicyError("Plan KMS key ARN is invalid")
        if not ROLE_ARN_RE.fullmatch(apply_role_arn):
            raise PolicyError("Apply role ARN is invalid")
        normalized_prefix = prefix.strip("/")
        key = f"{normalized_prefix}/{run_id}/{run_attempt}/{environment}/{commit_sha}/tfplan"
        return cls(
            bucket=bucket,
            prefix=normalized_prefix,
            run_id=run_id,
            run_attempt=run_attempt,
            environment=environment,
            commit_sha=commit_sha,
            workflow_ref=workflow_ref,
            kms_key_arn=kms_key_arn,
            apply_role_arn=apply_role_arn,
            key=key,
        )

    def metadata(self, digest: str) -> dict[str, str]:
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise PolicyError("Plan digest must be SHA-256")
        return {
            "commit-sha": self.commit_sha,
            "environment": self.environment,
            "run-id": self.run_id,
            "run-attempt": self.run_attempt,
            "plan-sha256": digest,
            "apply-role-sha256": hashlib.sha256(self.apply_role_arn.encode("utf-8")).hexdigest(),
            "workflow-ref-sha256": hashlib.sha256(self.workflow_ref.encode("utf-8")).hexdigest(),
        }


class PlanRecord(NamedTuple):
    bucket: str
    key: str
    version_id: str
    digest: str
    commit_sha: str
    environment: str
    run_id: str
    run_attempt: str
    apply_role_arn: str
    apply_role_digest: str


def validate_role_separation(plan_role_arn: str, apply_role_arn: str) -> None:
    if not ROLE_ARN_RE.fullmatch(plan_role_arn) or not ROLE_ARN_RE.fullmatch(apply_role_arn):
        raise PolicyError("Plan and apply role ARNs must be valid IAM role ARNs")
    if plan_role_arn == apply_role_arn:
        raise PolicyError("Plan and apply roles must be distinct")


def upload_exact_plan(store: Any, identity: PlanIdentity, body: bytes) -> PlanRecord:
    digest = hashlib.sha256(body).hexdigest()
    response = store.put_object(
        Bucket=identity.bucket,
        Key=identity.key,
        Body=body,
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=identity.kms_key_arn,
        Metadata=identity.metadata(digest),
    )
    version_id = response.get("VersionId")
    if not isinstance(version_id, str) or not VERSION_RE.fullmatch(version_id):
        raise PolicyError("Versioned plan upload did not return a valid VersionId")
    return PlanRecord(
        bucket=identity.bucket,
        key=identity.key,
        version_id=version_id,
        digest=digest,
        commit_sha=identity.commit_sha,
        environment=identity.environment,
        run_id=identity.run_id,
        run_attempt=identity.run_attempt,
        apply_role_arn=identity.apply_role_arn,
        apply_role_digest=hashlib.sha256(identity.apply_role_arn.encode("utf-8")).hexdigest(),
    )


def download_verified_plan(store: Any, identity: PlanIdentity, record: PlanRecord) -> bytes:
    if record.bucket != identity.bucket:
        raise PolicyError("Plan bucket does not match the configured bucket")
    if record.key != identity.key:
        raise PolicyError("Plan key is not the run-derived exact key")
    if (
        record.commit_sha != identity.commit_sha
        or record.environment != identity.environment
        or record.run_id != identity.run_id
        or record.run_attempt != identity.run_attempt
        or record.apply_role_arn != identity.apply_role_arn
    ):
        raise PolicyError("Plan record identity does not match this run")
    if (
        record.apply_role_digest
        != hashlib.sha256(identity.apply_role_arn.encode("utf-8")).hexdigest()
    ):
        raise PolicyError("Plan apply role digest does not match")
    if not VERSION_RE.fullmatch(record.version_id):
        raise PolicyError("Plan object version is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", record.digest):
        raise PolicyError("Plan digest is invalid")

    request = {
        "Bucket": identity.bucket,
        "Key": identity.key,
        "VersionId": record.version_id,
    }
    head = store.head_object(**request)
    if head.get("VersionId") != record.version_id:
        raise PolicyError("S3 returned a different plan version")
    if (
        head.get("ServerSideEncryption") != "aws:kms"
        or head.get("SSEKMSKeyId") != identity.kms_key_arn
    ):
        raise PolicyError("Plan object encryption metadata is invalid")
    if head.get("Metadata") != identity.metadata(record.digest):
        raise PolicyError("Plan object metadata does not match the expected identity")

    response = store.get_object(**request)
    if response.get("VersionId") != record.version_id:
        raise PolicyError("Downloaded plan version does not match")
    body = response.get("Body")
    if not isinstance(body, bytes):
        raise PolicyError("Downloaded plan body is invalid")
    if hashlib.sha256(body).hexdigest() != record.digest:
        raise PolicyError("Downloaded plan digest does not match")
    return body


def redact_plan_text(text: str) -> str:
    if PRIVATE_KEY_RE.search(text):
        raise PolicyError("Terraform plan contains a private key marker")

    def redact_assignment(match: re.Match[str]) -> str:
        key = match.group("key")
        value = match.group("value")
        if SENSITIVE_KEY_RE.search(key) or URL_RE.search(value):
            return f'{match.group("prefix")}"[REDACTED]"'
        return match.group(0)

    redacted = QUOTED_ASSIGNMENT_RE.sub(redact_assignment, text)
    redacted = URL_RE.sub("[REDACTED-URL]", redacted)
    return redacted


def safe_identifier(value: str, *, kind: str, maximum: int = 300) -> str:
    if not PRIVACY_BEARING_IDENTIFIER_RE.search(value) and re.fullmatch(
        rf"[A-Za-z0-9_.:/-]{{1,{maximum}}}", value
    ):
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"<{kind}:{digest}>"


def safe_address(address: Any) -> str:
    if not isinstance(address, str) or not address or len(address) > 1_000:
        raise PolicyError("Terraform resource address is invalid")
    redacted = re.sub(r'\["(?:[^"\\]|\\.)*"\]', '["<key>"]', address)
    if not re.fullmatch(r"[A-Za-z0-9_.\[\]\"<>:/-]{1,500}", redacted):
        return safe_identifier(address, kind="address")
    return redacted


def safe_actions(value: Any) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or not all(
            isinstance(action, str) and re.fullmatch(r"[a-z-]{1,32}", action) for action in value
        )
    ):
        raise PolicyError("Terraform resource actions are invalid")
    return list(value)


def collect_changed_paths(
    before: Any,
    after: Any,
    *,
    path: tuple[str | int, ...] = (),
    result: list[tuple[str | int, ...]],
    truncated: set[str],
) -> None:
    if len(result) >= MAX_PATHS_PER_CHANGE:
        truncated.add("changed_paths")
        return
    if len(path) >= MAX_PATH_DEPTH:
        if before != after:
            result.append(path)
            truncated.add("path_depth")
        return
    if isinstance(before, dict) and isinstance(after, dict):
        keys = sorted(set(before) | set(after))
        for key in keys:
            if len(result) >= MAX_PATHS_PER_CHANGE:
                truncated.add("changed_paths")
                break
            collect_changed_paths(
                before.get(key, MISSING),
                after.get(key, MISSING),
                path=(*path, key),
                result=result,
                truncated=truncated,
            )
        return
    if isinstance(before, list) and isinstance(after, list):
        for index in range(max(len(before), len(after))):
            if len(result) >= MAX_PATHS_PER_CHANGE:
                truncated.add("changed_paths")
                break
            collect_changed_paths(
                before[index] if index < len(before) else MISSING,
                after[index] if index < len(after) else MISSING,
                path=(*path, index),
                result=result,
                truncated=truncated,
            )
        return
    if before is MISSING or after is MISSING or before != after:
        result.append(path)


def render_path(path: tuple[str | int, ...] | list[Any]) -> str:
    if not path:
        return "$"
    rendered = ""
    for segment in path:
        if isinstance(segment, int) and segment >= 0:
            rendered += f"[{segment}]"
        elif isinstance(segment, str):
            safe_segment = safe_identifier(segment, kind="key", maximum=64)
            rendered += ("." if rendered else "") + safe_segment
        else:
            rendered += ("." if rendered else "") + "<segment>"
    return rendered[:500]


def path_is_sensitive(mask: Any, path: tuple[str | int, ...]) -> bool:
    current = mask
    if current is True:
        return True
    for segment in path:
        if current is True:
            return True
        if isinstance(segment, str) and isinstance(current, dict):
            current = current.get(segment, False)
        elif isinstance(segment, int) and isinstance(current, list):
            current = current[segment] if segment < len(current) else False
        else:
            return False
    return current is True or mask_has_sensitive(current)


def mask_has_sensitive(mask: Any) -> bool:
    if mask is True:
        return True
    if isinstance(mask, dict):
        return any(mask_has_sensitive(value) for value in mask.values())
    if isinstance(mask, list):
        return any(mask_has_sensitive(value) for value in mask)
    return False


def contains_public_cidr(value: Any) -> bool:
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, str) and current in {"0.0.0.0/0", "::/0"}:
            return True
        if isinstance(current, dict):
            pending.extend(current.values())
        elif isinstance(current, list):
            pending.extend(current)
    return False


def high_risk_categories(
    resource_type: str,
    changed_paths: list[str],
    before: Any,
    after: Any,
) -> list[str]:
    lowered_type = resource_type.lower()
    lowered_paths = " ".join(changed_paths).lower()
    categories: set[str] = set()
    if lowered_type.startswith("aws_iam_") or re.search(
        r"(?:^|[._])(role|policy|assume_role)", lowered_paths
    ):
        categories.add("identity_and_access")
    if (
        "security_group" in lowered_type
        or "network_acl" in lowered_type
        or re.search(r"(ingress|egress|cidr|source_ip)", lowered_paths)
    ):
        categories.add("network_security")
        if contains_public_cidr(after) and not contains_public_cidr(before):
            categories.add("public_network_exposure")
    if "lambda" in lowered_type and re.search(
        r"(role|environment|concurr|vpc_config|dead_letter)", lowered_paths
    ):
        categories.add("lambda_execution")
    if "apigateway" in lowered_type and re.search(
        r"(auth|authoriz|cors|origin|credential)", lowered_paths
    ):
        categories.add("api_auth_cors")
    if (
        "kms" in lowered_type
        or "s3_bucket_policy" in lowered_type
        or "s3_bucket_public_access" in lowered_type
        or re.search(r"(kms|encrypt|public|acl|bucket_policy)", lowered_paths)
    ):
        categories.add("encryption_and_key_controls")
    if "s3_bucket_public_access" in lowered_type or re.search(
        r"(block_public|ignore_public|restrict_public)", lowered_paths
    ):
        categories.add("storage_public_access")
    return sorted(categories)


def collect_complete_changed_paths(
    before: Any,
    after: Any,
) -> list[tuple[str | int, ...]]:
    result: list[tuple[str | int, ...]] = []
    pending: list[tuple[Any, Any, tuple[str | int, ...]]] = [(before, after, ())]
    while pending:
        current_before, current_after, path = pending.pop()
        if isinstance(current_before, dict) and isinstance(current_after, dict):
            keys = sorted(set(current_before) | set(current_after), reverse=True)
            pending.extend(
                (
                    current_before.get(key, MISSING),
                    current_after.get(key, MISSING),
                    (*path, key),
                )
                for key in keys
            )
        elif isinstance(current_before, list) and isinstance(current_after, list):
            pending.extend(
                (
                    current_before[index] if index < len(current_before) else MISSING,
                    current_after[index] if index < len(current_after) else MISSING,
                    (*path, index),
                )
                for index in reversed(range(max(len(current_before), len(current_after))))
            )
        elif (
            current_before is MISSING or current_after is MISSING or current_before != current_after
        ):
            result.append(path)
    return result


def action_counts(items: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("change"), dict):
            raise PolicyError("Terraform resource change must be an object")
        key = "+".join(safe_actions(item["change"].get("actions")))
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def classify_plan(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise PolicyError("Terraform plan JSON must be an object")
    resources = plan.get("resource_changes", [])
    drift = plan.get("resource_drift", [])
    outputs = plan.get("output_changes", {})
    if (
        not isinstance(resources, list)
        or not isinstance(drift, list)
        or not isinstance(outputs, dict)
    ):
        raise PolicyError("Terraform plan change collections are invalid")

    category_counts: dict[str, int] = {}
    high_risk_resource_count = 0
    high_risk_drift_count = 0
    replacement_path_count = 0
    sensitive_path_count = 0
    classified_items: list[dict[str, Any]] = []
    for collection_name, items in (
        ("resource", resources),
        ("drift", drift),
    ):
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("change"), dict):
                raise PolicyError("Terraform resource change must be an object")
            change = item["change"]
            resource_type = item.get("type", "unknown")
            if not isinstance(resource_type, str):
                resource_type = "unknown"
            paths = collect_complete_changed_paths(
                change.get("before", MISSING),
                change.get("after", MISSING),
            )
            raw_path_text = [".".join(str(segment) for segment in path) for path in paths]
            categories = high_risk_categories(
                resource_type,
                raw_path_text,
                change.get("before"),
                change.get("after"),
            )
            for category in categories:
                category_counts[category] = category_counts.get(category, 0) + 1
            if categories:
                if collection_name == "resource":
                    high_risk_resource_count += 1
                else:
                    high_risk_drift_count += 1
            before_sensitive = change.get("before_sensitive", False)
            after_sensitive = change.get("after_sensitive", False)
            sensitive_flags = [
                path_is_sensitive(before_sensitive, path)
                or path_is_sensitive(after_sensitive, path)
                for path in paths
            ]
            sensitive_path_count += sum(sensitive_flags)
            replace_paths = change.get("replace_paths", [])
            if not isinstance(replace_paths, list) or not all(
                isinstance(path, list) for path in replace_paths
            ):
                raise PolicyError("Terraform replace_paths must be an array of paths")
            replacement_path_count += len(replace_paths)
            classified_items.append(
                {
                    "actions": safe_actions(change.get("actions")),
                    "address_sha256": hashlib.sha256(
                        str(item.get("address", "")).encode("utf-8")
                    ).hexdigest(),
                    "categories": categories,
                    "collection": collection_name,
                    "path_sha256": [
                        hashlib.sha256(
                            json.dumps(path, separators=(",", ":")).encode("utf-8")
                        ).hexdigest()
                        for path in paths
                    ],
                    "replacement_path_sha256": [
                        hashlib.sha256(
                            json.dumps(path, separators=(",", ":")).encode("utf-8")
                        ).hexdigest()
                        for path in replace_paths
                    ],
                    "resource_type": safe_identifier(
                        resource_type, kind="resource-type", maximum=100
                    ),
                    "sensitive_flags": sensitive_flags,
                }
            )

    output_action_counts: dict[str, int] = {}
    sensitive_output_count = 0
    classified_outputs: list[dict[str, Any]] = []
    for name, change in sorted(outputs.items()):
        if not isinstance(name, str) or not isinstance(change, dict):
            raise PolicyError("Terraform output change is invalid")
        actions = safe_actions(change.get("actions"))
        action_key = "+".join(actions)
        output_action_counts[action_key] = output_action_counts.get(action_key, 0) + 1
        sensitive = mask_has_sensitive(change.get("before_sensitive", False)) or (
            mask_has_sensitive(change.get("after_sensitive", False))
        )
        sensitive_output_count += int(sensitive)
        classified_outputs.append(
            {
                "actions": actions,
                "name_sha256": hashlib.sha256(name.encode("utf-8")).hexdigest(),
                "sensitive": sensitive,
            }
        )

    public = {
        "drift_action_counts": action_counts(drift),
        "drift_count": len(drift),
        "high_risk_categories": sorted(category_counts),
        "high_risk_category_counts": dict(sorted(category_counts.items())),
        "high_risk_drift_count": high_risk_drift_count,
        "high_risk_resource_count": high_risk_resource_count,
        "output_action_counts": dict(sorted(output_action_counts.items())),
        "output_count": len(outputs),
        "replacement_path_count": replacement_path_count,
        "resource_action_counts": action_counts(resources),
        "resource_count": len(resources),
        "sensitive_output_count": sensitive_output_count,
        "sensitive_path_count": sensitive_path_count,
    }
    digest_input = {
        **public,
        "classified_items": classified_items,
        "classified_outputs": classified_outputs,
    }
    return {
        **public,
        "classification_sha256": hashlib.sha256(
            json.dumps(digest_input, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "schema_version": 1,
    }


def validate_classification(
    value: Any,
    *,
    require_review_attestation: bool = False,
) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise PolicyError("Plan classification schema is invalid")
    digest = value.get("classification_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise PolicyError("Plan classification digest is invalid")
    for key in CLASSIFICATION_COUNT_KEYS:
        count = value.get(key)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise PolicyError(f"Plan classification {key} is invalid")
    if require_review_attestation:
        if value.get("presentation_bounded") is not True:
            raise PolicyError("Plan classification lacks bounded-review attestation")
        if value.get("presentation_limits_sha256") != PRESENTATION_LIMITS_SHA256:
            raise PolicyError("Plan classification presentation limits do not match this code")
        summary_digest = value.get("review_summary_sha256")
        if not isinstance(summary_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", summary_digest):
            raise PolicyError("Plan review summary digest is invalid")
    return value


def classification_from_args(args: argparse.Namespace) -> dict[str, Any]:
    value: dict[str, Any] = {
        "classification_sha256": args.classification_sha256,
        "presentation_bounded": True,
        "presentation_limits_sha256": args.presentation_limits_sha256,
        "review_summary_sha256": args.review_summary_sha256,
        "schema_version": 1,
    }
    for key in CLASSIFICATION_COUNT_KEYS:
        raw = getattr(args, key)
        if not isinstance(raw, str) or not re.fullmatch(r"0|[1-9][0-9]*", raw):
            raise PolicyError(f"Plan classification {key} must be a canonical non-negative integer")
        value[key] = int(raw)
    return validate_classification(value, require_review_attestation=True)


def classification_metadata(classification: dict[str, Any]) -> dict[str, str]:
    validated = validate_classification(classification, require_review_attestation=True)
    metadata = {
        "classification-sha256": validated["classification_sha256"],
        "presentation-limits-sha256": validated["presentation_limits_sha256"],
        "review-summary-sha256": validated["review_summary_sha256"],
    }
    metadata.update(
        {key.replace("_", "-"): str(validated[key]) for key in CLASSIFICATION_COUNT_KEYS}
    )
    return metadata


def deployment_metadata(
    identity: PlanIdentity,
    plan_digest: str,
    classification: dict[str, Any],
) -> dict[str, str]:
    return {
        **identity.metadata(plan_digest),
        **classification_metadata(classification),
    }


def package_key(identity: PlanIdentity) -> str:
    return f"{identity.key.rsplit('/', 1)[0]}/reading-assistant-lambda.zip"


def package_metadata(
    identity: PlanIdentity,
    plan_digest: str,
    package_digest: str,
    classification: dict[str, Any],
) -> dict[str, str]:
    if not re.fullmatch(r"[0-9a-f]{64}", package_digest):
        raise PolicyError("Lambda package digest is invalid")
    return {
        **deployment_metadata(identity, plan_digest, classification),
        "package-sha256": package_digest,
    }


def validate_package_binding(value: Any, *, plan_key: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {
        "destination",
        "digest",
        "key",
        "version_id",
    }:
        raise PolicyError("Package record binding is invalid")
    expected_key = f"{plan_key.rsplit('/', 1)[0]}/reading-assistant-lambda.zip"
    if value["key"] != expected_key:
        raise PolicyError("Package key is not the plan-derived exact key")
    if value["destination"] != CANONICAL_PACKAGE_DESTINATION:
        raise PolicyError("Package destination is not canonical")
    if not isinstance(value["version_id"], str) or not VERSION_RE.fullmatch(value["version_id"]):
        raise PolicyError("Package version is invalid")
    if not isinstance(value["digest"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["digest"]):
        raise PolicyError("Lambda package digest is invalid")
    return dict(value)


def package_binding_from_args(args: argparse.Namespace) -> dict[str, str] | None:
    fields = {
        "key": args.package_key,
        "version_id": args.package_version_id,
        "digest": args.package_digest,
        "destination": args.package_destination,
    }
    supplied = [value is not None for value in fields.values()]
    if any(supplied) and not all(supplied):
        raise PolicyError("Package record binding is incomplete")
    if not any(supplied):
        if args.require_package:
            raise PolicyError("Package record binding is required")
        return None
    return validate_package_binding(fields, plan_key=args.key)


def verify_lambda_package(plan: Any, package_file: Path, package_digest: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", package_digest):
        raise PolicyError("Lambda package digest is invalid")
    if not package_file.is_file():
        raise PolicyError("Lambda package is missing from the canonical destination")
    if hashlib.sha256(package_file.read_bytes()).hexdigest() != package_digest:
        raise PolicyError("Lambda package digest does not match")
    expected_hash = base64.b64encode(bytes.fromhex(package_digest)).decode("ascii")
    resources = plan.get("resource_changes") if isinstance(plan, dict) else None
    if not isinstance(resources, list):
        raise PolicyError("Terraform plan resource changes are invalid")
    lambda_hashes = [
        item.get("change", {}).get("after", {}).get("source_code_hash")
        for item in resources
        if isinstance(item, dict) and item.get("type") == "aws_lambda_function"
    ]
    if len(lambda_hashes) != 2 or any(value != expected_hash for value in lambda_hashes):
        raise PolicyError("Approved plan Lambda source hashes do not match the package")


def summarize_resource_change(
    item: Any,
    *,
    truncation_reasons: set[str],
) -> dict[str, Any]:
    if not isinstance(item, dict) or not isinstance(item.get("change"), dict):
        raise PolicyError("Terraform resource change must be an object")
    change = item["change"]
    actions = safe_actions(change.get("actions"))
    resource_type_raw = item.get("type", "unknown")
    if not isinstance(resource_type_raw, str):
        resource_type_raw = "unknown"
    resource_type = safe_identifier(resource_type_raw, kind="resource-type", maximum=100)
    raw_paths: list[tuple[str | int, ...]] = []
    collect_changed_paths(
        change.get("before", MISSING),
        change.get("after", MISSING),
        result=raw_paths,
        truncated=truncation_reasons,
    )
    before_sensitive = change.get("before_sensitive", False)
    after_sensitive = change.get("after_sensitive", False)
    changed_paths = [
        {
            "path": render_path(path),
            "sensitive": path_is_sensitive(before_sensitive, path)
            or path_is_sensitive(after_sensitive, path),
        }
        for path in raw_paths
    ]
    changed_paths.sort(key=lambda entry: (entry["path"], entry["sensitive"]))
    replace_paths_raw = change.get("replace_paths", [])
    if not isinstance(replace_paths_raw, list):
        raise PolicyError("Terraform replace_paths must be an array")
    replace_paths = sorted(
        {
            render_path(path)
            for path in replace_paths_raw[:MAX_PATHS_PER_CHANGE]
            if isinstance(path, list)
        }
    )
    if len(replace_paths_raw) > MAX_PATHS_PER_CHANGE:
        truncation_reasons.add("replace_paths")
    action_reason = item.get("action_reason")
    replacement_reason = None
    if isinstance(action_reason, str) and re.fullmatch(r"[a-z0-9_-]{1,100}", action_reason):
        replacement_reason = action_reason
    categories = high_risk_categories(
        resource_type_raw,
        [entry["path"] for entry in changed_paths],
        change.get("before"),
        change.get("after"),
    )
    return {
        "actions": actions,
        "address": safe_address(item.get("address")),
        "changed_paths": changed_paths,
        "high_risk": bool(categories),
        "high_risk_categories": categories,
        "replace_paths": replace_paths,
        "replacement_reason": replacement_reason,
        "resource_type": resource_type,
    }


def trim_summary(summary: dict[str, Any], truncation_reasons: set[str]) -> None:
    def encoded_size() -> int:
        summary["truncation"]["reasons"] = sorted(truncation_reasons)
        summary["truncation"]["truncated"] = bool(truncation_reasons)
        return len((json.dumps(summary, indent=2, sort_keys=True) + "\n").encode("utf-8"))

    while encoded_size() > MAX_SUMMARY_BYTES:
        trimmed = False
        for collection_name in ("resource_changes", "resource_drift"):
            collection = summary[collection_name]
            for item in reversed(collection):
                if item["changed_paths"]:
                    item["changed_paths"].pop()
                    trimmed = True
                    break
            if trimmed:
                break
        if not trimmed:
            for collection_name in ("resource_changes", "resource_drift", "output_changes"):
                if summary[collection_name]:
                    summary[collection_name].pop()
                    trimmed = True
                    break
        if not trimmed:
            raise PolicyError("Terraform plan summary cannot fit the output bound")
        truncation_reasons.add("summary_size")


def summarize_plan(plan: Any, *, source_sha256: str | None = None) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise PolicyError("Terraform plan JSON must be an object")
    if source_sha256 is None:
        source_sha256 = hashlib.sha256(
            json.dumps(plan, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
    classification = classify_plan(plan)
    truncation_reasons: set[str] = set()
    changes = plan.get("resource_changes", [])
    drift = plan.get("resource_drift", [])
    outputs = plan.get("output_changes", {})
    if (
        not isinstance(changes, list)
        or not isinstance(drift, list)
        or not isinstance(outputs, dict)
    ):
        raise PolicyError("Terraform plan change collections are invalid")

    scanned_changes = changes[:MAX_SCAN_ITEMS]
    if len(changes) > MAX_SCAN_ITEMS:
        truncation_reasons.add("resource_scan_count")
    resource_changes: list[dict[str, Any]] = []
    for index, item in enumerate(scanned_changes):
        summarized = summarize_resource_change(item, truncation_reasons=truncation_reasons)
        if index < MAX_EMIT_RESOURCES:
            resource_changes.append(summarized)
        else:
            truncation_reasons.add("resource_output_count")

    resource_drift: list[dict[str, Any]] = []
    for index, item in enumerate(drift[:MAX_SCAN_ITEMS]):
        summarized = summarize_resource_change(item, truncation_reasons=truncation_reasons)
        if index < MAX_EMIT_RESOURCES:
            resource_drift.append(summarized)
        else:
            truncation_reasons.add("drift_output_count")
    if len(drift) > MAX_SCAN_ITEMS:
        truncation_reasons.add("drift_scan_count")

    output_changes: list[dict[str, Any]] = []
    for index, (name, change) in enumerate(sorted(outputs.items())):
        if index >= MAX_EMIT_OUTPUTS:
            truncation_reasons.add("output_count")
            break
        if not isinstance(name, str) or not isinstance(change, dict):
            raise PolicyError("Terraform output change is invalid")
        output_changes.append(
            {
                "actions": safe_actions(change.get("actions")),
                "name": safe_identifier(name, kind="output", maximum=100),
                "sensitive": mask_has_sensitive(change.get("before_sensitive", False))
                or mask_has_sensitive(change.get("after_sensitive", False)),
            }
        )

    aggregate_categories = classification["high_risk_categories"]
    summary: dict[str, Any] = {
        "action_counts": classification["resource_action_counts"],
        "classification": classification,
        "high_risk": bool(aggregate_categories),
        "high_risk_categories": aggregate_categories,
        "output_changes": output_changes,
        "resource_changes": sorted(
            resource_changes, key=lambda value: (value["address"], value["actions"])
        ),
        "resource_drift": sorted(
            resource_drift, key=lambda value: (value["address"], value["actions"])
        ),
        "total_output_changes": len(outputs),
        "total_resource_changes": len(changes),
        "total_resource_drift": len(drift),
        "truncation": {
            "reasons": [],
            "source_sha256": source_sha256,
            "truncated": False,
        },
    }
    trim_summary(summary, truncation_reasons)
    summary["truncation"]["reasons"] = sorted(truncation_reasons)
    summary["truncation"]["truncated"] = bool(truncation_reasons)
    if truncation_reasons:
        reasons = ",".join(sorted(truncation_reasons))
        raise PolicyError(
            "Terraform plan review truncation is forbidden "
            f"({reasons}); split the change or revise reviewed limits in code and PR"
        )
    return summary


def plan_record_digest(
    *,
    bucket: str,
    key: str,
    version_id: str,
    digest: str,
    commit_sha: str,
    environment: str,
    run_id: str,
    run_attempt: str,
    kms_key_arn: str,
    apply_role_arn: str,
    apply_role_digest: str,
    classification: dict[str, Any],
    package: dict[str, str] | None = None,
) -> str:
    validated_classification = validate_classification(
        classification, require_review_attestation=True
    )
    binding = {
        "apply_role_arn": apply_role_arn,
        "apply_role_digest": apply_role_digest,
        "bucket": bucket,
        "commit_sha": commit_sha,
        "digest": digest,
        "environment": environment,
        "key": key,
        "kms_key_arn": kms_key_arn,
        "run_attempt": run_attempt,
        "run_id": run_id,
        "version_id": version_id,
        "classification_sha256": validated_classification["classification_sha256"],
        "presentation_limits_sha256": validated_classification["presentation_limits_sha256"],
        "review_summary_sha256": validated_classification["review_summary_sha256"],
    }
    if package is not None:
        binding["package"] = validate_package_binding(package, plan_key=key)
    binding.update({key: validated_classification[key] for key in CLASSIFICATION_COUNT_KEYS})
    return hashlib.sha256(
        json.dumps(binding, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def write_github_outputs(path: Path, values: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as output:
        for key, value in values.items():
            if "\n" in value or "\r" in value:
                raise PolicyError(f"GitHub output {key} contains a newline")
            output.write(f"{key}={value}\n")


def identity_from_args(args: argparse.Namespace) -> PlanIdentity:
    return PlanIdentity.create(
        bucket=args.bucket,
        prefix=args.prefix,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        environment=args.environment,
        commit_sha=args.commit_sha,
        workflow_ref=args.workflow_ref,
        kms_key_arn=args.kms_key_arn,
        apply_role_arn=args.apply_role_arn,
    )


def plan_record_from_args(args: argparse.Namespace) -> PlanRecord:
    return PlanRecord(
        bucket=args.bucket,
        key=args.key,
        version_id=args.version_id,
        digest=args.digest,
        commit_sha=args.commit_sha,
        environment=args.environment,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        apply_role_arn=args.apply_role_arn,
        apply_role_digest=args.apply_role_digest,
    )


def validate_deploy_gate(args: argparse.Namespace) -> tuple[str, str]:
    validate_pre_api_context(
        trusted_actor_ids=args.trusted_actor_ids,
        actor_id=args.actor_id,
        repository=args.repository,
        issue_number=None,
        git_ref=args.git_ref,
        workflow_ref=args.workflow_ref,
        workflow_path=".github/workflows/deploy-reading-assistant.yml",
        checked_out_sha=args.checked_out_sha,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        ref_protected=args.ref_protected,
    )
    validate_role_separation(args.plan_role_arn, args.apply_role_arn)
    PlanIdentity.create(
        bucket=args.bucket,
        prefix=args.prefix,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        environment=args.environment,
        commit_sha=args.checked_out_sha,
        workflow_ref=args.workflow_ref,
        kms_key_arn=args.kms_key_arn,
        apply_role_arn=args.apply_role_arn,
    )
    if args.operation not in {"plan", "apply"}:
        raise PolicyError("Operation must be plan or apply")
    expected_confirmation = f"APPLY-PROD-{args.checked_out_sha}"
    if args.environment == "prod" and args.operation == "apply":
        if args.production_confirmation != expected_confirmation:
            raise PolicyError(f"Production apply confirmation must equal {expected_confirmation}")
    elif args.production_confirmation:
        raise PolicyError("Production confirmation is allowed only for production apply")

    api = GitHubApi(
        token=os.environ.get("GITHUB_TOKEN", ""),
        api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
    )
    return validate_default_branch_context(
        api_get=api.get,
        repository=args.repository,
        git_ref=args.git_ref,
        workflow_ref=args.workflow_ref,
        workflow_path=".github/workflows/deploy-reading-assistant.yml",
        checked_out_sha=args.checked_out_sha,
    )


def add_identity_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--workflow-ref", required=True)
    parser.add_argument("--kms-key-arn", required=True)
    parser.add_argument("--apply-role-arn", required=True)


def add_classification_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--classification-sha256", required=True)
    parser.add_argument("--presentation-limits-sha256", required=True)
    parser.add_argument("--review-summary-sha256", required=True)
    for key in CLASSIFICATION_COUNT_KEYS:
        parser.add_argument(f"--{key.replace('_', '-')}", required=True)


def add_package_binding_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--require-package", action="store_true")
    parser.add_argument("--package-key")
    parser.add_argument("--package-version-id")
    parser.add_argument("--package-digest")
    parser.add_argument("--package-destination")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    gate = commands.add_parser("gate-deploy")
    gate.add_argument("--trusted-actor-ids", required=True)
    gate.add_argument("--actor-id", required=True)
    gate.add_argument("--repository", required=True)
    gate.add_argument("--git-ref", required=True)
    gate.add_argument("--workflow-ref", required=True)
    gate.add_argument("--checked-out-sha", required=True)
    gate.add_argument("--run-id", required=True)
    gate.add_argument("--run-attempt", required=True)
    gate.add_argument("--ref-protected", required=True)
    gate.add_argument("--environment", required=True)
    gate.add_argument("--operation", required=True)
    gate.add_argument("--production-confirmation", required=True)
    gate.add_argument("--plan-role-arn", required=True)
    gate.add_argument("--apply-role-arn", required=True)
    gate.add_argument("--bucket", required=True)
    gate.add_argument("--prefix", required=True)
    gate.add_argument("--kms-key-arn", required=True)
    gate.add_argument("--github-output", required=True, type=Path)

    redact = commands.add_parser("redact")
    redact.add_argument("--input", required=True, type=Path)
    redact.add_argument("--output", required=True, type=Path)

    summarize = commands.add_parser("summarize-plan")
    summarize.add_argument("--input", required=True, type=Path)
    summarize.add_argument("--output", required=True, type=Path)
    summarize.add_argument("--classification-output", type=Path)
    summarize.add_argument("--github-output", type=Path)

    classify = commands.add_parser("classify-plan")
    classify.add_argument("--input", required=True, type=Path)
    classify.add_argument("--output", required=True, type=Path)

    failure = commands.add_parser("summarize-failure")
    failure.add_argument("--input", required=True, type=Path)
    failure.add_argument(
        "--command",
        dest="failed_command",
        required=True,
        choices=(
            "terraform-init",
            "terraform-plan",
            "terraform-show",
            "terraform-apply",
        ),
    )

    describe = commands.add_parser("describe")
    add_identity_args(describe)
    describe.add_argument("--plan-file", required=True, type=Path)
    describe.add_argument("--package-file", type=Path)
    describe.add_argument("--classification", required=True, type=Path)
    describe.add_argument("--output", required=True, type=Path)
    describe.add_argument("--github-output", type=Path)

    record = commands.add_parser("record-version")
    record.add_argument("--descriptor", required=True, type=Path)
    record.add_argument("--upload-response", required=True, type=Path)
    record.add_argument("--package-upload-response", type=Path)
    record.add_argument("--output", required=True, type=Path)
    record.add_argument("--github-output", required=True, type=Path)

    verify = commands.add_parser("verify-download")
    add_identity_args(verify)
    verify.add_argument("--key", required=True)
    verify.add_argument("--version-id", required=True)
    verify.add_argument("--digest", required=True)
    verify.add_argument("--apply-role-digest", required=True)
    verify.add_argument("--record-digest", required=True)
    add_classification_args(verify)
    add_package_binding_args(verify)
    verify.add_argument("--head-response", required=True, type=Path)
    verify.add_argument("--get-response", required=True, type=Path)
    verify.add_argument("--plan-file", required=True, type=Path)
    verify.add_argument("--package-head-response", type=Path)
    verify.add_argument("--package-get-response", type=Path)
    verify.add_argument("--package-file", type=Path)

    assert_record = commands.add_parser("assert-record")
    add_identity_args(assert_record)
    assert_record.add_argument("--key", required=True)
    assert_record.add_argument("--version-id", required=True)
    assert_record.add_argument("--digest", required=True)
    assert_record.add_argument("--apply-role-digest", required=True)
    assert_record.add_argument("--record-digest", required=True)
    add_classification_args(assert_record)
    add_package_binding_args(assert_record)

    verify_classification = commands.add_parser("verify-classification")
    verify_classification.add_argument("--input", required=True, type=Path)
    add_classification_args(verify_classification)

    verify_package = commands.add_parser("verify-lambda-package")
    verify_package.add_argument("--plan", required=True, type=Path)
    verify_package.add_argument("--package-file", required=True, type=Path)
    verify_package.add_argument("--package-digest", required=True)

    storage = commands.add_parser("verify-storage")
    storage.add_argument("--versioning-response", required=True, type=Path)
    storage.add_argument("--encryption-response", required=True, type=Path)
    storage.add_argument("--kms-key-arn", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "gate-deploy":
            default_branch, commit_sha = validate_deploy_gate(args)
            write_github_outputs(
                args.github_output,
                {
                    "default_branch": default_branch,
                    "commit_sha": commit_sha,
                    "plan_role_arn": args.plan_role_arn,
                    "plan_role_digest": hashlib.sha256(
                        args.plan_role_arn.encode("utf-8")
                    ).hexdigest(),
                    "apply_role_arn": args.apply_role_arn,
                    "apply_role_digest": hashlib.sha256(
                        args.apply_role_arn.encode("utf-8")
                    ).hexdigest(),
                },
            )
        elif args.command == "redact":
            redacted = redact_plan_text(args.input.read_text(encoding="utf-8"))
            args.output.write_text(redacted, encoding="utf-8")
            print(redacted, end="")
        elif args.command == "summarize-plan":
            raw_plan = args.input.read_bytes()
            if len(raw_plan) > MAX_PLAN_JSON_BYTES:
                raise PolicyError("Terraform plan JSON exceeds the private input bound")
            summary = summarize_plan(
                json.loads(raw_plan),
                source_sha256=hashlib.sha256(raw_plan).hexdigest(),
            )
            rendered = json.dumps(summary, indent=2, sort_keys=True) + "\n"
            args.output.write_text(rendered, encoding="utf-8")
            classification = {
                **summary["classification"],
                "presentation_bounded": True,
                "presentation_limits_sha256": PRESENTATION_LIMITS_SHA256,
                "review_summary_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
            }
            if args.classification_output:
                args.classification_output.write_text(
                    json.dumps(classification, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            if args.github_output:
                classification_outputs = {
                    key: str(classification[key]) for key in CLASSIFICATION_COUNT_KEYS
                }
                write_github_outputs(
                    args.github_output,
                    {
                        "classification_sha256": classification["classification_sha256"],
                        "presentation_limits_sha256": classification["presentation_limits_sha256"],
                        "review_summary_sha256": classification["review_summary_sha256"],
                        **classification_outputs,
                    },
                )
            print(rendered, end="")
        elif args.command == "classify-plan":
            raw_plan = args.input.read_bytes()
            if len(raw_plan) > MAX_PLAN_JSON_BYTES:
                raise PolicyError("Terraform plan JSON exceeds the private input bound")
            classification = classify_plan(json.loads(raw_plan))
            args.output.write_text(
                json.dumps(classification, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        elif args.command == "summarize-failure":
            args.input.stat()
            print(f"{args.failed_command} failed; details withheld by plan privacy policy.")
        elif args.command == "describe":
            identity = identity_from_args(args)
            digest = hashlib.sha256(args.plan_file.read_bytes()).hexdigest()
            classification = validate_classification(
                json.loads(args.classification.read_text(encoding="utf-8")),
                require_review_attestation=True,
            )
            descriptor = {
                "bucket": identity.bucket,
                "key": identity.key,
                "digest": digest,
                "commit_sha": identity.commit_sha,
                "environment": identity.environment,
                "run_id": identity.run_id,
                "run_attempt": identity.run_attempt,
                "kms_key_arn": identity.kms_key_arn,
                "apply_role_arn": identity.apply_role_arn,
                "apply_role_digest": hashlib.sha256(
                    identity.apply_role_arn.encode("utf-8")
                ).hexdigest(),
                "classification": classification,
                "metadata": deployment_metadata(identity, digest, classification),
            }
            if args.package_file:
                package_digest = hashlib.sha256(args.package_file.read_bytes()).hexdigest()
                descriptor["package"] = {
                    "destination": CANONICAL_PACKAGE_DESTINATION,
                    "digest": package_digest,
                    "key": package_key(identity),
                }
            args.output.write_text(
                json.dumps(descriptor, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            if args.github_output:
                write_github_outputs(
                    args.github_output,
                    {
                        "plan_key": identity.key,
                        "plan_digest": digest,
                        "workflow_ref_digest": identity.metadata(digest)["workflow-ref-sha256"],
                        "apply_role_arn": identity.apply_role_arn,
                        "apply_role_digest": descriptor["apply_role_digest"],
                        "classification_sha256": classification["classification_sha256"],
                        "presentation_limits_sha256": classification["presentation_limits_sha256"],
                        "review_summary_sha256": classification["review_summary_sha256"],
                        **{key: str(classification[key]) for key in CLASSIFICATION_COUNT_KEYS},
                        **(
                            {
                                "package_key": descriptor["package"]["key"],
                                "package_digest": descriptor["package"]["digest"],
                            }
                            if args.package_file
                            else {}
                        ),
                    },
                )
        elif args.command == "record-version":
            descriptor = json.loads(args.descriptor.read_text(encoding="utf-8"))
            upload = json.loads(args.upload_response.read_text(encoding="utf-8"))
            version_id = upload.get("VersionId")
            if not isinstance(version_id, str) or not VERSION_RE.fullmatch(version_id):
                raise PolicyError("Versioned upload did not return a valid VersionId")
            if (
                descriptor.get("apply_role_digest")
                != hashlib.sha256(descriptor["apply_role_arn"].encode("utf-8")).hexdigest()
            ):
                raise PolicyError("Descriptor apply role binding is invalid")
            classification = validate_classification(
                descriptor.get("classification"), require_review_attestation=True
            )
            package: dict[str, str] | None = None
            raw_package = descriptor.get("package")
            if raw_package is not None:
                if not isinstance(raw_package, dict) or set(raw_package) != {
                    "destination",
                    "digest",
                    "key",
                }:
                    raise PolicyError("Package descriptor binding is invalid")
                if args.package_upload_response is None:
                    raise PolicyError("Package descriptor requires an upload response")
                package_upload = json.loads(
                    args.package_upload_response.read_text(encoding="utf-8")
                )
                package_version_id = package_upload.get("VersionId")
                if not isinstance(package_version_id, str) or not VERSION_RE.fullmatch(
                    package_version_id
                ):
                    raise PolicyError("Package upload did not return a valid VersionId")
                package = validate_package_binding(
                    {**raw_package, "version_id": package_version_id},
                    plan_key=descriptor["key"],
                )
            elif args.package_upload_response is not None:
                raise PolicyError("Package upload response has no package descriptor")
            record = {**descriptor, "version_id": version_id}
            if package is not None:
                record["package"] = package
            record["record_digest"] = plan_record_digest(
                bucket=descriptor["bucket"],
                key=descriptor["key"],
                version_id=version_id,
                digest=descriptor["digest"],
                commit_sha=descriptor["commit_sha"],
                environment=descriptor["environment"],
                run_id=descriptor["run_id"],
                run_attempt=descriptor["run_attempt"],
                kms_key_arn=descriptor["kms_key_arn"],
                apply_role_arn=descriptor["apply_role_arn"],
                apply_role_digest=descriptor["apply_role_digest"],
                classification=classification,
                package=package,
            )
            args.output.write_text(
                json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            write_github_outputs(
                args.github_output,
                {
                    "plan_key": descriptor["key"],
                    "plan_version_id": version_id,
                    "plan_digest": descriptor["digest"],
                    "plan_bucket": descriptor["bucket"],
                    "plan_kms_key_arn": descriptor["kms_key_arn"],
                    "apply_role_arn": descriptor["apply_role_arn"],
                    "apply_role_digest": descriptor["apply_role_digest"],
                    "plan_record_digest": record["record_digest"],
                    "classification_sha256": classification["classification_sha256"],
                    "presentation_limits_sha256": classification["presentation_limits_sha256"],
                    "review_summary_sha256": classification["review_summary_sha256"],
                    **{key: str(classification[key]) for key in CLASSIFICATION_COUNT_KEYS},
                    **(
                        {
                            "package_key": package["key"],
                            "package_version_id": package["version_id"],
                            "package_digest": package["digest"],
                            "package_destination": package["destination"],
                        }
                        if package is not None
                        else {}
                    ),
                },
            )
        elif args.command == "verify-download":
            identity = identity_from_args(args)
            classification = classification_from_args(args)
            package = package_binding_from_args(args)
            record = PlanRecord(
                bucket=identity.bucket,
                key=args.key,
                version_id=args.version_id,
                digest=args.digest,
                commit_sha=identity.commit_sha,
                environment=identity.environment,
                run_id=identity.run_id,
                run_attempt=identity.run_attempt,
                apply_role_arn=identity.apply_role_arn,
                apply_role_digest=args.apply_role_digest,
            )
            head = json.loads(args.head_response.read_text(encoding="utf-8"))
            downloaded = json.loads(args.get_response.read_text(encoding="utf-8"))
            if record.key != identity.key:
                raise PolicyError("Plan key is not the run-derived exact key")
            if (
                record.apply_role_digest
                != hashlib.sha256(identity.apply_role_arn.encode("utf-8")).hexdigest()
            ):
                raise PolicyError("Plan apply role digest does not match")
            if args.record_digest != plan_record_digest(
                bucket=identity.bucket,
                key=record.key,
                version_id=record.version_id,
                digest=record.digest,
                commit_sha=record.commit_sha,
                environment=record.environment,
                run_id=record.run_id,
                run_attempt=record.run_attempt,
                kms_key_arn=identity.kms_key_arn,
                apply_role_arn=record.apply_role_arn,
                apply_role_digest=record.apply_role_digest,
                classification=classification,
                package=package,
            ):
                raise PolicyError("Plan record digest does not match")
            if head.get("VersionId") != record.version_id:
                raise PolicyError("S3 head returned a different plan version")
            if (
                head.get("ServerSideEncryption") != "aws:kms"
                or head.get("SSEKMSKeyId") != identity.kms_key_arn
                or head.get("Metadata")
                != deployment_metadata(identity, record.digest, classification)
            ):
                raise PolicyError("Plan object metadata or encryption is invalid")
            if downloaded.get("VersionId") != record.version_id:
                raise PolicyError("Downloaded object version does not match")
            if (
                downloaded.get("ServerSideEncryption") != "aws:kms"
                or downloaded.get("SSEKMSKeyId") != identity.kms_key_arn
                or downloaded.get("Metadata")
                != deployment_metadata(identity, record.digest, classification)
            ):
                raise PolicyError("Downloaded plan metadata or encryption is invalid")
            if hashlib.sha256(args.plan_file.read_bytes()).hexdigest() != record.digest:
                raise PolicyError("Downloaded plan digest does not match")
            if package is not None:
                if (
                    args.package_head_response is None
                    or args.package_get_response is None
                    or args.package_file is None
                ):
                    raise PolicyError("Package verification evidence is incomplete")
                if args.package_file.as_posix() != package["destination"]:
                    raise PolicyError("Package destination is not canonical")
                package_head = json.loads(args.package_head_response.read_text(encoding="utf-8"))
                package_download = json.loads(args.package_get_response.read_text(encoding="utf-8"))
                if package_head.get("VersionId") != package["version_id"]:
                    raise PolicyError("S3 head returned a different package version")
                if (
                    package_head.get("ServerSideEncryption") != "aws:kms"
                    or package_head.get("SSEKMSKeyId") != identity.kms_key_arn
                    or package_head.get("Metadata")
                    != package_metadata(identity, record.digest, package["digest"], classification)
                ):
                    raise PolicyError("Package object metadata or encryption is invalid")
                if package_download.get("VersionId") != package["version_id"]:
                    raise PolicyError("Downloaded package version does not match")
                if (
                    package_download.get("ServerSideEncryption") != "aws:kms"
                    or package_download.get("SSEKMSKeyId") != identity.kms_key_arn
                    or package_download.get("Metadata")
                    != package_metadata(identity, record.digest, package["digest"], classification)
                ):
                    raise PolicyError("Downloaded package metadata or encryption is invalid")
                if not args.package_file.is_file():
                    raise PolicyError("Lambda package is missing from the canonical destination")
                if hashlib.sha256(args.package_file.read_bytes()).hexdigest() != package["digest"]:
                    raise PolicyError("Downloaded package digest does not match")
        elif args.command == "assert-record":
            identity = identity_from_args(args)
            classification = classification_from_args(args)
            package = package_binding_from_args(args)
            if args.key != identity.key:
                raise PolicyError("Plan key is not the run-derived exact key")
            if not VERSION_RE.fullmatch(args.version_id):
                raise PolicyError("Plan version is invalid")
            if not re.fullmatch(r"[0-9a-f]{64}", args.digest):
                raise PolicyError("Plan digest is invalid")
            if (
                args.apply_role_digest
                != hashlib.sha256(identity.apply_role_arn.encode("utf-8")).hexdigest()
            ):
                raise PolicyError("Plan apply role digest does not match")
            if args.record_digest != plan_record_digest(
                bucket=identity.bucket,
                key=args.key,
                version_id=args.version_id,
                digest=args.digest,
                commit_sha=identity.commit_sha,
                environment=identity.environment,
                run_id=identity.run_id,
                run_attempt=identity.run_attempt,
                kms_key_arn=identity.kms_key_arn,
                apply_role_arn=identity.apply_role_arn,
                apply_role_digest=args.apply_role_digest,
                classification=classification,
                package=package,
            ):
                raise PolicyError("Plan record digest does not match")
        elif args.command == "verify-classification":
            raw_plan = args.input.read_bytes()
            if len(raw_plan) > MAX_PLAN_JSON_BYTES:
                raise PolicyError("Terraform plan JSON exceeds the private input bound")
            actual = classify_plan(json.loads(raw_plan))
            expected = classification_from_args(args)
            if actual["classification_sha256"] != expected["classification_sha256"] or any(
                actual[key] != expected[key] for key in CLASSIFICATION_COUNT_KEYS
            ):
                raise PolicyError("Downloaded plan classification does not match the record")
        elif args.command == "verify-lambda-package":
            verify_lambda_package(
                json.loads(args.plan.read_text(encoding="utf-8")),
                args.package_file,
                args.package_digest,
            )
        elif args.command == "verify-storage":
            versioning = json.loads(args.versioning_response.read_text(encoding="utf-8"))
            encryption = json.loads(args.encryption_response.read_text(encoding="utf-8"))
            rules = encryption.get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
            if versioning.get("Status") != "Enabled":
                raise PolicyError("Plan bucket versioning must be Enabled")
            if not any(
                rule.get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm") == "aws:kms"
                and rule.get("ApplyServerSideEncryptionByDefault", {}).get("KMSMasterKeyID")
                == args.kms_key_arn
                for rule in rules
            ):
                raise PolicyError("Plan bucket default SSE-KMS key does not match")
        else:
            raise PolicyError("Unknown exact-plan command")
    except (
        OSError,
        OnlinePolicyError,
        PolicyError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
    ) as error:
        print(f"Exact-plan policy rejected request: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
