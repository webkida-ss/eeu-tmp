#!/usr/bin/env python3
"""Scan git-tracked files for credentials and hardcoded account identifiers.

This is the local canonical secret scan. It is intentionally service-free:
it reads the working tree and never calls a provider. Fixture strings used
by sanitizer tests are allowlisted by exact value.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_IDENTIFIERS = ("-".join(("kst", "sakakida", "tf", "for", "state")),)

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github_token", re.compile(r"\b(?:ghp_|gho_|github_pat_)[A-Za-z0-9_]{20,}")),
    ("openai_like_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}")),
    ("stripe_live_key", re.compile(r"\bsk_live_[A-Za-z0-9]{10,}")),
    ("stripe_test_key", re.compile(r"\bsk_test_[A-Za-z0-9]{16,}")),
    ("stripe_webhook_secret", re.compile(r"\bwhsec_[A-Za-z0-9]{16,}")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
)

PRIVATE_KEY_BODY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----\s+MII[A-Za-z0-9+/=\s]{40,}",
    re.MULTILINE,
)

ALLOWLISTED_VALUES = {
    "AKIAIOSFODNN7EXAMPLE",
    "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
    "sk-proj-abcdefghijklmnopqrstuvwxyz",
    "sk-proj-supersecretvalue",
    "sk_test_dummy",
    "whsec_dummy",
}

SKIP_SUFFIXES = {
    ".lock",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".woff",
    ".woff2",
    ".ico",
}


def tracked_files(root: Path) -> list[Path]:
    listing = subprocess.check_output(
        ["git", "ls-files", "-z"],
        cwd=root,
        text=True,
    )
    return [root / relative for relative in listing.split("\0") if relative]


def is_skippable(path: Path) -> bool:
    return path.suffix.lower() in SKIP_SUFFIXES or path.name in {
        "package-lock.json",
        "Cargo.lock",
    }


def scan_text(text: str) -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    for match in PRIVATE_KEY_BODY.finditer(text):
        line_number = text.count("\n", 0, match.start()) + 1
        findings.append(("private_key_block", line_number, match.group(0)[:32]))
    for line_number, line in enumerate(text.splitlines(), start=1):
        for identifier in FORBIDDEN_IDENTIFIERS:
            if identifier in line:
                findings.append(("hardcoded_identifier", line_number, identifier))
        for name, pattern in PATTERNS:
            for match in pattern.finditer(line):
                value = match.group(0)
                if value in ALLOWLISTED_VALUES:
                    continue
                if "example" in value.lower() or "dummy" in value.lower():
                    continue
                if "replace" in value.lower() or "abcdefghijklmnopqrstuvwxyz" in value:
                    continue
                findings.append((name, line_number, value))
    return findings


def scan_repository(root: Path) -> list[tuple[str, str, int, str]]:
    findings: list[tuple[str, str, int, str]] = []
    for path in tracked_files(root):
        if is_skippable(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        relative = str(path.relative_to(root))
        for kind, line_number, value in scan_text(text):
            findings.append((relative, kind, line_number, value))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Repository root to scan (defaults to this repository).",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    findings = scan_repository(root)
    if not findings:
        print("No credential or forbidden-identifier findings in tracked files.")
        return 0
    for path, kind, line_number, value in findings:
        preview = value if kind == "hardcoded_identifier" else f"{value[:8]}…(len {len(value)})"
        print(f"{path}:{line_number}: {kind}: {preview}", file=sys.stderr)
    print(f"Secret scan failed with {len(findings)} finding(s).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
