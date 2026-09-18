# Cloud Development

## Supported environments

The repository dev container supports Linux `arm64` and `amd64` through the
same immutable Ubuntu 24.04 multi-platform image. It is intended for Cursor
dev containers and cloud agents, GitHub Codespaces, the Dev Container CLI, and
other implementations of the Development Containers specification.

The image is pinned to the Microsoft Dev Containers registry index digest in
`.devcontainer/base-image-lock.json`. Verification requests only the immutable
`repository@indexDigest` reference, hashes the returned index and child
manifests, and compares the locked `amd64` and `arm64` digests. The human source
tag is informational and is never trusted during validation.

APT reads only the signed Ubuntu snapshot at `20260719T000000Z`, recorded in
`.devcontainer/ubuntu-snapshot-lock.json`. TLS peer/host checks and archive
signature validation remain enabled; unauthenticated and insecure repositories
remain disabled. `Valid-Until` is disabled only because this dated snapshot is
immutable. Repository source is mounted at runtime and is never copied into an
image layer.

Host minimums are 4 CPUs, 8 GB RAM, 32 GB free storage, Git, Docker, and a
Dev Container-compatible client. Docker Desktop on macOS and Docker Engine on
Ubuntu are supported. Browser smoke tests are headless.

## Start and verify

From the repository root:

```sh
devcontainer up --workspace-folder .
devcontainer exec --workspace-folder . task setup
devcontainer exec --workspace-folder . task check
devcontainer exec --workspace-folder . task test:extension:smoke
```

The post-create hook already runs the secure repository bootstrap, `task
setup`, and the managed Playwright Chromium installation. Running setup again
is supported and verifies idempotence. A content manifest protects tracked,
dirty, and pre-existing untracked source by hashing bytes, symlink targets, and
executable mode before and after setup. The remote `PATH` includes the
repository-managed mise directories, so literal `task` commands work without
shell activation or `eval`.

In Cursor, use **Dev Containers: Reopen in Container**. A Cursor cloud agent
should select the repository dev container and use the same Taskfile commands.
In Codespaces, create the codespace from the desired branch; the checked-in
configuration is discovered automatically.

## Security model

The runtime user is non-root. The container drops all Linux capabilities and
sets `no-new-privileges`. It does not request privileged mode and does not
mount the host Docker socket, AWS configuration, SSH agent, or other host
credential directories. Auth and billing use mock providers, jobs run inline,
and storage uses local JSON by default.

Do not add API keys, cloud credentials, personal access tokens, `.env` files,
or production data to the image, dev container configuration, Codespaces
secrets, cloud-agent instructions, or repository files. Pull-request CI is
fork-safe, read-only, and receives no secrets. Any future AWS access must use
short-lived GitHub OIDC credentials after a separate approval; it is not part
of this container.

The absent Docker socket is intentional. Docker-backed DynamoDB integration
tasks cannot run inside the standard container. Run
`task test:backend:integration:local` on the host, or use the existing CI job
that provisions DynamoDB Local as an isolated service. Do not weaken the
container by mounting the host socket merely to run this optional integration
test.

## Local fallback

### Network-denied validation

Provision tools, application dependencies, and managed Chromium before denying
external traffic. The full gate additionally needs Lambda target wheels and
Terraform provider packages. In a credential-free provisioning environment,
use the committed requirements and provider locks without upgrading them:

```sh
mkdir -p /tmp/untangle-validation-inputs/wheels
./scripts/with-isolated-pypi.sh backend/.venv/bin/python -m pip download \
  --index-url https://pypi.org/simple --require-hashes \
  --requirement backend/requirements-lambda.txt \
  --dest /tmp/untangle-validation-inputs/wheels \
  --platform manylinux_2_28_aarch64 --platform manylinux2014_aarch64 \
  --implementation cp --python-version 3.12 --only-binary=:all:
./scripts/bootstrap.sh --exec terraform -chdir=infra/envs/dev get
./scripts/bootstrap.sh --exec terraform -chdir=infra/envs/dev providers mirror \
  -platform=darwin_arm64 -platform=darwin_amd64 \
  -platform=linux_amd64 -platform=linux_arm64 \
  /tmp/untangle-validation-inputs/providers
```

Retain the successful download/signature-verification log. Transfer these
inputs to the isolated validation container without transferring credentials or
user configuration. Create a dedicated Terraform CLI configuration there:

```hcl
provider_installation {
  filesystem_mirror {
    path = "/tmp/untangle-validation-inputs/providers"
  }
}
```

Do not add a `direct` fallback. With that file saved as
`/tmp/untangle-validation-inputs/offline.tfrc`, run inside the network-denied
container:

```sh
LAMBDA_WHEELHOUSE=/tmp/untangle-validation-inputs/wheels \
TERRAFORM_PROVIDER_MIRROR=/tmp/untangle-validation-inputs/providers \
TF_CLI_CONFIG_FILE=/tmp/untangle-validation-inputs/offline.tfrc \
  ./scripts/bootstrap.sh --exec task check
```

The optional inputs retain the default online workflow when unset. Lambda
installation still requires locked hashes and Linux arm64 binary wheels;
offline mode disables indexes. Terraform still initializes with a read-only
lock, checks all four platforms, and compares reproduced locks byte for byte.
The CLI configuration controls `init`; the explicit mirror variable controls
`providers lock`, which otherwise contacts the origin registry independently.
Mirror installation reports "unauthenticated" because it does not repeat
origin signature discovery; locked package hashes are still checked, and the
preparation phase verifies HashiCorp signatures. Never replace the lock to make
a changed mirror pass.

For agent-run DynamoDB integration, an externally managed DynamoDB Local
sidecar may share the network-denied test container's loopback namespace. Run
`task test:backend:integration` with its explicit local
`DYNAMODB_INTEGRATION_ENDPOINT`, require all four tests to pass without skips,
and stop only the owned sidecar afterward. Keep the Docker socket outside the
test container. This is an alternative to the host-managed Compose lifecycle,
not evidence that the Compose wrapper itself was executed in the container.

### Host workflow

The dev container is optional. On macOS 14+ or Ubuntu 24.04:

```sh
./scripts/bootstrap.sh
./scripts/bootstrap.sh --exec task setup
./scripts/bootstrap.sh --exec task setup:browser
./scripts/bootstrap.sh --exec task check
```

## Rebuild and update

Rebuild after changes to `.devcontainer/`, `mise.toml`, bootstrap scripts, or
dependency locks:

```sh
devcontainer up --workspace-folder . --remove-existing-container
devcontainer exec --workspace-folder . task setup
```

To update the base image, resolve the tag from authoritative MCR registry
metadata with `docker buildx imagetools inspect`, review both platform
manifests, update the index and platform digests in
`.devcontainer/base-image-lock.json`, update the Dockerfile digest, then build
and test both architectures. Run `task devcontainer:base-lock:verify`; it never
queries the mutable tag. Never replace the digest with a mutable tag.

To update Ubuntu packages, select and test a new timestamp from
`https://snapshot.ubuntu.com/ubuntu/`, then update the Dockerfile and
`.devcontainer/ubuntu-snapshot-lock.json` together. CI builds and runs package
and repository-tool smoke tests for both architectures; full checks and browser
smoke remain on native `amd64`.

## Troubleshooting

- **`task` is not found:** rebuild the container so the post-create hook and
  remote `PATH` are applied. Check that `.devcontainer-tools/mise/bin` and
  `.devcontainer-tools/mise/data/shims` are present in `PATH`.
- **Bootstrap checksum failure:** remove only the ignored
  `.devcontainer-tools/` directory and rerun the post-create script. Do not
  bypass checksum verification.
- **Chromium reports missing libraries:** rebuild the image. Playwright system
  dependencies belong in the Dockerfile; runtime sudo is not required.
- **Container health is unhealthy:** verify the runtime user is non-root and
  `/etc/os-release` reports Ubuntu 24.04.
- **Git is unavailable in a linked worktree:** the worktree's `.git` file may
  point to a common Git directory outside the mounted workspace. Use a normal
  clone for in-container Git operations. The container intentionally does not
  add an extra host Git-directory mount; Codespaces and cloud-agent clones do
  not have this linked-worktree limitation.
- **Setup changes repository files:** stop and inspect `git status`. The
  post-create hook fails closed if setup changes tracked, already-dirty, or
  pre-existing untracked source. When linked-worktree Git metadata is absent,
  secure workspace traversal provides the same content-aware protection while
  skipping only the documented generated directories in
  `.devcontainer/workspace-manifest-excludes.json`.
- **Out of memory or disk:** allocate at least the declared host requirements;
  image build, Python locks, Terraform providers, and Chromium need temporary
  working space.
