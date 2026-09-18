#!/usr/bin/env python3
"""Deterministic canonical OpenAPI validation, generation, and drift gates."""

from __future__ import annotations

import argparse
import copy
import difflib
import hashlib
import importlib
import inspect
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlencode, urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "contracts" / "openapi" / "openapi.yaml"
EXCEPTIONS = ROOT / "contracts" / "openapi" / "compatibility-exceptions.yaml"
ROUTE_SECURITY = ROOT / "contracts" / "openapi" / "route-security.yaml"
REPORT_DIR = ROOT / "output" / "schema"
REDOCLY = ROOT / "extension" / "node_modules" / ".bin" / "redocly"
BOOTSTRAP = ROOT / "scripts" / "bootstrap.sh"
OASDIFF_INSTALLER = ROOT / "scripts" / "install-oasdiff.sh"
OASDIFF = ROOT / ".tools" / "oasdiff" / "1.23.0" / "bin" / "oasdiff"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
OPERATION_ID_PATTERN = re.compile(r"^[a-z][A-Za-z0-9]*$")
PYTEST_NODE_PATTERN = re.compile(
    r"^backend/test_[A-Za-z0-9_]+\.py(?:::[A-Za-z_][A-Za-z0-9_]*(?:\[[A-Za-z0-9_.-]+\])?)+$"
)
ECMASCRIPT_RESERVED_WORDS = {
    "arguments",
    "await",
    "break",
    "case",
    "catch",
    "class",
    "const",
    "continue",
    "debugger",
    "default",
    "delete",
    "do",
    "else",
    "enum",
    "eval",
    "export",
    "extends",
    "false",
    "finally",
    "for",
    "function",
    "if",
    "implements",
    "import",
    "in",
    "instanceof",
    "interface",
    "let",
    "new",
    "null",
    "package",
    "private",
    "protected",
    "public",
    "return",
    "static",
    "super",
    "switch",
    "this",
    "throw",
    "true",
    "try",
    "typeof",
    "var",
    "void",
    "while",
    "with",
    "yield",
}
NORMALIZATION_EXTENSION_ALLOWLIST = {
    "x-contract-test",
    "x-contract-test-case",
    "x-id-compatibility",
    "x-runtime-feature",
}
UNSAFE_MANUAL = {
    "createAuthSession",
    "createPagePreload",
    "analyzeText",
    "createChatReply",
    "createBillingCheckout",
    "openBillingPortal",
    "processBillingWebhook",
}
KNOWN_AUTH = {"anonymous", "localBearer", "stripeSignature"}
KNOWN_SETUP = {
    "none",
    "authenticatedUser",
    "mockIdentity",
    "emptyRepositories",
    "fakePreloadPipeline",
    "fakeModelPipeline",
    "billingRepositories",
    "mockBilling",
    "signedWebhook",
}
GENERATED = {
    "backend/generated/admin_models.py": ROOT / "backend" / "generated" / "admin_models.py",
    "extension/generated/api-contract.js": ROOT / "extension" / "generated" / "api-contract.js",
    "backend/generated/openapi-contract-cases.json": ROOT
    / "backend"
    / "generated"
    / "openapi-contract-cases.json",
}
EXTENSION_CONSUMED_OPERATIONS = (
    "analyzeText",
    "closeAuthSession",
    "createAuthSession",
    "createBillingCheckout",
    "createChatReply",
    "createPagePreload",
    "getAuthConfig",
    "getBillingSummary",
    "getPagePreload",
    "getVocabularyBook",
    "openBillingPortal",
)
EXTENSION_BACKGROUND = ROOT / "extension" / "background.js"
EXTENSION_CONTRACT_RUNTIME = ROOT / "extension" / "api-contract-runtime.js"
EXTENSION_CONSUMER_CHECK = ROOT / "extension" / "test" / "check-api-contract-consumer.mjs"


class SchemaError(RuntimeError):
    pass


def run(
    command: list[str], *, cwd: Path = ROOT, check: bool = True
) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        text=True,
        capture_output=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": os.environ.get("HOME", ""),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "BOOTSTRAP_TOOLS_DIR": os.environ.get("BOOTSTRAP_TOOLS_DIR", ""),
            "BACKEND_VENV": os.environ.get("BACKEND_VENV", "backend/.venv"),
            "AUTH_PROVIDER": "mock",
            "BILLING_PROVIDER": "mock",
            "STORAGE_BACKEND": "json",
            "JOB_RUNNER": "inline",
            "PYTHON_DOTENV_DISABLED": "1",
            "ADMIN_ENABLED": "false",
        },
    )
    if check and process.returncode:
        raise SchemaError(
            f"Command failed ({process.returncode}): {' '.join(command)}\n"
            f"{process.stdout}{process.stderr}"
        )
    return process


def load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SchemaError(f"Could not read YAML {path}: {exc}") from exc


def validate_local_refs(source: Path) -> None:
    contract_root = source.resolve().parent
    if not source.is_file() or source.is_symlink():
        raise SchemaError(f"Canonical schema source is missing or unsafe: {source}")
    yaml_files = sorted(
        path for path in contract_root.rglob("*") if path.suffix.lower() in {".yaml", ".yml"}
    )
    for path in yaml_files:
        if path.is_symlink() or not path.is_file():
            raise SchemaError(f"Schema source must be a regular non-symlink file: {path}")
        resolved_path = path.resolve()
        if not resolved_path.is_relative_to(contract_root):
            raise SchemaError(f"Schema source escapes contract root: {path}")
        document = load_yaml(path)

        def inspect_refs(value: Any, source_path: Path = path) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == "$ref":
                        if not isinstance(item, str) or not item:
                            raise SchemaError(
                                f"Invalid $ref in {source_path.relative_to(contract_root)}"
                            )
                        decoded = unquote(item)
                        parsed = urlsplit(decoded)
                        ref_path = parsed.path
                        if (
                            parsed.scheme
                            or parsed.netloc
                            or parsed.query
                            or ref_path.startswith(("/", "\\"))
                            or "\\" in ref_path
                        ):
                            raise SchemaError(
                                f"External or absolute reference is forbidden in "
                                f"{source_path.relative_to(contract_root)}: {item}"
                            )
                        if ref_path:
                            target = (source_path.parent / ref_path).resolve()
                            if not target.is_relative_to(contract_root):
                                raise SchemaError(
                                    f"Reference escapes contracts/openapi in "
                                    f"{source_path.relative_to(contract_root)}: {item}"
                                )
                            if (
                                target.suffix.lower() not in {".yaml", ".yml"}
                                or not target.is_file()
                            ):
                                raise SchemaError(
                                    f"Reference target is missing or not YAML in "
                                    f"{source_path.relative_to(contract_root)}: {item}"
                                )
                    inspect_refs(item)
            elif isinstance(value, list):
                for item in value:
                    inspect_refs(item)

        inspect_refs(document)


def redocly_bundle(source: Path = CANONICAL) -> dict[str, Any]:
    validate_local_refs(source)
    if not REDOCLY.is_file():
        raise SchemaError("Redocly CLI is unavailable; run task setup.")
    with tempfile.TemporaryDirectory(prefix="untangle-openapi-") as directory:
        output = Path(directory) / "bundle.json"
        run(
            [
                str(BOOTSTRAP),
                "--exec",
                str(REDOCLY),
                "lint",
                str(source),
                "--config",
                str(ROOT / "redocly.yaml"),
            ]
        )
        run(
            [
                str(BOOTSTRAP),
                "--exec",
                str(REDOCLY),
                "bundle",
                str(source),
                "--config",
                str(ROOT / "redocly.yaml"),
                "--output",
                str(output),
                "--ext",
                "json",
            ]
        )
        try:
            return json.loads(output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SchemaError(f"Redocly produced an unreadable bundle: {exc}") from exc


def iter_operations(bundle: dict[str, Any]):
    for path in sorted(bundle.get("paths", {})):
        path_item = bundle["paths"][path]
        for method in sorted(HTTP_METHODS):
            if method in path_item:
                yield path, method, path_item[method]


def validate_operation_ids(bundle: dict[str, Any]) -> dict[str, tuple[str, str]]:
    operation_map: dict[str, tuple[str, str]] = {}
    method_path_map: dict[tuple[str, str], str] = {}
    for path, method, operation in iter_operations(bundle):
        operation_id = operation.get("operationId")
        if not isinstance(operation_id, str) or not OPERATION_ID_PATTERN.fullmatch(operation_id):
            raise SchemaError(
                f"{method.upper()} {path} has an invalid operationId: {operation_id!r}"
            )
        if operation_id in ECMASCRIPT_RESERVED_WORDS:
            raise SchemaError(f"{operation_id!r} is an ECMAScript reserved operationId.")
        if operation_id in operation_map:
            raise SchemaError(f"Duplicate operationId: {operation_id}")
        key = (method, path)
        if key in method_path_map:
            raise SchemaError(f"Duplicate method/path: {method.upper()} {path}")
        operation_map[operation_id] = key
        method_path_map[key] = operation_id
    return operation_map


def collect_pytest_nodes(nodes: set[str]) -> set[str]:
    if not nodes:
        return set()
    files: set[str] = set()
    for node in nodes:
        if not PYTEST_NODE_PATTERN.fullmatch(node):
            raise SchemaError(f"Unsafe pytest node ID in contract ownership: {node!r}")
        files.add(node.split("::", 1)[0])
    venv = Path(os.environ.get("BACKEND_VENV", "backend/.venv"))
    venv_root = (ROOT / venv).resolve()
    if not venv_root.is_relative_to(ROOT):
        raise SchemaError("Backend test environment must remain inside the repository.")
    python = venv_root / "bin" / "python"
    if not python.is_file():
        raise SchemaError("Backend test environment is unavailable for ownership collection.")
    result = run(
        [str(python), "-m", "pytest", "--collect-only", "-q", *sorted(files)],
        check=False,
    )
    if result.returncode:
        raise SchemaError(f"Pytest ownership collection failed:\n{result.stdout}{result.stderr}")
    return {
        line.strip()
        for line in result.stdout.splitlines()
        if PYTEST_NODE_PATTERN.fullmatch(line.strip())
    }


def require_collected_pytest_nodes(nodes: set[str]) -> None:
    collected = collect_pytest_nodes(nodes)
    missing = sorted(nodes - collected)
    if missing:
        raise SchemaError(
            f"Contract ownership references stale collected pytest node IDs: {missing}"
        )


def validate_contract_metadata(bundle: dict[str, Any]) -> None:
    seen_cases: set[tuple[str, str]] = set()
    manual_nodes: set[str] = set()
    for _path, _method, operation in iter_operations(bundle):
        operation_id = operation["operationId"]
        metadata = operation.get("x-contract-test")
        if not isinstance(metadata, dict):
            raise SchemaError(f"{operation_id} is missing x-contract-test.")
        required = {"mode", "owner", "auth", "setup"}
        if not required.issubset(metadata):
            raise SchemaError(
                f"{operation_id} x-contract-test lacks {sorted(required - metadata.keys())}."
            )
        if metadata["mode"] not in {"generic", "manual"}:
            raise SchemaError(f"{operation_id} has unknown contract mode.")
        if not isinstance(metadata["owner"], str) or not metadata["owner"].strip():
            raise SchemaError(f"{operation_id} has no contract owner.")
        if metadata["auth"] not in KNOWN_AUTH or metadata["setup"] not in KNOWN_SETUP:
            raise SchemaError(f"{operation_id} names an unknown auth/setup fixture.")
        if operation_id in UNSAFE_MANUAL and metadata["mode"] != "manual":
            raise SchemaError(f"Unsafe provider operation {operation_id} cannot be generic.")
        if metadata["mode"] == "manual":
            if not all(
                isinstance(metadata.get(key), str) and metadata[key].strip()
                for key in ("reason", "test")
            ):
                raise SchemaError(
                    f"Manual operation {operation_id} requires reason and test ownership."
                )
            manual_nodes.add(metadata["test"])

        request_cases: set[str] = set()
        for content in operation.get("requestBody", {}).get("content", {}).values():
            for example in content.get("examples", {}).values():
                case_id = example.get("x-contract-test-case")
                if not isinstance(case_id, str) or not case_id:
                    raise SchemaError(f"{operation_id} has an unowned named request example.")
                request_cases.add(case_id)
        response_cases: set[str] = set()
        has_response_example = False
        for response in operation.get("responses", {}).values():
            for content in response.get("content", {}).values():
                if "example" in content:
                    has_response_example = True
                for example in content.get("examples", {}).values():
                    has_response_example = True
                    case_id = example.get("x-contract-test-case")
                    if not isinstance(case_id, str) or not case_id:
                        raise SchemaError(f"{operation_id} has an unowned named response example.")
                    key = (operation_id, case_id)
                    if key in seen_cases:
                        raise SchemaError(f"Duplicate contract case ID: {operation_id}/{case_id}")
                    seen_cases.add(key)
                    response_cases.add(case_id)
        if not has_response_example:
            raise SchemaError(f"{operation_id} has no response example.")
        if (
            metadata["mode"] == "generic"
            and request_cases
            and response_cases
            and request_cases != response_cases
        ):
            raise SchemaError(
                f"{operation_id} request/response cases are unpaired: "
                f"request={sorted(request_cases)}, response={sorted(response_cases)}"
            )
    require_collected_pytest_nodes(manual_nodes)


def validate_exceptions(path: Path = EXCEPTIONS) -> list[dict[str, Any]]:
    document = load_yaml(path)
    if not isinstance(document, dict) or document.get("version") != 1:
        raise SchemaError("Compatibility exceptions must have version: 1.")
    entries = document.get("exceptions")
    if not isinstance(entries, list):
        raise SchemaError("Compatibility exceptions must contain an exceptions list.")
    seen: set[str] = set()
    seen_fingerprints: set[str] = set()
    today = __import__("datetime").date.today()
    for entry in entries:
        if not isinstance(entry, dict):
            raise SchemaError("Every compatibility exception must be an object.")
        common = {"id", "kind", "owner", "reason", "approval", "expires"}
        kind = entry.get("kind")
        eligible = common | (
            {
                "fingerprint",
                "operationId",
                "property",
                "consumers",
                "rollout",
                "monitoring",
                "rollback",
            }
            if kind == "compatibility"
            else {"operationId", "property", "test"}
            if kind == "security"
            else set()
        )
        if kind not in {"compatibility", "security"}:
            raise SchemaError(f"Unknown compatibility exception kind: {kind!r}")
        if set(entry) != eligible:
            raise SchemaError(
                f"Exception {entry.get('id')!r} fields must be exactly {sorted(eligible)}."
            )
        for key in common - {"expires"}:
            if not isinstance(entry.get(key), str) or not entry[key].strip():
                raise SchemaError(f"Exception {entry.get('id')!r} has invalid {key}.")
        if entry["id"] in seen:
            raise SchemaError(f"Duplicate compatibility exception ID: {entry['id']}")
        seen.add(entry["id"])
        if not isinstance(entry.get("expires"), str):
            raise SchemaError(f"Exception {entry['id']} expiry must be an ISO date string.")
        try:
            expiry = __import__("datetime").date.fromisoformat(entry["expires"])
        except ValueError as exc:
            raise SchemaError(f"Exception {entry['id']} has invalid ISO expiry.") from exc
        if expiry < today:
            raise SchemaError(f"Compatibility exception {entry['id']} expired on {expiry}.")
        if kind == "compatibility":
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(entry["fingerprint"])):
                raise SchemaError(f"Compatibility exception {entry['id']} has invalid fingerprint.")
            if entry["fingerprint"] in seen_fingerprints:
                raise SchemaError(
                    f"Duplicate compatibility finding fingerprint: {entry['fingerprint']}"
                )
            seen_fingerprints.add(entry["fingerprint"])
            if not OPERATION_ID_PATTERN.fullmatch(str(entry["operationId"])):
                raise SchemaError(f"Compatibility exception {entry['id']} has invalid operationId.")
            if (
                not isinstance(entry["property"], str)
                or not entry["property"].strip()
                or entry["property"] in {"*", "operation", "schema"}
                or "*" in entry["property"]
            ):
                raise SchemaError(
                    f"Compatibility exception {entry['id']} lacks an exact changed property/location."
                )
            if not isinstance(entry["consumers"], list) or not entry["consumers"]:
                raise SchemaError(
                    f"Compatibility exception {entry['id']} needs affected consumers."
                )
            for key in ("rollout", "monitoring", "rollback"):
                if not isinstance(entry[key], str) or not entry[key].strip():
                    raise SchemaError(f"Compatibility exception {entry['id']} has invalid {key}.")
        else:
            if not OPERATION_ID_PATTERN.fullmatch(entry["operationId"]):
                raise SchemaError(f"Exception {entry['id']} has invalid operationId.")
            if (
                entry["property"] in {"*", "operation", "schema", "security"}
                or "*" in entry["property"]
            ):
                raise SchemaError(
                    f"Exception {entry['id']} is broad rather than an eligible exact finding."
                )
            require_collected_pytest_nodes({entry["test"]})
    return entries


def normalized_oasdiff_finding(finding: dict[str, Any]) -> dict[str, Any]:
    def normalize(value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            return {item_key: normalize(item, item_key) for item_key, item in sorted(value.items())}
        if isinstance(value, list):
            return [normalize(item, key) for item in value]
        if isinstance(value, str) and key.lower() in {"file", "filename"}:
            return "<schema>"
        return value

    return normalize(finding)


def finding_fingerprint(finding: dict[str, Any]) -> str:
    encoded = json.dumps(
        normalized_oasdiff_finding(finding),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def finding_review_identity(finding: dict[str, Any]) -> tuple[str, str]:
    operation_id = finding.get("operationId")
    if not isinstance(operation_id, str) or not OPERATION_ID_PATTERN.fullmatch(operation_id):
        raise SchemaError("oasdiff finding lacks a reviewable operationId and cannot be waived.")
    explicit_property = finding.get("property")
    if isinstance(explicit_property, str) and explicit_property.strip():
        return operation_id, explicit_property
    source = finding.get("baseSource")
    if not isinstance(source, dict):
        source = finding.get("revisionSource")
    if not isinstance(source, dict):
        source = {}
    location = (
        f"{finding.get('section', 'unknown')}:{finding.get('path', 'unknown')}"
        f"@{source.get('line', '?')}:{source.get('column', '?')}"
        f"[{finding.get('id', 'unknown')}] {finding.get('text', '')}"
    )
    return operation_id, location


def apply_compatibility_exceptions(
    findings: list[dict[str, Any]],
    exceptions: list[dict[str, Any]],
) -> set[str]:
    compatibility = {
        entry["fingerprint"]: entry for entry in exceptions if entry["kind"] == "compatibility"
    }
    applied: set[str] = set()
    for finding in findings:
        fingerprint = finding_fingerprint(finding)
        exception = compatibility.get(fingerprint)
        if exception is None:
            raise SchemaError(
                f"oasdiff found an unapproved exact finding {fingerprint}: "
                f"{normalized_oasdiff_finding(finding)}"
            )
        operation_id, property_location = finding_review_identity(finding)
        if exception["operationId"] != operation_id or exception["property"] != property_location:
            raise SchemaError(
                f"Compatibility exception {exception['id']} review identity does not match "
                f"fingerprinted finding: expected operationId={operation_id!r}, "
                f"property={property_location!r}."
            )
        applied.add(exception["id"])
    unused = {entry["id"] for entry in exceptions if entry["kind"] == "compatibility"} - applied
    if unused:
        raise SchemaError(
            f"Compatibility exceptions did not match exact findings: {sorted(unused)}"
        )
    return applied


def reject_unused_compatibility_exceptions(
    exceptions: list[dict[str, Any]],
    *,
    context: str,
) -> None:
    unused = sorted(entry["id"] for entry in exceptions if entry["kind"] == "compatibility")
    if unused:
        raise SchemaError(
            f"{context} has unused compatibility exceptions: {unused}. "
            "Remove them or compare against the finding they approve."
        )


def query_path(path: str, operation: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    parameters: dict[str, Any] = {}
    query: list[tuple[str, str]] = []
    expanded = path
    for parameter in operation.get("parameters", []):
        value = parameter.get("example", parameter.get("schema", {}).get("default"))
        if parameter.get("required") and value is None:
            raise SchemaError(
                f"{operation['operationId']} required parameter {parameter['name']} lacks an example."
            )
        if value is None:
            continue
        parameters[parameter["name"]] = value
        if parameter["in"] == "path":
            expanded = expanded.replace("{" + parameter["name"] + "}", str(value))
        elif parameter["in"] == "query":
            query.append(
                (parameter["name"], str(value).lower() if isinstance(value, bool) else str(value))
            )
    if query:
        expanded += "?" + urlencode(sorted(query))
    return expanded, parameters


def generated_outputs(bundle: dict[str, Any]) -> dict[str, bytes]:
    validate_operation_ids(bundle)
    validate_contract_metadata(bundle)
    operations: dict[str, Any] = {}
    cases: list[dict[str, Any]] = []
    for path, method, operation in iter_operations(bundle):
        operation_id = operation["operationId"]
        responses = {
            str(status): sorted(response.get("content", {}).keys())
            for status, response in sorted(operation["responses"].items())
        }
        success = sorted(
            status for status in responses if status.isdigit() and 200 <= int(status) < 300
        )
        query_parameters = []
        for parameter in operation.get("parameters", []):
            if parameter.get("in") != "query":
                continue
            style = parameter.get("style", "form")
            explode = parameter.get("explode", style == "form")
            query_parameters.append(
                {
                    "explode": bool(explode),
                    "name": parameter["name"],
                    "repeat": parameter.get("schema", {}).get("type") == "array",
                    "required": bool(parameter.get("required", False)),
                    "style": style,
                }
            )
        query_parameters.sort(key=lambda parameter: parameter["name"])
        operations[operation_id] = {
            "method": method.upper(),
            "path": path,
            "queryParameters": query_parameters,
            "responses": responses,
            "successStatuses": success,
        }
        metadata = operation["x-contract-test"]
        if metadata["mode"] == "manual":
            cases.append(
                {
                    "operationId": operation_id,
                    "mode": "manual",
                    "method": method.upper(),
                    "path": path,
                    "owner": metadata["owner"],
                    "reason": metadata["reason"],
                    "test": metadata["test"],
                    "auth": metadata["auth"],
                    "setup": metadata["setup"],
                    "invoke": False,
                }
            )
            continue

        request_examples: dict[str, tuple[str, Any]] = {}
        for media_type, media in operation.get("requestBody", {}).get("content", {}).items():
            for example in media.get("examples", {}).values():
                request_examples[example["x-contract-test-case"]] = (media_type, example["value"])
        default_request: tuple[str | None, Any] = (None, None)
        if len(request_examples) == 1:
            default_request = next(iter(request_examples.values()))
        elif len(request_examples) > 1:
            default_request = (None, None)
        expanded_path, parameters = query_path(path, operation)
        emitted = 0
        for status, response in sorted(operation["responses"].items()):
            for media_type, media in sorted(response.get("content", {}).items()):
                for example_name, example in sorted(media.get("examples", {}).items()):
                    case_id = example["x-contract-test-case"]
                    request_media, request_body = request_examples.get(case_id, (None, None))
                    is_success = status.isdigit() and 200 <= int(status) < 300
                    cases.append(
                        {
                            "operationId": operation_id,
                            "caseId": case_id,
                            "exampleName": example_name,
                            "mode": "generic",
                            "caseKind": "success" if is_success else "documentedError",
                            "invoke": is_success,
                            "method": method.upper(),
                            "path": expanded_path,
                            "parameters": parameters,
                            "requestMediaType": request_media,
                            "requestBody": request_body,
                            "expectedStatus": int(status),
                            "expectedMediaType": media_type,
                            "responseExample": example["value"],
                            "auth": metadata["auth"],
                            "setup": metadata["setup"],
                        }
                    )
                    emitted += 1
                if "example" in media:
                    is_success = status.isdigit() and 200 <= int(status) < 300
                    case_id = (
                        f"response-{status}-"
                        f"{re.sub(r'[^a-z0-9]+', '-', media_type.lower()).strip('-')}-example"
                    )
                    if len(request_examples) > 1:
                        request_case_id = media.get("x-contract-test-case")
                        if request_case_id not in request_examples:
                            raise SchemaError(
                                f"{operation_id} singular response example {status}/{media_type} "
                                "must select one request x-contract-test-case."
                            )
                        request_media, request_body = request_examples[request_case_id]
                    else:
                        request_media, request_body = default_request
                    cases.append(
                        {
                            "operationId": operation_id,
                            "caseId": case_id,
                            "exampleName": "example",
                            "mode": "generic",
                            "caseKind": "success" if is_success else "documentedError",
                            "invoke": is_success,
                            "method": method.upper(),
                            "path": expanded_path,
                            "parameters": parameters,
                            "requestMediaType": request_media,
                            "requestBody": request_body,
                            "expectedStatus": int(status),
                            "expectedMediaType": media_type,
                            "responseExample": media["example"],
                            "auth": metadata["auth"],
                            "setup": metadata["setup"],
                        }
                    )
                    emitted += 1
        if emitted == 0:
            raise SchemaError(f"Generic operation {operation_id} generated no executable case.")

    all_operations = dict(sorted(operations.items()))
    missing_consumed = sorted(set(EXTENSION_CONSUMED_OPERATIONS) - set(all_operations))
    if missing_consumed:
        raise SchemaError(
            f"Extension-consumed operations are missing from the canonical schema: {missing_consumed}"
        )
    operations = {
        operation_id: all_operations[operation_id] for operation_id in EXTENSION_CONSUMED_OPERATIONS
    }
    cases.sort(
        key=lambda case: (case["operationId"], case.get("caseId", ""), case.get("exampleName", ""))
    )
    js_object = json.dumps(operations, indent=2, sort_keys=True, ensure_ascii=False)
    js_payload = json.dumps(js_object, ensure_ascii=False)
    js = (
        "// GENERATED FILE - DO NOT EDIT.\n"
        "// Source: contracts/openapi/openapi.yaml\n\n"
        "((global) => {\n"
        '  "use strict";\n\n'
        "  const objectCreate = Object.create;\n"
        "  const objectDefineProperty = Object.defineProperty;\n"
        "  const objectFreeze = Object.freeze;\n"
        "  const objectKeys = Object.keys;\n"
        "  const arrayIsArray = Array.isArray;\n"
        "  const arrayMap = Function.call.bind(Array.prototype.map);\n"
        "  const jsonParse = JSON.parse;\n\n"
        "  const toSafeFrozenValue = (value) => {\n"
        "    if (arrayIsArray(value)) {\n"
        "      return objectFreeze(arrayMap(value, toSafeFrozenValue));\n"
        "    }\n"
        '    if (value && typeof value === "object") {\n'
        "      const safe = objectCreate(null);\n"
        "      for (const key of objectKeys(value)) {\n"
        "        safe[key] = toSafeFrozenValue(value[key]);\n"
        "      }\n"
        "      return objectFreeze(safe);\n"
        "    }\n"
        "    return value;\n"
        "  };\n\n"
        f"  const operations = toSafeFrozenValue(jsonParse({js_payload}));\n"
        "  const operationFields = toSafeFrozenValue([\n"
        "    ...new Set(\n"
        "      objectKeys(operations).flatMap((operationId) => objectKeys(operations[operationId])),\n"
        "    ),\n"
        "  ].sort());\n"
        "  const namespace = toSafeFrozenValue({ operationFields, operations });\n\n"
        '  objectDefineProperty(global, "UntangleApiContract", {\n'
        "    value: namespace,\n"
        "    writable: false,\n"
        "    configurable: false,\n"
        "    enumerable: true,\n"
        "  });\n"
        "})(globalThis);\n"
    )
    case_document = {
        "_generated": "DO NOT EDIT. Source: contracts/openapi/openapi.yaml",
        "version": 2,
        "cases": cases,
    }
    return {
        "extension/generated/api-contract.js": js.encode("utf-8"),
        "backend/generated/openapi-contract-cases.json": (
            json.dumps(case_document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        ).encode("utf-8"),
    }


def write_generated(output_root: Path) -> None:
    bundle = redocly_bundle()
    outputs = generated_outputs(bundle)
    outputs["backend/generated/admin_models.py"] = generated_admin_models(bundle)
    for relative, content in outputs.items():
        destination = output_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        temporary.write_bytes(content)
        temporary.replace(destination)


def referenced_schemas(value: Any, schemas: dict[str, Any]) -> set[str]:
    """Find the transitive schema closure without dropping unrelated schema definitions."""
    found: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            reference = item.get("$ref", "")
            if isinstance(reference, str) and reference.startswith("#/components/schemas/"):
                name = reference.removeprefix("#/components/schemas/")
                if name not in schemas:
                    raise SchemaError(f"Missing bundled schema: {name}")
                if name not in found:
                    found.add(name)
                    visit(schemas[name])
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return found


def generated_admin_models(bundle: dict[str, Any]) -> bytes:
    """Generate only implemented admin transport models from the canonical bundle."""
    operation = bundle["paths"]["/admin/v1/session"]["get"]
    schemas = bundle["components"]["schemas"]
    names = referenced_schemas(operation, schemas)
    document = {
        "openapi": bundle["openapi"],
        "info": bundle["info"],
        "paths": {},
        "components": {"schemas": {name: schemas[name] for name in sorted(names)}},
    }
    with tempfile.TemporaryDirectory(prefix="untangle-admin-models-") as directory:
        source = Path(directory) / "admin-components.json"
        output = Path(directory) / "admin_models.py"
        source.write_text(json.dumps(document), encoding="utf-8")
        run(
            [
                sys.executable,
                "-m",
                "datamodel_code_generator",
                "--input",
                str(source),
                "--input-file-type",
                "openapi",
                "--output",
                str(output),
                "--output-model-type",
                "pydantic_v2.BaseModel",
                "--use-standard-collections",
                "--use-union-operator",
                "--target-python-version",
                "3.12",
                "--formatters",
                "ruff-format",
                "--use-double-quotes",
                "--disable-timestamp",
                "--enum-field-as-literal",
                "all",
            ]
        )
        return output.read_bytes()


def check_generated() -> None:
    with tempfile.TemporaryDirectory(prefix="untangle-generated-") as directory:
        root = Path(directory)
        write_generated(root)
        for relative, committed in GENERATED.items():
            candidate = root / relative
            if not committed.is_file():
                raise SchemaError(f"Generated artifact is missing: {relative}")
            actual = committed.read_bytes()
            expected = candidate.read_bytes()
            if actual != expected:
                diff = "".join(
                    difflib.unified_diff(
                        actual.decode().splitlines(True),
                        expected.decode().splitlines(True),
                        fromfile=str(committed),
                        tofile="regenerated",
                    )
                )
                raise SchemaError(f"Generated artifact is stale: {relative}\n{diff}")


def check_extension_consumer(bundle: dict[str, Any]) -> None:
    background = EXTENSION_BACKGROUND.read_text(encoding="utf-8")
    import_order = [
        background.find(f"'{script}'")
        for script in (
            "generated/api-contract.js",
            "api-contract-runtime.js",
            "settings.js",
            "i18n.js",
            "shared.js",
        )
    ]
    if any(index < 0 for index in import_order) or import_order != sorted(import_order):
        raise SchemaError(
            "The classic service worker must load the generated contract and runtime before API calls."
        )

    canonical = {
        operation["operationId"]: {"method": method.upper(), "path": path}
        for path, method, operation in iter_operations(bundle)
    }
    referenced_symbols = set(re.findall(r"\bAPI_OPERATIONS\.([A-Za-z0-9]+)\b", background))
    expected_symbols = set(EXTENSION_CONSUMED_OPERATIONS)
    if referenced_symbols != expected_symbols:
        raise SchemaError(
            "Extension generated-operation usage is stale: "
            f"expected {sorted(expected_symbols)}, found {sorted(referenced_symbols)}."
        )
    for operation_id in EXTENSION_CONSUMED_OPERATIONS:
        symbol = f"API_OPERATIONS.{operation_id}"
        if symbol not in background:
            raise SchemaError(f"Extension consumer does not use generated symbol {symbol}.")
        path = canonical[operation_id]["path"]
        literal_pattern = re.compile(rf"([\"'`]){re.escape(path)}(?:\?|[\"'`])")
        if literal_pattern.search(background):
            raise SchemaError(
                f"Extension consumer duplicates canonical path literal for {operation_id}: {path}"
            )

    duplicated_method = re.search(
        r"\bmethod\s*:\s*([\"'])(?:GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD|TRACE)\1",
        background,
    )
    if duplicated_method:
        raise SchemaError("Extension consumer duplicates a canonical HTTP method literal.")

    run(
        [
            str(BOOTSTRAP),
            "--exec",
            "node",
            str(EXTENSION_CONSUMER_CHECK.relative_to(ROOT)),
        ]
    )


def normalized_schema(value: Any) -> Any:
    ignored = {
        "description",
        "summary",
        "title",
        "example",
        "examples",
        "security",
    }
    if isinstance(value, dict):
        result = {
            key: normalized_schema(item)
            for key, item in value.items()
            if key not in ignored and key not in NORMALIZATION_EXTENSION_ALLOWLIST
        }
        if "parameters" in result and isinstance(result["parameters"], list):
            result["parameters"] = sorted(
                result["parameters"],
                key=lambda parameter: (parameter.get("in", ""), parameter.get("name", "")),
            )
        return result
    if isinstance(value, list):
        return [normalized_schema(item) for item in value]
    return value


def runtime_bundle() -> dict[str, Any]:
    runtime_admin_enabled()
    os.environ.update(
        {
            "AUTH_PROVIDER": "mock",
            "BILLING_PROVIDER": "mock",
            "STORAGE_BACKEND": "json",
            "JOB_RUNNER": "inline",
            "PRELOAD_CONTENT_BUCKET": "",
            "PYTHON_DOTENV_DISABLED": "1",
        }
    )
    sys.path.insert(0, str(ROOT / "backend"))
    from main import app

    return app.openapi()


def runtime_admin_enabled() -> bool:
    value = os.environ.get("ADMIN_ENABLED", "false").strip().lower()
    if value not in {"", "0", "1", "false", "true", "off", "on", "no", "yes"}:
        raise SchemaError(f"Unknown ADMIN_ENABLED runtime mode: {value!r}")
    return value in {"1", "true", "on", "yes"}


def contract_for_runtime(bundle: dict[str, Any], *, admin_enabled: bool) -> dict[str, Any]:
    result = copy.deepcopy(bundle)
    removed_operations = []
    for path, method, operation in list(iter_operations(result)):
        feature = operation.get("x-runtime-feature")
        is_session = (path, method, operation["operationId"]) == (
            "/admin/v1/session",
            "get",
            "getAdminSession",
        )
        if (feature is not None and (feature != "admin" or not is_session)) or (
            is_session and feature != "admin"
        ):
            raise SchemaError(f"Invalid runtime feature on {method.upper()} {path}: {feature!r}")
        if feature == "admin" and not admin_enabled:
            removed_operations.append(result["paths"][path].pop(method))
            if not result["paths"][path]:
                del result["paths"][path]
    schemas = result.get("components", {}).get("schemas", {})
    removed_names = referenced_schemas(removed_operations, schemas)
    retained_names = referenced_schemas(result["paths"], schemas)
    for name in removed_names - retained_names:
        del schemas[name]
    return result


def write_json_report(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_raw_report(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if str(ROOT) in content:
        raise SchemaError("Raw schema report contains an absolute repository path.")
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def write_oasdiff_reports(
    *,
    raw_report: str,
    findings: list[dict[str, Any]],
    status: str,
    base_label: str,
    applied: set[str],
    report_dir: Path = REPORT_DIR,
) -> None:
    def reject_absolute_sources(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for item_key, item in value.items():
                reject_absolute_sources(item, item_key)
        elif isinstance(value, list):
            for item in value:
                reject_absolute_sources(item, key)
        elif (
            isinstance(value, str)
            and key.lower() in {"file", "filename", "source"}
            and (value.startswith("/") or value.startswith("file:/"))
        ):
            raise SchemaError("Raw oasdiff report contains an absolute source path.")

    reject_absolute_sources(findings)
    write_raw_report(report_dir / "oasdiff.json", raw_report)
    report_findings = []
    for finding in findings:
        try:
            operation_id, property_location = finding_review_identity(finding)
        except SchemaError:
            operation_id, property_location = None, None
        report_findings.append(
            {
                **normalized_oasdiff_finding(finding),
                "fingerprint": finding_fingerprint(finding),
                "reviewOperationId": operation_id,
                "reviewProperty": property_location,
            }
        )
    write_json_report(
        report_dir / "oasdiff-normalized.json",
        {
            "status": status,
            "base": base_label,
            "findings": report_findings,
            "appliedExceptions": sorted(applied),
        },
    )


def sanitized_report_error(error: Exception) -> str:
    return str(error).replace(str(ROOT), "<repository>")


def check_runtime_drift(
    bundle: dict[str, Any],
    *,
    report_path: Path | None = None,
) -> None:
    runtime = runtime_bundle()
    bundle = contract_for_runtime(bundle, admin_enabled=runtime_admin_enabled())
    canonical_surface = {
        "paths": bundle.get("paths", {}),
        "schemas": bundle.get("components", {}).get("schemas", {}),
    }
    runtime_surface = {
        "paths": runtime.get("paths", {}),
        "schemas": runtime.get("components", {}).get("schemas", {}),
    }
    normalized_runtime = normalized_schema(runtime_surface)
    normalized_canonical = normalized_schema(canonical_surface)
    left = json.dumps(normalized_runtime, indent=2, sort_keys=True)
    right = json.dumps(normalized_canonical, indent=2, sort_keys=True)
    matches = normalized_runtime == normalized_canonical
    if report_path is not None:
        write_json_report(
            report_path,
            {
                "status": "passed" if matches else "failed",
                "runtime": normalized_runtime,
                "canonical": normalized_canonical,
            },
        )
    if not matches:
        diff = "".join(
            difflib.unified_diff(
                left.splitlines(True),
                right.splitlines(True),
                fromfile="FastAPI runtime",
                tofile="canonical",
            )
        )
        raise SchemaError(f"FastAPI adapter drift detected after strict normalization:\n{diff}")


def dependency_calls(dependant: Any) -> set[Any]:
    calls: set[Any] = set()
    for child in dependant.dependencies:
        if child.call is not None:
            calls.add(child.call)
        calls.update(dependency_calls(child))
    return calls


def dotted_object(name: str) -> Any:
    parts = name.split(".")
    for index in range(len(parts), 0, -1):
        try:
            value = importlib.import_module(".".join(parts[:index]))
        except ModuleNotFoundError:
            continue
        for attribute in parts[index:]:
            value = getattr(value, attribute)
        return value
    raise SchemaError(f"Could not resolve dotted object: {name}")


def check_route_security(bundle: dict[str, Any]) -> set[str]:
    security_exceptions = [entry for entry in validate_exceptions() if entry["kind"] == "security"]
    applied: set[str] = set()

    def security_issue(operation_id: str, property_name: str, message: str) -> bool:
        matches = [
            entry
            for entry in security_exceptions
            if entry["operationId"] == operation_id and entry["property"] == property_name
        ]
        if len(matches) == 1:
            applied.add(matches[0]["id"])
            return True
        if len(matches) > 1:
            raise SchemaError(f"Multiple security exceptions match {operation_id}/{property_name}.")
        raise SchemaError(message)

    document = load_yaml(ROUTE_SECURITY)
    mappings = document.get("operations") if isinstance(document, dict) else None
    if not isinstance(mappings, list):
        raise SchemaError("route-security.yaml must contain an operations list.")
    by_id: dict[str, dict[str, Any]] = {}
    for mapping in mappings:
        operation_id = mapping.get("operationId")
        if operation_id in by_id:
            raise SchemaError(f"Duplicate route-security mapping: {operation_id}")
        by_id[operation_id] = mapping
    canonical = {operation["operationId"]: operation for _, _, operation in iter_operations(bundle)}
    if set(by_id) != set(canonical):
        raise SchemaError(
            f"Route-security map mismatch: missing={sorted(set(canonical) - set(by_id))}, "
            f"extra={sorted(set(by_id) - set(canonical))}"
        )

    bundle = contract_for_runtime(bundle, admin_enabled=runtime_admin_enabled())
    canonical = {operation["operationId"]: operation for _, _, operation in iter_operations(bundle)}

    runtime_bundle()
    from fastapi.routing import APIRoute
    from main import app

    def iter_runtime_routes(routes: list[Any]):
        for route in routes:
            if isinstance(route, APIRoute):
                yield route
                continue
            included_router = getattr(route, "original_router", None)
            if included_router is not None:
                yield from iter_runtime_routes(included_router.routes)

    routes = {route.operation_id: route for route in iter_runtime_routes(app.routes)}
    if set(routes) != set(canonical):
        raise SchemaError("FastAPI route operation IDs do not match canonical security operations.")
    current_user = dotted_object("deps.get_current_user")
    for operation_id, operation in canonical.items():
        mapping = by_id[operation_id]
        security = operation.get("security", [])
        calls = dependency_calls(routes[operation_id].dependant)
        kind = mapping.get("kind")
        if security == []:
            if kind != "public" or not mapping.get("owner") or not mapping.get("reason"):
                if security_issue(
                    operation_id,
                    "publicOwnership",
                    f"Public operation {operation_id} lacks owned public rationale.",
                ):
                    continue
            if current_user in calls:
                if security_issue(
                    operation_id,
                    "unexpectedBearerDependency",
                    f"Public operation {operation_id} unexpectedly requires bearer auth.",
                ):
                    continue
        elif security == [{"bearerAuth": []}]:
            if kind != "bearerAuth" or mapping.get("dependency") != "deps.get_current_user":
                if security_issue(
                    operation_id,
                    "bearerMapping",
                    f"Bearer security mapping is invalid for {operation_id}.",
                ):
                    continue
            if current_user not in calls:
                if security_issue(
                    operation_id,
                    "bearerDependency",
                    f"{operation_id} lacks transitive deps.get_current_user.",
                ):
                    continue
            if operation_id == "getAdminSession":
                if (
                    mapping.get("authorizationDependency") != "admin.deps.get_admin_user"
                    or dotted_object("admin.deps.get_admin_user") not in calls
                ):
                    raise SchemaError(
                        "Admin session lacks its administrator authorization dependency."
                    )
        elif security == [{"stripeSignature": []}]:
            if kind != "stripeSignature":
                if security_issue(
                    operation_id,
                    "signatureMapping",
                    f"Webhook security mapping is invalid for {operation_id}.",
                ):
                    continue
            dependency = dotted_object(mapping["dependency"])
            if dependency not in calls:
                if security_issue(
                    operation_id,
                    "signatureDependency",
                    f"{operation_id} lacks mapped provider dependency.",
                ):
                    continue
            verifier = dotted_object(mapping["verifier"])
            if not inspect.isfunction(verifier):
                if security_issue(
                    operation_id,
                    "signatureVerifier",
                    f"{operation_id} verifier is not concrete.",
                ):
                    continue
            try:
                require_collected_pytest_nodes({mapping["test"]})
            except SchemaError:
                if security_issue(
                    operation_id,
                    "signatureVerifierTest",
                    f"{operation_id} verifier test is missing.",
                ):
                    continue
        else:
            if security_issue(
                operation_id,
                "canonicalSecurity",
                f"{operation_id} has unsupported or ambiguous canonical security.",
            ):
                continue
    unused = {entry["id"] for entry in security_exceptions} - applied
    if unused:
        raise SchemaError(f"Security exceptions did not match an exact finding: {sorted(unused)}")
    if applied:
        print(f"Applied security exceptions: {sorted(applied)}")
    return applied


def write_check_reports(
    bundle: dict[str, Any],
    *,
    report_dir: Path = REPORT_DIR,
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    for name in ("normalization.json", "operation-map.json", "route-security.json"):
        (report_dir / name).unlink(missing_ok=True)
    runtime = runtime_bundle()
    canonical_map = operation_map(
        contract_for_runtime(bundle, admin_enabled=runtime_admin_enabled())
    )
    runtime_map = operation_map(runtime)
    write_json_report(
        report_dir / "operation-map.json",
        {
            "status": "passed" if canonical_map == runtime_map else "failed",
            "canonical": canonical_map,
            "runtime": runtime_map,
        },
    )
    if canonical_map != runtime_map:
        raise SchemaError("Canonical and runtime operation maps differ.")
    check_runtime_drift(bundle, report_path=report_dir / "normalization.json")
    try:
        applied_security_exceptions = check_route_security(bundle)
    except SchemaError as exc:
        write_json_report(
            report_dir / "route-security.json",
            {"status": "failed", "error": sanitized_report_error(exc)},
        )
        raise
    write_json_report(
        report_dir / "route-security.json",
        {
            "status": "passed",
            "appliedExceptions": sorted(applied_security_exceptions),
            "operations": sorted(
                operation["operationId"] for _, _, operation in iter_operations(bundle)
            ),
        },
    )


def operation_map(bundle: dict[str, Any]) -> dict[str, str]:
    return {
        operation["operationId"]: f"{method.upper()} {path}"
        for path, method, operation in iter_operations(bundle)
    }


def extract_contract_from_git(revision: str, destination: Path) -> bool:
    probe = run(
        ["git", "cat-file", "-e", f"{revision}:contracts/openapi/openapi.yaml"],
        check=False,
    )
    if probe.returncode:
        return False
    archive = subprocess.run(
        ["git", "archive", "--format=tar", revision, "contracts/openapi"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
    )
    if archive.returncode:
        raise SchemaError(f"Could not archive merge-base contract: {archive.stderr.decode()}")
    with tempfile.NamedTemporaryFile() as stream:
        stream.write(archive.stdout)
        stream.flush()
        with tarfile.open(stream.name) as tar:
            for member in tar.getmembers():
                parts = PurePosixPath(member.name).parts
                if (
                    member.issym()
                    or member.islnk()
                    or ".." in parts
                    or parts[:2] != ("contracts", "openapi")
                ):
                    raise SchemaError(f"Unsafe path in merge-base contract archive: {member.name}")
            tar.extractall(destination, filter="data")
    return True


@dataclass(frozen=True)
class CompatibilityBaseState:
    mode: str
    base_ref: str
    merge_base: str


def select_compatibility_baseline(
    *,
    event_name: str,
    before_sha: str,
    pull_request_base_sha: str,
) -> str:
    selected = pull_request_base_sha if event_name == "pull_request" else before_sha
    if not re.fullmatch(r"[0-9a-f]{40}", selected):
        raise ValueError(f"Invalid GitHub compatibility baseline SHA for {event_name}.")
    if selected == "0" * 40:
        raise ValueError("All-zero push baselines are never trusted compatibility baselines.")
    return selected


def classify_compatibility_base(
    *,
    repository: Path = ROOT,
    head: str = "HEAD",
    configured_ref: str | None = None,
    baseline_sha: str | None = None,
) -> CompatibilityBaseState:
    explicit_baseline = baseline_sha or os.environ.get("SCHEMA_BASE_SHA")
    if explicit_baseline == "0" * 40:
        raise SchemaError(
            "All-zero push baselines always fail closed. Establish the remote/default branch "
            "first without enabling the schema compatibility required check, then introduce "
            "the canonical schema through a pull request with a non-zero trusted base SHA. "
            "Alternatively, provide an explicit trusted prior commit SHA through a manually "
            "approved workflow path."
        )
    if explicit_baseline and not re.fullmatch(r"[0-9a-f]{40}", explicit_baseline):
        raise SchemaError("SCHEMA_BASE_SHA must be a full 40-character lowercase Git SHA.")
    explicit_ref = configured_ref or os.environ.get("SCHEMA_BASE_REF")
    candidates = (
        [explicit_ref]
        if explicit_ref
        else ([explicit_baseline] if explicit_baseline else ["origin/main", "main"])
    )
    base_ref = next(
        (
            candidate
            for candidate in candidates
            if candidate
            and run(
                ["git", "rev-parse", "--verify", "--quiet", candidate],
                cwd=repository,
                check=False,
            ).returncode
            == 0
        ),
        None,
    )
    if base_ref is None:
        requested = explicit_ref or "origin/main or main"
        raise SchemaError(
            f"Configured compatibility base ref {requested!r} is unavailable. "
            "Fetch the base branch with full history or set SCHEMA_BASE_REF to an existing "
            "local/fetched ref."
        )

    if explicit_baseline:
        if run(
            ["git", "rev-parse", "--verify", "--quiet", explicit_baseline],
            cwd=repository,
            check=False,
        ).returncode:
            raise SchemaError(
                "SCHEMA_BASE_SHA is unavailable locally. Fetch the event baseline commit "
                "with full history before compatibility checks."
            )
        merge_base = explicit_baseline
    else:
        merge_result = run(
            ["git", "merge-base", head, base_ref],
            cwd=repository,
            check=False,
        )
        merge_base = merge_result.stdout.strip()
        if merge_result.returncode or not merge_base:
            raise SchemaError(
                f"Git merge base for {head} and {base_ref} is unavailable. "
                "This is commonly a shallow checkout; fetch full history and the base ref, "
                "or set SCHEMA_BASE_REF explicitly."
            )

    contract_path = "contracts/openapi/openapi.yaml"

    def has_contract(revision: str) -> bool:
        return (
            run(
                ["git", "cat-file", "-e", f"{revision}:{contract_path}"],
                cwd=repository,
                check=False,
            ).returncode
            == 0
        )

    base_tip_has_contract = has_contract(base_ref)
    merge_base_has_contract = has_contract(merge_base)
    base_history_has_contract = bool(
        run(
            ["git", "log", base_ref, "--format=%H", "--", contract_path],
            cwd=repository,
        ).stdout.strip()
    )

    if not explicit_baseline and base_tip_has_contract and not merge_base_has_contract:
        raise SchemaError(
            f"Compatibility base {base_ref} has an established canonical schema, but merge base "
            f"{merge_base} does not. This stale branch cannot re-open bootstrap mode; rebase or "
            "merge the current base branch."
        )
    if not base_tip_has_contract and base_history_has_contract:
        raise SchemaError(
            f"Compatibility base {base_ref} removed an established canonical schema. "
            "Bootstrap mode cannot be selected again."
        )
    if merge_base_has_contract:
        return CompatibilityBaseState("compare", base_ref, merge_base)
    return CompatibilityBaseState("bootstrap", base_ref, merge_base)


def check_compatibility(base: Path | None = None, revision: Path = CANONICAL) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("oasdiff.json", "oasdiff-normalized.json"):
        (REPORT_DIR / name).unlink(missing_ok=True)
    exceptions = validate_exceptions()
    current = redocly_bundle(revision)
    validate_operation_ids(current)
    base_label = "explicit"
    if base is None:
        state = classify_compatibility_base()
        base_label = state.base_ref
        merge_base = state.merge_base
        temporary = tempfile.TemporaryDirectory(prefix="untangle-base-contract-")
        base_root = Path(temporary.name)
        if state.mode == "bootstrap":
            reject_unused_compatibility_exceptions(exceptions, context="bootstrap")
            evidence = (
                ROOT
                / "contracts"
                / "openapi"
                / "migration-evidence"
                / "fastapi-openapi-baseline.json"
            )
            adr = ROOT / "docs" / "adr" / "0002-canonical-openapi-schema-migration.md"
            if not evidence.is_file() or not adr.is_file():
                temporary.cleanup()
                raise SchemaError(
                    "First-schema bootstrap requires ADR 0002 and reviewed runtime evidence."
                )
            observed = json.loads(evidence.read_text(encoding="utf-8")).get("observed")
            if observed != {"openapi": "3.1.0", "paths": 15, "operations": 17, "schemas": 26}:
                temporary.cleanup()
                raise SchemaError(
                    "First-schema bootstrap evidence does not record the accepted 15/17/26 baseline."
                )
            temporary.cleanup()
            write_oasdiff_reports(
                raw_report="[]\n",
                findings=[],
                status="bootstrap",
                base_label=state.base_ref,
                applied=set(),
            )
            print(
                f"Compatibility bootstrap: {state.base_ref} tip and merge base "
                "truly have no canonical schema."
            )
            return
        if not extract_contract_from_git(merge_base, base_root):
            temporary.cleanup()
            raise SchemaError(
                f"Established canonical schema is unreadable at merge base {merge_base}."
            )
        base = base_root / "contracts" / "openapi" / "openapi.yaml"
    else:
        temporary = None

    try:
        baseline = redocly_bundle(base)
        old_map = operation_map(baseline)
        new_map = operation_map(current)
        for operation_id, location in old_map.items():
            if new_map.get(operation_id) != location:
                raise SchemaError(
                    f"Breaking operationId stability change: {operation_id}: "
                    f"{location} -> {new_map.get(operation_id)}"
                )
        old_reverse = {location: operation_id for operation_id, location in old_map.items()}
        new_reverse = {location: operation_id for operation_id, location in new_map.items()}
        for location, operation_id in old_reverse.items():
            if new_reverse.get(location) != operation_id:
                raise SchemaError(
                    f"Breaking method/path operationId change: {location}: "
                    f"{operation_id} -> {new_reverse.get(location)}"
                )
        try:
            run([str(OASDIFF_INSTALLER), "--verify"])
        except SchemaError as exc:
            write_raw_report(REPORT_DIR / "oasdiff.json", "")
            write_json_report(
                REPORT_DIR / "oasdiff-normalized.json",
                {
                    "status": "tool-error",
                    "base": base_label,
                    "findings": [],
                    "appliedExceptions": [],
                    "error": sanitized_report_error(exc),
                },
            )
            raise
        with tempfile.TemporaryDirectory(prefix="untangle-oasdiff-") as directory:
            bundled_base = Path(directory) / "base.json"
            bundled_revision = Path(directory) / "revision.json"
            bundled_base.write_text(
                json.dumps(baseline, sort_keys=True, separators=(",", ":")), encoding="utf-8"
            )
            bundled_revision.write_text(
                json.dumps(current, sort_keys=True, separators=(",", ":")), encoding="utf-8"
            )
            result = run(
                [
                    str(OASDIFF),
                    "breaking",
                    "base.json",
                    "revision.json",
                    "--allow-external-refs=false",
                    "--fail-on",
                    "ERR",
                    "--format",
                    "json",
                ],
                cwd=Path(directory),
                check=False,
            )
        if result.returncode:
            report = result.stdout + result.stderr
            try:
                findings = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                write_raw_report(REPORT_DIR / "oasdiff.json", result.stdout)
                write_json_report(
                    REPORT_DIR / "oasdiff-normalized.json",
                    {
                        "status": "tool-error",
                        "base": base_label,
                        "findings": [],
                        "appliedExceptions": [],
                        "error": "oasdiff returned invalid JSON.",
                    },
                )
                raise SchemaError(
                    f"oasdiff failed without a valid JSON finding report:\n{report}"
                ) from exc
            if not isinstance(findings, list) or not findings:
                write_raw_report(REPORT_DIR / "oasdiff.json", result.stdout)
                write_json_report(
                    REPORT_DIR / "oasdiff-normalized.json",
                    {
                        "status": "tool-error",
                        "base": base_label,
                        "findings": [],
                        "appliedExceptions": [],
                        "error": "oasdiff returned no breaking findings with a failing status.",
                    },
                )
                raise SchemaError(f"oasdiff tool failure or empty breaking report:\n{report}")
            write_oasdiff_reports(
                raw_report=result.stdout,
                findings=findings,
                status="failed",
                base_label=base_label,
                applied=set(),
            )
            applied = apply_compatibility_exceptions(findings, exceptions)
            write_oasdiff_reports(
                raw_report=result.stdout,
                findings=findings,
                status="waived",
                base_label=base_label,
                applied=applied,
            )
            print(f"Applied compatibility exceptions: {sorted(applied)}")
            return
        reject_unused_compatibility_exceptions(exceptions, context="compatibility check")
        write_oasdiff_reports(
            raw_report=result.stdout,
            findings=[],
            status="passed",
            base_label=base_label,
            applied=set(),
        )
        print("oasdiff compatibility: no breaking changes.")
    finally:
        if temporary is not None:
            temporary.cleanup()


def validate() -> dict[str, Any]:
    bundle = redocly_bundle()
    validate_operation_ids(bundle)
    contract_for_runtime(bundle, admin_enabled=True)
    validate_contract_metadata(bundle)
    validate_exceptions()
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    generate_parser = subparsers.add_parser("generate")
    generate_parser.add_argument("--output-root", type=Path, default=ROOT)
    admin_parser = subparsers.add_parser("generate-admin")
    admin_parser.add_argument("--output", type=Path, required=True)
    subparsers.add_parser("check")
    compatibility_parser = subparsers.add_parser("compatibility")
    compatibility_parser.add_argument("--base", type=Path)
    compatibility_parser.add_argument("--revision", type=Path, default=CANONICAL)
    args = parser.parse_args()
    try:
        if args.command == "validate":
            validate()
        elif args.command == "generate":
            validate()
            write_generated(args.output_root.resolve())
        elif args.command == "generate-admin":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(generated_admin_models(redocly_bundle()))
        elif args.command == "check":
            bundle = validate()
            check_generated()
            check_extension_consumer(bundle)
            write_check_reports(
                bundle,
                report_dir=REPORT_DIR / "admin-enabled" if runtime_admin_enabled() else REPORT_DIR,
            )
        elif args.command == "compatibility":
            check_compatibility(args.base, args.revision)
        return 0
    except SchemaError as exc:
        print(f"schema: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
