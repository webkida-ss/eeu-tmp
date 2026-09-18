"""Behavioral tests for offline validation inputs used by build scripts."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolate_script_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "LAMBDA_WHEELHOUSE",
        "TERRAFORM_PROVIDER_MIRROR",
        "TF_CLI_CONFIG_FILE",
        "MUTATE_LOCK",
    ):
        monkeypatch.delenv(name, raising=False)


def _copy_repository_script(relative_path: str, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / Path(relative_path).name
    shutil.copy2(REPOSITORY_ROOT / relative_path, target)
    target.chmod(0o755)
    return target


def _make_lambda_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "lambda fixture with spaces"
    backend = root / "backend"
    scripts = root / "scripts"
    backend.mkdir(parents=True)
    for name in (
        "main.py",
        "config.py",
        "deps.py",
        "schemas.py",
        "secret_resolver.py",
        "lambda_handler.py",
        "worker_handler.py",
    ):
        (backend / name).write_text("# fixture\n", encoding="utf-8")
    (backend / "requirements-lambda.txt").write_text(
        "example==1.0 --hash=sha256:" + "0" * 64 + "\n",
        encoding="utf-8",
    )
    for package in (
        "accounts",
        "admin",
        "auth",
        "core",
        "generated",
        "jobs",
        "middleware",
        "repositories",
        "services",
        "storage",
    ):
        package_dir = backend / package
        package_dir.mkdir()
        (package_dir / "__init__.py").write_text("# fixture\n", encoding="utf-8")
    runner = scripts / "with-isolated-pypi.sh"
    runner.parent.mkdir(parents=True)
    runner.write_text(
        '#!/usr/bin/env bash\nset -eu\nprintf \'%s\\n\' "$@" > "${CAPTURE_FILE}"\n',
        encoding="utf-8",
    )
    runner.chmod(0o755)
    script = _copy_repository_script("backend/scripts/build_lambda.sh", backend / "scripts")
    return root, script, backend


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True)


def test_lambda_default_keeps_index_and_all_runtime_safeguards(tmp_path: Path) -> None:
    root, script, _ = _make_lambda_fixture(tmp_path)
    capture = tmp_path / "pip-args.txt"
    env = {**os.environ, "CAPTURE_FILE": str(capture)}

    result = _run([str(script)], cwd=root, env=env)

    assert result.returncode == 0
    args = capture.read_text(encoding="utf-8").splitlines()
    assert "--index-url" in args
    assert "https://pypi.org/simple" in args
    assert "--require-hashes" in args
    assert "--platform" in args
    assert args.count("--platform") == 2
    assert "manylinux_2_28_aarch64" in args
    assert "manylinux2014_aarch64" in args
    assert "--implementation" in args and "cp" in args
    assert "--python-version" in args and "3.12" in args
    assert "--only-binary=:all:" in args


@pytest.mark.parametrize("relative", [False, True])
def test_lambda_offline_wheelhouse_supports_spaces_and_retains_safeguards(
    tmp_path: Path,
    relative: bool,
) -> None:
    root, script, _ = _make_lambda_fixture(tmp_path)
    wheelhouse = root / "wheelhouse with spaces"
    wheelhouse.mkdir()
    capture = tmp_path / "pip-args.txt"
    wheelhouse_input = wheelhouse.relative_to(root) if relative else wheelhouse
    env = {**os.environ, "CAPTURE_FILE": str(capture), "LAMBDA_WHEELHOUSE": str(wheelhouse_input)}

    result = _run([str(script)], cwd=root, env=env)

    assert result.returncode == 0
    args = capture.read_text(encoding="utf-8").splitlines()
    assert "--no-index" in args
    assert "--find-links" in args
    assert str(wheelhouse) in args
    assert "--index-url" not in args
    assert "--require-hashes" in args
    assert args.count("--platform") == 2
    assert "--only-binary=:all:" in args


def test_lambda_invalid_wheelhouse_fails_before_build_cleanup(tmp_path: Path) -> None:
    root, script, backend = _make_lambda_fixture(tmp_path)
    build_dir = backend / "build" / "lambda"
    build_dir.mkdir(parents=True)
    marker = build_dir / "marker.txt"
    marker.write_text("preserve", encoding="utf-8")
    env = {**os.environ, "LAMBDA_WHEELHOUSE": str(tmp_path / "missing-wheelhouse")}

    result = _run([str(script)], cwd=root, env=env)

    assert result.returncode != 0
    assert marker.read_text(encoding="utf-8") == "preserve"
    assert "LAMBDA_WHEELHOUSE" in result.stderr


def _make_terraform_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "terraform fixture with spaces"
    (root / "infra" / "envs" / "dev").mkdir(parents=True)
    (root / "infra" / "envs" / "prod").mkdir(parents=True)
    (root / "infra" / "modules").mkdir(parents=True)
    for environment in ("dev", "prod"):
        lock = root / "infra" / "envs" / environment / ".terraform.lock.hcl"
        lock.write_text("provider lock\n", encoding="utf-8")
    bootstrap = root / "scripts" / "bootstrap.sh"
    bootstrap.parent.mkdir(parents=True)
    bootstrap.write_text(
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        'printf \'%s\\n\' "$@" >> "${CAPTURE_FILE}"\n'
        'if [ "$1" = "--exec" ]; then\n'
        "  shift\n"
        "fi\n"
        'if [ "$1" = "terraform" ]; then\n'
        "  shift\n"
        "fi\n"
        'for arg in "$@"; do\n'
        '  case "$arg" in -chdir=*) dir="${arg#-chdir=}";; esac\n'
        '  case "$arg" in init|providers) command_name="$arg";; esac\n'
        "done\n"
        'if [ "${command_name:-}" = init ]; then mkdir -p "${dir}/.terraform"; fi\n'
        'if [ "${command_name:-}" = providers ] && [ "${MUTATE_LOCK:-0}" = 1 ]; then printf \'mismatch\\n\' > "${dir}/.terraform.lock.hcl"; fi\n',
        encoding="utf-8",
    )
    bootstrap.chmod(0o755)
    script = _copy_repository_script("scripts/check_terraform_locks.sh", root / "scripts")
    mirror = root / "provider mirror with spaces"
    mirror.mkdir()
    return root, script, mirror


def test_terraform_default_keeps_all_platforms_and_readonly_init(tmp_path: Path) -> None:
    root, script, _ = _make_terraform_fixture(tmp_path)
    capture = tmp_path / "terraform-args.txt"
    env = {**os.environ, "CAPTURE_FILE": str(capture)}

    result = _run([str(script)], cwd=root, env=env)

    assert result.returncode == 0
    args = capture.read_text(encoding="utf-8").splitlines()
    assert "-lockfile=readonly" in args
    assert args.count("-platform=darwin_arm64") == 2
    assert args.count("-platform=darwin_amd64") == 2
    assert args.count("-platform=linux_amd64") == 2
    assert args.count("-platform=linux_arm64") == 2
    assert "-fs-mirror=" not in "\n".join(args)


@pytest.mark.parametrize("relative", [False, True])
def test_terraform_offline_mirror_supports_spaces(tmp_path: Path, relative: bool) -> None:
    root, script, mirror = _make_terraform_fixture(tmp_path)
    capture = tmp_path / "terraform-args.txt"
    mirror_input = mirror.relative_to(root) if relative else mirror
    env = {
        **os.environ,
        "CAPTURE_FILE": str(capture),
        "TERRAFORM_PROVIDER_MIRROR": str(mirror_input),
    }

    result = _run([str(script)], cwd=root, env=env)

    assert result.returncode == 0
    args = capture.read_text(encoding="utf-8").splitlines()
    assert f"-fs-mirror={mirror}" in args


def test_terraform_invalid_mirror_fails_before_temp_work(tmp_path: Path) -> None:
    root, script, _ = _make_terraform_fixture(tmp_path)
    capture = tmp_path / "terraform-args.txt"
    env = {
        **os.environ,
        "CAPTURE_FILE": str(capture),
        "TERRAFORM_PROVIDER_MIRROR": str(tmp_path / "missing-mirror"),
    }

    result = _run([str(script)], cwd=root, env=env)

    assert result.returncode != 0
    assert not capture.exists()
    assert "TERRAFORM_PROVIDER_MIRROR" in result.stderr


@pytest.mark.parametrize("offline", [False, True])
def test_terraform_lock_mismatch_remains_a_failure(tmp_path: Path, offline: bool) -> None:
    root, script, mirror = _make_terraform_fixture(tmp_path)
    capture = tmp_path / "terraform-args.txt"
    env = {**os.environ, "CAPTURE_FILE": str(capture), "MUTATE_LOCK": "1"}
    if offline:
        env["TERRAFORM_PROVIDER_MIRROR"] = str(mirror)

    result = _run([str(script)], cwd=root, env=env)

    assert result.returncode != 0
    assert "differ" in result.stderr or "differ" in result.stdout


def _make_provider_guard_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / 'provider guard fixture with spaces and "quotes"'
    module = root / "infra" / "modules" / "reading-assistant-api"
    tests = module / "tests"
    tests.mkdir(parents=True)
    for name in ("main.tf", "outputs.tf", "variables.tf", "versions.tf"):
        (module / name).write_text("# fixture\n", encoding="utf-8")
    (tests / "provider-guards.tftest.hcl").write_text("# fixture\n", encoding="utf-8")
    (root / "infra" / "envs" / "dev").mkdir(parents=True)
    (root / "infra" / "envs" / "dev" / ".terraform.lock.hcl").write_text(
        "provider lock\n",
        encoding="utf-8",
    )
    bootstrap = root / "scripts" / "bootstrap.sh"
    bootstrap.parent.mkdir(parents=True)
    bootstrap.write_text(
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        'printf \'%s\\n\' "$@" >> "${CAPTURE_FILE}"\n'
        'printf \'%s\\n\' "${TF_CLI_CONFIG_FILE:-}" >> "${CONFIG_PATH_CAPTURE}"\n'
        'cp -- "${TF_CLI_CONFIG_FILE}" "${CONFIG_CAPTURE}"\n',
        encoding="utf-8",
    )
    bootstrap.chmod(0o755)
    script = _copy_repository_script("scripts/test_terraform_provider_guards.sh", root / "scripts")
    mirror = root / 'provider mirror ${template} %{directive} with \\backslash and "quotes"'
    provider = mirror / "registry.terraform.io" / "hashicorp" / "aws" / "6.55.0" / "linux_amd64"
    provider.mkdir(parents=True)
    (provider / "terraform-provider-aws_v6.55.0_x5").write_text("fixture\n", encoding="utf-8")
    return root, script, mirror


def test_provider_guards_generate_a_private_filesystem_only_config(tmp_path: Path) -> None:
    root, script, mirror = _make_provider_guard_fixture(tmp_path)
    capture = tmp_path / "terraform-args.txt"
    config_path_capture = tmp_path / "terraform-config-path.txt"
    config_capture = tmp_path / "terraform-config.txt"
    caller_config = tmp_path / "misleading.tfrc"
    caller_config.write_text(
        "# filesystem_mirror\n"
        'provider_installation { network_mirror { url = "https://example.invalid" } }\n',
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "CAPTURE_FILE": str(capture),
        "CONFIG_PATH_CAPTURE": str(config_path_capture),
        "CONFIG_CAPTURE": str(config_capture),
        "TERRAFORM_PROVIDER_MIRROR": str(mirror),
        "TF_CLI_CONFIG_FILE": str(caller_config),
    }

    result = _run([str(script)], cwd=root, env=env)

    assert result.returncode == 0, result.stderr
    config_paths = config_path_capture.read_text(encoding="utf-8").splitlines()
    assert len(config_paths) == 2
    assert all(path != str(caller_config) for path in config_paths)
    config = config_capture.read_text(encoding="utf-8")
    assert "disable_checkpoint = true" in config
    assert "filesystem_mirror" in config
    assert "network_mirror" not in config
    assert not re.search(r"(?m)^\s*direct\s*\{", config)
    escaped_mirror = (
        str(mirror)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("${", "$${")
        .replace("%{", "%%{")
    )
    assert escaped_mirror in config
    args = capture.read_text(encoding="utf-8").splitlines()
    assert "init" in args
    assert "test" in args


def test_provider_guards_fail_before_init_when_aws_provider_is_missing(tmp_path: Path) -> None:
    root, script, mirror = _make_provider_guard_fixture(tmp_path)
    provider_binary = next(mirror.rglob("terraform-provider-aws_v*"))
    provider_binary.unlink()
    capture = tmp_path / "terraform-args.txt"
    env = {
        **os.environ,
        "CAPTURE_FILE": str(capture),
        "CONFIG_PATH_CAPTURE": str(tmp_path / "terraform-config-path.txt"),
        "CONFIG_CAPTURE": str(tmp_path / "terraform-config.txt"),
        "TERRAFORM_PROVIDER_MIRROR": str(mirror),
    }

    result = _run([str(script)], cwd=root, env=env)

    assert result.returncode != 0
    assert "missing the cached hashicorp/aws provider" in result.stderr
    assert not capture.exists()


def test_provider_guards_reject_control_characters_before_init(tmp_path: Path) -> None:
    root, script, mirror = _make_provider_guard_fixture(tmp_path)
    control_mirror = mirror.with_name("provider\x0bmirror")
    mirror.rename(control_mirror)
    capture = tmp_path / "terraform-args.txt"
    env = {
        **os.environ,
        "CAPTURE_FILE": str(capture),
        "CONFIG_PATH_CAPTURE": str(tmp_path / "terraform-config-path.txt"),
        "CONFIG_CAPTURE": str(tmp_path / "terraform-config.txt"),
        "TERRAFORM_PROVIDER_MIRROR": str(control_mirror),
    }

    result = _run([str(script)], cwd=root, env=env)

    assert result.returncode != 0
    assert "unsupported control character" in result.stderr
    assert not capture.exists()
