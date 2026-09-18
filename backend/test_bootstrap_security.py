from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts" / "bootstrap.sh"


def test_bootstrap_ignores_hostile_mise_environment():
    environment = {
        **os.environ,
        "MISE_CONFIG_FILE": "/tmp/hostile-mise.toml",
        "MISE_DATA_DIR": "/tmp/hostile-mise-data",
        "MISE_AUTO_INSTALL": "1",
    }
    result = subprocess.run(
        [str(BOOTSTRAP), "--dry-run"],
        cwd=ROOT,
        env=environment,
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Host supported:" in result.stdout
    assert "/tmp/hostile" not in result.stdout


def test_bootstrap_rejects_tools_directory_outside_repository(tmp_path):
    result = subprocess.run(
        [str(BOOTSTRAP), "--dry-run"],
        cwd=ROOT,
        env={**os.environ, "BOOTSTRAP_TOOLS_DIR": str(tmp_path / "outside")},
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "must remain inside the repository" in result.stderr


def test_bootstrap_env_activates_configured_data_directory_shims_with_clean_path():
    with tempfile.TemporaryDirectory(dir=ROOT, prefix=".bootstrap-tools-") as tools_root:
        data_directory = Path(tools_root) / "mise" / "data"
        bin_directory = Path(tools_root) / "mise" / "bin"
        shims_directory = data_directory / "shims"
        shims_directory.mkdir(parents=True)
        expected_versions = {
            "python": "Python 3.12.7",
            "node": "v22.23.1",
            "terraform": "Terraform v1.15.5",
            "task": "Task version: v3.40.0",
        }
        for tool, version in expected_versions.items():
            shim = shims_directory / tool
            shim.write_text(
                f"#!/usr/bin/env bash\nprintf '%s\n' '{version}'\n",
                encoding="utf-8",
            )
            shim.chmod(0o755)

        environment = {
            "BOOTSTRAP_TOOLS_DIR": tools_root,
            "PATH": "/usr/bin:/bin",
        }
        result = subprocess.run(
            [str(BOOTSTRAP), "--env"],
            cwd=ROOT,
            env=environment,
            check=False,
            text=True,
            capture_output=True,
        )

        assert result.returncode == 0, result.stderr
        assert f"export MISE_DATA_DIR={data_directory}" in result.stdout
        assert f"export PATH={bin_directory}:{shims_directory}:$PATH" in result.stdout

        activated = subprocess.run(
            [
                "/bin/bash",
                "-ceu",
                'eval "$1"\nfor tool in python node terraform task; do command -v "$tool"; done\n'
                "python --version\nnode --version\nterraform version\ntask --version",
                "bootstrap-env",
                result.stdout,
            ],
            cwd=ROOT,
            env=environment,
            check=False,
            text=True,
            capture_output=True,
        )

        assert activated.returncode == 0, activated.stderr
        assert activated.stdout.splitlines() == [
            *(str(shims_directory / tool) for tool in expected_versions),
            *expected_versions.values(),
        ]


def test_bootstrap_verifies_current_pinned_toolchain():
    subprocess.run([str(BOOTSTRAP), "--verify"], cwd=ROOT, check=True)
