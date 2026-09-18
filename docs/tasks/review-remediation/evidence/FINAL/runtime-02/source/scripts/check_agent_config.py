#!/usr/bin/env python3
"""Verify generated agent configuration without external side effects."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

RULE_NAMES = (
    "api",
    "backend/backend",
    "backend/go",
    "backend/rust",
    "basic-strategy",
    "data-model",
    "documentation",
    "frontend/frontend",
    "frontend/next",
    "frontend/nuxt",
    "infra/aws",
    "infra/terraform",
    "task",
)
SHARED_SKILL_FILES = (
    "ci-failure-triage/SKILL.md",
    "design-direction/SKILL.md",
    "design-direction/references/design-direction-template.md",
    "extract-ubiquitous-language/SKILL.md",
    "init-project/SKILL.md",
    "init-project/references/gitignore.template",
    "init-project/scripts/scaffold.sh",
    "online-task-intake/SKILL.md",
    "pr-evidence-preparation/SKILL.md",
    "release-preparation/SKILL.md",
    "verify-agents/SKILL.md",
)
SUBAGENT_NAMES = (
    "ci-investigator",
    "correctness-reviewer",
    "implementer",
    "planner",
    "release-preparer",
    "security-reviewer",
    "test-runner",
)
MANAGED_DIRECTORIES = (".cursor", ".claude", ".codex", ".agents")
MANAGED_ROOT_FILES = ("AGENTS.md", ".mcp.json")
UNMANAGED_LOCAL_FILES = {
    ".claude/settings.local.json",
}
UNMANAGED_LOCAL_SUFFIXES = (".log",)
# No target overlays are currently required. Any future overlay must be listed
# here, documented, copied as a regular file, and applied after clean generation.
OVERLAY_FILES: tuple[tuple[str, str], ...] = ()
EXPECTED_MCP = {
    "context7": {
        "type": "stdio",
        "command": "./node_modules/.bin/context7-mcp",
        "args": [],
        "env": {},
    },
    "playwright": {
        "type": "stdio",
        "command": "./node_modules/.bin/playwright-mcp",
        "args": [],
        "env": {},
    },
}
LOCKED_PACKAGES = {
    "rulesync": ("14.0.1", "rulesync", "dist/cli/index.js"),
    "@upstash/context7-mcp": ("3.2.4", "context7-mcp", "dist/index.js"),
    "@playwright/mcp": ("0.0.78", "playwright-mcp", "cli.js"),
}
SECRET_DENY_PATTERNS = {
    ".env",
    "**/.env",
    ".env.local",
    "**/.env.local",
    ".env.development.local",
    "**/.env.development.local",
    ".env.test.local",
    "**/.env.test.local",
    ".env.production.local",
    "**/.env.production.local",
    "credentials/**",
    "**/credentials/**",
    ".aws/**",
    "**/.aws/**",
    ".ssh/**",
    "**/.ssh/**",
    ".config/gcloud/**",
    "**/.config/gcloud/**",
    "**/*.key",
    "**/*.pem",
    "**/*.p12",
    "**/*.pfx",
    "**/*.crt",
    "**/*.cer",
    "**/*.tfstate",
    "**/*.tfstate.*",
    "**/*.tfvars",
}


@dataclass(frozen=True)
class Entry:
    kind: str
    mode: int
    data: bytes = b""


def expected_files() -> set[str]:
    files = {
        "AGENTS.md",
        ".mcp.json",
        ".cursor/cli.json",
        ".cursor/hooks.json",
        ".cursor/mcp.json",
        ".claude/settings.json",
        ".claude/skills/reload/SKILL.md",
        ".codex/config.toml",
        ".codex/hooks.json",
        ".codex/rules/rulesync.rules",
    }
    for name in SUBAGENT_NAMES:
        files.add(f".cursor/agents/{name}.md")
        files.add(f".claude/agents/{name}.md")
        files.add(f".codex/agents/{name}.toml")
    for name in RULE_NAMES:
        files.add(f".cursor/rules/{name}.mdc")
        files.add(f".claude/rules/{name}.md")
        files.add(f".agents/memories/{name}.md")
    for name in SHARED_SKILL_FILES:
        files.add(f".cursor/skills/{name}")
        files.add(f".claude/skills/{name}")
        files.add(f".agents/skills/{name}")
    return files


def expected_inventory_paths() -> set[str]:
    paths = set(expected_files())
    for relative in tuple(paths):
        parent = Path(relative).parent
        while parent.as_posix() not in ("", "."):
            paths.add(parent.as_posix())
            parent = parent.parent
    return paths


def regular_bytes(path: Path) -> bytes:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"Expected regular file, found unsafe type: {path}")
    return path.read_bytes()


def normalized_mode(metadata: os.stat_result, *, directory: bool) -> int:
    actual = stat.S_IMODE(metadata.st_mode)
    expected = 0o755 if directory or actual & 0o111 else 0o644
    if actual != expected:
        raise RuntimeError(f"Unsafe mode {actual:o}; expected {expected:o}")
    return expected


def scan_directory(root: Path, directory: Path, inventory: dict[str, Entry]) -> None:
    metadata = directory.lstat()
    if not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError(f"Expected directory, found unsafe type: {directory}")
    relative = directory.relative_to(root).as_posix()
    inventory[relative] = Entry("directory", normalized_mode(metadata, directory=True))
    with os.scandir(directory) as entries:
        for item in sorted(entries, key=lambda entry: entry.name):
            path = Path(item.path)
            metadata = path.lstat()
            relative = path.relative_to(root).as_posix()
            if relative in UNMANAGED_LOCAL_FILES or relative.endswith(UNMANAGED_LOCAL_SUFFIXES):
                continue
            if stat.S_ISLNK(metadata.st_mode):
                raise RuntimeError(f"Symlink rejected in generated inventory: {relative}")
            if stat.S_ISDIR(metadata.st_mode):
                scan_directory(root, path, inventory)
            elif stat.S_ISREG(metadata.st_mode):
                inventory[relative] = Entry(
                    "file",
                    normalized_mode(metadata, directory=False),
                    regular_bytes(path),
                )
            else:
                raise RuntimeError(f"Unsafe generated path type: {relative}")


def scan_generated(root: Path) -> dict[str, Entry]:
    inventory: dict[str, Entry] = {}
    for relative in MANAGED_DIRECTORIES:
        path = root / relative
        if os.path.lexists(path):
            scan_directory(root, path, inventory)
    for relative in MANAGED_ROOT_FILES:
        path = root / relative
        if not os.path.lexists(path):
            continue
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError(f"Unsafe generated root file type: {relative}")
        inventory[relative] = Entry(
            "file", normalized_mode(metadata, directory=False), regular_bytes(path)
        )
    return inventory


def copy_regular_file(source: Path, destination: Path) -> None:
    metadata = source.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"Canonical input must be a regular file: {source}")
    mode = normalized_mode(metadata, directory=False)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    if os.path.lexists(destination):
        destination_metadata = destination.lstat()
        if not stat.S_ISREG(destination_metadata.st_mode):
            raise RuntimeError(f"Copy destination must be a regular file: {destination}")
        flags = os.O_WRONLY | os.O_TRUNC
    else:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(destination, flags, mode)
    try:
        os.write(descriptor, source.read_bytes())
    finally:
        os.close(descriptor)
    destination.chmod(mode)


def copy_regular_tree(source: Path, destination: Path) -> None:
    metadata = source.lstat()
    if not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError(f"Canonical input must be a directory: {source}")
    normalized_mode(metadata, directory=True)
    destination.mkdir(parents=True, exist_ok=True, mode=0o755)
    with os.scandir(source) as entries:
        for item in sorted(entries, key=lambda entry: entry.name):
            source_path = Path(item.path)
            destination_path = destination / item.name
            metadata = source_path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise RuntimeError(f"Symlink rejected in canonical input: {source_path}")
            if stat.S_ISDIR(metadata.st_mode):
                copy_regular_tree(source_path, destination_path)
            elif stat.S_ISREG(metadata.st_mode):
                copy_regular_file(source_path, destination_path)
            else:
                raise RuntimeError(f"Unsafe canonical input type: {source_path}")


def inventory_digest(inventory: dict[str, Entry]) -> str:
    digest = hashlib.sha256()
    for name in sorted(inventory):
        entry = inventory[name]
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(entry.kind.encode("ascii"))
        digest.update(b"\0")
        digest.update(f"{entry.mode:o}".encode("ascii"))
        digest.update(b"\0")
        digest.update(entry.data)
        digest.update(b"\0")
    return digest.hexdigest()


def assert_inventory(actual: dict[str, Entry], expected: dict[str, Entry]) -> None:
    actual_paths = set(actual)
    expected_paths = set(expected)
    missing = sorted(expected_paths - actual_paths)
    extra = sorted(actual_paths - expected_paths)
    if missing or extra:
        raise RuntimeError(f"Generated inventory drifted; missing={missing}, extra={extra}")
    for relative in sorted(expected):
        if actual[relative] != expected[relative]:
            raise RuntimeError(f"Generated type, mode, or bytes drifted: {relative}")


def write_clean_inventory(root: Path, clean: dict[str, Entry]) -> None:
    current = scan_generated(root)
    extra = sorted(set(current) - set(clean))
    if extra:
        raise RuntimeError(f"Refusing to overwrite unexpected generated paths: {extra}")
    for relative, entry in sorted(clean.items(), key=lambda item: (item[0].count("/"), item[0])):
        path = root / relative
        if entry.kind == "directory":
            if os.path.lexists(path):
                metadata = path.lstat()
                if not stat.S_ISDIR(metadata.st_mode):
                    raise RuntimeError(f"Refusing to replace unsafe path: {relative}")
            else:
                path.mkdir(mode=entry.mode)
            path.chmod(entry.mode)
            continue
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        if os.path.lexists(path):
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode):
                raise RuntimeError(f"Refusing to replace unsafe path: {relative}")
            flags = os.O_WRONLY | os.O_TRUNC
        else:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, entry.mode)
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as output:
                output.write(entry.data)
                output.flush()
                os.fsync(output.fileno())
        finally:
            os.close(descriptor)
        path.chmod(entry.mode, follow_symlinks=False)


def assert_hardcoded_inventory(inventory: dict[str, Entry]) -> None:
    expected = expected_inventory_paths()
    actual = set(inventory)
    if actual != expected:
        raise RuntimeError(
            "Clean generation inventory changed; "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def run_clean_generation(root: Path, rulesync: Path) -> dict[str, Entry]:
    with tempfile.TemporaryDirectory(prefix="untangle-agents-clean-") as temporary:
        clean = Path(temporary)
        copy_regular_tree(root / ".rulesync", clean / ".rulesync")
        for relative in ("rulesync.jsonc", "package.json", "package-lock.json"):
            copy_regular_file(root / relative, clean / relative)
        overlay_inputs: list[tuple[Path, str]] = []
        for index, (source, target) in enumerate(OVERLAY_FILES):
            copied = clean / ".rulesync-overlay-inputs" / str(index)
            copy_regular_file(root / source, copied)
            overlay_inputs.append((copied, target))

        command = [str(rulesync), "generate", "--config", str(clean / "rulesync.jsonc")]
        subprocess.run(command, cwd=clean, check=True, capture_output=True, text=True)
        for source, target in overlay_inputs:
            copy_regular_file(source, clean / target)
        first = scan_generated(clean)
        assert_hardcoded_inventory(first)
        first_digest = inventory_digest(first)

        subprocess.run(command, cwd=clean, check=True, capture_output=True, text=True)
        for source, target in overlay_inputs:
            copy_regular_file(source, clean / target)
        second = scan_generated(clean)
        if first_digest != inventory_digest(second) or first != second:
            raise RuntimeError("Second clean Rulesync generation was not deterministic")
        return first


def lexical_relative(path: Path, parent: Path) -> Path:
    try:
        return path.relative_to(parent)
    except ValueError as error:
        raise RuntimeError(f"Path escapes expected package directory: {path}") from error


def require_directory(path: Path) -> None:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError(f"Expected non-symlink directory: {path}")


def validate_directory_chain(root: Path, relative: Path) -> Path:
    current = root
    for part in relative.parts:
        current /= part
        require_directory(current)
    return current


def validate_bin_link(root: Path, package: str, executable: str, target: str) -> None:
    node_modules = validate_directory_chain(root, Path("node_modules"))
    bin_directory = validate_directory_chain(root, Path("node_modules/.bin"))
    package_dir = validate_directory_chain(root, Path("node_modules").joinpath(*package.split("/")))
    target_parent = validate_directory_chain(package_dir, Path(target).parent)
    link = bin_directory / executable
    metadata = link.lstat()
    if not stat.S_ISLNK(metadata.st_mode):
        raise RuntimeError(f"Expected npm bin symlink: {link}")
    raw_target = os.readlink(link)
    if os.path.isabs(raw_target):
        raise RuntimeError(f"Absolute npm bin target rejected: {link}")
    candidate = Path(os.path.normpath(link.parent / raw_target))
    lexical_relative(package_dir, node_modules)
    lexical_relative(candidate, package_dir)
    expected = target_parent / Path(target).name
    if candidate != expected:
        raise RuntimeError(f"Unexpected npm bin target for {executable}: {raw_target}")
    target_metadata = candidate.lstat()
    if not stat.S_ISREG(target_metadata.st_mode):
        raise RuntimeError(f"npm bin target must be a regular file: {candidate}")
    normalized_mode(target_metadata, directory=False)


def assert_locked_packages(root: Path) -> None:
    package = json.loads(regular_bytes(root / "package.json"))
    lock = json.loads(regular_bytes(root / "package-lock.json"))
    if package.get("private") is not True or lock.get("lockfileVersion") != 3:
        raise RuntimeError("Root npm package or lock metadata is invalid")
    if lock["packages"][""].get("devDependencies") != package.get("devDependencies"):
        raise RuntimeError("Root package and package-lock dependencies differ")
    validate_directory_chain(root, Path("node_modules"))
    for name, (version, executable, target) in LOCKED_PACKAGES.items():
        if package["devDependencies"].get(name) != version:
            raise RuntimeError(f"{name} must be exactly pinned to {version}")
        locked = lock["packages"].get("node_modules/" + name, {})
        if locked.get("version") != version:
            raise RuntimeError(f"{name} lock version does not match {version}")
        if not locked.get("integrity", "").startswith("sha512-"):
            raise RuntimeError(f"{name} lock integrity is missing")
        if not locked.get("resolved", "").startswith("https://registry.npmjs.org/"):
            raise RuntimeError(f"{name} lock resolution is not the npm registry")
        package_dir = validate_directory_chain(
            root, Path("node_modules").joinpath(*name.split("/"))
        )
        installed = package_dir / "package.json"
        installed_package = json.loads(regular_bytes(installed))
        if installed_package.get("version") != version:
            raise RuntimeError(f"Installed {name} version does not match the lock")
        if installed_package.get("bin", {}).get(executable) != target:
            raise RuntimeError(f"Installed {name} binary metadata drifted")
        validate_bin_link(root, name, executable, target)


def assert_json_mcp(path: Path) -> None:
    parsed = json.loads(regular_bytes(path))
    if parsed.get("mcpServers") != EXPECTED_MCP:
        raise RuntimeError(f"Unexpected MCP JSON configuration: {path}")


def assert_toml_mcp(path: Path) -> None:
    parsed = tomllib.loads(regular_bytes(path).decode("utf-8"))
    servers = parsed.get("mcp_servers", {})
    if set(servers) != set(EXPECTED_MCP):
        raise RuntimeError(f"Unexpected Codex MCP server set: {path}")
    for name, expected in EXPECTED_MCP.items():
        actual = dict(servers[name])
        actual.setdefault("env", {})
        if actual != expected:
            raise RuntimeError(f"Unexpected Codex MCP server {name}: {actual}")


def assert_mcp(root: Path) -> None:
    for relative in (".rulesync/mcp.json", ".cursor/mcp.json", ".mcp.json"):
        assert_json_mcp(root / relative)
    assert_toml_mcp(root / ".codex/config.toml")
    for server in EXPECTED_MCP.values():
        command = server["command"]
        if any(token in command for token in (";", "&&", "||", "|", "`", "$(")):
            raise RuntimeError(f"Shell syntax rejected in MCP command: {command}")
        if ".." in Path(command).parts or not command.startswith("./node_modules/.bin/"):
            raise RuntimeError(f"Unsafe MCP command path: {command}")


def assert_permissions(root: Path) -> None:
    source = json.loads(regular_bytes(root / ".rulesync/permissions.json"))
    read_rules = source.get("permission", {}).get("read", {})
    if set(read_rules) != SECRET_DENY_PATTERNS or set(read_rules.values()) != {"deny"}:
        raise RuntimeError("Canonical secret-read deny patterns drifted")
    for allowed_example in (".env.example", "backend/.env.example", "dev.tfvars.example"):
        if allowed_example in read_rules:
            raise RuntimeError(f"Example documentation was denied: {allowed_example}")

    cursor = json.loads(regular_bytes(root / ".cursor/cli.json"))
    claude = json.loads(regular_bytes(root / ".claude/settings.json"))
    expected = {f"Read({pattern})" for pattern in SECRET_DENY_PATTERNS}
    if set(cursor["permissions"]["deny"]) != expected:
        raise RuntimeError("Cursor secret-read permissions drifted")
    if set(claude["permissions"]["deny"]) != expected:
        raise RuntimeError("Claude secret-read permissions drifted")
    codex = tomllib.loads(regular_bytes(root / ".codex/config.toml").decode("utf-8"))
    filesystem = codex["permissions"]["rulesync"]["filesystem"][":workspace_roots"]
    denied = {key for key, value in filesystem.items() if value == "deny"}
    if denied != SECRET_DENY_PATTERNS:
        raise RuntimeError("Codex secret-read permissions drifted")


def assert_source_counts(root: Path) -> None:
    counts = {"rules": 0, "skills": 0, "subagents": 0}
    for directory, key, suffix in (
        (root / ".rulesync/rules", "rules", ".md"),
        (root / ".rulesync/skills", "skills", "SKILL.md"),
        (root / ".rulesync/subagents", "subagents", ".md"),
    ):
        for base, dirs, files in os.walk(directory, followlinks=False):
            for name in dirs:
                if stat.S_ISLNK((Path(base) / name).lstat().st_mode):
                    raise RuntimeError("Symlink rejected in Rulesync source")
            for name in files:
                path = Path(base) / name
                if not stat.S_ISREG(path.lstat().st_mode):
                    raise RuntimeError("Unsafe Rulesync source path")
                if (suffix == "SKILL.md" and name == suffix) or (
                    suffix == ".md" and name.endswith(suffix)
                ):
                    counts[key] += 1
    expected = {"rules": 14, "skills": 9, "subagents": 7}
    if counts != expected:
        raise RuntimeError(f"Rulesync source counts drifted: {counts} != {expected}")
    hooks = json.loads(regular_bytes(root / ".rulesync/hooks.json"))["hooks"]
    if len(hooks) != 1:
        raise RuntimeError("Rulesync hook count drifted")


def assert_content(root: Path) -> None:
    config = json.loads(regular_bytes(root / "rulesync.jsonc"))
    expected_targets = {
        "cursor": ["rules", "mcp", "subagents", "skills", "hooks", "permissions"],
        "claudecode": ["rules", "mcp", "subagents", "skills", "hooks", "permissions"],
        "codexcli": ["mcp", "subagents", "skills", "hooks", "permissions"],
        "agentsmd": ["rules"],
    }
    if config.get("targets") != expected_targets:
        raise RuntimeError("Rulesync target order or feature ownership drifted")
    if config.get("outputRoots") != ["."] or config.get("delete") is not False:
        raise RuntimeError("Rulesync output-root or delete behavior drifted")

    agents = " ".join(regular_bytes(root / "AGENTS.md").decode("utf-8").split())
    for text in (
        "FastAPI on Python 3.12",
        "Chrome Manifest V3",
        "Terraform on AWS",
        "task agents:check",
        "UUID v7",
        "untrusted data",
        "explicit approval",
        "AUTH_PROVIDER=mock",
        "BILLING_PROVIDER=mock",
        "STORAGE_BACKEND=json",
        "must not call external providers",
        "repository-managed Playwright Chromium",
        "normal Chrome",
        "headed and UI-sensitive behavior",
        "no production browser",
    ):
        if text not in agents:
            raise RuntimeError(f"AGENTS.md is missing required content: {text}")

    reload_skill = " ".join(
        regular_bytes(root / ".claude/skills/reload/SKILL.md").decode("utf-8").split()
    )
    for text in (
        "cannot reload extensions launched by Playwright",
        "--load-extension",
        "normal Chrome",
        "Load unpacked",
        "already open tabs still require a page refresh",
    ):
        if text not in reload_skill:
            raise RuntimeError(f"Generated reload skill is missing caveat: {text}")

    claude = json.loads(regular_bytes(root / ".claude/settings.json"))
    hook = claude["hooks"]["PostToolUse"][0]["hooks"][0]
    if hook["timeout"] != 15 or ".rulesync/hooks/format.sh" not in hook["command"]:
        raise RuntimeError("Claude formatter hook semantics drifted")


def verify(root: Path, rulesync: Path) -> None:
    assert_source_counts(root)
    assert_locked_packages(root)
    assert_mcp(root)
    assert_permissions(root)
    assert_content(root)
    clean = run_clean_generation(root, rulesync)
    current = scan_generated(root)
    assert_inventory(current, clean)


def preflight(root: Path) -> None:
    assert_locked_packages(root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).absolute().parents[1])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--generate", action="store_true")
    mode.add_argument("--postflight", action="store_true")
    args = parser.parse_args()
    root = args.root.absolute()
    preflight(root)
    if args.preflight:
        print("Agent executable preflight verified.")
        return 0
    if args.generate:
        assert_source_counts(root)
        clean = run_clean_generation(root, root / "node_modules/.bin/rulesync")
        write_clean_inventory(root, clean)
    verify(root, root / "node_modules/.bin/rulesync")
    print("Agent configuration clean generation, integrity, and security verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
