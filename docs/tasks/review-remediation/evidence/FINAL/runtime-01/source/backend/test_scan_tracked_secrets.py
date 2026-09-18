from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import scan_tracked_secrets  # noqa: E402


def test_scan_text_allows_documented_fixtures() -> None:
    text = "\n".join(
        [
            "AKIAIOSFODNN7EXAMPLE",
            "sk-proj-supersecretvalue",
            "sk_test_dummy",
            "whsec_dummy",
        ]
    )
    assert scan_tracked_secrets.scan_text(text) == []


def test_scan_text_flags_private_key_material() -> None:
    findings = scan_tracked_secrets.scan_text(
        "-----BEGIN PRIVATE KEY-----\nMIIBOgIBAAJBAK8"
        + ("A" * 40)
        + "\n-----END PRIVATE KEY-----\n"
    )
    assert any(kind == "private_key_block" for kind, _line, _value in findings)


def test_scan_text_flags_live_key_shapes_and_old_bucket_name() -> None:
    bucket = "-".join(("kst", "sakakida", "tf", "for", "state"))
    findings = scan_tracked_secrets.scan_text(
        "\n".join(
            [
                "sk-proj-" + "looksrealenoughforascanner",
                f'bucket = "{bucket}"',
            ]
        )
    )
    kinds = {kind for kind, _line, _value in findings}
    assert "openai_like_key" in kinds
    assert "hardcoded_identifier" in kinds


def test_backend_tf_does_not_pin_a_bucket_name() -> None:
    for environment in ("dev", "prod"):
        text = (ROOT / "infra" / "envs" / environment / "backend.tf").read_text(encoding="utf-8")
        assert re.search(r"(?m)^\s*bucket\s*=", text) is None
        assert "replace-with-state-bucket" not in text


def test_tracked_repository_has_no_secret_findings() -> None:
    assert scan_tracked_secrets.scan_repository(ROOT) == []
