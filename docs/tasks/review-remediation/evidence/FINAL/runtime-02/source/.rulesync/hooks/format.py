#!/usr/bin/env python3
"""Safely format one repository file reported by an agent hook."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

MAX_INPUT_BYTES = 1024 * 1024
FORMAT_TIMEOUT_SECONDS = 10
PYTHON_SUFFIXES = {".py"}
PRETTIER_SUFFIXES = {".css", ".html", ".js", ".json", ".mjs"}
SKIPPED_PARTS = {
    ".git",
    ".terraform",
    ".tools",
    ".venv",
    "build",
    "dist",
    "generated",
    "node_modules",
    "output",
    "vendor",
    "venv",
}


def read_payload() -> dict | None:
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        return None
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def original_tool_failed(payload: dict) -> bool:
    if payload.get("success") is False or payload.get("tool_error"):
        return True
    response = payload.get("tool_response")
    return isinstance(response, dict) and (
        response.get("is_error") is True or response.get("success") is False
    )


def changed_path(payload: dict) -> str | None:
    candidates = [payload, payload.get("tool_input")]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key in ("file_path", "filePath", "path"):
            value = candidate.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def safe_repository_path(root: Path, reported_path: str) -> Path | None:
    candidate = Path(reported_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=True)
        relative = resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    if not resolved.is_file() or any(part in SKIPPED_PARTS for part in relative.parts):
        return None
    if (
        resolved.name == "package-lock.json"
        or resolved.name == ".terraform.lock.hcl"
        or (
            resolved.parent.name == "backend"
            and resolved.name.startswith("requirements")
            and resolved.suffix == ".txt"
        )
    ):
        return None
    return resolved


def formatter_command(root: Path, path: Path) -> list[str] | None:
    if path.suffix in PYTHON_SUFFIXES:
        python = root / "backend" / ".venv" / "bin" / "python"
        if python.is_file():
            return [str(python), "-m", "ruff", "format", str(path)]
    if path.suffix in PRETTIER_SUFFIXES:
        prettier = root / "extension" / "node_modules" / ".bin" / "prettier"
        if prettier.is_file():
            return [str(prettier), "--write", str(path)]
    return None


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    payload = read_payload()
    if payload is None or original_tool_failed(payload):
        return 0
    reported_path = changed_path(payload)
    if reported_path is None:
        return 0
    path = safe_repository_path(root, reported_path)
    if path is None:
        return 0
    command = formatter_command(root, path)
    if command is None:
        return 0
    try:
        return subprocess.run(
            command, cwd=root, check=False, timeout=FORMAT_TIMEOUT_SECONDS
        ).returncode
    except subprocess.TimeoutExpired:
        print(f"Formatter timed out after {FORMAT_TIMEOUT_SECONDS}s: {path}", file=sys.stderr)
        return 124


if __name__ == "__main__":
    raise SystemExit(main())
