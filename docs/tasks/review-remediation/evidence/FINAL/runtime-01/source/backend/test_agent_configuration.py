from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import check_agent_config as agent_check

ROOT = Path(__file__).absolute().parents[1]
CHECKER = ROOT / "scripts/check_agent_config.py"
RULESYNC = ROOT / "node_modules/.bin/rulesync"


def copy_fixture(destination: Path) -> None:
    agent_check.copy_regular_tree(ROOT / ".rulesync", destination / ".rulesync")
    for relative in ("rulesync.jsonc", "package.json", "package-lock.json"):
        agent_check.copy_regular_file(ROOT / relative, destination / relative)
    agent_check.write_clean_inventory(destination, agent_check.scan_generated(ROOT))

    agent_check.assert_locked_packages(ROOT)
    bin_dir = destination / "node_modules/.bin"
    bin_dir.mkdir(parents=True, mode=0o755)
    for package, (_, executable, target) in agent_check.LOCKED_PACKAGES.items():
        package_dir = destination / "node_modules" / package
        agent_check.copy_regular_file(
            ROOT / "node_modules" / package / "package.json",
            package_dir / "package.json",
        )
        agent_check.copy_regular_file(
            ROOT / "node_modules" / package / target,
            package_dir / target,
        )
        source_link = ROOT / "node_modules/.bin" / executable
        (bin_dir / executable).symlink_to(os.readlink(source_link))


def rulesync_check(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(RULESYNC),
            "generate",
            "--check",
            "--config",
            str(root / "rulesync.jsonc"),
        ],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )


class AgentConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="agent-config-test-")
        self.copy = Path(self.temporary.name) / "repository"
        self.copy.mkdir(mode=0o755)
        copy_fixture(self.copy)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def assert_inventory_rejected(self) -> None:
        with self.assertRaises(RuntimeError):
            inventory = agent_check.scan_generated(self.copy)
            agent_check.assert_hardcoded_inventory(inventory)

    def test_agent_configuration_contract_is_current(self) -> None:
        result = subprocess.run(
            ["python3", str(CHECKER)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("clean generation", result.stdout)

    def test_npm_scripts_preflight_before_rulesync_execution(self) -> None:
        scripts = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["scripts"]
        self.assertEqual(
            scripts["agents:preflight"],
            "python3 scripts/check_agent_config.py --preflight",
        )
        check = scripts["agents:check"]
        self.assertLess(check.index("--preflight"), check.index("rulesync generate --check"))
        self.assertLess(check.index("rulesync generate --check"), check.index("--postflight"))

    def test_agents_md_contains_provider_defaults_and_browser_boundaries(self) -> None:
        agents = " ".join((ROOT / "AGENTS.md").read_text(encoding="utf-8").split())
        for required in (
            "AUTH_PROVIDER=mock",
            "BILLING_PROVIDER=mock",
            "STORAGE_BACKEND=json",
            "must not call external providers",
            "repository-managed Playwright Chromium",
            "normal Chrome",
            "headed and UI-sensitive behavior",
            "no production browser profile or secrets",
        ):
            self.assertIn(required, agents)

    def test_generated_reload_skill_preserves_browser_caveats(self) -> None:
        reload_skill = " ".join(
            (ROOT / ".claude/skills/reload/SKILL.md").read_text(encoding="utf-8").split()
        )
        for required in (
            "cannot reload extensions launched by Playwright",
            "--load-extension",
            "normal Chrome",
            "Load unpacked",
            "already open tabs still require a page refresh",
        ):
            self.assertIn(required, reload_skill)

    def test_rulesync_check_detects_generated_output_edit_and_deletion(self) -> None:
        generated = self.copy / ".cursor/rules/basic-strategy.mdc"
        generated.write_bytes(generated.read_bytes() + b"\nmanual edit\n")
        self.assertNotEqual(rulesync_check(self.copy).returncode, 0)
        agent_check.copy_regular_file(ROOT / ".cursor/rules/basic-strategy.mdc", generated)
        generated.unlink()
        self.assertNotEqual(rulesync_check(self.copy).returncode, 0)

    def test_agents_check_detects_agents_md_edit_and_deletion(self) -> None:
        agents = self.copy / "AGENTS.md"
        agents.write_bytes(agents.read_bytes() + b"\nmanual edit\n")
        self.assertNotEqual(rulesync_check(self.copy).returncode, 0)
        agent_check.copy_regular_file(ROOT / "AGENTS.md", agents)
        agents.unlink()
        self.assertNotEqual(rulesync_check(self.copy).returncode, 0)

    def test_generated_external_and_internal_symlinks_are_rejected(self) -> None:
        agents = self.copy / "AGENTS.md"
        agents.unlink()
        agents.symlink_to(Path(self.temporary.name) / "outside")
        self.assert_inventory_rejected()
        agents.unlink()
        agent_check.copy_regular_file(ROOT / "AGENTS.md", agents)
        rule = self.copy / ".cursor/rules/basic-strategy.mdc"
        rule.unlink()
        rule.symlink_to(self.copy / "AGENTS.md")
        self.assert_inventory_rejected()

    def test_generated_unsafe_mode_is_rejected(self) -> None:
        path = self.copy / "AGENTS.md"
        path.chmod(0o777)
        self.assert_inventory_rejected()

    def test_missing_extra_and_type_changes_are_rejected(self) -> None:
        (self.copy / "AGENTS.md").unlink()
        self.assert_inventory_rejected()
        agent_check.copy_regular_file(ROOT / "AGENTS.md", self.copy / "AGENTS.md")
        (self.copy / ".cursor/rules/manual.mdc").write_bytes(b"manual\n")
        self.assert_inventory_rejected()
        (self.copy / ".cursor/rules/manual.mdc").unlink()
        unexpected_directory = self.copy / ".cursor/unexpected"
        unexpected_directory.mkdir(mode=0o755)
        self.assert_inventory_rejected()
        unexpected_directory.rmdir()
        agents = self.copy / "AGENTS.md"
        agents.unlink()
        agents.mkdir(mode=0o755)
        self.assert_inventory_rejected()

    def test_fifo_is_rejected(self) -> None:
        if not hasattr(os, "mkfifo"):
            self.skipTest("FIFO creation is unavailable")
        agents = self.copy / "AGENTS.md"
        agents.unlink()
        os.mkfifo(agents)
        self.assert_inventory_rejected()

    def test_canonical_source_and_config_symlinks_are_rejected(self) -> None:
        source = Path(self.temporary.name) / "source-link"
        source.symlink_to(ROOT / ".rulesync", target_is_directory=True)
        with self.assertRaises(RuntimeError):
            agent_check.copy_regular_tree(source, self.copy / "bad-source")
        config = Path(self.temporary.name) / "config-link"
        config.symlink_to(ROOT / "rulesync.jsonc")
        with self.assertRaises(RuntimeError):
            agent_check.copy_regular_file(config, self.copy / "bad-config")

    def test_source_change_and_count_drift_are_detected(self) -> None:
        source = self.copy / ".rulesync/rules/basic-strategy.md"
        source.write_bytes(source.read_bytes() + b"\nSource drift.\n")
        self.assertNotEqual(rulesync_check(self.copy).returncode, 0)
        extra = self.copy / ".rulesync/rules/extra.md"
        extra.write_bytes(b"---\ntargets: ['*']\n---\nExtra.\n")
        with self.assertRaises(RuntimeError):
            agent_check.assert_source_counts(self.copy)

    def test_mcp_rejects_malicious_command_and_extra_server(self) -> None:
        path = self.copy / ".cursor/mcp.json"
        parsed = json.loads(path.read_text(encoding="utf-8"))
        parsed["mcpServers"]["context7"]["command"] = "sh -c 'steal-secrets'"
        path.write_text(json.dumps(parsed), encoding="utf-8")
        with self.assertRaises(RuntimeError):
            agent_check.assert_mcp(self.copy)
        agent_check.copy_regular_file(ROOT / ".cursor/mcp.json", path)
        parsed = json.loads(path.read_text(encoding="utf-8"))
        parsed["mcpServers"]["unexpected"] = parsed["mcpServers"]["context7"]
        path.write_text(json.dumps(parsed), encoding="utf-8")
        with self.assertRaises(RuntimeError):
            agent_check.assert_mcp(self.copy)

    def test_mcp_bin_external_and_internal_symlink_targets_are_rejected(self) -> None:
        link = self.copy / "node_modules/.bin/context7-mcp"
        link.unlink()
        link.symlink_to(Path(self.temporary.name) / "outside")
        with self.assertRaises(RuntimeError):
            agent_check.assert_locked_packages(self.copy)
        link.unlink()
        link.symlink_to("../@playwright/mcp/cli.js")
        with self.assertRaises(RuntimeError):
            agent_check.assert_locked_packages(self.copy)

    def test_tampered_rulesync_executable_is_never_executed(self) -> None:
        marker = Path(self.temporary.name) / "executed"
        link = self.copy / "node_modules/.bin/rulesync"
        link.unlink()
        link.write_text(f"#!/bin/sh\ntouch '{marker}'\n", encoding="utf-8")
        link.chmod(0o755)
        result = subprocess.run(
            [
                "python3",
                str(CHECKER),
                "--root",
                str(self.copy),
                "--postflight",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(marker.exists())

    def test_unscoped_package_directory_symlink_is_rejected(self) -> None:
        package = self.copy / "node_modules/rulesync"
        (package / "dist/cli/index.js").unlink()
        (package / "dist/cli").rmdir()
        (package / "dist").rmdir()
        (package / "package.json").unlink()
        package.rmdir()
        package.symlink_to(Path(self.temporary.name) / "external-rulesync")
        with self.assertRaises(RuntimeError):
            agent_check.assert_locked_packages(self.copy)

    def test_scoped_package_and_scope_directory_symlinks_are_rejected(self) -> None:
        package = self.copy / "node_modules/@upstash/context7-mcp"
        (package / "dist/index.js").unlink()
        (package / "dist").rmdir()
        (package / "package.json").unlink()
        package.rmdir()
        package.symlink_to(Path(self.temporary.name) / "external-context7")
        with self.assertRaises(RuntimeError):
            agent_check.assert_locked_packages(self.copy)

        package.unlink()
        scope = self.copy / "node_modules/@upstash"
        scope.rmdir()
        scope.symlink_to(Path(self.temporary.name) / "external-scope")
        with self.assertRaises(RuntimeError):
            agent_check.assert_locked_packages(self.copy)

    def test_package_lock_integrity_is_required(self) -> None:
        path = self.copy / "package-lock.json"
        parsed = json.loads(path.read_text(encoding="utf-8"))
        del parsed["packages"]["node_modules/@upstash/context7-mcp"]["integrity"]
        path.write_text(json.dumps(parsed), encoding="utf-8")
        with self.assertRaises(RuntimeError):
            agent_check.assert_locked_packages(self.copy)

    def test_permissions_cover_secret_paths_but_not_examples(self) -> None:
        agent_check.assert_permissions(ROOT)
        source = json.loads((ROOT / ".rulesync/permissions.json").read_text(encoding="utf-8"))
        rules = source["permission"]["read"]
        for example in (".env.example", "backend/.env.example", "dev.tfvars.example"):
            self.assertNotIn(example, rules)

    def test_second_clean_generation_is_deterministic_and_no_diff(self) -> None:
        clean = agent_check.run_clean_generation(ROOT, RULESYNC)
        agent_check.assert_inventory(agent_check.scan_generated(ROOT), clean)


if __name__ == "__main__":
    unittest.main()
