# Local Admin Site Design

## Status

Approved for implementation planning on 2026-07-20.

## Purpose

Build a local administration site for authorized operators to inspect product usage and operational signals across all users. The site includes a backend API, a browser-based frontend, administrator authentication and authorization, limited account controls, and automated tests.

The design extends the existing FastAPI ports-and-adapters architecture. It keeps application logic independent of FastAPI, Next.js, JSON files, DynamoDB, and future analytics infrastructure.

## Goals

- Provide a single view of user growth, activity, token consumption, estimated cost, product usage, quota pressure, and processing failures.
- Let authorized administrators search users, inspect user details, suspend accounts, and reactivate accounts.
- Protect internal token and cost data from learner-facing APIs.
- Run deterministically with local JSON data and no external infrastructure.
- Define the API contract before backend and frontend implementation.
- Cover domain logic, adapters, API contracts, frontend behavior, authorization, and critical user journeys with automated tests.

## Non-goals

- AWS infrastructure, DynamoDB indexes, or production deployment.
- Billing mutations, plan changes, quota adjustments, usage resets, or user deletion.
- A large-scale analytics warehouse or asynchronous analytics pipeline.
- Persisted alert lifecycle management such as acknowledgement or assignment.
- Migrating existing user identifiers from UUID v4. New persisted entities introduced by this feature use UUID v7.
- Visual polish beyond a clear, usable internal interface.

## Approved Architecture

The admin backend is an isolated module inside the existing FastAPI application. It uses the same dependency-injection and ports-and-adapters conventions as the learner-facing backend. The admin frontend is a separate Next.js application.

Dependency direction is:

1. The Next.js frontend calls a generated TypeScript client.
2. The client calls endpoints under `/admin/v1`.
3. FastAPI adapters authenticate, authorize, validate, and translate HTTP messages.
4. Framework-independent application services execute admin use cases.
5. Application services depend on repository protocols.
6. Local JSON adapters implement those protocols for version one.

The application services must not import FastAPI, Next.js, JSON storage implementations, or AWS SDKs. Existing handler-independence tests are extended to include admin services.

### Technology choices

- Backend: the existing Python and FastAPI application.
- Frontend: Next.js App Router, TypeScript, Tailwind CSS, and pnpm.
- Contract: OpenAPI authored from `contracts/openapi/openapi.yaml`, with reusable schemas and paths split into the repository-standard subdirectories.
- Generated artifacts: Python API component models and a TypeScript API client.
- Version-one persistence: local JSON selected through existing dependency injection.
- Tests: pytest, frontend unit/component tests, Playwright, type checking, linting, and production builds.

The browser extension remains vanilla JavaScript because of its current distribution constraints. The admin site does not copy that constraint; alignment means shared domain vocabulary, authentication semantics, API contracts, and backend services.

## Runtime Boundary

The local admin site requires `STORAGE_BACKEND=json` for the entire application. Admin and learner use cases must read and write the same local data source. Starting the admin site while another storage backend is selected fails at startup with a clear configuration error.

Version one does not combine learner data from DynamoDB with admin data from JSON. Future DynamoDB or analytics adapters can replace JSON implementations without changing application services or HTTP contracts.

## Authentication and Authorization

### Login

The browser uses Google Identity Services to obtain a Google ID token and submits it to the existing backend login flow. The backend remains responsible for token verification and session issuance.

Local development and automated tests may use the existing mock authentication provider. A mock administrator must still have an explicit email address included in the administrator allowlist.

### Administrator allowlist

- `ADMIN_EMAILS` contains explicitly allowed administrator email addresses.
- Addresses are trimmed and case-normalized before exact comparison.
- Empty, missing, malformed, or wildcard allowlists fail closed.
- Every admin API request authenticates the session and checks the current email against `ADMIN_EMAILS`.
- A learner session does not become an admin session without the allowlist check.
- `/admin/v1/session` returns `403` for authenticated but non-allowlisted users.

### Origin policy

Admin API CORS accepts only the configured local admin frontend origin. Credentials and authorization headers are not accepted from arbitrary origins.

## Account Suspension

Account control state is stored separately from authentication profiles:

- `account_status`: `active` or `suspended`, defaulting to `active` for existing records.
- `suspended_at`: nullable UTC timestamp.
- `suspended_reason`: nullable operator-provided reason.

The JSON adapter stores account control records and their admin audit events in one `admin_control.json` document. A user without an account control record is active. Keeping the status overlay separate avoids changing existing user identifiers or authentication-profile formats and lets a status transition and its audit event commit atomically.

Suspension and reactivation:

- Preserve the user and all associated data.
- Require a non-empty reason for both operations.
- Are idempotent.
- Revoke all current sessions for the target user when suspension causes an actual state transition.
- Recheck account status on every protected learner request as defense in depth.
- Reject suspended users with `403` and stable error code `account_suspended`.
- Allow only session introspection and logout on the learner surface while suspended.
- Reject all other learner-facing product endpoints, including metered and unmetered reads.

An allowlisted administrator who is suspended as a learner may still use admin endpoints. Admin authorization is evaluated independently on every request so an administrator can recover from accidental self-suspension.

Idempotent retries return the current state without writing another audit event. Audit events are written only for actual state transitions.

## Persisted Admin Data

All new primary identifiers use UUID v7.

### Activity event

An append-only `activity_event` is recorded for every article or chat attempt that reaches a terminal result, independent of usage-reservation mode.

Required fields:

- `id`
- `source_id`: the originating operation or preload identifier used for idempotency
- `user_id`
- `operation`: `article` or `chat`
- `status`: `success`, `failed`, or `quota_blocked`
- `recorded_at`
- `error_code`, nullable and sanitized
- `input_tokens`, nullable
- `output_tokens`, nullable
- `tokens`, nullable
- `actual_cost_micro_usd`, nullable
- `model`, nullable

No learner content, prompt text, authentication token, or stack trace is stored in an activity event.

Appending an activity event is idempotent by `source_id`; retries return the original event instead of creating duplicates. Successful events are the source for active-user calculations and daily usage trends. Failed and quota-blocked events are the source for operational alerts. Existing monthly usage aggregates remain the source for current quota consumption and committed/reserved totals.

### Admin audit event

An append-only `admin_audit_event` contains:

- `id`
- `actor_user_id`
- `actor_email`
- `target_user_id`
- `action`: `user_suspended` or `user_reactivated`
- `reason`
- `recorded_at`
- `correlation_id`

Every audit event represents a successful state transition and is immutable. Idempotent requests that observe the requested state and perform no transition do not add an event. Failed requests are written to sanitized operational logs with their correlation IDs, not to the immutable state-transition audit stream.

Admin audit events are distinct from usage and activity events.

## Repository Ports

The application layer depends on focused protocols:

- `AdminMetricsRepository`
  - Read aggregate totals, daily series, plan distribution, top consumers, and alert inputs.
- `AdminUserRepository`
  - Page and filter users and fetch user details with effective account status.
- `AdminAccountControlRepository`
  - Atomically transition account status and append the corresponding audit event.
- `AdminActivityRepository`
  - Append and query activity events.
- `AdminAuditRepository`
  - Page immutable admin audit events.
- `SessionRepository`
  - Revoke all active sessions for a user.

JSON and in-memory adapters must pass the same repository contract tests. Future DynamoDB or analytics adapters must satisfy those contracts.

## Metrics

### Reporting periods

- Default: rolling 30 days.
- Presets: rolling 7 days, rolling 30 days, and current calendar month.
- Custom range: inclusive start and exclusive end, with a maximum span of 90 days.
- Aggregation timezone: UTC.

### Overview metrics

- Total registered users.
- New users in the selected period.
- Suspended users.
- Active users: distinct users with at least one successful article or chat activity event in the selected period.
- Active-user percentage of total users.
- User distribution by subscription plan and status.
- Successful articles.
- Successful chat operations.
- Input, output, and total tokens.
- Actual estimated cost stored as integer micro-USD and formatted only at presentation boundaries.
- Daily activity, token, and cost series.
- Top users by total token consumption.

### Alerts

Alerts are computed when read and are not persisted in version one.

- Quota pressure: a user at or above 80 percent of a monthly article, chat, or token limit.
- Quota block: every `quota_blocked` activity event in the selected period.
- Processing failure spike: at least five failed operations in a 15-minute UTC bucket.
- Elevated failure rate: at least 20 attempts in a 15-minute UTC bucket and a failure rate of at least 10 percent.

The alerts page exposes the computed snapshot for the selected range and supports filtering by alert type, operation, and user. Alert acknowledgement and history are out of scope.

## User Experience

### Navigation

- Overview
- Users
- Alerts
- Audit Log

### Overview

The overview prioritizes:

1. Total users, active users, tokens, and estimated cost.
2. Daily usage trends and plan distribution.
3. Items needing attention.
4. Article and chat totals.
5. Top users by token usage.

### Users

The user list supports server-side pagination, email search, account-status filtering, plan filtering, and sorting by created date or token usage.

The user detail page displays:

- Identity and account status.
- Subscription and current period.
- Current usage and quota percentages.
- Recent activity events.
- Recent admin audit events for the user.

Suspension and reactivation appear only on the detail page. A confirmation dialog explains the effect and requires a reason. The UI cannot bypass backend authorization, status checks, or reason validation.

### Partial failures

An authenticated, valid dashboard request returns `200` when at least one independent section can be evaluated. Each section has an envelope:

```json
{
  "status": "ok",
  "data": {}
}
```

or:

```json
{
  "status": "error",
  "error": {
    "code": "section_unavailable",
    "correlation_id": "..."
  }
}
```

The frontend renders available sections and marks failed sections as unavailable. Authentication, authorization, and request-validation failures are never converted into partial success.

## API Contract

The source of truth is `contracts/openapi/openapi.yaml`. Reusable schemas live under `contracts/openapi/components/schemas/`, and endpoint definitions live under `contracts/openapi/paths/`. Backend models and the frontend client are generated from the entry file. CI fails when generated artifacts differ from the committed contract.

Endpoints:

- `GET /admin/v1/session`
- `GET /admin/v1/dashboard`
- `GET /admin/v1/users`
- `GET /admin/v1/users/{id}`
- `POST /admin/v1/users/{id}/suspend`
- `POST /admin/v1/users/{id}/reactivate`
- `GET /admin/v1/alerts`
- `GET /admin/v1/audit-events`

List endpoints use opaque cursor pagination with a bounded page size. Dashboard and alert ranges have the 90-day maximum described above.

### Errors

All API responses include `X-Correlation-ID`. A valid incoming `X-Correlation-ID` may be propagated; otherwise the backend generates one. Invalid or oversized values are replaced.

Stable error categories:

- `401 unauthenticated`
- `403 admin_forbidden`
- `403 account_suspended`
- `404 user_not_found`
- `422 validation_error`
- `500 internal_error`

Internal exceptions, credentials, learner content, and stack traces are not returned to clients.

## Error Handling and Consistency

- Account status transition and audit append form one repository operation.
- The JSON account-control adapter holds an exclusive lock, writes the updated status and audit event to a temporary document, synchronizes it, and atomically replaces `admin_control.json`.
- If the replacement cannot complete, neither the status transition nor audit event is committed.
- Session revocation occurs after the transition commits. A revocation failure returns an internal error, retains the suspended status, and writes a sanitized operational error with the same correlation ID. Per-request status checks continue to block access.
- Missing optional metrics produce an unavailable section rather than fabricated zeroes.
- Invalid date ranges, cursors, filters, and reasons are rejected before repository calls.
- Logs use correlation IDs and stable event names while excluding credentials and learner content.

## Testing Strategy

### Domain and application services

- Aggregate totals and daily series.
- UTC reporting boundaries and 90-day limits.
- Active-user definition and de-duplication.
- Quota-pressure and failure-alert thresholds.
- Integer micro-USD arithmetic.
- Administrator allowlist normalization and fail-closed behavior.
- Suspension, reactivation, session revocation, idempotency, and audit behavior.
- Partial dashboard success.

### Repository contract tests

The same contract suite runs against in-memory and JSON adapters:

- Pagination and deterministic ordering.
- Filtering and range boundaries.
- Append-only activity and audit behavior.
- Atomic status transitions.
- Concurrent JSON writes and lock behavior.
- Session revocation.

### API and schema tests

- OpenAPI linting and generated-artifact drift detection.
- Request and response conformance for every endpoint.
- Authentication, admin authorization, and suspended-account behavior.
- Stable error codes and `X-Correlation-ID`.
- Page-size and reporting-range bounds.
- Proof that learner-facing API schemas do not expose admin-only token, cost, or audit fields.

### Frontend tests

- KPI, trend, alert, user-list, and audit-log rendering.
- Loading, empty, partial-error, and full-error states.
- Filters, pagination, and date-range controls.
- Suspension and reactivation dialogs with required reasons.
- Unauthorized and expired-session handling.
- Generated client integration.

### End-to-end release gates

- Allowlisted admin login, overview load, user search, suspension, learner API rejection, audit verification, and reactivation.
- Authenticated but non-allowlisted user receives `403` from admin endpoints.
- Suspended allowlisted administrator can access admin endpoints but not learner product endpoints.
- External APIs are not called; deterministic fixtures and a fixed clock are used.

### Quality gates

- Backend pytest suite.
- Frontend unit and component test suite.
- Python and TypeScript linting.
- Type checking.
- Backend contract generation checks.
- Next.js production build.
- Playwright end-to-end suite.
- Existing extension tests remain green.

These gates extend the repository-wide direction in `docs/TEST_AUTOMATION_PLAN.md`; they do not create a competing test strategy.

## Implementation Boundaries

Implementation should proceed in small, independently verifiable slices:

1. Contract and generated models.
2. Account status, activity, audit, and session ports.
3. In-memory and JSON adapters with contract tests.
4. Framework-independent admin use cases.
5. Admin HTTP adapters and authorization.
6. Next.js shell and generated client integration.
7. Overview, users, alerts, and audit features.
8. End-to-end journeys and complete quality gates.

Production infrastructure design begins only after the local implementation is accepted. At that point, cross-user access patterns can be implemented with DynamoDB indexes or an analytics projection behind the existing ports.

## Acceptance Criteria

- The complete admin site runs locally with JSON storage and no AWS resources.
- Only explicitly allowlisted authenticated users can use admin APIs and pages.
- The dashboard displays all approved metrics for deterministic fixtures.
- Active users and daily trends are based on persisted successful activity events.
- Alerts follow the specified thresholds.
- Administrators can suspend and reactivate users with reasons.
- Suspension revokes sessions and blocks learner product access immediately.
- Every actual account-state transition has an immutable UUID v7 audit event.
- OpenAPI is the contract source of truth and the frontend uses a generated client.
- Application services remain independent of frameworks and storage adapters.
- All stated quality gates pass.
