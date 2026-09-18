from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "workspace-manifest.py"
EXCLUDES = ROOT / ".devcontainer" / "workspace-manifest-excludes.json"


def prepare_workspace(tmp_path: Path, *, git: bool) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / ".devcontainer").mkdir(parents=True)
    (workspace / ".devcontainer" / EXCLUDES.name).write_bytes(EXCLUDES.read_bytes())
    (workspace / "tracked.txt").write_text("tracked baseline\n", encoding="utf-8")
    (workspace / "untracked.txt").write_text("untracked baseline\n", encoding="utf-8")
    if git:
        (workspace / ".gitignore").write_text("*.secret\n", encoding="utf-8")
        (workspace / "preexisting.secret").write_text("ignored but protected\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(workspace)], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(workspace),
                "add",
                ".devcontainer",
                ".gitignore",
                "tracked.txt",
            ],
            check=True,
        )
        (workspace / "tracked.txt").write_text("already dirty\n", encoding="utf-8")
    else:
        (workspace / ".git").write_text(
            "gitdir: /host/path/not-mounted/.git/worktrees/example\n",
            encoding="utf-8",
        )
    return workspace


def capture(workspace: Path, manifest: Path, *, fallback: bool = False) -> None:
    command = [
        sys.executable,
        str(SCRIPT),
        "capture",
        "--root",
        str(workspace),
        "--manifest",
        str(manifest),
    ]
    if fallback:
        command.append("--force-fallback")
    subprocess.run(command, check=True)


def verify(
    workspace: Path, manifest: Path, *, fallback: bool = False
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(SCRIPT),
        "verify",
        "--root",
        str(workspace),
        "--manifest",
        str(manifest),
    ]
    if fallback:
        command.append("--force-fallback")
    return subprocess.run(command, check=False, capture_output=True, text=True)


@pytest.mark.parametrize("git", [True, False])
def test_manifest_is_content_aware_for_dirty_and_untracked_files(tmp_path: Path, git: bool) -> None:
    workspace = prepare_workspace(tmp_path, git=git)
    manifest = tmp_path / "manifest.json"
    capture(workspace, manifest, fallback=not git)
    baseline = json.loads(manifest.read_text(encoding="utf-8"))
    assert baseline["strategy"] == ("git" if git else "fallback")

    (workspace / "tracked.txt").write_text("dirty file changed again\n", encoding="utf-8")
    (workspace / "untracked.txt").write_text("untracked file changed\n", encoding="utf-8")
    if git:
        assert "preexisting.secret" in baseline["entries"]
        (workspace / "preexisting.secret").write_text("ignored file changed\n", encoding="utf-8")
    result = verify(workspace, manifest, fallback=not git)
    assert result.returncode == 1
    assert "modified: tracked.txt" in result.stderr
    assert "modified: untracked.txt" in result.stderr
    if git:
        assert "modified: preexisting.secret" in result.stderr


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("add", "added: added.txt"),
        ("delete", "deleted: untracked.txt"),
        ("executable", "modified: tracked.txt"),
        ("symlink", "modified: link.txt"),
    ],
)
def test_fallback_detects_add_delete_mode_and_symlink_changes(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    workspace = prepare_workspace(tmp_path, git=False)
    first_target = tmp_path / "outside-one"
    second_target = tmp_path / "outside-two"
    first_target.write_text("outside content must not be read\n", encoding="utf-8")
    second_target.write_text("different outside content\n", encoding="utf-8")
    (workspace / "link.txt").symlink_to(first_target)
    manifest = tmp_path / "manifest.json"
    capture(workspace, manifest, fallback=True)

    if mutation == "add":
        (workspace / "added.txt").write_text("new\n", encoding="utf-8")
    elif mutation == "delete":
        (workspace / "untracked.txt").unlink()
    elif mutation == "executable":
        os.chmod(workspace / "tracked.txt", 0o755)
    else:
        (workspace / "link.txt").unlink()
        (workspace / "link.txt").symlink_to(second_target)

    result = verify(workspace, manifest, fallback=True)
    assert result.returncode == 1
    assert expected in result.stderr


@pytest.mark.parametrize("git", [True, False])
def test_manifest_excludes_only_declared_runtime_directories(tmp_path: Path, git: bool) -> None:
    workspace = prepare_workspace(tmp_path, git=git)
    manifest = tmp_path / "manifest.json"
    capture(workspace, manifest, fallback=not git)

    for relative in (
        ".devcontainer-tools/cache.bin",
        "backend/.devcontainer-venv/state.bin",
        "node_modules/package/file.js",
        "extension/node_modules/package/file.js",
        "output/report.json",
    ):
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("generated\n", encoding="utf-8")

    result = verify(workspace, manifest, fallback=not git)
    assert result.returncode == 0, result.stderr

    unrelated = workspace / "frontend" / "node_modules" / "package" / "file.js"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("not an excluded runtime path\n", encoding="utf-8")
    result = verify(workspace, manifest, fallback=not git)
    assert result.returncode == 1
    assert "added: frontend/node_modules/package/file.js" in result.stderr
