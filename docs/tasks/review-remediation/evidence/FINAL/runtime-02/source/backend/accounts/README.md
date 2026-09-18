# `accounts` — shared account foundation (sign-in + subscriptions)

Google / mock sign-in and Stripe / mock subscription billing, independent of
any host application's domain.

**This directory is kept byte-identical across the webkida applications**
(`english-extension-untangle`, `realtime`, …). Each repository carries its own
copy for now; the copies exist so the package can later be lifted into a
standalone distribution (`webkida-accounts`) that every application installs,
without a single call site changing.

## Rules that keep it extractable

1. **Never import anything outside `accounts`.** Only the standard library,
   `pydantic`, and — inside `accounts.api` alone — `fastapi`. The moment a
   module reaches for the host's `config`, `models`, `services`, or `storage`,
   the package stops being liftable.
2. **Never encode application-specific knowledge.** How many articles a reader
   gets per month, or how many minutes of audio a session may run, is the
   host's business. This package knows only *which plan ids exist*
   (`PlanCatalog`) and *whether a subscription is live* (`resolve_plan_id`).
3. **Take persistence through ports.** `AuthService` and
   `SubscriptionRepository` are Protocols. JSON-file and in-memory reference
   implementations ship here; adapters for a host's own datastore (DynamoDB,
   Postgres) are written in the host and injected.
4. **Keep HTTP inside `accounts.api`.** No other module knows FastAPI exists.
   Other transports — a WebSocket handshake, a Lambda handler — call
   `AccountsContainer` methods such as `resolve_user()` directly.

## Layout

```text
accounts/
  models.py             User / IdentityClaims / auth and billing I/O models
  plans.py              PlanCatalog (the set of plan ids) and resolve_plan_id
  ports.py              IdentityProvider / AuthService / BillingProvider /
                        SubscriptionRepository, plus their errors and values
  settings.py           AccountsSettings, assembled from environment variables
  identity/             google_identity.py (ID-token verification), mock_identity.py
  billing/              stripe_billing.py (Checkout + Portal + webhooks), mock_billing.py
  services/             auth_flow.py (sign-in), billing_flow.py (subscription changes)
  storage/              JSON-file and in-memory reference implementations
  api/                  FastAPI router factory and dependencies (the only FastAPI import)
  container.py          Composition root: settings + injected ports -> one object
  testing.py            build_test_accounts() for host test suites
```

## Wiring it into an application

```python
from accounts import AccountsSettings, PlanCatalog, build_accounts_container
from accounts.api import build_accounts_router

PLANS = PlanCatalog(basic_plan_id="basic", paid_plan_ids=("pro", "max"))
_accounts = build_accounts_container(
    AccountsSettings.from_env(PLANS, app_name="Untangle"),
    plans=PLANS,
    auth_service=my_dynamo_auth_service,        # optional; JSON store by default
    subscription_repository=my_dynamo_subscriptions,
)

def get_accounts():
    return _accounts

app.include_router(build_accounts_router(get_accounts))
```

The router is given a *provider* rather than the container itself, so a test
replaces the entire accounts stack with one
`app.dependency_overrides[get_accounts]` entry.

Endpoints served: `/auth/config`, `/auth/login`, `/auth/me`, `/auth/logout`,
`/billing/checkout`, `/billing/portal`, `/billing/webhook`, `/billing/done`.

A usage summary such as `/billing/me` is deliberately *not* provided. This
package answers "which plan, and until when" (`describe_subscription()`); the
host's entitlement layer turns that into remaining articles, minutes, or
whatever it meters.

## Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `AUTH_PROVIDER` | `mock` | `mock` or `google` |
| `GOOGLE_OAUTH_CLIENT_ID` | — | Required when `AUTH_PROVIDER=google` |
| `AUTH_SESSION_TTL_DAYS` | `30` | Lifetime of an issued session |
| `BILLING_PROVIDER` | `mock` | `mock` or `stripe` |
| `STRIPE_SECRET_KEY` | — | Required when `BILLING_PROVIDER=stripe` |
| `STRIPE_WEBHOOK_SECRET` | — | Webhook signature verification; unset fails closed with 500 |
| `STRIPE_PRICE_ID_<PLAN>` | — | Stripe price per paid plan id (e.g. `STRIPE_PRICE_ID_PRO`) |
| `API_BASE_URL` | host-supplied | Base for the default return URLs |
| `BILLING_SUCCESS_URL` / `BILLING_CANCEL_URL` / `BILLING_PORTAL_RETURN_URL` | `API_BASE_URL/billing/done?state=…` | Checkout and Portal return targets |

Optional runtime dependencies: `google-auth` + `requests` for
`AUTH_PROVIDER=google`, and `stripe` for `BILLING_PROVIDER=stripe`. Both are
imported lazily, so a mock-provider environment needs neither.
