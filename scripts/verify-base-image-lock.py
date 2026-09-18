from __future__ import annotations

import hashlib
import json
import ssl
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / ".devcontainer" / "base-image-lock.json"
ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)


def fetch_manifest(repository: str, digest: str) -> tuple[bytes, str]:
    registry, path = repository.split("/", 1)
    assert registry == "mcr.microsoft.com"
    assert digest.startswith("sha256:")
    url = f"https://{registry}/v2/{path}/manifests/{digest}"
    request = urllib.request.Request(url, headers={"Accept": ACCEPT})
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, context=context, timeout=30) as response:
        body = response.read()
        served_digest = response.headers.get("Docker-Content-Digest", "")
    actual_digest = f"sha256:{hashlib.sha256(body).hexdigest()}"
    assert actual_digest == digest, (actual_digest, digest)
    assert served_digest == digest, (served_digest, digest)
    return body, url


def main() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    repository = lock["repository"]
    index_digest = lock["indexDigest"]
    immutable_reference = f"{repository}@{index_digest}"
    assert lock["immutableReference"] == immutable_reference
    assert lock["sourceTagInformationalOnly"] is True
    assert lock["sourceTag"] not in lock["verificationCommand"]

    body, index_url = fetch_manifest(repository, index_digest)
    index = json.loads(body)
    observed = {
        f"{manifest['platform']['os']}/{manifest['platform']['architecture']}": manifest["digest"]
        for manifest in index["manifests"]
        if manifest.get("platform", {}).get("os") == "linux"
        and manifest.get("platform", {}).get("architecture") in {"amd64", "arm64"}
    }
    assert observed == lock["platforms"], (observed, lock["platforms"])

    child_urls = []
    for platform, digest in sorted(lock["platforms"].items()):
        child_body, child_url = fetch_manifest(repository, digest)
        child = json.loads(child_body)
        assert child["schemaVersion"] == 2, platform
        child_urls.append(child_url)

    print(f"Verified immutable OCI index: {immutable_reference}")
    print(f"Registry endpoint: {index_url}")
    for platform, digest in sorted(lock["platforms"].items()):
        print(f"{platform}: {digest}")
    assert all(lock["sourceTag"] not in url for url in [index_url, *child_urls])


if __name__ == "__main__":
    main()
