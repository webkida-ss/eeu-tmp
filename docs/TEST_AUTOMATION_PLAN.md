# Test Automation Plan

## Purpose

Build a test and development workflow that remains fully usable on a local
machine, then progressively moves execution and agent-driven work to GitHub and
cloud environments.

Local development remains the fallback after cloud adoption. Cloud agents and
CI must use the same Taskfile commands and quality gates as local developers.

## Authorization and Delivery Model

Implementation remains incremental: each change must be small, independently
verifiable, and easy to review or revert.

The user has explicitly authorized continuous repository-side implementation
of all five phases. Proceed from one verified repository change to the next
without repeated approval. This authorization covers files, tests, workflows,
containers, and agent configuration committed to the repository.

It does not pre-authorize external side effects. Stop for an explicit gate
before changing GitHub settings, AWS resources or configuration, Cursor
Automations, credentials or secrets, deployments, or any other external
system. Also stop for a material decision not settled by this plan.

## Goals

- Run all essential checks locally with one command and without paid services.
- Make development setup reproducible from a fresh clone.
- Prevent regressions through required GitHub checks.
- Test the Chrome extension in a real browser environment.
- Allow cloud agents to receive online instructions and submit verified pull
  requests.
- Keep production deployment behind explicit human approval.

## Current Baseline

Baseline observations are anchored to source commit
`0bf858454d90884159d6d7efff6535b8c82ab6f4`:

- `cd backend && .venv/bin/python -m pytest -q` observed 352 passed, 4 skipped,
  and 17 subtests.
- `cd extension && node --test test/shared.test.mjs` observed 33 passing tests.
- DynamoDB integration tests skip when `DYNAMODB_INTEGRATION_ENDPOINT` is
  unset.
- When that endpoint is set, the shared fixture waits for the service, creates
  an isolated table for the test module, and deletes it afterward. A
  pre-initialized table and `STORAGE_BACKEND=dynamodb` are not prerequisites
  for the current integration tests.
- `terraform -chdir=infra fmt -check -recursive`,
  `terraform -chdir=infra/envs/dev init -backend=false -input=false &&
  terraform -chdir=infra/envs/dev validate`, and
  `terraform -chdir=infra/envs/prod init -backend=false -input=false &&
  terraform -chdir=infra/envs/prod validate` observed success.
- `.github/workflows/reading-assistant-ci.yml` already covers backend tests,
  extension unit tests, and conditional Terraform validation, but invokes
  pytest, Node, and Terraform directly.
- AWS deployment is defined as a manually triggered GitHub Actions workflow
  using GitHub OIDC and Terraform.
- `task test:backend:coverage` observed 456 passing tests, 17 passing
  subtests, 85.45% line coverage, and 69.87% branch coverage. Coverage.py's
  combined terminal total rounded to 82%.
- `task test:extension:coverage` observed 56 passing tests, 34.67% statement
  and line coverage, 80.04% branch coverage, and 58.04% function coverage.
  The `--all` report intentionally records unexercised classic-script UI files
  at 0% rather than hiding them.

These counts are observations for detecting unexpected change, not permanent
pass-count gates. Success gates use command exit status and scenario outcomes.
The coverage percentages are also observations, not pass thresholds.

The exact baseline commands are:

```sh
./scripts/bootstrap.sh --exec task test:backend:coverage
./scripts/bootstrap.sh --exec task test:extension:coverage
```

Backend terminal, Cobertura XML, JSON, and HTML reports are written under
`output/coverage/backend/`. Extension terminal, JSON summary, LCOV, and HTML
reports are written under `output/coverage/extension/`. Both output directories
are ignored build artifacts. No coverage threshold is configured initially.

The observed quality-tool versions in the managed locks are Ruff 0.15.22,
pytest-cov 7.1.0 with Coverage.py 7.15.2, ESLint 10.7.0, Prettier 3.9.5,
globals 17.7.0, and c8 12.0.0.

The main gaps are:

- There is no unified local command runner, despite the repository rule
  prescribing `Taskfile.yaml`.
- Python, Node.js, Playwright, and Terraform provider dependencies are not all
  reproducibly locked.
- The Playwright smoke test depends on undeclared packages and macOS-specific
  browser paths.
- Several substantial extension UI and orchestration files have little
  automated coverage outside the smoke test; avoid relying on a fragile exact
  line count as these files change.
- DynamoDB integration now has a committed, end-to-end local service bootstrap
  that exposes `DYNAMODB_INTEGRATION_ENDPOINT`; table lifecycle remains handled
  by the test fixture.
- There are no lint, coverage, Lambda packaging, or post-deployment health
  gates.
- Formatting hooks use the managed Ruff and Prettier installations and are
  generated consistently for Cursor, Claude, and Codex from `.rulesync/`.
- Repository guidance uses the canonical fixture-managed local integration
  Task command instead of a separate table bootstrap script.

## Guiding Principles

1. Local checks are the source of truth. CI invokes the same Taskfile tasks.
2. Tests use mock providers and JSON storage by default.
3. Real OpenAI, Stripe, Google, and AWS calls are excluded from pull request
   checks.
4. Fast service-free checks and the existing DynamoDB integration job run on
   every pull request; browser checks may initially run nightly.
5. A cloud agent creates a branch and pull request. It does not push directly
   to `main`.
6. Production changes always require human approval.
7. Automation is introduced in small, independently verifiable units.
8. API automation follows the schema-first repository rule. The current
   code-first FastAPI/Pydantic schemas are not treated as the canonical
   schema by default.
9. All committed code, comments, and documentation are written in English.
10. Repository implementation for all five phases is authorized. External
    writes, credentials, settings, automations, and deployments require a
    separate explicit approval at the point of action.

## Target Workflow

```text
Online instruction or local edit
             |
             v
Feature branch created
             |
             v
Local or cloud agent runs task check
             |
             v
Pull request created
             |
             v
GitHub required checks
  - lint and static checks
  - backend unit tests
  - extension unit tests
  - contract checks
  - Terraform validation
             |
             v
Review and human approval
             |
             v
Merge to main
             |
             v
Explicit dev deployment approval and smoke verification
             |
             v
Explicit production approval
```

## Fresh-Clone Bootstrap Contract

Support macOS 14 or newer and Ubuntu 24.04 LTS. A fresh machine needs only Git,
`curl`, and standard OS certificate tooling before repository bootstrap.

Phase 1 adds `scripts/bootstrap.sh`. It must detect the supported OS, install or
verify Task, Python 3.12, Node.js 22, and Terraform 1.15.5, then print actionable
errors for unsupported systems. Exact releases and the trusted mise binary
checksums are recorded in the repository bootstrap configuration.

Dependency reproducibility uses:

- exact runtime patch versions recorded by the bootstrap/tool-version files;
- a small Python development/test input file followed by generated,
  hash-checked deterministic locks for development/test and Lambda;
- `package-lock.json` for Node.js and Playwright tooling;
- committed Terraform environment lockfiles while retaining the justified
  `~> 6.0` AWS provider constraint; and
- the repository's pinned Rulesync package and generator command.

`./scripts/bootstrap.sh --exec task setup` installs project dependencies after
bootstrap without requiring the bootstrap process to mutate its parent shell's
`PATH`. Browser binaries are the repository's responsibility:
`./scripts/bootstrap.sh --exec task setup:browser` installs managed Playwright
Chromium and required Ubuntu system packages; it must not depend on a
developer's system Chrome path.

Bootstrap acceptance target:

- On clean macOS 14+ and Ubuntu 24.04 environments,
  `./scripts/bootstrap.sh &&
  ./scripts/bootstrap.sh --exec task setup &&
  ./scripts/bootstrap.sh --exec task check` exits `0`.
- A second run exits `0` without changing tracked files.
- `git diff --exit-code` exits `0` after both runs.
- Neither run prompts for service credentials or starts a deployment.

## Test Execution Matrix

- **`task check`:** in Phase 1, compose exactly backend unit tests, extension
  unit tests, and Terraform validation. In Phase 2, expand it with lint,
  contract/schema checks, coverage collection, and Lambda build validation.
  It remains service-free and targets at most 10 minutes locally.
- **Required PR:** fan out equivalent Taskfile tasks into backend unit,
  extension unit, the existing DynamoDB integration job, and a path-filtered
  Terraform job. Current CI already provisions pinned DynamoDB Local and sets
  `DYNAMODB_INTEGRATION_ENDPOINT=http://localhost:8000`; preserve that
  non-skipping required integration behavior. `task check` may include
  Terraform locally while CI fans out and path-filters the equivalent
  `task infra:validate` task. Every required command must exit `0`.
- **Optional PR:** run `task test:extension:smoke` on an explicit label or
  manual dispatch while browser stability is being established. It is
  non-blocking, targets at most 10 minutes, and uploads traces, screenshots,
  and console logs on failure.
- **Nightly:** rerun `task test:backend:integration` with provisioned DynamoDB
  and run `task test:extension:smoke` with managed Playwright Chromium. Each
  command must exit `0`. Retain reports and failure artifacts for 14 days; a
  failure opens or updates one visible issue.

Durations are initial targets, not claims about current performance. Record
actual p50 and p95 durations for four weeks before tightening them.

## Phase 1: Reproducible Local Automation

Create one local interface from small, focused tasks that follow the repository
Taskfile rule:

- `task setup`
- `task run:backend`
- `task test:backend:unit`
- `task test:backend:integration`
- `task test:extension:unit`
- `task test:extension:smoke`
- `task lint:backend`
- `task lint:extension`
- `task infra:validate`
- `task build:lambda`
- `task check`

In Phase 1, `task check` composes only `task test:backend:unit`,
`task test:extension:unit`, and `task infra:validate`. DynamoDB integration and
browser tasks remain independently callable.

Implementation units:

1. Add `Taskfile.yaml` with granular tasks and explicit composite tasks.
2. Add the fresh-clone `scripts/bootstrap.sh`, pin Python 3.12 and Node.js 22,
   and record the exact Task release and checksums.
3. Add a small Python development/test requirements unit first. Inventory
   imports and test skips in the current repository to verify optional
   dependencies before adding them; for example, Stripe is currently optional
   in local requirements and present in Lambda requirements. Do not add
   packages based only on assumptions.
4. After the development/test dependency split is proven, introduce
   deterministic Python locks for development/test and production/Lambda
   environments.
5. Add `extension/package.json` and a lockfile for the existing test tooling
   before adding further browser packages.
6. Make the Playwright smoke test discover its managed Chromium executable on
   macOS and Linux.
7. Keep formatting hooks disabled until real formatters are installed. Use the
   canonical local integration Task command in repository guidance; the
   integration fixture creates and removes its own table, so a separate table
   bootstrap script is not required.
8. Remove `.terraform.lock.hcl` from `.gitignore`, run Terraform initialization
   in each root environment, and commit the resulting
   `infra/envs/dev/.terraform.lock.hcl` and
   `infra/envs/prod/.terraform.lock.hcl`. Retain the current AWS provider
   constraint `~> 6.0` unless compatibility evidence or an ADR justifies a
   tighter constraint; committed lockfiles provide exact reproducibility.
9. Update the root README with the one-command workflow.

Acceptance criteria:

- On both supported clean environments, the bootstrap acceptance commands
  above exit `0`.
- `task check` exits `0` without API keys, AWS credentials, DynamoDB, or other
  network services and meets the 10-minute target once measured.
- `task test:backend:unit` exits `0` with `STORAGE_BACKEND=json`.
- With no `DYNAMODB_INTEGRATION_ENDPOINT`,
  `task test:backend:integration` exits `0` and reports the current integration
  tests as skipped. Phase 1 does not start DynamoDB automatically.
- With a caller-supplied reachable `DYNAMODB_INTEGRATION_ENDPOINT`, the same
  task exits `0` and those integration tests do not skip. The fixture creates
  and removes its table; no pre-initialized table is required.
- `test -f extension/manifest.json`, both
  `rg -q 'Load the unpacked extension' README.md` and
  `rg -q 'select the .*extension/.* directory' README.md` exit `0`, and running
  bootstrap/setup leaves `git diff --exit-code -- README.md extension` at `0`.
  This preserves the documented manual unpacked-extension loading path without
  adding a Phase 1 browser-flow requirement.
- Both Terraform environment lockfiles are tracked; `task infra:validate` and
  `git diff --exit-code` exit `0`.

## API Schema Migration Prerequisite

Before adding generated API contract tests, create an ADR under `docs/adr/`
that decides how to migrate from the current code-first FastAPI/Pydantic
schemas to a canonical API schema.

The ADR must document:

- the selected canonical schema format and ownership;
- how backend server types, frontend client types, clients, and contract tests
  will be generated where practical;
- the transition strategy for existing FastAPI routes and Pydantic models;
- compatibility checks during migration;
- exceptions where generation is impractical, including their rationale; and
- alternatives, trade-offs, and rollback considerations.

Do not present tests generated from FastAPI's runtime OpenAPI output as
schema-first compliance. They may be used temporarily as migration evidence
only if the ADR explicitly defines that role. Contract generation begins after
the ADR is accepted.

## Phase 2: Expand Local Test Coverage

### Backend

- Separate unit and integration tests with pytest markers.
- Add coverage reporting without initially enforcing an arbitrary percentage.
- Implement the accepted API schema ADR, then generate contract artifacts and
  tests from the canonical schema where practical.
- Cover SQS runner, worker handler, and Lambda packaging behavior.
- Add `task dynamodb:start`, `task dynamodb:stop`, and a composite local
  `task test:backend:integration:local` task that starts the pinned DynamoDB
  Local service, waits for readiness, exports
  `DYNAMODB_INTEGRATION_ENDPOINT`, runs the integration tests without skips,
  and cleans up. The fixture continues to manage its temporary table.
- Keep unit tests on `STORAGE_BACKEND=json`.
- Resolve the current FastAPI test-client deprecation warning.

### Chrome Extension

- Extract testable behavior from `content.js`, `panel-ui.js`,
  `reading-panel.js`, and `background.js` into small modules.
- Add unit tests for state transitions, message handling, rendering, storage,
  localization, and API error behavior.
- Keep a small Playwright smoke suite for extension loading and primary user
  flows.
- Save Playwright traces, screenshots, and console errors on failure.

The deterministic smoke scenario follows the existing smoke-test scope:

1. Load the unpacked extension and verify its service worker starts.
2. Open the fixture article and verify the content script answers `PING`.
3. Open the side panel and mount the fixture preload.
4. Assert the sentence list and sentence detail, including vocabulary
   rendering.
5. Switch locale and assert the relocalized UI, then enable and assert the dark
   theme.
6. Fail on any fatal console error or page error.

### Quality Gates

- Add Ruff for Python formatting and linting.
- Add ESLint and Prettier for extension JavaScript.
- Validate the Lambda package in a clean environment.
- Record coverage as a CI artifact, then set file-specific thresholds after a
  stable baseline is available.
- Expand `task check` from its Phase 1 composition with lint,
  contract/schema checks, coverage collection, and Lambda build validation.

Acceptance criteria:

- `task test:backend:unit` exits `0` in a target of five minutes and requires no
  service.
- `task test:backend:integration:local` exits `0` in a target of five minutes,
  reports no skipped tests in the two DynamoDB integration files, and leaves
  no test container running. It requires neither a pre-initialized table nor
  `STORAGE_BACKEND=dynamodb`.
- `task test:extension:smoke` completes all six deterministic scenarios above
  in a target of 10 minutes with no fatal console or page errors. On forced
  failure, CI uploads a trace, screenshot, and console log.
- `task build:lambda` exits `0` in a clean environment and produces a
  versioned artifact whose contents pass an import smoke test.
- The schema generator exits `0`, generated contract tests pass, and rerunning
  generation followed by `git diff --exit-code` exits `0`.
- Coverage commands exit `0` and upload machine-readable and HTML reports;
  thresholds are added only after a baseline is recorded.

## Phase 3: GitHub CI and Repository Protection

1. Create or connect the GitHub repository.
2. Require pull requests for `main`.
3. Migrate every direct test and validation command in
   `.github/workflows/reading-assistant-ci.yml` to the corresponding Taskfile
   command. This includes dependency setup as appropriate, backend unit and
   DynamoDB integration tests, extension unit tests, Terraform formatting, and
   both Terraform environment validations.
4. Keep backend unit, extension unit, DynamoDB integration, and path-filtered
   Terraform jobs required, using the Taskfile tasks equivalent to local
   `task check` plus the service-backed integration task.
5. Add a nightly workflow that reruns DynamoDB integration and adds
   `task test:extension:smoke`.
6. Upload coverage, Playwright traces, and Lambda artifacts.
7. Add dependency update automation and CodeQL after the core checks are
   stable.
8. Add lightweight repository governance only as needed. Pull request and issue
   templates, `CODEOWNERS`, `CONTRIBUTING.md`, and `SECURITY.md` are later-stage
   additions rather than prerequisites for core test automation.
9. Configure concurrency so obsolete runs are cancelled.
10. Migrate every third-party GitHub Action from a mutable major-version tag to
    a reviewed full commit SHA, retaining a comment with the human-readable
    release version.

The required PR suite targets at most 10 minutes on the standard Ubuntu runner.
Retries must not hide flaky tests; each accepted flaky test needs an owner,
issue, and removal date.

Acceptance criteria:

- Workflow lint passes, all migrated workflow commands invoke Taskfile tasks,
  and no direct pytest, Node test, or Terraform validation command remains in
  `reading-assistant-ci.yml`.
- A test pull request with an intentional unit-test failure is blocked; after
  reverting the failure, all required checks exit `0`.
- The required DynamoDB PR job provisions the pinned service, supplies
  `DYNAMODB_INTEGRATION_ENDPOINT`, and runs both integration files without
  skips.
- The measured required-suite duration is recorded; enforcement begins only
  after its p95 is at most the 10-minute target.
- A forced nightly smoke failure uploads the named browser artifacts and opens
  or updates one issue; a subsequent passing run closes or annotates it.
- Every external `uses:` entry is pinned to a 40-character commit SHA.
- External branch-protection or repository-setting changes occur only after
  the explicit side-effect gate.

## Phase 4: Reproducible Cloud Development

Phase 4 repository implementation is authorized and starts after Phases 1-3
meet their acceptance criteria. External cloud configuration and deployment
remain behind the explicit side-effect gate.

Repository-side Phase 4 was implemented on 2026-07-19. The immutable
multi-platform Ubuntu 24.04 base, non-root least-capability runtime, secure
post-create bootstrap, fork-safe dev-container CI, and operator guidance live
under `.devcontainer/`, `.github/workflows/devcontainer-ci.yml`, and
`docs/CLOUD_DEVELOPMENT.md`. No external cloud setting or deployment is part of
this phase.

- Add a dev container with Python 3.12, Node.js 22, Terraform, Task,
  Chromium, and required system packages.
- Use the dev container for GitHub Codespaces and compatible cloud agents.
- Make `task setup` the cloud environment bootstrap command.
- Keep mock providers as the default cloud-agent configuration.
- Use GitHub OIDC for AWS access; do not store long-lived AWS credentials.
- Configure GitHub Environments for `dev` and `prod` when cloud deployment is
  enabled.
- Prepare repository workflows for `dev` and `prod`, but require explicit
  approval immediately before each deployment.

Acceptance criteria:

- From a clean clone, `devcontainer up --workspace-folder .` and
  `devcontainer exec --workspace-folder . task setup` exit `0` in a target of
  15 minutes; `devcontainer exec --workspace-folder . task check` exits `0` in
  the matrix's 10-minute target.
- Rebuilding the container and rerunning setup leaves
  `git diff --exit-code` at `0`.
- A pull request from a fork receives no environment secret and has read-only
  repository permissions.
- The supported macOS and Ubuntu bootstrap scenarios continue to exit `0`.
- Creating GitHub Environments, OIDC trust, or a deployment requires a
  separate explicit approval.

The actual verification commands are:

```sh
devcontainer up --workspace-folder .
devcontainer exec --workspace-folder . task setup
devcontainer exec --workspace-folder . task check
devcontainer exec --workspace-folder . task test:extension:smoke
```

On an Apple Silicon Docker Desktop host, the measured observations after
snapshot and content-manifest hardening on 2026-07-19 were 85.14 seconds for
the first container recreation plus post-create after the image change (33.73
seconds warm), 7.27 seconds for idempotent setup, 322.11 seconds for `task
check`, and 11.43 seconds for the browser smoke. A static `linux/amd64`
snapshot image build under emulation took 124.28 seconds; both platform images
passed exact-architecture, non-root, package, and repository-tool smoke tests.
These are single observations, not p50/p95 claims; the 15-minute setup and
10-minute check targets remain unchanged.

## Phase 5: Online Agent Operations

Phase 5 repository implementation is authorized and begins after local, CI,
and cloud automation meet their acceptance criteria. Committing role
definitions, workflows, policies, and dry-run automation is in scope.
Activating Cursor Automations, issuing tokens, changing GitHub settings,
writing to external systems, or deploying remains behind an explicit gate.

Repository-side Phase 5 was implemented on 2026-07-20. Rulesync owns focused
roles and online-operation skills; a manual read-only issue intake gate
validates immutable actor IDs and emits sanitized evidence; policy tests cover
untrusted actors, forks, labels, prompt injection, workflow provenance, role
separation, and deploy gates. The deploy workflow is plan-by-default with
job-scoped OIDC, strict deploy actor/default-branch gates, distinct plan/apply
roles, private versioned SSE-KMS plan storage, exact object-version and digest
verification, apply-role and whole-record digest binding, dependent Environment
approval, and exact production confirmation. Terraform values and stderr are
not logged; bounded review output contains only sanitized resource addresses,
action kinds, changed/sensitive paths, replacement reasons, drift/output
metadata, high-risk categories, and a source hash. Any presentation truncation
fails before plan upload with no runtime bypass. Complete-plan classification
occurs before presentation limits; its digest and counts are bound into the
record and reverified from the downloaded plan before apply. Separate
environment plan-role templates deny cross-environment state, Lambda, SSM, and
stack reads. Apply consumes the reviewed binary without re-planning.
Operational, release, and inactive Cursor Automation drafts live under
`docs/`.

No Git remote exists, the CODEOWNERS handle is unknown,
`TRUSTED_AGENT_ACTOR_IDS` and `TRUSTED_DEPLOY_ACTOR_IDS` are unset, GitHub
Environments, exact AWS OIDC subjects, distinct roles, private plan S3/KMS,
Cursor compute, and Automations are inactive. Those external blockers are
deliberately not changed by repository implementation.

Possible roles:

- **Planner:** identifies scope, risks, contracts, and required tests.
- **Implementer:** changes one approved implementation unit at a time.
- **Test runner:** read-only; analyzes immutable parent- or CI-provided check
  evidence and requests exact execution from the parent.
- **CI investigator:** diagnoses failed GitHub checks from artifacts and logs.
- **Reviewer:** performs correctness review; security review is invoked for
  authentication, billing, secrets, or infrastructure changes.
- **Release agent:** read-only; proposes the dev release plan and evidence
  content for the parent to write.

Possible online entry points:

- Cursor cloud-agent instructions.
- GitHub issues labeled as ready for agent work.
- Pull request comments requesting a focused update.
- Scheduled automation for nightly failure triage and dependency maintenance,
  when its cost and maintenance burden are justified.

Agent permissions:

- Agents may create branches, commits, and pull requests for an approved task.
- Agents may not bypass checks, force-push protected branches, read production
  secrets, or approve their own production deployment.
- Agents must report test evidence and known limitations in the pull request.

### Online-Agent Security Controls

- Accept write-capable instructions only from a configured allowlist of trusted
  GitHub actor IDs or equivalent immutable identities. Display names and
  untrusted issue labels are insufficient.
- Treat issue bodies, pull request text, comments, repository content, web
  pages, logs, and tool output as untrusted data that may contain prompt
  injection. They cannot override repository policy, expand scope, reveal
  secrets, or authorize tools.
- Isolate fork-originated workflows. They receive no secrets, no cloud
  credentials, and read-only `GITHUB_TOKEN` permissions; privileged follow-up
  runs require trusted review and a new explicit approval.
- Default every workflow and token to least privilege. Use job-scoped
  permissions, short-lived OIDC credentials, scoped installation or fine-grain
  tokens, protected environments, and explicit allowlists for writable paths
  and external destinations.
- Require an explicit human approval immediately before every external write,
  deployment, credential issuance, environment change, or automation
  activation. Planning and dry runs do not grant execution permission.
- Log the trusted actor identity, source event, commit SHA, requested scope,
  approvals, tool calls, test evidence, and resulting pull request or
  deployment.
- Pin all third-party Actions to reviewed full commit SHAs before enabling
  write-capable online automation.

Acceptance criteria:

- A dry-run event from an allowlisted actor produces a branch/PR plan tied to
  the exact source commit; the same event from a non-allowlisted actor performs
  no write and records a denial.
- A fork test confirms no secret values or write permissions are present.
- A prompt-injection fixture that requests secret disclosure, policy override,
  or deployment is quoted as untrusted input and causes no prohibited tool
  call.
- A write/deploy scenario pauses before the side effect and proceeds only
  after a recorded approval scoped to that exact action and commit SHA.
- All jobs declare explicit permissions, write-capable tokens are short-lived
  and destination-scoped, and every third-party Action uses a 40-character
  commit SHA.
- The produced pull request links passing required checks, artifacts, actor
  identity, source event, and audit log. A forced failure produces no external
  write and exits nonzero.

## Configuration Ownership

Commit to the repository:

- Task definitions and setup scripts.
- Dependency and Terraform lockfiles.
- Tests, fixtures, lint configuration, and coverage configuration.
- GitHub Actions workflows.
- Dev container configuration when Phase 4 begins.
- `.rulesync/` source files and generated agent configuration.
- Architecture decisions under `docs/adr/`.

Configure outside the repository:

- Branch protection and required checks.
- GitHub Environment reviewers, variables, and secrets.
- AWS OIDC trust and SSM secret values.
- Cursor cloud compute and automation triggers.
- External service credentials and notification destinations.

## Agent Configuration Maintenance

`.rulesync/` is the existing source of truth for shared agent guidance. Update
rules, skills, subagents, hooks, and related shared configuration there, then
run Rulesync to generate tool-specific Cursor, Claude, Codex, and root files.

Rulesync 14.0.1, Context7 MCP 3.2.4, and Playwright MCP 0.0.78 are exact root
development dependencies. `task setup:agents` installs them with
`npm ci --ignore-scripts`. MCP configuration uses only repository-local locked
binaries; no generated target uses `npx`, `@latest`, credentials, or automatic
authentication. Starting either MCP server remains optional and outside the
service-free quality gate.

`AGENTS.md` must be generated through Rulesync. Do not hand-maintain it.

The CI drift check must:

1. run Rulesync's native `generate --check`;
2. verify the exact generated inventory, target and source counts, root
   instructions, locked MCP commands, hook timeout, and Claude deny rule;
3. generate twice in a temporary copy and require a no-diff result; and
4. test manual edits, deletions, additions, source drift, target-count drift,
   and mutable MCP command rejection.

This makes stale or manually edited generated files visible. The generated
`AGENTS.md` should include the actual FastAPI/Python and Chrome Manifest
V3/JavaScript stack, canonical Taskfile commands, mock-provider and JSON-storage
defaults, secret restrictions, pull request and deployment boundaries, and
browser-testing limitations.

Reintroduce generated formatting hooks only after the quality-gate unit
installs and configures the real Ruff and Prettier formatters.

## Metrics

Track lightweight metrics first:

- Pull request check duration and success rate.
- Flaky test count.
- Browser-test failure evidence availability.
- Coverage trend by subsystem.
- Escaped regressions found after merge.

When Phases 4-5 reach operation, also track:

- Time from online instruction to reviewable pull request.
- Dev deployment success and rollback rate.
- Cloud-agent and scheduled-automation cost.

## Risks and Controls

- **Browser test instability:** use managed Chromium, deterministic fixtures,
  traces, and narrowly scoped end-to-end flows.
- **Dependency drift:** use lockfiles and automated update pull requests after
  core checks are stable.
- **Agent rule drift:** use `.rulesync/` as the source and run the generator
  followed by `git diff --exit-code`.
- **Contract drift:** select a canonical API schema in a `docs/adr/` decision
  and generate artifacts where practical.
- **DynamoDB false confidence:** keep JSON unit tests service-free and require
  a reachable `DYNAMODB_INTEGRATION_ENDPOINT` for integration. Let the fixture
  create and remove its isolated table automatically.
- **Secret exposure:** use mock providers, OIDC, scoped environments, and
  secret scanning.
- **Cloud-only dependency:** preserve and regularly run the local workflow.
- **Unsafe deployment:** separate build, dev verification, and production
  approval.
- **Automation cost growth:** keep pull request checks fast, introduce
  expensive suites and online-agent tooling later, and require an explicit gate
  before activating cost-bearing external automation.

## Recommended Implementation Order

The user has authorized continuous repository-side execution of these
independently verifiable units across all five phases. Pause at each external
side-effect gate:

1. Add granular Taskfile commands and canonical local composites.
2. Add `scripts/bootstrap.sh` with supported-platform checks and pinned tool
   installation.
3. Add the small development/test requirements unit after verifying current
   optional dependencies.
4. Add deterministic Python, Node.js, and Terraform locks.
5. Make Playwright portable and reproducible.
6. Keep formatter hooks disabled and repository setup guidance canonical.
7. Add linting, coverage collection, and Lambda build validation.
8. Create and accept the API schema migration ADR under `docs/adr/`.
9. Generate contract artifacts and tests according to that ADR.
10. Add a committed DynamoDB Local service bootstrap that exports
   `DYNAMODB_INTEGRATION_ENDPOINT`, then rely on the test fixture for table
   creation and cleanup.
11. Migrate all `reading-assistant-ci.yml` direct commands to Taskfile tasks
    while keeping DynamoDB integration required on pull requests.
12. Connect GitHub and protect `main`; add nightly DynamoDB reruns and
    Playwright without removing required PR integration.
13. Consolidate generated agent configuration around `.rulesync/` and add the
    generator-plus-diff drift check.
14. Implement Phase 4 repository configuration after core CI meets its
    acceptance criteria; request approval before external cloud changes.
15. Implement Phase 5 repository controls after Phase 4 meets its acceptance
    criteria; request approval before activating automations, issuing
    credentials, writing externally, or deploying.
