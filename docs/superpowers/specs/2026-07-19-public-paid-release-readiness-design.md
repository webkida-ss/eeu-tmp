# Public Paid Release Readiness Design

## Purpose

Prepare Untangle for a staged public paid launch in Japan within one month.
The release must support real Google sign-in, paid Stripe subscriptions, Chrome
Web Store distribution, production operations, and customer support without
depending on manual developer intervention for normal user flows.

This design coordinates release work with the test automation and admin
console efforts already running in separate workstreams. It does not duplicate
their implementation plans.

## Release Strategy

Use a staged launch:

1. Establish the public distribution, legal, identity, and payment paths.
2. Verify failure handling and production operations.
3. Run a paid pilot with 5–20 users.
4. Open the same release to the public after a formal go/no-go review.

Chrome Web Store and Google OAuth review times are external dependencies.
Submit them during the first week rather than waiting for all implementation
work to finish. If either review is incomplete at the end of the month, delay
public availability instead of weakening the release criteria.

## Current Readiness Summary

The repository already contains:

- Existing AWS and Stripe accounts. Their production configuration and
  end-to-end integration still need release verification.
- A Manifest V3 Chrome extension with Google sign-in, reading assistance,
  vocabulary, usage display, an 80-percent quota warning, and subscription
  controls.
- A FastAPI backend with repository interfaces, DynamoDB adapters, Google and
  mock identity providers, Stripe and mock billing providers, and usage quotas.
- Terraform for separate AWS dev and prod environments using Lambda, API
  Gateway, SQS, DynamoDB, S3, CloudWatch, SNS, SSM, and AWS Budgets.
- Manual GitHub Actions deployment through OIDC and environment approval.
- Backend, extension unit, DynamoDB integration, and Terraform validation
  workflows.
- A separate test automation plan and an active automation branch.

The release currently has important gaps:

- Google OAuth production configuration and Chrome Web Store developer setup
  are not ready.
- No public privacy policy, terms of service, commercial transaction
  disclosure, or support channel is present in the repository.
- No account and user-data deletion flow was found.
- Product analytics for activation, successful analysis, quota pressure, and
  checkout conversion were not found.
- The extension API endpoint is a packaging-time source replacement rather
  than a reproducible release-build input.
- The manifest requests access to all HTTP and HTTPS pages. The permissions,
  user disclosure, and store justification need to agree.
- Existing AWS alerting covers budget and invocation volume, but not the main
  user-impact signals such as API failures, worker failures, DLQ depth,
  processing latency, or billing webhook failures.
- The documented composite usage reservation enforcement remains disabled
  pending staging concurrency verification.
- The repository has no configured Git remote in the inspected checkout, so
  branch protection, release tags, and remote deployment checks cannot yet be
  relied upon from this checkout.

## Scope and Priority

### P0: Required for public paid launch

- Reproducible extension release packaging and versioning.
- Chrome Web Store submission and policy-complete listing.
- Production Google OAuth, Stripe, AWS, OpenAI, and extension integration.
- Public legal pages and a monitored support channel.
- An approved launch-pricing decision supported by unit economics and a clear
  customer-facing plan comparison.
- Verified subscription purchase, renewal, cancellation, downgrade, refund,
  webhook replay, and entitlement behavior.
- Account deletion and deletion of user-owned data.
- Production health, error, queue, cost, and billing alerts.
- Backup, rollback, incident response, and customer-support runbooks.
- Completion of release-critical automated and manual regression tests.
- A successful paid pilot and a documented go/no-go decision.

### P1: Include only if P0 remains on schedule

- Minimal first-run onboarding that gets a new user to the first successful
  article analysis.
- A support or feedback link in the extension.
- Minimal privacy-conscious product events for activation, first analysis,
  processing failure, quota reached, checkout started, and checkout completed.

### P2: Post-launch

- Monthly recap email.
- Review cards and expanded study features.
- Annual plans, discounts, team plans, and referral systems.
- Priority processing and a higher-quality max-plan model.
- A broader analytics platform or marketing automation.
- Major admin-console features beyond launch operations.

## Release Gates

### Gate 1: Distribution

Required outcomes:

- Chrome Web Store developer registration is complete.
- The listing contains final Japanese copy, screenshots, icons, category,
  support URL, privacy policy URL, and accurate single-purpose and permission
  explanations.
- A single command produces a clean ZIP from tracked source, injects the
  production API URL without source editing, validates required icon assets,
  and rejects development-only files.
- The package version is tied to a Git tag and release notes.
- The submitted package is smoke-tested after installation through the same
  channel users will receive.

### Gate 2: Production Platform

Required outcomes:

- Prod deploys are reproducible through the approved GitHub environment.
- Google OAuth consent, client ID, redirect URI, authorized domains, and test
  users are verified using a store-installed extension ID.
- Stripe live products, prices, Customer Portal, webhook endpoint, signing
  secret, tax settings, receipts, and customer-facing business details are
  configured.
- OpenAI has explicit project-level spend and rate limits.
- Production uses Google auth, Stripe billing, DynamoDB storage, SQS jobs, and
  the intended usage-meter mode.
- Secrets contain no placeholders and secret rotation has been rehearsed.
- DynamoDB point-in-time recovery and the S3 lifecycle policy are confirmed.

### Gate 3: Legal and Trust

Required outcomes:

- Publish Japanese terms of service, privacy policy, commercial transaction
  disclosure, support contact, cancellation and refund explanation, and an AI
  output disclaimer.
- State what page content, account data, vocabulary, usage data, and payment
  identifiers are sent or stored, why they are needed, their retention period,
  and the deletion process.
- Ensure the Chrome Web Store privacy declarations, legal pages, extension
  behavior, backend logs, and third-party processor list are consistent.
- Have the final legal text reviewed by a qualified professional before broad
  promotion. Repository planning is not legal advice.

### Gate 4: Quality and Security

Required outcomes:

- Merge the test automation work and make its fast checks required for changes.
- Verify sign-in, sign-out, token expiry, article preload, cached and uncached
  selection, chat, quota limits, checkout, plan updates, cancellation, and
  webhook recovery in a production-like environment.
- Exercise duplicate, delayed, out-of-order, and invalid Stripe webhooks.
- Verify that authorization isolates every user-owned record.
- Confirm logs and analytics do not contain article text, selected text,
  credentials, full payment identifiers, or replay payloads.
- Review extension permissions and remove any that are not required.
- Add dependency, secret, and static security scanning to the release gate.
- Complete the staging concurrency tests required before enabling composite
  usage reservation enforcement. Do not enable it on an unverified assumption.

### Gate 5: Operations

Required outcomes:

- Alert on API errors, Lambda errors and throttles, worker errors, DLQ depth,
  stale processing jobs, latency, Stripe webhook failures, OpenAI failures,
  and abnormal cost or signup patterns.
- Provide dashboards or saved queries for the same signals.
- Define severity levels, response ownership, customer communication, rollback,
  and recovery procedures.
- Verify rollback to the previous backend artifact and previous extension ZIP.
- Verify DynamoDB recovery and safe replay of failed jobs and webhooks.
- Monitor the published support channel and establish an initial response
  target.

The admin console should provide read-only launch operations first: user
lookup, subscription state, current usage, preload status, and identifiers
needed to correlate structured logs. Mutation features must use explicit,
audited service operations rather than direct database edits. A full admin
console is not a launch blocker if the same safe operational tasks are covered
by documented AWS and Stripe procedures during the pilot.

### Gate 6: Product

Required outcomes:

- Hold a separate pricing review covering target users, willingness-to-pay
  hypotheses, expected provider cost, Stripe fees, taxes, quotas, and margin.
- Approve JPY launch prices, quotas, and plan names before the paid pilot.
- Present price, billing period, quota, renewal, cancellation, and tax details
  before checkout.
- Make the first successful analysis achievable without developer assistance.
- Show useful, localized errors for auth, quota, provider, queue, and network
  failures.
- Record only the minimal launch funnel events needed to assess activation,
  reliability, quota pressure, and purchase completion.

## Four-Week Schedule

### Week 1: Create the Public Release Path

- Freeze non-P0 feature work.
- Register and submit the first Chrome Web Store package.
- Implement reproducible release packaging, icon validation, API URL injection,
  version validation, and artifact checks.
- Configure production Google OAuth.
- Publish the legal and support pages.
- Start the pricing review and collect the cost assumptions needed for a
  decision in Week 2.
- Configure the existing Stripe account for live Customer Portal, webhook
  destination, and customer-facing business information. Create final live
  products only after the pricing decision.
- Deploy or verify the dev and prod infrastructure baseline.

Exit criteria:

- Store and OAuth review submissions are in progress.
- A store-ready ZIP can be reproduced.
- Legal and support URLs are publicly reachable.
- A new production account can complete Google sign-in.

### Week 2: Control Failure Modes

- Complete the production-like end-to-end billing and entitlement suite.
- Implement account and user-data deletion.
- Add the missing operational alerts and saved diagnostic views.
- Exercise backup, restore, deployment rollback, secret rotation, DLQ, and
  webhook replay procedures.
- Complete the pricing review, approve launch prices and quotas, and create the
  corresponding Stripe live products.
- Complete privacy and permission review.
- Complete the staging concurrency and idempotency checks for the usage meter.
- Integrate the release-critical portion of test automation.

Exit criteria:

- The complete sign-in-to-cancellation journey works in production-like
  conditions.
- Operational owners receive a test notification from every critical alert
  path.
- Recovery procedures have execution evidence, not only documentation.
- No unresolved P0 security or data-isolation issue remains.

### Week 3: Run a Paid Pilot

- Invite 5–20 users and charge the approved pilot price.
- Verify purchase, renewal simulation where possible, cancellation, refund,
  logout and login, and entitlement updates.
- Add P1 onboarding, support link, and minimal events only when P0 remains
  green; verify the existing quota warning with pilot users.
- Review support cases, failed jobs, auth failures, billing failures, latency,
  and provider cost every day.
- Reopen price or quota decisions only if pilot evidence invalidates a recorded
  assumption; otherwise keep them stable through public launch.
- Fix only P0 and high-value P1 defects.

Exit criteria:

- At least one real transaction has completed, cancelled, and been refunded
  with the correct entitlement at each step.
- Pilot users can reach first value without developer intervention.
- No unexplained data loss, cross-user access, duplicate charge, or runaway
  provider cost has occurred.
- Known issues and support responses are documented.

### Week 4: Decide and Launch

- Freeze changes for the final 72 hours except release blockers.
- Run the final automated suite and store-installed manual regression.
- Prepare the production database recovery point, previous backend artifact,
  previous extension ZIP, release notes, and incident communication.
- Hold the formal go/no-go review.
- Publish the store listing and begin a controlled announcement.
- Monitor auth, billing, OpenAI cost, worker jobs, DLQ, latency, support, and
  store reviews closely for the first 48 hours.

Exit criteria:

- Every go condition is supported by current evidence.
- The on-call owner can stop new promotion or charging and execute rollback.
- Release notes, known limitations, and support information are public.

## Go/No-Go Decision

The public paid launch is a Go only when all of the following are true:

- A new store user can install, sign in, analyze an article, see usage, buy a
  plan, receive the entitlement, cancel it, and contact support.
- Payment and entitlement state remain consistent under webhook retries and
  delays.
- Public legal pages and accurate store privacy declarations are live.
- Required checks pass and there are no open P0 defects.
- Critical alerts, rollback, data recovery, and support procedures have been
  exercised.
- Real pilot usage shows bounded OpenAI cost and acceptable completion time.
- The store package and deployed backend versions are identifiable and
  recoverable.

The launch is No-Go if Chrome Web Store or OAuth approval is incomplete, a
payment can be duplicated or lose entitlement, user data cannot be deleted, a
cross-user authorization issue exists, production failures are not observable,
or cost controls have not been verified.

## Workstream Coordination

### Test Automation Thread

Owns local and CI commands, dependency locking, browser smoke tests, integration
tests, artifacts, and required checks. The release plan consumes its evidence
at Gates 4 and 6. It should prioritize store-installed smoke coverage and the
production-like auth, billing, quota, and deletion journeys over broad coverage
percentage goals.

### Admin Console Thread

Owns launch operations for user, subscription, usage, and preload diagnosis.
It must use backend service interfaces and audited actions. Direct DynamoDB
mutation is out of scope for the initial release.

### Release Thread

Owns store submission, release packaging, production configuration, legal and
support publication, observability, runbooks, pilot coordination, and the final
go/no-go record.

Each thread should report dependencies, current evidence, open P0 risks, and
the next gate it is unblocking. A shared release checklist should link to the
separate implementation plans rather than copy them.

## Success Measures

During the pilot and first public week, track:

- Install-to-sign-in completion.
- Sign-in-to-first-successful-analysis completion.
- Preload success rate and end-to-end latency.
- Auth, API, worker, and billing failure counts.
- Basic-plan quota and sentence-cap reach rate.
- Checkout start-to-completion rate.
- Refund, cancellation, and support case counts.
- OpenAI cost per active user and per successful article.

Do not set arbitrary optimization targets before baseline data exists. The hard
release requirement is that failures and costs are visible, attributable, and
bounded.

## Key Risks and Controls

- **External review delay:** submit store and OAuth reviews in Week 1 and keep
  public launch date conditional on approval.
- **Billing/entitlement divergence:** use verified webhooks, idempotency,
  production-like replay tests, and daily pilot reconciliation.
- **OpenAI cost growth:** enforce per-user quotas, project spend limits,
  concurrency limits, rate cards, and cost alerts.
- **Sensitive content leakage:** minimize logs and analytics, document data
  handling, and test redaction.
- **Operational overload:** keep the pilot small, freeze scope, and establish
  support and incident ownership before public promotion.
- **Concurrent work drift:** maintain one release checklist with explicit
  dependencies on the test automation and admin-console plans.

## Explicitly Deferred

The release does not depend on a large marketing site, advanced CRM, monthly
email summaries, review-card generation, team billing, annual plans, referral
programs, or a complete admin platform. These features should be prioritized
only after the first cohort provides activation, retention, cost, and support
evidence.
