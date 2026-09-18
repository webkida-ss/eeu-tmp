from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".rulesync" / "hooks" / "format.sh"


def run_hook(payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(HOOK)],
        cwd=ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )


def temporary_repository_file(directory: Path, suffix: str, content: str):
    path = directory / f".format-hook-{uuid.uuid4().hex}{suffix}"
    path.write_text(content, encoding="utf-8")
    return path


def test_formats_changed_supported_repository_file():
    path = temporary_repository_file(ROOT / "extension", ".js", "const value={answer:42};\n")
    try:
        result = run_hook({"tool_input": {"file_path": str(path)}})
        assert result.returncode == 0, result.stderr
        assert path.read_text(encoding="utf-8") == "const value = { answer: 42 };\n"
    finally:
        path.unlink(missing_ok=True)


def test_rejects_path_outside_repository(tmp_path):
    path = tmp_path / "outside.js"
    path.write_text("const value={answer:42};\n", encoding="utf-8")
    result = run_hook({"file_path": str(path)})
    assert result.returncode == 0, result.stderr
    assert path.read_text(encoding="utf-8") == "const value={answer:42};\n"


def test_rejects_symlink_escape(tmp_path):
    outside = tmp_path / "outside.js"
    outside.write_text("const value={answer:42};\n", encoding="utf-8")
    link = ROOT / "extension" / f".format-hook-{uuid.uuid4().hex}.js"
    link.symlink_to(outside)
    try:
        result = run_hook({"tool_input": {"path": str(link)}})
        assert result.returncode == 0, result.stderr
        assert outside.read_text(encoding="utf-8") == "const value={answer:42};\n"
    finally:
        link.unlink(missing_ok=True)


def test_skips_generated_and_lock_files():
    generated = temporary_repository_file(
        ROOT / "extension" / "generated", ".js", "const value={answer:42};\n"
    )
    lock = ROOT / "extension" / "package-lock.json"
    before_lock = lock.read_bytes()
    try:
        generated_result = run_hook({"file_path": str(generated)})
        lock_result = run_hook({"file_path": str(lock)})
        assert generated_result.returncode == 0, generated_result.stderr
        assert lock_result.returncode == 0, lock_result.stderr
        assert generated.read_text(encoding="utf-8") == "const value={answer:42};\n"
        assert lock.read_bytes() == before_lock
    finally:
        generated.unlink(missing_ok=True)


def test_skips_formatting_when_original_tool_failed():
    path = temporary_repository_file(ROOT / "extension", ".js", "const value={answer:42};\n")
    try:
        result = run_hook(
            {
                "tool_input": {"file_path": str(path)},
                "tool_response": {"is_error": True},
            }
        )
        assert result.returncode == 0, result.stderr
        assert path.read_text(encoding="utf-8") == "const value={answer:42};\n"
    finally:
        path.unlink(missing_ok=True)


def test_malformed_and_oversized_input_returns_promptly():
    malformed = subprocess.run(
        [str(HOOK)],
        cwd=ROOT,
        input="{",
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )
    oversized = subprocess.run(
        [str(HOOK)],
        cwd=ROOT,
        input=json.dumps({"file_path": "x" * (1024 * 1024 + 1)}),
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )
    assert malformed.returncode == 0
    assert oversized.returncode == 0


def test_rulesync_and_generated_hook_configs_stay_consistent():
    rulesync = json.loads((ROOT / ".rulesync" / "hooks.json").read_text(encoding="utf-8"))
    cursor = json.loads((ROOT / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
    claude = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    codex = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))

    expected = rulesync["hooks"]["postToolUse"][0]
    assert expected == {
        "matcher": "Write|Edit",
        "command": ".rulesync/hooks/format.sh",
        "timeout": 15,
    }
    assert cursor["hooks"]["postToolUse"][0] == {
        "command": expected["command"],
        "matcher": expected["matcher"],
        "timeout": expected["timeout"],
    }
    for generated in (claude, codex):
        hook = generated["hooks"]["PostToolUse"][0]
        assert hook["matcher"] == expected["matcher"]
        command_hook = hook["hooks"][0]
        assert command_hook["type"] == "command"
        assert command_hook["timeout"] == expected["timeout"]
        assert command_hook["command"].endswith(expected["command"])
