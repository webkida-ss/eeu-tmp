# Historical admin API proposal

These files preserve the unimplemented API design from the original admin branch.
They are planning inputs, not an additional canonical API or a runtime conformance
claim. The auth definitions and session here are historical snapshots.

The sole supported contract is `contracts/openapi/openapi.yaml`. It contains the
implemented `GET /admin/v1/session` endpoint, available with `ADMIN_ENABLED=true`.
Dashboard, user listing/detail, suspension/reactivation, alerts, audit HTTP APIs,
and the admin frontend remain feature backlog. Promote each endpoint into the
canonical contract only alongside its implementation and contract tests.

Generate implemented admin models with `task api:generate`; `task api:check`
checks generation drift, explicit feature availability, adapter conformance, and
transitive authentication/administrator authorization. `task schema:check` runs
disabled and enabled configurations in separate processes. The admin-enabled
test task also exercises ordinary learner responses, so enabling administration
cannot silently replace the learner `ApiError` wire format.

Admin CORS permits only `ADMIN_ALLOWED_ORIGIN`, GET/OPTIONS, and the Authorization,
Content-Type, and X-Correlation-ID headers (plus browser-safelisted headers).
Responses expose X-Correlation-ID. Learner routes retain their existing origin
policy. An allowed origin never grants administrator access: every session
request still requires an authenticated user and an exact email allowlist match.
