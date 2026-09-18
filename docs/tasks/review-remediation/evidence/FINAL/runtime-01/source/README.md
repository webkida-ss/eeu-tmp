# Untangle

Untangle is a Chrome extension paired with a FastAPI backend that explains
foreign-language articles inline while you read. Select a sentence or phrase on
any page and Untangle returns a translation, grammar and nuance notes,
vocabulary, and worked examples in an in-page reading panel — so you can keep
reading instead of switching to a dictionary or translator.

## Layout

```text
extension/   # Chrome extension (Manifest V3): content scripts, side panel, UI
backend/     # FastAPI service that calls the LLM provider and stores results
infra/       # Terraform for the AWS serverless deployment (Lambda + API + DynamoDB)
docs/        # Architecture, plan, performance, billing, and monetization notes
```

## Run locally

### Backend

One-time setup:

```sh
cd backend
cp .env.example .env          # then set OPENAI_API_KEY (and any other values)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Start DynamoDB Local, create the table, and run the API (keep this terminal open):

```sh
cd backend
./dev.sh
```

`dev.sh` starts DynamoDB Local on port 18000 via Docker, bootstraps the local
table, then runs uvicorn on port 18765. The extension talks to the backend on
`http://localhost:18765`.

For JSON storage without Docker, set `STORAGE_BACKEND=json` in `.env` and run
uvicorn directly instead.

### Extension

Load the unpacked extension in Chrome:

1. Open `chrome://extensions`.
2. Enable Developer mode.
3. Click "Load unpacked" and select the `extension/` directory.

For development with automatic reload on file changes, run `extension/dev.sh`
instead — it watches `extension/` and reloads the extension in Chrome via a
local reload server.

## Testing

```sh
./scripts/bootstrap.sh
./scripts/bootstrap.sh --exec task setup
./scripts/bootstrap.sh --exec task setup:browser
./scripts/bootstrap.sh --exec task test:extension:unit
./scripts/bootstrap.sh --exec task test:extension:smoke
```

The smoke test loads the unpacked Manifest V3 extension in Playwright's managed
Chromium. Failure traces, screenshots, and error reports are written under
`output/playwright/`.

### Local DynamoDB integration tests

Docker and Docker Compose v2 are required for the managed local integration
workflow:

```sh
task test:backend:integration:local
```

The task starts the CI-pinned DynamoDB Local image in memory on
`127.0.0.1:18000`, runs all four integration tests, verifies that none skipped,
and removes only this worktree's Compose container and network on exit. The
test fixture creates and deletes its temporary table; no table setup script or
persistent credentials/data are needed.

Use `task dynamodb:up` and `task dynamodb:down` to manage the same service
manually. The bounded Compose project name is derived from a stable hash of the
canonical checkout path and validated port. A per-project invocation lock under
the ignored `.runtime/` directory prevents overlapping lifecycle commands from
tearing down each other's resources and reports the active owner PID.
Concurrent checkouts and ports therefore use distinct projects; another
process can still own a requested host port. Stop that owner or select an unused
loopback port, for example
`DYNAMODB_LOCAL_PORT=18001 task test:backend:integration:local`. The default
and documented endpoint remains `http://127.0.0.1:18000`. The normal
`task check` remains service-free and never starts Docker.

Run `task test:dynamodb:automation` to check project identity, strict port
validation, and protection against hostile root `.env` overrides.

### Dev container

Docker and the Dev Container CLI provide the reproducible non-root cloud
development environment:

```sh
devcontainer up --workspace-folder .
devcontainer exec --workspace-folder . task setup
devcontainer exec --workspace-folder . task check
devcontainer exec --workspace-folder . task test:extension:smoke
```

The image supports `arm64` and `amd64`, defaults to mock auth and billing with
JSON storage, and does not mount cloud credentials, an SSH agent, or the host
Docker socket. Its base image is digest-pinned and APT uses a signed dated
Ubuntu snapshot; CI builds and runs non-root tool/package smoke checks on both
architectures. See `docs/CLOUD_DEVELOPMENT.md` for Cursor, cloud-agent,
Codespaces, rebuild, security, and integration-test guidance.

The initial targets are 15 minutes for container setup and 10 minutes for
`task check`. After the snapshot and content-manifest hardening, the 2026-07-19
Apple Silicon measurements were 85.14 seconds for the first
recreation/post-create after the image change (33.73 seconds warm), 7.27
seconds for setup, 322.11 seconds for `task check`, and 11.43 seconds for the
headless smoke test.

The extension unit suite also covers page-region detection, sentence matching,
markup, settings, and shared helpers against representative page fixtures.
Run `task test:extension:fidelity` after changing DOM analysis or its jsdom
harness so the fast tests cannot silently drift from real Chromium behavior.

## Documentation

See `docs/` for the architecture overview (`ARCHITECTURE.md`), the product plan
(`PLAN.md`), and notes on performance, billing, and monetization.

Repository-side online-agent policy, immutable actor-ID intake, role
separation, audit controls, external blockers, and local fallback are in
`docs/ONLINE_AGENT_OPERATIONS.md`. Reviewed but inactive Cursor Automation
drafts are in `docs/CURSOR_AUTOMATION_DRAFTS.md`. Deployment evidence,
approval, smoke, and rollback are in `docs/RELEASE_RUNBOOK.md`; production
always requires explicit human approval. Repository deployment is
plan-by-default and applies only the exact encrypted, versioned plan approved
for the protected default-branch commit—never a fresh re-plan.

## Deployment

`infra/` deploys the backend to AWS (Lambda + HTTP API + DynamoDB + SSM + cost
alerting) in two environments, `dev` and `prod`. See `infra/README.md` for the
architecture, bootstrap, secrets, and deploy runbook.

Build the Chrome Web Store upload artifact after deploying the backend:

```sh
python3 extension/scripts/build_release.py \
  --api-base-url "https://YOUR_API_ID.execute-api.ap-northeast-1.amazonaws.com" \
  --output "dist/untangle-0.1.0.zip"
```

The build validates the release manifest and runtime assets, injects the
production API URL into a temporary staging directory, and prints the artifact
SHA-256 digest. It does not modify the extension source files.
