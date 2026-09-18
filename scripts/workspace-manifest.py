from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path(__file__).resolve().parents[1]


def load_excludes(root: Path) -> dict[str, Any]:
    path = root / ".devcontainer" / "workspace-manifest-excludes.json"
    return json.loads(path.read_text(encoding="utf-8"))


def git_paths(root: Path, excludes: dict[str, Any]) -> list[str] | None:
    probe = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode or probe.stdout.strip() != "true":
        return None
    result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "ls-files",
            "-z",
            "--cached",
            "--others",
        ],
        check=True,
        capture_output=True,
    )
    paths = (path.decode("utf-8") for path in result.stdout.split(b"\0") if path)
    return sorted(path for path in paths if not is_excluded(path, excludes, directory=False))


def is_excluded(path: str, excludes: dict[str, Any], *, directory: bool) -> bool:
    parts = Path(path).parts
    if any(name in excludes["directoryNames"] for name in parts):
        return True
    if any(
        path == prefix or path.startswith(f"{prefix}/")
        for prefix in excludes["relativeDirectories"]
    ):
        return True
    if not directory and any(path.endswith(suffix) for suffix in excludes["fileSuffixes"]):
        return True
    return False


def fallback_paths(root: Path, excludes: dict[str, Any]) -> list[str]:
    paths: list[str] = []

    def visit(directory: Path, relative: str = "") -> None:
        with os.scandir(directory) as entries:
            for entry in sorted(entries, key=lambda item: item.name):
                path = f"{relative}/{entry.name}" if relative else entry.name
                if entry.is_symlink():
                    if not is_excluded(path, excludes, directory=False):
                        paths.append(path)
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if not is_excluded(path, excludes, directory=True):
                        visit(Path(entry.path), path)
                    continue
                if not is_excluded(path, excludes, directory=False):
                    paths.append(path)

    visit(root)
    return paths


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def describe_path(root: Path, relative: str) -> dict[str, Any]:
    path = root / relative
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return {"type": "missing"}
    if stat.S_ISLNK(metadata.st_mode):
        target = os.readlink(path)
        return {
            "type": "symlink",
            "targetSha256": hashlib.sha256(os.fsencode(target)).hexdigest(),
            "target": target,
        }
    if stat.S_ISREG(metadata.st_mode):
        return {
            "type": "file",
            "sha256": hash_file(path),
            "executable": bool(metadata.st_mode & 0o111),
        }
    raise RuntimeError(f"Unsupported workspace entry type: {relative}")


def capture(
    root: Path, *, force_fallback: bool = False, strategy: str | None = None
) -> dict[str, Any]:
    excludes = load_excludes(root)
    paths = None if force_fallback or strategy == "fallback" else git_paths(root, excludes)
    if strategy == "git" and paths is None:
        raise RuntimeError("Git metadata used by the baseline is no longer available.")
    selected_strategy = "fallback" if paths is None else "git"
    if strategy and selected_strategy != strategy:
        raise RuntimeError(
            f"Workspace traversal strategy changed: {strategy} -> {selected_strategy}"
        )
    if paths is None:
        paths = fallback_paths(root, excludes)
    entries = {path: describe_path(root, path) for path in paths}
    return {
        "schemaVersion": 1,
        "strategy": selected_strategy,
        "entries": entries,
    }


def differences(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    changes: list[str] = []
    before_entries = before["entries"]
    after_entries = after["entries"]
    for path in sorted(set(before_entries) | set(after_entries)):
        if path not in before_entries:
            changes.append(f"added: {path}")
        elif path not in after_entries:
            changes.append(f"deleted: {path}")
        elif before_entries[path] != after_entries[path]:
            changes.append(f"modified: {path}")
    return changes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("capture", "verify"))
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--force-fallback", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    if args.command == "capture":
        manifest = capture(root, force_fallback=args.force_fallback)
        args.manifest.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 0

    before = json.loads(args.manifest.read_text(encoding="utf-8"))
    after = capture(
        root,
        force_fallback=args.force_fallback,
        strategy=before["strategy"],
    )
    changes = differences(before, after)
    if changes:
        print("Workspace source changed during setup:", file=sys.stderr)
        for change in changes:
            print(f"  {change}", file=sys.stderr)
        return 1
    print(f"Workspace source manifest unchanged ({before['strategy']} traversal).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
