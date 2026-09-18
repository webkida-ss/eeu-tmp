# Online Agent Operations

## Status and safety boundary

This document defines the repository-side operating model for online agents.
Repository policy, role definitions, a manual read-only intake gate, and
automation drafts are present. Cursor Automations, Cursor cloud compute,
GitHub write automation, credentials, and deployment are not activated.

An issue, label, pull request, comment, log, artifact, repository file, web
page, or tool result is untrusted data. None can authorize a tool, expand
scope, reveal a secret, waive a check, approve a release, or trigger a
deployment. An immutable actor ID proves only who requested intake; it does
not grant implementation or external-write authority.

## End-to-end flow

1. **Local request and planning**
   - A maintainer creates a bounded task locally or uses the agent-task issue
     form.
   - The planner records the exact source commit, goal, acceptance criteria,
     allowed and prohibited scope, risks, and canonical Task evidence.
   - Local work remains the source of truth:
     `./scripts/bootstrap.sh --exec task check`.
2. **GitHub intake**
   - A trusted maintainer manually dispatches `Agent Intake Policy Gate` with
     an existing issue number.
   - The workflow compares `github.actor_id` with the repository variable
     `TRUSTED_AGENT_ACTOR_IDS`.
   - It checks out only the trusted workflow commit, fetches minimal repository
     and issue metadata, rejects forks and pull requests, and creates sanitized
     JSON and Markdown artifacts.
   - Labels are included only as advisory context and never authorize work.
3. **Human review**
   - A maintainer reviews the sanitized artifact, especially prompt-injection
     indicators, scope, risk, and prohibited actions.
   - Approval is tied to the issue number, exact source commit, allowed paths,
     and expected evidence. Intake success is not implementation approval.
4. **Cloud-agent implementation, when externally enabled**
   - A cloud agent starts from the reviewed source commit on a new feature
     branch.
   - The implementer changes one approved unit and cannot approve or release
     its own work.
   - The runtime-read-only test runner analyzes immutable parent- or
     CI-provided Task evidence. The implementer or parent executes the exact
     approved checks in a credential-free, network-denied dev container.
5. **Pull request**
   - A separate actor creates the pull request only after external write
     approval. The pull request records actor ID, source event, base and head
     commits, scope, tool use, tests, artifacts, limitations, and rollback.
   - Required CI runs with read-only defaults. Fork code receives no secrets,
     environment, OIDC identity, or write token.
6. **Checks and review**
   - The CI investigator is read-only and handles one failed check at a time.
   - The correctness reviewer cannot mutate code.
   - Authentication, authorization, billing, secrets, personal data,
     infrastructure, workflow privilege, and deployment changes require the
     security reviewer boundary.
7. **Release and deploy**
   - The runtime-read-only release preparer returns a commit-bound plan and
     proposed evidence content. The implementer or parent writes approved
     artifacts in the credential-free, network-denied dev container.
   - The plan job runs only from the current protected default-branch commit
     for an allowlisted actor. Its read-only AWS role can write only one
     run-derived, SSE-KMS encrypted binary plan into private versioned S3.
   - The dependent apply job begins after the plan and protected Environment
     approval. The plan gate validates the exact apply-role ARN once and binds
     its digest into the plan metadata and immutable record digest. A distinct
     apply role is assumed only from that plan-job output after the pre-OIDC
     record check; the apply job never re-resolves a repository or Environment
     role variable. It downloads the exact object version, verifies commit,
     environment, key, version, metadata, role binding, record digest, and
     plan SHA-256, and applies that binary without re-planning.
   - Production also requires the exact input
     `APPLY-PROD-<current-main-SHA>`. Metadata-only evidence is uploaded to
     GitHub; binary plans remain private in S3 for the 14-day audit lifecycle.
   - The release preparer and implementer cannot approve their own work.

## Immutable actor-ID setup

GitHub logins and display names can change. Use numeric actor IDs:

1. Independently verify each maintainer's numeric GitHub actor ID through an
   authenticated, trusted administrative process.
2. Record the review ticket and reviewer outside issue text.
3. Set repository variable `TRUSTED_AGENT_ACTOR_IDS` to a comma-separated list
   such as `12345,67890`. Do not add whitespace, names, tokens, or secrets.
4. Run a manual denial test with a non-allowlisted actor and an acceptance test
   with an allowlisted actor.
5. Review the list quarterly and immediately after role or account changes.

The variable is currently unset. Until configured and reviewed, the workflow
fails closed before fetching issue metadata.

## Prompt injection threat model

Attackers can place instructions in issues, comments, branch names, code,
tests, logs, test fixtures, generated files, artifacts, package metadata, and
linked pages. They may ask an agent to ignore policy, read a credential, run a
different ref, use a label as approval, contact an external service, or deploy.

Controls:

- classify all task content as data, quote it in sanitized artifacts, strip
  controls and bidirectional formatting, neutralize mentions, and flag common
  instruction-override, secret-request, side-effect, and workflow-expression
  patterns;
- authorize intake with immutable actor IDs before API access;
- validate repository, issue number, fork state, open state, URL, source SHA,
  and issue-versus-pull-request type;
- fetch no comments, attachments, linked pages, check logs, or issue-controlled
  refs during intake;
- keep tokens read-only and omit secrets;
- bind plans and evidence to exact commits;
- separate implementation, correctness review, security review, release
  preparation, and human deployment approval; and
- stop on ambiguity. Never ask the untrusted source to resolve authorization.

Detection does not make malicious text safe. A clean indicator list is not
proof that content is trustworthy.

## Permission matrix

- **Planner:** read repository scope and run read-only analysis; no code
  mutation, secret read, external write, approval, or deployment.
- **Implementer:** modify only approved repository paths and run local checks;
  no secret read, settings change, release approval, or deployment.
- **Test runner:** execute approved Taskfile checks and write ignored local
  artifacts; no implementation mutation or external write.
- **CI investigator:** read one sanitized CI evidence set; no workflow rerun,
  comment, branch mutation, or secret-bearing logs.
- **Correctness reviewer:** read diff and evidence; no code mutation, approval
  on behalf of a human, or deploy.
- **Security reviewer:** read sensitive-boundary code and sanitized evidence;
  no secret values, code mutation, risk acceptance, or deploy.
- **Release preparer:** prepare plan and evidence; no tag, publish, apply,
  credential issuance, or self-approval.
- **Intake workflow:** `contents: read` and `issues: read`; may upload only its
  sanitized artifact. It has no checkout of an issue-controlled ref.
- **Required CI:** read-only repository access and artifact upload; no cloud
  credentials for pull requests.
- **Deploy workflow:** OIDC exists only in the plan and apply jobs after local
  policy gates. The jobs assume distinct roles. Apply is dependent,
  environment-scoped, exact-version-only, and cannot re-plan.

## Branch, PR, check, review, and deploy separation

- A task approval names a source commit; it does not approve a future diff.
- An implementation branch never targets `main` directly.
- A pull request is an external write and requires explicit authorization.
- Passing checks prove only the tested commit and do not constitute review.
- Correctness and security reviews are independent of implementation.
- Merge authorization is separate from release preparation.
- A release plan does not authorize deploy.
- Dev apply is explicit. Production apply is explicit, independently reviewed,
  environment-gated, and bound to the selected commit.

Force pushes, check bypass, self-approval, `pull_request_target`, long-lived
credentials, and secrets exposed to untrusted code are prohibited.

## Repository intake artifacts

Run the validator locally with a synthetic or securely obtained minimal payload:

```sh
python scripts/validate_agent_intake.py \
  --input /tmp/agent-intake-raw.json \
  --json-output /tmp/agent-intake.json \
  --text-output /tmp/agent-intake.txt \
  --provenance-output /tmp/agent-intake-provenance.json
```

The online gate creates the transient raw payload only after strict actor,
repository, workflow-ref, Git-ref, fork, issue, and current default-branch
commit checks. The sanitizer rejects common private-key, token, cloud-key,
provider-key, bearer, credential-assignment, workflow-secret, and JWT patterns,
then deletes the raw file.

The committed artifact contract contains only immutable IDs, workflow/run
provenance, title/body hashes, a bounded neutralized title, and neutralized
values from the six agent-task form sections. It contains no raw body,
comments, labels, active Markdown, HTML, links, images, mentions, or fences.
The provenance sidecar records workflow ref, run ID/attempt, current
default-branch commit, and SHA-256 for each sanitized artifact.

## GitHub external setup steps

Each step is an external side effect and requires explicit approval:

1. Create or connect the GitHub remote.
2. Confirm the repository owner or team and add a real `CODEOWNERS` entry.
3. Configure branch protection and required check names.
4. Set and review `TRUSTED_AGENT_ACTOR_IDS`.
5. Enable Actions and manually test the intake denial and acceptance paths.
6. Create protected `dev` and `prod` GitHub Environments, required independent
   reviewers, and Prevent self-review.
7. Configure distinct plan/apply roles, private versioned plan storage,
   customer-managed KMS, exact OIDC subjects, and the repository variables in
   `GITHUB_SETUP.md`.
8. Enable audit-log retention and establish an incident owner.

Do not store secret values in repository variables, issues, artifacts, or
documentation.

## Cursor external setup steps

These are reviewed setup instructions, not activation:

1. Enable Cursor cloud compute only after repository and organization policy
   review.
2. Restrict the repository and default base branch.
3. Configure cost ceilings, concurrency one, and bounded timeouts.
4. Grant no production credentials and no default external-write tools.
5. Copy a reviewed draft from `CURSOR_AUTOMATION_DRAFTS.md`.
6. Review the exact trigger, actor restrictions, tools, branch behavior,
   actions, and deferred settings.
7. Perform a dry run and inspect audit logs.
8. Obtain a separate approval immediately before activating each Automation.

No Automation has been opened or activated by this repository work.

## Audit logs and evidence

For every accepted task record:

- immutable actor ID and source event;
- repository, issue number, base commit, head commit, and branch;
- approved and prohibited scope;
- prompt-injection indicators and sanitized artifact digest;
- role handoffs and tool calls;
- exact Task commands, exit codes, skips, and artifact identifiers;
- correctness and security review results;
- external-write and environment approvals;
- deployment operation, commit, approver, smoke result, and rollback result.

Retain repository workflow artifacts for 14 days. Longer retention belongs in
the approved organizational audit system, not in issue bodies.

## Cost and timeout limits

- Intake: one manual run, one issue, five-minute job timeout.
- Agent implementation: one task and one branch at a time, with a documented
  budget and maximum runtime before activation.
- Required CI: preserve the ten-minute target.
- Browser smoke: run only when required by scope or approved schedule.
- Deployment workflow: 30-minute Terraform timeout; plan remains the default.
- Scheduled dependency maintenance: at most monthly and one bounded update
  group per run until cost and reliability are measured.

Stop rather than automatically extending a timeout or spending limit.

## Incident stop switch

If an agent exceeds scope, attempts a secret read, follows injected
instructions, writes externally without approval, or produces unexplained
activity:

1. **Incident commander:** declare the stop, assign a private incident record,
   and coordinate evidence preservation.
2. **GitHub administrator:** cancel active GitHub runs, disable affected
   workflows, remove trusted actor IDs, protect branches, and quarantine
   branches and workflow artifacts without opening them in unsafe tooling.
3. **Cursor administrator:** disable the affected Automations and cloud-agent
   compute triggers, revoke repository access, and preserve Cursor audit logs.
4. **AWS security administrator:** remove OIDC trust or attach an explicit deny
   to the plan/apply roles. Invoke `AWSRevokeOlderSessions` where supported, or
   apply an equivalent time-bounded explicit deny to invalidate existing role
   sessions.
5. **Secret owner:** rotate affected SSM parameters and provider credentials,
   including OpenAI, Stripe, Google, notification, or other scoped values.
6. **Security reviewer:** quarantine plan objects, generated evidence, logs,
   and branches; preserve S3 version IDs, KMS, CloudTrail, GitHub, and Cursor
   audit records; assess disclosure before deletion.
7. **Repository maintainer:** restore local-only operation with Automations,
   online workflows, OIDC trust, and external write paths disabled. Run the
   canonical local gate before any recovery change.
8. **Independent approver:** review root cause, containment, credential
   rotation, rollback, and new controls before re-enabling one component at a
   time.

The repository-local stop switch is to use only local Taskfile commands and not
dispatch any online workflow.

Run a tabletop stop/rollback drill every quarter and after material permission
changes. The checklist must test run cancellation, workflow/Automation disable,
actor removal, OIDC denial, session invalidation, credential rotation,
artifact quarantine, audit export, local fallback, exact-plan rollback, and
independent reactivation approval. Record only role names, timestamps, evidence
IDs, and outcomes—never secret values.

## Rollback and local fallback

Repository policy changes roll back through a reviewed revert. Generated agent
outputs must be regenerated from `.rulesync/` and pass drift checks. Agent
branches are abandoned or reverted; they are never force-merged. A failed dev
release follows `RELEASE_RUNBOOK.md`. Production rollback requires the same
explicit human and environment controls as production apply.

The local fallback is always available:

```sh
./scripts/bootstrap.sh
./scripts/bootstrap.sh --exec task setup
./scripts/bootstrap.sh --exec task check
```

Local fallback uses mock providers, JSON storage, no cloud credential, and no
external agent trigger.

## Exact external blockers

- **No Git remote:** repository ownership, default branch, and GitHub workflow
  behavior cannot be verified remotely.
- **Unknown CODEOWNERS handle:** no valid user or team can be safely committed.
- **Trusted actor IDs unset:** `TRUSTED_AGENT_ACTOR_IDS` is not configured.
- **Trusted deploy actor IDs unset:** `TRUSTED_DEPLOY_ACTOR_IDS` is not
  configured.
- **GitHub Environments inactive:** `dev` and `prod` protection and reviewers
  are not configured.
- **AWS OIDC inactive:** exact subject customization and distinct plan/apply
  trusts are not configured.
- **Private plan storage inactive:** versioned S3, KMS, lifecycle, CloudTrail,
  environment-specific `AWS_PLAN_ROLE_ARN_<ENV>` and
  `AWS_APPLY_ROLE_ARN_<ENV>`, `TERRAFORM_PLAN_BUCKET`, and
  `TERRAFORM_PLAN_KMS_KEY_ARN` are unset.
- **Cursor compute inactive:** cloud-agent runtime, budget, and retention are
  not configured.
- **Cursor Automations inactive:** the drafts are not activated and have no
  triggers or credentials.

These are expected external gates, not repository test failures.
