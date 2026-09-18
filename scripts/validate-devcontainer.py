from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEVCONTAINER = ROOT / ".devcontainer"


def main() -> None:
    config = json.loads((DEVCONTAINER / "devcontainer.json").read_text(encoding="utf-8"))
    dockerfile = (DEVCONTAINER / "Dockerfile").read_text(encoding="utf-8")
    image_lock = json.loads((DEVCONTAINER / "base-image-lock.json").read_text(encoding="utf-8"))
    snapshot_lock = json.loads(
        (DEVCONTAINER / "ubuntu-snapshot-lock.json").read_text(encoding="utf-8")
    )
    ci_image_lock = json.loads((DEVCONTAINER / "ci-image-lock.json").read_text(encoding="utf-8"))

    assert config["remoteUser"] == "vscode"
    assert config["containerUser"] == "vscode"
    assert config["containerEnv"] == {
        "AUTH_PROVIDER": "mock",
        "BILLING_PROVIDER": "mock",
        "JOB_RUNNER": "inline",
        "STORAGE_BACKEND": "json",
        "DEVCONTAINER": "1",
    }
    assert "features" not in config
    assert "mounts" not in config
    assert "privileged" not in config
    assert config["runArgs"] == [
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
    ]
    assert config["remoteEnv"]["BOOTSTRAP_TOOLS_DIR"].endswith("/.devcontainer-tools")
    assert config["remoteEnv"]["BACKEND_VENV"] == "backend/.devcontainer-venv"
    assert config["remoteEnv"]["MISE_AUTO_INSTALL"] == "0"
    assert config["remoteEnv"]["MISE_GLOBAL_CONFIG_FILE"] == "/dev/null"
    assert config["remoteEnv"]["MISE_DATA_DIR"].endswith("/mise/data")
    assert config["remoteEnv"]["REPOSITORY_TOOLS_DIR"].endswith("/.devcontainer-tools/repository")
    assert ".devcontainer-tools/mise/bin" in config["remoteEnv"]["PATH"]
    assert ".devcontainer-tools/mise/data/shims" in config["remoteEnv"]["PATH"]
    assert config["postCreateCommand"] == "./scripts/devcontainer-post-create.sh"

    index_digest = image_lock["indexDigest"]
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", index_digest)
    assert set(image_lock["platforms"]) == {"linux/amd64", "linux/arm64"}
    assert all(
        re.fullmatch(r"sha256:[0-9a-f]{64}", digest) for digest in image_lock["platforms"].values()
    )
    assert image_lock["schemaVersion"] == 2
    assert image_lock["immutableReference"] == f"{image_lock['repository']}@{index_digest}"
    assert image_lock["sourceTagInformationalOnly"] is True
    assert image_lock["sourceTag"] not in image_lock["verificationCommand"]
    assert f"@{index_digest}" in dockerfile
    assert not re.search(r"(?im)^\s*(ADD|COPY)\s+", dockerfile)
    assert re.search(r"(?m)^USER vscode$", dockerfile)

    timestamp = snapshot_lock["timestamp"]
    assert re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", timestamp)
    assert snapshot_lock["baseUri"] == f"https://snapshot.ubuntu.com/ubuntu/{timestamp}/"
    assert snapshot_lock["suites"] == ["noble", "noble-updates", "noble-security"]
    assert snapshot_lock["signedBy"] == "/usr/share/keyrings/ubuntu-archive-keyring.gpg"
    assert snapshot_lock["validUntilPolicy"] == "disabled-for-immutable-snapshot-only"
    for security_control in (
        "tlsPeerVerification",
        "tlsHostVerification",
    ):
        assert snapshot_lock[security_control] is True
    for forbidden_control in (
        "allowInsecureRepositories",
        "allowUnauthenticatedPackages",
    ):
        assert snapshot_lock[forbidden_control] is False
    assert snapshot_lock["baseUri"] in dockerfile
    assert "Check-Valid-Until: no" in dockerfile
    assert 'Acquire::https::Verify-Peer "true"' in dockerfile
    assert 'Acquire::https::Verify-Host "true"' in dockerfile
    assert "archive.ubuntu.com" not in dockerfile
    assert "security.ubuntu.com" not in dockerfile

    workflow = (ROOT / ".github" / "workflows" / "devcontainer-ci.yml").read_text(encoding="utf-8")
    assert set(re.findall(r"(?m)^\s+- (amd64|arm64)$", workflow)) == {
        "amd64",
        "arm64",
    }
    assert ci_image_lock["qemuBinfmt"] in workflow
    assert ci_image_lock["buildkit"] in workflow
    assert '--platform "linux/${{ matrix.arch }}"' in workflow
    assert "devcontainer-platform-smoke.sh" in workflow

    forbidden = (
        "/var/run/docker.sock",
        ".aws",
        "SSH_AUTH_SOCK",
        "OPENAI_API_KEY",
        "STRIPE_SECRET_KEY",
        "--privileged",
    )
    config_text = json.dumps(config, sort_keys=True)
    assert all(value not in config_text for value in forbidden)


if __name__ == "__main__":
    main()
