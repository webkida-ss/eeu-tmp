# GitHub Repository Setup

This document describes external GitHub and AWS configuration that cannot be
completed by repository files alone. Applying any item below is an external
side effect and requires explicit approval. Do not place secrets in this file,
repository variables, issue bodies, or workflow logs.

## Branch protection for `main`

Enable a ruleset or branch protection rule that:

- requires pull requests and at least one independent approval;
- dismisses stale approvals after new commits;
- requires conversation resolution;
- blocks force pushes and branch deletion;
- prevents administrators and automation from bypassing the rule by default;
- requires branches to be up to date if the repository's merge policy needs it;
- requires signed commits only if all contributors and automation can support
  that policy; and
- requires the stable checks from `reading-assistant-ci.yml`:
  - `Detect changed areas`
  - `Backend tests`
  - `Extension tests`
  - `Secret scan`
  - `Terraform validate`

`Backend tests` includes the non-skipping DynamoDB integration task.
`Terraform validate` is path-filtered and can complete as skipped when no
infrastructure path changed. Confirm the exact check names from an initial
pull request before saving the protection rule. Add the two CodeQL matrix
checks after GitHub Code Scanning is enabled and their names have been
observed.

The repository has no Git remote metadata that proves a valid GitHub user or
team owner. `CODEOWNERS` is therefore intentionally absent. After ownership is
confirmed in GitHub, maintainers must add a real user or team and then decide
whether code-owner review is required.

## Optional browser workflow

Create the `run-browser-smoke` label. Configure the repository variable
`TRUSTED_BROWSER_AUTOMATION_ACTOR_IDS` as a comma-separated list of immutable
numeric GitHub actor IDs authorized to apply that label or manually dispatch
the workflow. Do not use display names. The workflow also requires the pull
request author association to be `OWNER`, `MEMBER`, or `COLLABORATOR`; fork and
untrusted pull requests receive no secret and no write-capable token.

## Online agent intake

Configure repository variable `TRUSTED_AGENT_ACTOR_IDS` as a comma-separated
list of independently verified numeric GitHub actor IDs. This variable is
separate from `TRUSTED_BROWSER_AUTOMATION_ACTOR_IDS`. Display names, team
names, author association, issue labels, comments, and issue content are not
authorization.

The `Agent Intake Policy Gate` is manual and read-only. Test an untrusted actor,
a fork repository fixture, a pull request number, and a malicious prompt before
using an acceptance artifact. The workflow must deny those cases without
fetching broader data or checking out an issue-controlled ref. It uploads only
sanitized JSON and Markdown; raw issue content is not retained as an artifact.

Cursor cloud compute and the drafts in `docs/CURSOR_AUTOMATION_DRAFTS.md`
remain inactive until separately approved. Follow
`docs/ONLINE_AGENT_OPERATIONS.md` for audit, cost, timeout, incident-stop, and
local-fallback controls.

## GitHub Environments and AWS OIDC

Create `dev` and `prod` GitHub Environments. Configure required reviewers for
both; production must require at least one independent human reviewer. Enable
**Prevent self-review** so the actor who dispatched or prepared a deployment
cannot approve that run. Do not allow administrators or automation to bypass
the environment gate. The `apply` job enters the selected Environment only
after the exact plan job has completed and stored its immutable object version.

Configure these non-secret application variables at repository scope so the
plan job can produce the same input set that the approved apply consumes:

- `READING_ASSISTANT_GOOGLE_OAUTH_CLIENT_ID`
- `READING_ASSISTANT_ALERT_EMAIL`
- `READING_ASSISTANT_STRIPE_PRICE_ID_PRO`
- `READING_ASSISTANT_STRIPE_PRICE_ID_MAX`
- `READING_ASSISTANT_APP_EXTRA_ENVIRONMENT` (optional JSON object)

Configure these repository variables for the exact-plan control plane:

- `TRUSTED_DEPLOY_ACTOR_IDS`: strict comma-separated immutable numeric actor
  IDs, with no spaces or empty values;
- `AWS_PLAN_ROLE_ARN_DEV` and `AWS_PLAN_ROLE_ARN_PROD`: separate read-only
  Terraform plan roles, each limited to one environment plus its run-derived
  encrypted `PutObject` key shape;
- `AWS_APPLY_ROLE_ARN_DEV` and `AWS_APPLY_ROLE_ARN_PROD`: separate
  write-capable Terraform apply roles;
- `TERRAFORM_PLAN_BUCKET`: private, block-public-access, versioned S3 bucket;
- `TERRAFORM_PLAN_KMS_KEY_ARN`: customer-managed KMS key dedicated to plans;
- `TERRAFORM_STATE_BUCKET`: the account S3 bucket that holds Terraform
  state. This is an identifier, not a secret; do not commit the real name.
  The workflow passes it to `terraform init` as `-backend-config=bucket=...`.

The workflow fails before requesting OIDC when any value is absent, malformed,
the roles are equal, the actor is untrusted, the workflow/ref is not the
current protected default branch, or production confirmation is not exactly
`APPLY-PROD-<current-main-SHA>`.

Plan review limits are compile-time policy, not workflow inputs. If resource,
changed-path, drift, output, replacement-path, path-depth, scan, or summary-byte
presentation would truncate, the plan job fails before descriptor creation and
S3 upload. Operators must split the change or revise the constants and
adversarial tests in a reviewed code change; do not add a runtime bypass. The
workflow binds complete-plan classification digest/counts into the S3 metadata
and plan record, and the apply job reclassifies the downloaded plan before
apply.

Configure GitHub's OIDC subject template with `repo`, `context`, and
`job_workflow_ref`, and use immutable repository subject IDs where the
organization supports them. The plan subject's context must be the protected
default ref. Each apply subject's context must be exactly its protected
Environment; its `job_workflow_ref` must end in the protected default ref.
The repository gate independently rejects a non-default or unprotected run ref
before either job requests OIDC.

Attach separate trust policies to the plan, dev-apply, and prod-apply roles.
Use exact `StringEquals` for both `aud=sts.amazonaws.com` and the complete
subject; do not combine the role subjects or use wildcards. Start from:

- `docs/examples/aws-plan-oidc-trust-policy.json`
- `docs/examples/aws-apply-dev-oidc-trust-policy.json`
- `docs/examples/aws-apply-prod-oidc-trust-policy.json`

Replace every account, owner, repository, workflow, branch, and Environment
placeholder. Independently capture and verify each rendered token subject
before attaching the matching policy. A plan subject must not assume either
apply role, and an apply subject must not assume the plan or other
Environment's role.

The dev-plan, prod-plan, dev-apply, and prod-apply roles must have separate
permission policies. Plan-role OIDC trust uses the same exact protected
workflow/default-ref subject because the plan job intentionally has no
Environment approval; the repository gate selects the environment-specific
role from fixed variables before OIDC. Apply trust additionally binds the
matching protected Environment.

- each plan role can read only its exact state object/version and stack
  resources, cannot lock or write Terraform state, cannot mutate
  infrastructure, and can only encrypt and write the two run-derived objects
  `terraform-plans/<run>/<attempt>/<environment>/<commit>/tfplan` and its
  sibling `reading-assistant-lambda.zip`; its KMS context must list exactly
  those same two object patterns. The workflow therefore plans with `-lock=false`;
- the apply role can read only a specified version of those same two objects,
  decrypt with the matching two-object plan-key context, and perform the
  reviewed Terraform apply;
- neither role can delete plan versions; private bucket lifecycle policy
  expires current and noncurrent versions after 14 days; and
- the KMS key policy admits only the plan/apply roles and security audit role.

Use the separate templates:

- `docs/examples/aws-plan-role-policy-dev.json`
- `docs/examples/aws-plan-role-policy-prod.json`
- `docs/examples/aws-apply-plan-read-policy-dev.json`
- `docs/examples/aws-apply-plan-read-policy-prod.json`

Replace `ACCOUNT_ID`, `REGION`, `STATE_BUCKET`, `STATE_KMS_KEY_ARN`,
`PRIVATE_PLAN_BUCKET`, and `PLAN_KMS_KEY_ARN`, then run
`python scripts/validate_aws_plan_policies.py`. Do not attach both plan
templates to one role. The templates intentionally enumerate exact read
actions and environment resources rather than using `Get*`, `List*`, or
`Describe*` Allow actions.

Some provider refresh APIs cannot be resource-scoped. Lambda event-source
mapping listing, log-group listing, subscription lookup, and alarm description
are isolated in `RegionalAccountScopedUnscopableReads` with a required region
and account condition where AWS supplies the account key. Caller identity is
isolated as the sole action in `CallerIdentityOnly`. The role remains
account-bound, and an organization SCP
must deny access outside approved regions/accounts and deny mutation as a
second boundary. Validate the policy against AWS service authorization
metadata and a sandbox plan before activation; remove any residual read action
the provider does not actually call. Add only stack-specific apply permissions
proven by Terraform. Do not copy placeholder account, bucket, key, owner,
repository, or branch values into production.

Do not create long-lived AWS access-key secrets in GitHub. Application secret
values remain in the approved external secret store. Before first use, verify
S3 versioning, default SSE-KMS, lifecycle expiry, CloudTrail data events, KMS
audit logging, role boundaries, and denial of plan-role infrastructure writes.

## Nightly issue permissions

Scheduled workflows must be enabled for the repository. The nightly workflow
uses `contents: read` by default; only its notification job receives
`issues: write`. Confirm that organization or repository Actions policy allows
the workflow token to create and close issues. The issue contains only a
static title, status, and GitHub run URL; logs remain in workflow artifacts.

## Private vulnerability reporting

Enable GitHub Private Vulnerability Reporting in the repository security
settings if available. Keep public blank issues disabled. If private reporting
is unavailable, establish a private repository-owner contact channel without
publishing credentials or inventing an email address. See `SECURITY.md`.

## Initial schema compatibility baseline

The schema compatibility check fails closed when a push has an all-zero
`before` SHA. After the canonical schema is present on the default branch,
select a reviewed, non-zero commit SHA containing the accepted schema and run
`Reading Assistant CI` manually with that exact SHA as
`trusted_base_sha`. For later pull requests and ordinary pushes, the workflow
uses the event's base or previous commit automatically. Never substitute
`HEAD` as a compatibility baseline.

## External side-effect checklist

Complete these only with explicit approval and record the reviewer and exact
scope:

- [ ] Connect or create the GitHub remote.
- [ ] Confirm repository owner/team and add `CODEOWNERS`.
- [ ] Create the branch ruleset and required checks.
- [ ] Enable GitHub Actions and scheduled workflows.
- [ ] Create the browser label and trusted numeric actor-ID variable.
- [ ] Configure and denial-test `TRUSTED_AGENT_ACTOR_IDS`.
- [ ] Enable Code Scanning and confirm CodeQL availability for the repository.
- [ ] Enable Dependabot alerts and update pull requests.
- [ ] Enable Private Vulnerability Reporting.
- [ ] Confirm nightly workflow issue-write policy.
- [ ] Create protected `dev` and `prod` Environments and variables.
- [ ] Set required reviewers and Prevent self-review on both Environments.
- [ ] Configure and denial-test `TRUSTED_DEPLOY_ACTOR_IDS`.
- [ ] Create private versioned plan S3, dedicated KMS, 14-day lifecycle, and
      CloudTrail data events.
- [ ] Create distinct dev/prod plan and apply roles; run the policy validator
      and cross-environment denial tests, then verify each plan role cannot
      mutate, apply, write state, read the other environment, or delete plans.
- [ ] Customize the GitHub OIDC subject and install exact aud/sub plan,
      dev-apply, and prod-apply trusts without wildcards.
- [ ] Populate production secrets through the approved external secret store.
- [ ] Run the initial schema-baseline dispatch.
- [ ] Perform any deployment only through an explicitly approved environment.
- [ ] Review Cursor compute limits and each Automation draft before activation.

Current blockers are intentional: there is no Git remote, the CODEOWNERS
handle is unknown, trusted agent/deploy actor IDs are unset, GitHub
Environments and exact OIDC trust are inactive, private plan S3/KMS and
distinct plan/apply roles do not exist, and Cursor compute and Automations are
inactive.
