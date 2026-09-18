# Local Admin Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the local, JSON-backed admin API, activity telemetry, account controls, and automated backend quality gates described in the approved design.

**Architecture:** Add framework-independent admin services and repository protocols to the existing FastAPI ports-and-adapters application. Keep JSON, HTTP, and authentication details in adapters; use a contract-first OpenAPI entry file to generate admin Pydantic models and the later frontend client.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, pytest, OpenAPI 3.1, datamodel-code-generator, JSON file adapters, existing dependency injection.

---

## File Structure

Create or modify the following focused units:

```text
contracts/openapi/
  openapi.yaml                         # Contract entry point
  components/schemas/admin.yaml        # Shared admin request/response schemas
  paths/auth-config.yaml                # Existing authentication configuration
  paths/auth-login.yaml                 # Existing identity-token login
  paths/auth-logout.yaml                # Existing logout operation
  paths/admin-session.yaml             # Session introspection
  paths/admin-dashboard.yaml           # Dashboard query
  paths/admin-users.yaml               # User list
  paths/admin-user.yaml                # User detail
  paths/admin-user-suspend.yaml        # Suspend command
  paths/admin-user-reactivate.yaml     # Reactivate command
  paths/admin-alerts.yaml              # Computed alerts
  paths/admin-audit-events.yaml        # Audit pagination
backend/
  admin/router.py                      # FastAPI-only admin routes
  generated/admin_models.py            # Generated Pydantic DTOs
  middleware/correlation.py            # X-Correlation-ID middleware
  repositories/admin_activity.py       # Activity port and domain record
  repositories/memory_admin_activity.py # In-memory contract adapter
  repositories/json_admin_activity.py  # JSON activity adapter
  repositories/admin_account_control.py # Account-control and audit port
  repositories/memory_admin_account_control.py # In-memory contract adapter
  repositories/json_admin_account_control.py # Atomic whole-document adapter
  repositories/admin_users.py          # User-query port
  repositories/memory_admin_users.py   # In-memory contract adapter
  repositories/json_admin_users.py     # JSON user-query adapter
  repositories/admin_metrics.py        # Aggregate query port
  repositories/memory_admin_metrics.py # In-memory contract adapter
  repositories/json_admin_metrics.py   # JSON aggregate adapter
  repositories/session_repository.py   # Session-revocation port
  repositories/memory_session_repository.py # In-memory contract adapter
  repositories/json_session_repository.py # JSON session adapter
  services/admin_auth.py               # Allowlist policy
  services/admin_activity.py           # Idempotent event recording
  services/admin_accounts.py           # Suspend/reactivate use cases
  services/admin_metrics.py            # Dashboard calculations
  services/admin_alerts.py             # Alert calculations
  services/admin_users.py              # User list/detail use cases
  services/account_access.py           # Learner suspension policy
  scripts/generate_admin_models.sh      # Deterministic Python generation
  scripts/check_admin_openapi.sh        # Contract validation and drift check
```

Do not modify the concurrently edited usage-meter files in this plan:
`backend/repositories/usage_repository.py`,
`backend/repositories/dynamodb_billing_repositories.py`,
`backend/services/usage_meter.py`,
`backend/test_usage_meter.py`, and
`backend/test_usage_repository.py`.

### Task 1: Establish the OpenAPI contract and Python generation

**Files:**
- Create: `contracts/openapi/openapi.yaml`
- Create: `contracts/openapi/components/schemas/admin.yaml`
- Create: `contracts/openapi/paths/auth-config.yaml`
- Create: `contracts/openapi/paths/auth-login.yaml`
- Create: `contracts/openapi/paths/auth-logout.yaml`
- Create: `contracts/openapi/paths/admin-session.yaml`
- Create: `contracts/openapi/paths/admin-dashboard.yaml`
- Create: `contracts/openapi/paths/admin-users.yaml`
- Create: `contracts/openapi/paths/admin-user.yaml`
- Create: `contracts/openapi/paths/admin-user-suspend.yaml`
- Create: `contracts/openapi/paths/admin-user-reactivate.yaml`
- Create: `contracts/openapi/paths/admin-alerts.yaml`
- Create: `contracts/openapi/paths/admin-audit-events.yaml`
- Create: `backend/requirements-dev.txt`
- Create: `backend/scripts/generate_admin_models.sh`
- Create: `backend/scripts/check_admin_openapi.sh`
- Create: `backend/test_admin_openapi.py`
- Generate: `backend/generated/admin_models.py`

- [ ] **Step 1: Write the failing contract test**

```python
# backend/test_admin_openapi.py
from pathlib import Path

from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "openapi" / "openapi.yaml"


def test_admin_openapi_is_valid() -> None:
    spec, base_uri = read_from_filename(str(CONTRACT))
    validate(spec, base_uri=base_uri)


def test_admin_openapi_exposes_required_operations() -> None:
    spec, _ = read_from_filename(str(CONTRACT))
    operations = {
        operation["operationId"]
        for path in spec["paths"].values()
        for operation in path.values()
        if isinstance(operation, dict) and "operationId" in operation
    }
    assert operations == {
        "getAuthConfig",
        "login",
        "logout",
        "getAdminSession",
        "getAdminDashboard",
        "listAdminUsers",
        "getAdminUser",
        "suspendAdminUser",
        "reactivateAdminUser",
        "listAdminAlerts",
        "listAdminAuditEvents",
    }
```

- [ ] **Step 2: Add deterministic development dependencies and verify the test fails**

```text
# backend/requirements-dev.txt
-r requirements.txt
pytest>=8.0
stripe>=10.0
openapi-spec-validator>=0.7
datamodel-code-generator>=0.31
```

Run:

```bash
cd backend
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q test_admin_openapi.py
```

Expected: FAIL because `contracts/openapi/openapi.yaml` does not exist.

- [ ] **Step 3: Author the contract entry file**

```yaml
# contracts/openapi/openapi.yaml
openapi: 3.1.0
info:
  title: Untangle Admin API
  version: 1.0.0
servers:
  - url: http://localhost:18765
paths:
  /auth/config:
    $ref: ./paths/auth-config.yaml
  /auth/login:
    $ref: ./paths/auth-login.yaml
  /auth/logout:
    $ref: ./paths/auth-logout.yaml
  /admin/v1/session:
    $ref: ./paths/admin-session.yaml
  /admin/v1/dashboard:
    $ref: ./paths/admin-dashboard.yaml
  /admin/v1/users:
    $ref: ./paths/admin-users.yaml
  /admin/v1/users/{id}:
    $ref: ./paths/admin-user.yaml
  /admin/v1/users/{id}/suspend:
    $ref: ./paths/admin-user-suspend.yaml
  /admin/v1/users/{id}/reactivate:
    $ref: ./paths/admin-user-reactivate.yaml
  /admin/v1/alerts:
    $ref: ./paths/admin-alerts.yaml
  /admin/v1/audit-events:
    $ref: ./paths/admin-audit-events.yaml
components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: opaque
security:
  - bearerAuth: []
```

Define `contracts/openapi/components/schemas/admin.yaml` with these explicit schemas and fields:

```yaml
CorrelationError:
  type: object
  required: [code, message, correlation_id]
  properties:
    code: { type: string }
    message: { type: string }
    correlation_id: { type: string, minLength: 1, maxLength: 128 }
AdminSession:
  type: object
  required: [user_id, email, display_name]
  properties:
    user_id: { type: string }
    email: { type: string, format: email }
    display_name: { type: string }
AuthConfig:
  type: object
  required: [provider]
  properties:
    provider: { type: string, enum: [mock, google] }
    google_client_id: { type: [string, "null"] }
SsoLoginRequest:
  type: object
  required: [credential]
  properties:
    credential: { type: string, minLength: 1, maxLength: 4096 }
AuthSessionResponse:
  type: object
  required: [access_token, token_type, user]
  properties:
    access_token: { type: string }
    token_type: { type: string, const: Bearer }
    user: { $ref: "#/AdminSession" }
SectionError:
  type: object
  required: [code, correlation_id]
  properties:
    code: { type: string, const: section_unavailable }
    correlation_id: { type: string }
MetricTotals:
  type: object
  required: [total_users, new_users, suspended_users, active_users, active_user_percentage, articles, chats, input_tokens, output_tokens, tokens, actual_cost_micro_usd]
  properties:
    total_users: { type: integer, minimum: 0 }
    new_users: { type: integer, minimum: 0 }
    suspended_users: { type: integer, minimum: 0 }
    active_users: { type: integer, minimum: 0 }
    active_user_percentage: { type: number, minimum: 0, maximum: 100 }
    articles: { type: integer, minimum: 0 }
    chats: { type: integer, minimum: 0 }
    input_tokens: { type: integer, minimum: 0 }
    output_tokens: { type: integer, minimum: 0 }
    tokens: { type: integer, minimum: 0 }
    actual_cost_micro_usd: { type: integer, minimum: 0 }
DailyMetric:
  type: object
  required: [date, articles, chats, tokens, actual_cost_micro_usd]
  properties:
    date: { type: string, format: date }
    articles: { type: integer, minimum: 0 }
    chats: { type: integer, minimum: 0 }
    tokens: { type: integer, minimum: 0 }
    actual_cost_micro_usd: { type: integer, minimum: 0 }
PlanCount:
  type: object
  required: [plan_id, count]
  properties:
    plan_id: { type: string }
    count: { type: integer, minimum: 0 }
TopUser:
  type: object
  required: [user_id, email, plan_id, tokens, quota_percentage]
  properties:
    user_id: { type: string }
    email: { type: string, format: email }
    plan_id: { type: string }
    tokens: { type: integer, minimum: 0 }
    quota_percentage: { type: number, minimum: 0 }
DashboardResponse:
  type: object
  required: [totals, daily, plans, top_users, alerts]
  properties:
    totals: { $ref: "#/MetricTotalsSection" }
    daily: { $ref: "#/DailyMetricsSection" }
    plans: { $ref: "#/PlanCountsSection" }
    top_users: { $ref: "#/TopUsersSection" }
    alerts: { $ref: "#/AlertsSection" }
MetricTotalsSection:
  oneOf:
    - type: object
      required: [status, data]
      properties:
        status: { const: ok }
        data: { $ref: "#/MetricTotals" }
    - type: object
      required: [status, error]
      properties:
        status: { const: error }
        error: { $ref: "#/SectionError" }
DailyMetricsSection:
  oneOf:
    - type: object
      required: [status, data]
      properties:
        status: { const: ok }
        data: { type: array, items: { $ref: "#/DailyMetric" } }
    - type: object
      required: [status, error]
      properties:
        status: { const: error }
        error: { $ref: "#/SectionError" }
PlanCountsSection:
  oneOf:
    - type: object
      required: [status, data]
      properties:
        status: { const: ok }
        data: { type: array, items: { $ref: "#/PlanCount" } }
    - type: object
      required: [status, error]
      properties:
        status: { const: error }
        error: { $ref: "#/SectionError" }
TopUsersSection:
  oneOf:
    - type: object
      required: [status, data]
      properties:
        status: { const: ok }
        data: { type: array, items: { $ref: "#/TopUser" } }
    - type: object
      required: [status, error]
      properties:
        status: { const: error }
        error: { $ref: "#/SectionError" }
Alert:
  type: object
  required: [type, recorded_at, user_id, operation, message]
  properties:
    type: { type: string, enum: [quota_pressure, quota_blocked, failure_spike, elevated_failure_rate] }
    recorded_at: { type: string, format: date-time }
    user_id: { type: string }
    operation: { type: string, enum: [article, chat] }
    message: { type: string }
AlertsSection:
  oneOf:
    - type: object
      required: [status, data]
      properties:
        status: { const: ok }
        data: { type: array, items: { $ref: "#/Alert" } }
    - type: object
      required: [status, error]
      properties:
        status: { const: error }
        error: { $ref: "#/SectionError" }
AdminUserSummary:
  type: object
  required: [id, email, display_name, created_at, account_status, plan_id, tokens]
  properties:
    id: { type: string }
    email: { type: string, format: email }
    display_name: { type: string }
    created_at: { type: string, format: date-time }
    account_status: { type: string, enum: [active, suspended] }
    plan_id: { type: string }
    tokens: { type: integer, minimum: 0 }
AdminUserDetail:
  allOf:
    - $ref: "#/AdminUserSummary"
    - type: object
      required: [suspended_at, suspended_reason, current_usage, recent_activity, recent_audit_events]
      properties:
        suspended_at: { type: [string, "null"], format: date-time }
        suspended_reason: { type: [string, "null"] }
        current_usage: { $ref: "#/UserUsage" }
        recent_activity: { type: array, items: { $ref: "#/ActivityEvent" } }
        recent_audit_events: { type: array, items: { $ref: "#/AdminAuditEvent" } }
UserUsage:
  type: object
  required: [articles, chats, input_tokens, output_tokens, tokens, actual_cost_micro_usd, article_quota_percentage, chat_quota_percentage, token_quota_percentage]
  properties:
    articles: { type: integer, minimum: 0 }
    chats: { type: integer, minimum: 0 }
    input_tokens: { type: integer, minimum: 0 }
    output_tokens: { type: integer, minimum: 0 }
    tokens: { type: integer, minimum: 0 }
    actual_cost_micro_usd: { type: integer, minimum: 0 }
    article_quota_percentage: { type: number, minimum: 0 }
    chat_quota_percentage: { type: number, minimum: 0 }
    token_quota_percentage: { type: number, minimum: 0 }
ActivityEvent:
  type: object
  required: [id, source_id, user_id, operation, status, recorded_at]
  properties:
    id: { type: string, format: uuid }
    source_id: { type: string }
    user_id: { type: string }
    operation: { type: string, enum: [article, chat] }
    status: { type: string, enum: [success, failed, quota_blocked] }
    recorded_at: { type: string, format: date-time }
    error_code: { type: [string, "null"] }
    input_tokens: { type: [integer, "null"], minimum: 0 }
    output_tokens: { type: [integer, "null"], minimum: 0 }
    tokens: { type: [integer, "null"], minimum: 0 }
    actual_cost_micro_usd: { type: [integer, "null"], minimum: 0 }
    model: { type: [string, "null"] }
AdminAuditEvent:
  type: object
  required: [id, actor_user_id, actor_email, target_user_id, action, reason, recorded_at, correlation_id]
  properties:
    id: { type: string, format: uuid }
    actor_user_id: { type: string }
    actor_email: { type: string, format: email }
    target_user_id: { type: string }
    action: { type: string, enum: [user_suspended, user_reactivated] }
    reason: { type: string }
    recorded_at: { type: string, format: date-time }
    correlation_id: { type: string }
AccountTransitionRequest:
  type: object
  required: [reason]
  properties:
    reason: { type: string, minLength: 1, maxLength: 500 }
AccountTransitionResponse:
  type: object
  required: [user_id, account_status, changed]
  properties:
    user_id: { type: string }
    account_status: { type: string, enum: [active, suspended] }
    changed: { type: boolean }
CursorPage:
  type: object
  required: [next_cursor]
  properties:
    next_cursor: { type: [string, "null"] }
AdminUserPage:
  allOf:
    - $ref: "#/CursorPage"
    - type: object
      required: [items]
      properties:
        items: { type: array, items: { $ref: "#/AdminUserSummary" } }
AlertPage:
  allOf:
    - $ref: "#/CursorPage"
    - type: object
      required: [items]
      properties:
        items: { type: array, items: { $ref: "#/Alert" } }
AuditEventPage:
  allOf:
    - $ref: "#/CursorPage"
    - type: object
      required: [items]
      properties:
        items: { type: array, items: { $ref: "#/AdminAuditEvent" } }
```

The authentication path files expose `getAuthConfig`, `login`, and `logout`; config and login are public, while logout uses bearer security. Each admin path file defines the operation ID from the test, bearer security, explicit query/path parameters, a success response schema from `../components/schemas/admin.yaml`, and `401`, `403`, `404`, or `422` responses using `CorrelationError` where applicable. Use `start` and `end` date-time parameters for dashboard/alerts, opaque `cursor`, and `limit` constrained to `1..100` for lists.

- [ ] **Step 4: Add deterministic generation and drift scripts**

```bash
#!/usr/bin/env bash
# backend/scripts/generate_admin_models.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
"$ROOT/backend/.venv/bin/datamodel-codegen" \
  --input "$ROOT/contracts/openapi/openapi.yaml" \
  --input-file-type openapi \
  --output "$ROOT/backend/generated/admin_models.py" \
  --output-model-type pydantic_v2.BaseModel \
  --use-standard-collections \
  --use-union-operator \
  --target-python-version 3.12
```

```bash
#!/usr/bin/env bash
# backend/scripts/check_admin_openapi.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEMP="$(mktemp)"
trap 'rm -f "$TEMP"' EXIT
"$ROOT/backend/.venv/bin/datamodel-codegen" \
  --input "$ROOT/contracts/openapi/openapi.yaml" \
  --input-file-type openapi \
  --output "$TEMP" \
  --output-model-type pydantic_v2.BaseModel \
  --use-standard-collections \
  --use-union-operator \
  --target-python-version 3.12
diff -u "$ROOT/backend/generated/admin_models.py" "$TEMP"
```

- [ ] **Step 5: Generate models and run the contract checks**

Run:

```bash
chmod +x backend/scripts/generate_admin_models.sh backend/scripts/check_admin_openapi.sh
backend/scripts/generate_admin_models.sh
cd backend
.venv/bin/python -m pytest -q test_admin_openapi.py
scripts/check_admin_openapi.sh
```

Expected: all commands exit `0`.

- [ ] **Step 6: Commit the contract slice**

```bash
git add contracts/openapi backend/requirements-dev.txt backend/scripts backend/generated backend/test_admin_openapi.py docs/superpowers/specs/2026-07-20-admin-site-design.md
git commit -m "Define admin API contract and generation"
```

### Task 2: Add admin runtime configuration and correlation IDs

**Files:**
- Modify: `backend/config.py`
- Modify: `backend/main.py`
- Modify: `backend/.env.example`
- Create: `backend/middleware/__init__.py`
- Create: `backend/middleware/correlation.py`
- Create: `backend/test_admin_runtime.py`
- Create: `backend/test_correlation_middleware.py`

- [ ] **Step 1: Write failing configuration and middleware tests**

```python
# backend/test_admin_runtime.py
import pytest

from config import validate_admin_runtime


def test_admin_requires_json_storage() -> None:
    with pytest.raises(RuntimeError, match="STORAGE_BACKEND=json"):
        validate_admin_runtime(admin_enabled=True, storage_backend="dynamodb")


def test_disabled_admin_does_not_break_dynamodb_tests() -> None:
    validate_admin_runtime(admin_enabled=False, storage_backend="dynamodb")
```

```python
# backend/test_correlation_middleware.py
from fastapi.testclient import TestClient

from main import app


def test_response_generates_correlation_id() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"]


def test_response_propagates_safe_correlation_id() -> None:
    response = TestClient(app).get(
        "/health", headers={"X-Correlation-ID": "test-request-123"}
    )
    assert response.headers["X-Correlation-ID"] == "test-request-123"
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```bash
cd backend
.venv/bin/python -m pytest -q test_admin_runtime.py test_correlation_middleware.py
```

Expected: FAIL because the validator and middleware do not exist.

- [ ] **Step 3: Implement configuration and middleware**

Add to `backend/config.py`:

```python
ADMIN_ENABLED = os.getenv("ADMIN_ENABLED", "false").strip().lower() in {
    "1", "true", "yes", "on",
}
ADMIN_EMAILS = tuple(
    email.strip().lower()
    for email in os.getenv("ADMIN_EMAILS", "").split(",")
    if email.strip()
)
ADMIN_ALLOWED_ORIGIN = os.getenv(
    "ADMIN_ALLOWED_ORIGIN", "http://localhost:3000"
).strip()
ADMIN_ACTIVITY_PATH = DATA_DIR / "admin_activity.json"
ADMIN_CONTROL_PATH = DATA_DIR / "admin_control.json"


def validate_admin_runtime(*, admin_enabled: bool, storage_backend: str) -> None:
    if admin_enabled and storage_backend != "json":
        raise RuntimeError(
            "The local admin site requires STORAGE_BACKEND=json."
        )
```

Create `backend/middleware/correlation.py`:

```python
from __future__ import annotations

import re
import uuid

from starlette.middleware.base import BaseHTTPMiddleware

SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        incoming = request.headers.get("X-Correlation-ID", "")
        correlation_id = incoming if SAFE_ID.fullmatch(incoming) else str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response
```

Call `validate_admin_runtime(...)` before mounting admin routes and add
`CorrelationIdMiddleware` to `app`. Use a route-scoped CORS policy for `/admin/`:
allow only `ADMIN_ALLOWED_ORIGIN`, the implemented methods, and explicit
Authorization, Content-Type, and X-Correlation-ID headers. Do not append the
admin origin to learner origins or apply the extension-origin pattern to admin
routes. The implemented session is in the canonical OpenAPI root; the remaining
HTTP design is preserved in `../specs/admin-api-backlog/` until implemented.

- [ ] **Step 4: Run focused and regression tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest -q test_admin_runtime.py test_correlation_middleware.py test_handler_independence.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/config.py backend/main.py backend/.env.example backend/middleware backend/test_admin_runtime.py backend/test_correlation_middleware.py
git commit -m "Add guarded admin runtime configuration"
```

### Task 3: Implement idempotent activity events

**Files:**
- Create: `backend/repositories/admin_activity.py`
- Create: `backend/repositories/memory_admin_activity.py`
- Create: `backend/repositories/json_admin_activity.py`
- Create: `backend/services/admin_activity.py`
- Create: `backend/test_admin_activity_repository.py`
- Create: `backend/test_admin_activity_service.py`
- Modify: `backend/config.py`
- Modify: `backend/deps.py`

- [ ] **Step 1: Write failing repository contract tests**

```python
# backend/test_admin_activity_repository.py
from datetime import datetime, timezone
from pathlib import Path

from repositories.admin_activity import ActivityEvent
from repositories.json_admin_activity import JsonAdminActivityRepository


def event(source_id: str) -> ActivityEvent:
    return ActivityEvent(
        id="019bf000-0000-7000-8000-000000000001",
        source_id=source_id,
        user_id="user-1",
        operation="chat",
        status="success",
        recorded_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        input_tokens=3,
        output_tokens=5,
        tokens=8,
        actual_cost_micro_usd=9,
        model="test-model",
    )


@pytest.mark.parametrize("kind", ["memory", "json"])
def test_append_is_idempotent_by_source_id(tmp_path: Path, kind: str) -> None:
    repository = (
        MemoryAdminActivityRepository()
        if kind == "memory"
        else JsonAdminActivityRepository(tmp_path / "activity.json")
    )
    first = repository.append(event("operation-1"))
    second = repository.append(event("operation-1"))
    assert second == first
    assert repository.query(user_id="user-1") == [first]
```

- [ ] **Step 2: Run the test and verify failure**

Run:

```bash
cd backend
.venv/bin/python -m pytest -q test_admin_activity_repository.py
```

Expected: FAIL because repository modules do not exist.

- [ ] **Step 3: Implement the port and JSON adapter**

```python
# backend/repositories/admin_activity.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol


@dataclass(frozen=True)
class ActivityEvent:
    id: str
    source_id: str
    user_id: str
    operation: Literal["article", "chat"]
    status: Literal["success", "failed", "quota_blocked"]
    recorded_at: datetime
    error_code: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    tokens: int | None = None
    actual_cost_micro_usd: int | None = None
    model: str | None = None


class AdminActivityRepository(Protocol):
    def append(self, event: ActivityEvent) -> ActivityEvent: ...
    def query(
        self,
        *,
        user_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[ActivityEvent]: ...
```

Implement `MemoryAdminActivityRepository` over a private list and `JsonAdminActivityRepository` with `json_list_lock`, `read_json_list`, and `write_json_list`. Both return the existing event when `source_id` matches; otherwise they append it. Query with inclusive `start`, exclusive `end`, and deterministic `(recorded_at, id)` ordering.

- [ ] **Step 4: Add the framework-independent recording service**

```python
# backend/services/admin_activity.py
from datetime import datetime, timezone

from repositories.admin_activity import ActivityEvent, AdminActivityRepository
from schemas import generate_uuid7


def record_activity(
    repository: AdminActivityRepository,
    *,
    source_id: str,
    user_id: str,
    operation: str,
    status: str,
    recorded_at: datetime | None = None,
    error_code: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    tokens: int | None = None,
    actual_cost_micro_usd: int | None = None,
    model: str | None = None,
) -> ActivityEvent:
    return repository.append(
        ActivityEvent(
            id=generate_uuid7(),
            source_id=source_id,
            user_id=user_id,
            operation=operation,
            status=status,
            recorded_at=recorded_at or datetime.now(timezone.utc),
            error_code=error_code,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tokens=tokens,
            actual_cost_micro_usd=actual_cost_micro_usd,
            model=model,
        )
    )
```

Add a dependency singleton using `ADMIN_ACTIVITY_PATH`.

- [ ] **Step 5: Run tests and architecture guard**

Run:

```bash
cd backend
.venv/bin/python -m pytest -q test_admin_activity_repository.py test_admin_activity_service.py test_handler_independence.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/config.py backend/deps.py backend/repositories/admin_activity.py backend/repositories/memory_admin_activity.py backend/repositories/json_admin_activity.py backend/services/admin_activity.py backend/test_admin_activity_repository.py backend/test_admin_activity_service.py backend/test_handler_independence.py
git commit -m "Persist idempotent admin activity events"
```

### Task 4: Record chat and article terminal activity

**Files:**
- Modify: `backend/services/reading.py`
- Modify: `backend/jobs/inline_runner.py`
- Modify: `backend/worker_handler.py`
- Modify: `backend/deps.py`
- Modify: `backend/main.py`
- Modify: `backend/test_preload_jobs.py`
- Create: `backend/test_admin_chat_activity.py`

- [ ] **Step 1: Write failing chat activity tests**

Create tests that pass an in-memory implementation of `AdminActivityRepository` into `reading.chat_reply(...)` and assert:

```python
assert events[0].source_id == request.operation_id
assert events[0].operation == "chat"
assert events[0].status == "success"
assert events[0].tokens == tally.total_tokens
```

Add provider-failure and quota-block tests asserting `failed` and `quota_blocked` with sanitized `error_code`.

- [ ] **Step 2: Run chat tests and verify failure**

Run:

```bash
cd backend
.venv/bin/python -m pytest -q test_admin_chat_activity.py
```

Expected: FAIL because `chat_reply` does not accept an activity repository.

- [ ] **Step 3: Add chat recording at terminal boundaries**

Extend the signature:

```python
def chat_reply(
    repository: PagePreloadRepository,
    user_id: str,
    request: ChatRequest,
    guard: EntitlementGuard | None = None,
    usage_meter: UsageMeter | None = None,
    activity_repository: AdminActivityRepository | None = None,
) -> ChatResponse:
```

Record `quota_blocked` before re-raising `EntitlementError`, `failed` before re-raising provider/settlement failures, and `success` after usage settlement but before returning. Only record when the repository is provided. Pass the dependency from `main.chat`.

- [ ] **Step 4: Write failing preload terminal tests**

Extend `backend/test_preload_jobs.py` to assert one event for:

```python
("ready", "success")
("failed", "failed")
("quota rejection", "quota_blocked")
```

Use `preload_id` or request `operation_id` as `source_id`, and assert retries do not add duplicates.

- [ ] **Step 5: Wire article activity through job runners**

Add `activity_repository: AdminActivityRepository | None = None` to `run_preload_job`, store it on `InlinePreloadJobRunner`, and pass `get_admin_activity_repository()` from `deps.py` and `worker_handler.py`. Record only after a terminal preload transition is successfully published. A repository write failure must propagate from the worker so the idempotent job is retried.

- [ ] **Step 6: Run focused and existing reading tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest -q test_admin_chat_activity.py test_preload_jobs.py test_handler_independence.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/services/reading.py backend/jobs/inline_runner.py backend/worker_handler.py backend/deps.py backend/main.py backend/test_preload_jobs.py backend/test_admin_chat_activity.py
git commit -m "Record terminal learner activity"
```

### Task 5: Implement atomic account control and session revocation

**Files:**
- Create: `backend/repositories/admin_account_control.py`
- Create: `backend/repositories/memory_admin_account_control.py`
- Create: `backend/repositories/json_admin_account_control.py`
- Create: `backend/repositories/session_repository.py`
- Create: `backend/repositories/memory_session_repository.py`
- Create: `backend/repositories/json_session_repository.py`
- Create: `backend/services/admin_accounts.py`
- Create: `backend/test_admin_account_control.py`
- Create: `backend/test_admin_accounts_service.py`
- Create: `backend/test_admin_session_repository.py`
- Modify: `backend/deps.py`

- [ ] **Step 1: Write failing atomicity and idempotency tests**

```python
def test_suspend_atomically_adds_control_and_audit(tmp_path):
    repository = repository_factory(tmp_path)
    result = repository.transition(
        target_user_id="user-1",
        desired_status="suspended",
        actor_user_id="admin-1",
        actor_email="admin@example.com",
        reason="Abuse investigation",
        correlation_id="request-1",
        recorded_at=FIXED_NOW,
        audit_event_id=UUID7,
    )
    assert result.changed is True
    assert repository.get_status("user-1").account_status == "suspended"
    assert len(repository.list_audit_events(target_user_id="user-1")) == 1


def test_duplicate_suspend_does_not_add_audit(tmp_path):
    repository = repository_factory(tmp_path)
    first = suspend(repository)
    second = suspend(repository)
    assert first.changed is True
    assert second.changed is False
    assert len(repository.list_audit_events(target_user_id="user-1")) == 1
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
cd backend
.venv/bin/python -m pytest -q test_admin_account_control.py test_admin_session_repository.py
```

Expected: FAIL because repositories do not exist.

- [ ] **Step 3: Implement the account-control document and port**

Use this versioned document:

```json
{
  "version": 1,
  "account_controls": {
    "user-1": {
      "account_status": "suspended",
      "suspended_at": "2026-07-20T00:00:00+00:00",
      "suspended_reason": "Abuse investigation"
    }
  },
  "admin_audit_events": []
}
```

Define immutable `AccountControl`, `AdminAuditEvent`, and `TransitionResult` dataclasses plus an `AdminAccountControlRepository` protocol. Run the same contract suite against an in-memory adapter and the JSON adapter. The JSON adapter uses a dedicated `fcntl` lock, temporary file, `fsync`, and `os.replace`; it never updates status without appending the corresponding UUID v7 audit event in the same replacement document.

- [ ] **Step 4: Implement session revocation**

```python
# backend/repositories/session_repository.py
from typing import Protocol


class SessionRepository(Protocol):
    def revoke_all(self, user_id: str) -> int: ...
```

`MemorySessionRepository` and `JsonSessionRepository` pass the same revocation contract. The JSON implementation locks `AUTH_SESSIONS_PATH`, removes records whose `user_id` matches, writes the remaining list atomically, and returns the removed count.

- [ ] **Step 5: Implement suspend/reactivate use cases**

```python
def suspend_user(
    account_repository: AdminAccountControlRepository,
    session_repository: SessionRepository,
    *,
    actor: User,
    target_user_id: str,
    reason: str,
    correlation_id: str,
) -> TransitionResult:
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValueError("A suspension reason is required.")
    result = account_repository.transition(
        target_user_id=target_user_id,
        desired_status="suspended",
        actor_user_id=actor.id,
        actor_email=actor.email,
        reason=normalized_reason,
        correlation_id=correlation_id,
    )
    if result.changed:
        session_repository.revoke_all(target_user_id)
    return result
```

Implement `reactivate_user` with the same reason validation but no session revocation.

Add a service test whose session repository raises after a successful suspension. Assert the use case raises, the account remains suspended, the transition audit exists, and a retry returns `changed=False` without another audit.

- [ ] **Step 6: Run focused tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest -q test_admin_account_control.py test_admin_session_repository.py test_admin_accounts_service.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/deps.py backend/repositories/admin_account_control.py backend/repositories/memory_admin_account_control.py backend/repositories/json_admin_account_control.py backend/repositories/session_repository.py backend/repositories/memory_session_repository.py backend/repositories/json_session_repository.py backend/services/admin_accounts.py backend/test_admin_account_control.py backend/test_admin_session_repository.py backend/test_admin_accounts_service.py
git commit -m "Add atomic admin account controls"
```

### Task 6: Add admin authorization and learner suspension enforcement

**Files:**
- Create: `backend/services/admin_auth.py`
- Create: `backend/services/account_access.py`
- Create: `backend/admin/__init__.py`
- Create: `backend/admin/deps.py`
- Create: `backend/admin/router.py`
- Create: `backend/test_admin_auth.py`
- Create: `backend/test_learner_suspension.py`
- Modify: `backend/deps.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Write failing allowlist tests**

```python
from models.user import User
from services.admin_auth import require_admin


def test_allowlist_is_normalized() -> None:
    user = User(id="1", email="Admin@Example.com", display_name="Admin")
    assert require_admin(user, ("admin@example.com",)) == user


def test_empty_allowlist_fails_closed() -> None:
    user = User(id="1", email="admin@example.com", display_name="Admin")
    with pytest.raises(AdminForbidden):
        require_admin(user, ())
```

- [ ] **Step 2: Write failing suspension API tests**

Use FastAPI dependency overrides and assert:

```python
assert client.get("/auth/me", headers=suspended).status_code == 200
assert client.post("/analyze", json=payload, headers=suspended).status_code == 403
assert client.post("/analyze", json=payload, headers=suspended).json()["code"] == "account_suspended"
assert client.get("/admin/v1/session", headers=suspended_admin).status_code == 200
```

- [ ] **Step 3: Implement framework-independent policies**

`require_admin(user, allowlist)` returns the user or raises `AdminForbidden`. `require_active_learner(user_id, account_repository)` raises `AccountSuspended` when effective status is suspended. Neither module imports FastAPI.

- [ ] **Step 4: Implement FastAPI dependencies and session route**

`backend/admin/deps.py` maps `AdminForbidden` to `HTTPException(403)` with stable code `admin_forbidden`. `backend/admin/router.py` defines `GET /admin/v1/session` using generated `AdminSession`. Mount the router only when `ADMIN_ENABLED`.

Add `get_active_learner_user` to `backend/deps.py`. Replace `get_current_user` with it on all learner product routes except `/auth/me`, `/auth/logout`, and admin routes. Keep billing webhook and public endpoints unchanged.

- [ ] **Step 5: Run policy, API, and architecture tests**

Run:

```bash
cd backend
ADMIN_ENABLED=true ADMIN_EMAILS=admin@example.com STORAGE_BACKEND=json \
  .venv/bin/python -m pytest -q \
  test_admin_auth.py test_learner_suspension.py test_handler_independence.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/admin backend/deps.py backend/main.py backend/services/admin_auth.py backend/services/account_access.py backend/test_admin_auth.py backend/test_learner_suspension.py backend/test_handler_independence.py
git commit -m "Enforce admin and learner access policies"
```

### Task 7: Implement users, metrics, and alerts

**Files:**
- Create: `backend/repositories/admin_users.py`
- Create: `backend/repositories/memory_admin_users.py`
- Create: `backend/repositories/json_admin_users.py`
- Create: `backend/repositories/admin_metrics.py`
- Create: `backend/repositories/memory_admin_metrics.py`
- Create: `backend/repositories/json_admin_metrics.py`
- Create: `backend/services/admin_users.py`
- Create: `backend/services/admin_metrics.py`
- Create: `backend/services/admin_alerts.py`
- Create: `backend/test_admin_users_service.py`
- Create: `backend/test_admin_metrics_service.py`
- Create: `backend/test_admin_alerts_service.py`
- Modify: `backend/deps.py`

- [ ] **Step 1: Write failing metrics tests with a fixed clock**

```python
def test_dashboard_counts_distinct_active_users() -> None:
    events = [
        activity("a1", "user-1", "article", "success", "2026-07-01T00:00:00Z"),
        activity("a2", "user-1", "chat", "success", "2026-07-02T00:00:00Z"),
        activity("a3", "user-2", "chat", "failed", "2026-07-02T00:00:00Z"),
    ]
    totals = calculate_totals(users=USERS, events=events, start=START, end=END)
    assert totals.active_users == 1
    assert totals.articles == 1
    assert totals.chats == 1
```

Add tests for inclusive start/exclusive end, UTC day buckets, rolling 7/30 days, calendar month, and rejection above 90 days.

- [ ] **Step 2: Write failing alert threshold tests**

```python
def test_failure_spike_requires_five_failures_in_bucket() -> None:
    alerts = calculate_failure_alerts(
        [failed_event(minute=index) for index in range(5)]
    )
    assert [alert.type for alert in alerts] == ["failure_spike"]


def test_elevated_rate_requires_twenty_attempts_and_ten_percent_failures() -> None:
    events = [success_event(index) for index in range(18)]
    events += [failed_event(index) for index in range(2)]
    alerts = calculate_failure_alerts(events)
    assert "elevated_failure_rate" in {alert.type for alert in alerts}
```

- [ ] **Step 3: Implement focused repository ports**

`AdminUserRepository` returns raw user records with deterministic cursor pagination and email/status/plan filters. `AdminMetricsRepository` exposes read-only access to users, subscriptions, monthly usage, activity, and account controls. In-memory and JSON implementations pass the same query contract; the JSON implementation composes existing JSON files rather than duplicating writes.

- [ ] **Step 4: Implement pure calculations**

In `services/admin_metrics.py`, implement:

```python
def validate_period(start: datetime, end: datetime) -> None:
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("A valid UTC reporting period is required.")
    if end - start > timedelta(days=90):
        raise ValueError("Reporting periods cannot exceed 90 days.")
```

Group successful activity by UTC date; count distinct successful users; sum integer token and micro-USD fields; calculate plan counts and top users. Each dashboard section is evaluated independently and converted to an `ok` or `error` envelope with the request correlation ID.

In `services/admin_alerts.py`, calculate:

- quota pressure at `>= 80%`;
- one quota-block alert per `quota_blocked` event;
- failure spike at `>= 5` failures per 15-minute bucket;
- elevated rate at `>= 20` attempts and `failed / attempts >= 0.10`.

- [ ] **Step 5: Run service tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest -q test_admin_users_service.py test_admin_metrics_service.py test_admin_alerts_service.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/deps.py backend/repositories/admin_users.py backend/repositories/memory_admin_users.py backend/repositories/json_admin_users.py backend/repositories/admin_metrics.py backend/repositories/memory_admin_metrics.py backend/repositories/json_admin_metrics.py backend/services/admin_users.py backend/services/admin_metrics.py backend/services/admin_alerts.py backend/test_admin_users_service.py backend/test_admin_metrics_service.py backend/test_admin_alerts_service.py
git commit -m "Calculate admin users metrics and alerts"
```

### Task 8: Complete admin HTTP endpoints and conformance tests

**Files:**
- Modify: `backend/admin/router.py`
- Modify: `backend/admin/deps.py`
- Create: `backend/test_admin_api.py`
- Create: `backend/test_admin_api_contract.py`

- [ ] **Step 1: Write failing route tests**

Cover all operation IDs with allowlisted mock authentication:

```python
assert client.get("/admin/v1/dashboard", params=period, headers=admin).status_code == 200
assert client.get("/admin/v1/users", headers=admin).status_code == 200
assert client.get(f"/admin/v1/users/{USER_ID}", headers=admin).status_code == 200
assert client.post(
    f"/admin/v1/users/{USER_ID}/suspend",
    json={"reason": "Investigation"},
    headers=admin,
).json()["changed"] is True
assert client.post(
    f"/admin/v1/users/{USER_ID}/reactivate",
    json={"reason": "Investigation complete"},
    headers=admin,
).json()["changed"] is True
assert client.get("/admin/v1/alerts", params=period, headers=admin).status_code == 200
assert client.get("/admin/v1/audit-events", headers=admin).status_code == 200
```

Also assert non-admin `403`, missing reason `422`, missing user `404`, cursor/page limits, 90-day bounds, stable error codes, and correlation IDs.

- [ ] **Step 2: Run the API suite and verify failure**

Run:

```bash
cd backend
ADMIN_ENABLED=true ADMIN_EMAILS=admin@example.com STORAGE_BACKEND=json \
  .venv/bin/python -m pytest -q test_admin_api.py test_admin_api_contract.py
```

Expected: FAIL because the remaining routes do not exist.

- [ ] **Step 3: Implement thin FastAPI handlers**

Handlers must:

- depend on `get_admin_user`;
- read `request.state.correlation_id`;
- delegate to one application service;
- return generated Pydantic response models;
- map domain validation to `422`, missing users to `404`, and unexpected failures to `500 internal_error`;
- never calculate metrics or mutate JSON directly.

- [ ] **Step 4: Validate responses against generated models**

In `test_admin_api_contract.py`, call each route and validate its JSON with the generated model's `model_validate`. Confirm learner-facing route schemas still exclude `actual_cost_micro_usd`, raw model pricing, and admin audit fields.

- [ ] **Step 5: Run backend regression gates**

Run:

```bash
cd backend
.venv/bin/python -m pytest -q \
  --ignore=test_dynamodb_storage.py \
  --ignore=test_preload_dynamodb_integration.py
scripts/check_admin_openapi.sh
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/admin backend/test_admin_api.py backend/test_admin_api_contract.py
git commit -m "Expose authorized admin API endpoints"
```

### Task 9: Add backend CI gates and operator documentation

**Files:**
- Modify: `.github/workflows/reading-assistant-ci.yml`
- Modify: `backend/.env.example`
- Modify: `README.md`
- Create: `backend/test_admin_acceptance.py`

- [ ] **Step 1: Add the backend acceptance test**

Create one deterministic test that:

1. logs in with `mock:admin@example.com`;
2. loads dashboard fixtures;
3. suspends `learner@example.com`;
4. verifies the learner product route returns `403 account_suspended`;
5. verifies one audit event;
6. reactivates the learner with a reason.

- [ ] **Step 2: Run the acceptance test**

Run:

```bash
cd backend
ADMIN_ENABLED=true ADMIN_EMAILS=admin@example.com AUTH_PROVIDER=mock STORAGE_BACKEND=json \
  .venv/bin/python -m pytest -q test_admin_acceptance.py
```

Expected: PASS.

- [ ] **Step 3: Add CI contract and path coverage**

Add `contracts/**` and `frontend/**` to pull-request and push path filters. Install `backend/requirements-dev.txt` in the backend job, run `scripts/check_admin_openapi.sh`, and keep DynamoDB integration tests unchanged with admin disabled.

- [ ] **Step 4: Document local backend startup**

Document:

```bash
cd backend
cp .env.example .env
ADMIN_ENABLED=true \
ADMIN_EMAILS=admin@example.com \
AUTH_PROVIDER=mock \
STORAGE_BACKEND=json \
.venv/bin/uvicorn main:app --reload --port 18765
```

Explain that `POST /auth/login` with `{"credential":"mock:admin@example.com"}` is local-only and that production Google configuration is not part of this plan.

- [ ] **Step 5: Run all backend gates**

Run:

```bash
cd backend
.venv/bin/python -m pytest -q \
  --ignore=test_dynamodb_storage.py \
  --ignore=test_preload_dynamodb_integration.py
scripts/check_admin_openapi.sh
cd ../extension
node --test test/shared.test.mjs
```

Expected: all suites pass.

- [ ] **Step 6: Request Opus 4.8 implementation review**

Ask Opus 4.8 to review the backend branch diff against `docs/superpowers/specs/2026-07-20-admin-site-design.md`, focusing on authorization bypasses, event duplication, JSON atomicity, session revocation, API contract drift, and accidental edits to concurrent usage-meter work. Resolve all blocking findings and rerun Step 5.

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/reading-assistant-ci.yml backend/.env.example backend/test_admin_acceptance.py README.md
git commit -m "Add admin backend release gates"
```
