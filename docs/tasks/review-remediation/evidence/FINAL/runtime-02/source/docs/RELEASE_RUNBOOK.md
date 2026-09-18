# Release Runbook

Production always requires explicit human approval. A plan, passing check,
actor allowlist, issue label, merge, release artifact, or previous approval
does not authorize a deployment.

## 1. Prepare the dev plan

The release preparer works read-only and binds the candidate to:

- exact commit SHA and target `dev` environment;
- included pull requests and approved scope;
- immutable Lambda artifact identity or digest;
- Terraform and data-migration impact;
- required configuration names without values;
- smoke, monitoring, incident-stop, and rollback steps.

Use the manual deploy workflow with the default `operation=plan`. Do not select
apply during evidence gathering. The plan job first verifies the immutable
actor, current protected default-branch commit, exact workflow ref, separate
role ARNs, bucket, KMS key, and operation. Only then does it assume the
read-only plan role.

The plan role runs Terraform with state locking disabled. Terraform stdout,
plan values, JSON, and stderr remain private on the ephemeral runner and are
deleted after use. The workflow prints only a deterministic value-free summary
of resource addresses, action kinds, changed attribute paths with sensitive
markers, replacement paths/reasons, drift, output names/actions/sensitivity,
and high-risk categories. It never prints before/after values. The summary is
count/size bounded. Any resource, changed-path, drift, output, replacement-path,
path-depth, scan, or byte truncation is a policy failure: the workflow stops
before descriptor creation or upload. There is no dispatch input or runtime
bypass. Split the infrastructure change into a reviewable plan, or change the
limits in `scripts/exact_plan_policy.py` through a separately reviewed pull
request with updated adversarial tests. Failures emit a generic message without
raw stderr.

Before applying presentation limits, the policy classifies the complete private
plan. It binds the full-plan classification SHA-256 and resource, drift, output,
high-risk, replacement, and sensitivity counts into object metadata and the
immutable plan record. It then hashes the binary and stores it at the
run-derived key:

```text
terraform-plans/<run-id>/<attempt>/<environment>/<commit>/tfplan
```

The private S3 bucket must be versioned and default to the configured SSE-KMS
key. Separate dev/prod plan roles receive only their exact state and
environment resource reads plus the narrow encrypted run-derived object write;
neither can read the other environment, apply, mutate infrastructure, write
state, or delete plans. The validated apply-role ARN digest is included in
object metadata, and a record digest binds the role, bucket, key, version, plan
SHA, full-plan classification digest/counts, commit, environment, run, and KMS
key. The same immutable record also binds the Lambda ZIP's canonical object key,
S3 VersionId, SHA-256, and fixed restore destination
`backend/dist/reading-assistant-lambda.zip`. GitHub receives metadata-only
evidence, never either binary.

## 2. Gather evidence

Record fresh evidence for the candidate commit:

```sh
./scripts/bootstrap.sh --exec task agents:check
./scripts/bootstrap.sh --exec task test:agents
./scripts/bootstrap.sh --exec task test:online-agents
./scripts/bootstrap.sh --exec task test:deploy:policy
./scripts/bootstrap.sh --exec task check
./scripts/bootstrap.sh --exec task test:backend:integration:local
./scripts/bootstrap.sh --exec task test:extension:smoke
```

Service-backed and browser checks are required when the release affects those
boundaries. Record exact commands, exit codes, skipped checks, workflow run and
artifact IDs, source commit, correctness review, security review, residual
risk, and rollback owner. Never copy secret values or raw sensitive logs into
evidence.

## 3. Human approval

An independent human compares the plan and evidence with the exact commit.
Approval must name environment, operation, commit, known risk, and rollback.
The implementer and release preparer cannot approve their own work.

For dev apply:

- explicitly dispatch `operation=apply` and `environment=dev`;
- leave `production_confirmation` empty; and
- satisfy required independent `dev` Environment review with Prevent
  self-review enabled.

For production:

- verify the tested dev commit is the production candidate;
- require independent correctness and applicable security review;
- explicitly dispatch `operation=apply`, `environment=prod`, and
  `production_confirmation=APPLY-PROD-<current-main-SHA>`; and
- approve the protected `prod` GitHub Environment immediately before the job.

If the protected environments or OIDC trust are absent, stop. Do not substitute
local credentials or a less protected workflow.

## 4. Deploy

Only the approved manual workflow may apply. The apply job depends on the plan
job and begins only after Environment approval. It checks out the exact planned
commit, derives the only acceptable object key from run, attempt, environment,
and commit. Before OIDC it verifies the plan-record digest and the exact
plan-bound apply-role ARN digest, then assumes only the ARN emitted by the plan
job, never a newly resolved variable. It downloads the recorded S3
`VersionId` and verifies version, KMS key, metadata, environment, commit,
workflow-ref hash, role binding, binary SHA-256, and classification
digest/counts. It restores the separately recorded Lambda ZIP only to its fixed
destination and verifies its VersionId, SSE-KMS metadata, plan association, and
actual SHA-256 before Terraform initialization. After Terraform initialization it independently classifies the
downloaded exact plan and compares every bound classification field before
running `terraform apply` against that exact `tfplan`. It never runs a fresh
plan.

Confirm the run, plan digest, commit, environment, and independent reviewer
before approval. A changed plan, missing object version, digest mismatch,
metadata mismatch, newer S3 version, failed check, stale approval, or
classification mismatch, summary truncation, unexpected resource replacement,
or presentation overflow fails closed and returns the release to planning.

The binary plan is retained privately for 14 days by S3 current/noncurrent
version lifecycle, then expired. Workflow roles cannot delete it. CloudTrail
data events, KMS events, GitHub run logs, and the metadata-only artifact form
the audit trail.

Do not apply from a pull-request or fork workflow. Do not use
`pull_request_target`, long-lived AWS keys, force pushes, self-approval, or
check bypass.

## 5. Smoke and observe

After an approved dev apply:

1. confirm the health endpoint and expected deployment outputs;
2. run the approved API smoke using non-production test data;
3. run the extension smoke against the approved dev endpoint when applicable;
4. inspect alarms, Lambda errors, latency, and cost signals;
5. record timestamps and sanitized evidence; and
6. stop promotion on any unexplained result.

After production apply, run the smallest approved smoke. Do not broaden access
or inspect customer data. Monitor the agreed window and record the human owner.

## 6. Rollback

Rollback is an external side effect and requires the same explicit human and
environment controls as apply.

1. Invoke the incident stop switch and halt further promotion.
2. The GitHub administrator cancels active runs and disables the workflow.
3. The Cursor administrator disables affected Automations and compute.
4. The AWS security administrator removes OIDC trust or applies an explicit
   deny and uses `AWSRevokeOlderSessions` or an equivalent deny to invalidate
   sessions.
5. The secret owner rotates affected SSM and provider credentials.
6. The security reviewer quarantines plan versions, artifacts, logs, and
   branches while preserving audit evidence.
7. Identify the last known-good commit and immutable artifact.
8. Review Terraform and data compatibility before reverting.
9. Prepare a new exact plan bound to the rollback commit.
10. Obtain independent approval for the exact environment and operation.
11. Apply through the protected manual workflow.
12. Repeat smoke and monitoring, restore local fallback, and document result.

Never use an unreviewed force push, mutable artifact, ad hoc local AWS
credential, or destructive state command as rollback.

## Current external blockers

No Git remote exists; the CODEOWNERS handle is unknown; trusted actor IDs are
unset; distinct plan/apply roles, private versioned plan S3, KMS, exact OIDC
subjects, and GitHub Environments are inactive; Cursor compute and Cursor
Automations are inactive. Repository evidence can be prepared locally, but
deployment must not proceed until each applicable external gate is configured
and explicitly approved.
