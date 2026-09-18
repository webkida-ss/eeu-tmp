# Preload DynamoDB Regression Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the real `POST /pages/preload` request path fail in CI if DynamoDB transaction writes return an internal server error.

**Architecture:** Enable the existing repository-to-DynamoDB integration tests and add one narrow test that crosses the FastAPI transport boundary, reading service, `DynamoPagePreloadRepository`, `DynamoDbStore`, and a real DynamoDB Local process. Share a pytest fixture that creates an isolated table and fails when a configured service is unavailable. Keep OpenAI and background processing outside the HTTP test by injecting a recording runner.

**Tech Stack:** Python 3.12, pytest, FastAPI `TestClient`, boto3, DynamoDB Local, GitHub Actions

---

## Why the Existing Tests Missed the 500

The existing API tests replace the preload repository with
`JsonPagePreloadRepository`, so they never execute DynamoDB serialization or
`TransactWriteItems`.

The store transaction unit test uses a hand-written recording client. It
proves delegation but cannot reproduce boto3's different request transformation
behavior between a standalone low-level client and `resource.meta.client`.

`backend/test_dynamodb_storage.py` already exercises the real preload
repository and the broken transaction path. However, it skips unless
`STORAGE_BACKEND=dynamodb` and skips again when a pre-created table is absent.
CI provides neither, so the relevant coverage never runs.

The required gates are therefore:

1. Run the existing repository integration tests against a fixture-owned table
   in required CI.
2. Prove at the HTTP boundary that a valid preload submission returns 202
   rather than an unnoticed 500.

## Required Coverage

- A valid `POST /pages/preload` returns HTTP 202 and `processing`.
- The preload is readable by URL after the request.
- Both the immutable preload record and URL index are persisted.
- The runner is invoked exactly once after persistence.
- Existing DynamoDB auth, preload, and phrase repository tests run against a
  real service.
- No mock or fake transaction client is used in these integration tests.
- A configured but missing or unhealthy DynamoDB service fails CI.
- The test is proven with RED/GREEN evidence by temporarily restoring the
  broken `resource.meta.client` call.

## Out of Scope

- Real OpenAI calls.
- Full asynchronous article analysis.
- SQS and Lambda worker execution.
- Browser automation.
- Production AWS credentials or resources.

## Opus 4.8 Review Amendments

Opus 4.8 reviewed the initial design and returned **Approve with changes**.
This revision applies all blocking recommendations:

- Uses article HTML longer than `_extract_article_text`'s 100-character
  minimum, avoiding a false 400 before DynamoDB is reached.
- Enables the existing real repository integration tests instead of treating
  the new HTTP test as the only missing coverage.
- Overrides every mutable FastAPI dependency used by preload submission.
- Cleans up app overrides, temporary files, and the test table.
- Uses one explicit integration endpoint convention and makes the CI
  invocation non-skippable.

### Task 1: Add an Isolated DynamoDB Fixture

**Files:**
- Create: `backend/conftest.py`
- Modify: `backend/test_dynamodb_storage.py`

- [ ] **Step 1: Write the fixture**

Add a module-scoped `dynamodb_store` fixture. Read
`DYNAMODB_INTEGRATION_ENDPOINT`; skip only when it is absent so the default
service-free suite remains fast. When it is present, retry `list_tables` for up
to 30 seconds and call `pytest.fail` if the service is not healthy.

Create a unique table using the production key schema:

```python
client.create_table(
    TableName=f"english-test-reading-assistant-{uuid.uuid4()}",
    KeySchema=[
        {"AttributeName": "pk", "KeyType": "HASH"},
        {"AttributeName": "sk", "KeyType": "RANGE"},
    ],
    AttributeDefinitions=[
        {"AttributeName": "pk", "AttributeType": "S"},
        {"AttributeName": "sk", "AttributeType": "S"},
    ],
    BillingMode="PAY_PER_REQUEST",
)
```

Construct both a real resource and a standalone client:

```python
yield DynamoDbStore(
    table_name=table_name,
    resource=resource,
    client=client,
)
```

Delete the table in `finally`. This preserves isolation and exercises the
standalone-client distinction that fixed the regression.

- [ ] **Step 2: Enable the existing integration tests**

Remove the `STORAGE_BACKEND=dynamodb` marker and old service-detection fixture
from `backend/test_dynamodb_storage.py`. Change its three tests to request
`dynamodb_store`.

- [ ] **Step 3: Verify the existing preload repository test**

```bash
cd backend
DYNAMODB_INTEGRATION_ENDPOINT=http://localhost:18000 \
  .venv/bin/python -m pytest -q \
  test_dynamodb_storage.py::test_dynamodb_page_preload_repository
```

Expected: one pass and zero skips.

### Task 2: Add the API-to-DynamoDB Regression Test

**Files:**
- Create: `backend/test_preload_dynamodb_integration.py`
- Use fixture: `backend/conftest.py`
- Reference: `backend/test_preload_jobs.py:3274-3341`

- [ ] **Step 1: Build isolated FastAPI dependencies**

Use the shared `dynamodb_store` fixture only for
`DynamoPagePreloadRepository`. Create temporary JSON repositories for auth,
usage, and subscriptions plus a temporary `FilesystemPreloadContentStore`.

Mirror the complete override set used by `PreloadApiTests`:

```python
app.dependency_overrides[get_auth_service] = lambda: auth_service
app.dependency_overrides[get_identity_provider] = MockIdentityProvider
app.dependency_overrides[get_page_preload_repository] = lambda: preloads
app.dependency_overrides[get_usage_repository] = lambda: usage
app.dependency_overrides[get_subscription_repository] = lambda: subscriptions
app.dependency_overrides[get_preload_content_store] = lambda: content
app.dependency_overrides[get_preload_job_runner] = lambda: runner
```

Let the normal entitlement guard and usage meter resolve from these isolated
repositories. Define a recording runner whose `enqueue` accepts optional
`usage_context` and never starts OpenAI work.

- [ ] **Step 2: Write the HTTP regression assertion**

Use `TestClient(app, raise_server_exceptions=False)`, log in with the mock
identity provider, and submit extractable HTML longer than 100 characters:

```python
response = client.post(
    "/pages/preload",
    json={
        "page_url": "https://example.com/integration",
        "page_title": "Integration",
        "html": (
            "<article>"
            "<p>The quick brown fox jumps over the lazy dog every morning.</p>"
            "<p>She sells fresh seashells by the seashore in summer.</p>"
            "<p>Programming languages evolve as developers demand more power.</p>"
            "</article>"
        ),
    },
    headers=headers,
)

assert response.status_code == 202, response.text
assert response.json()["status"] == "processing"
stored = preloads.get_by_page_url(user_id, "https://example.com/integration")
assert stored is not None
assert stored["status"] == "processing"
assert len(runner.calls) == 1
```

Query the table and assert that one immutable preload record and one URL index
exist for this user.

- [ ] **Step 3: Add unconditional cleanup**

Use pytest fixtures or `try/finally` to always close `TestClient`, clear
`app.dependency_overrides`, and remove the temporary directory. The shared
DynamoDB fixture deletes the table.

- [ ] **Step 4: Verify GREEN with the current fix**

```bash
cd backend
DYNAMODB_INTEGRATION_ENDPOINT=http://localhost:18000 \
  .venv/bin/python -m pytest -q test_preload_dynamodb_integration.py
```

Expected: one pass and zero skips.

- [ ] **Step 5: Prove RED against the original defect**

Temporarily replace:

```python
self._client.transact_write_items(TransactItems=items)
```

with:

```python
self._resource.meta.client.transact_write_items(TransactItems=items)
```

Run the focused API test. Expected: failure because the API returns HTTP 500
and DynamoDB Local reports `ValidationException: Invalid attribute value type`.
Restore the fixed implementation and rerun. Expected: pass.

### Task 3: Make Integration Coverage a Required CI Gate

**Files:**
- Modify: `.github/workflows/reading-assistant-ci.yml`

- [ ] **Step 1: Start DynamoDB Local**

Add this service to `backend-test`:

```yaml
services:
  dynamodb:
    image: amazon/dynamodb-local@sha256:d89f8fcc6b1a39cb35976c248ed42a28c66ae00dc043099210f5571e42648ab4
    ports:
      - 8000:8000
```

- [ ] **Step 2: Run all DynamoDB integration tests explicitly**

```yaml
- name: Run DynamoDB integration tests
  env:
    DYNAMODB_INTEGRATION_ENDPOINT: http://localhost:8000
  run: |
    .venv/bin/python -m pytest -q \
      test_dynamodb_storage.py \
      test_preload_dynamodb_integration.py
```

The endpoint is set in required CI, so the fixture must not skip. Its readiness
retry converts an unavailable configured service into a test failure.

- [ ] **Step 3: Keep the fast suite service-independent**

```yaml
run: |
  .venv/bin/python -m pytest -q \
    --ignore=test_dynamodb_storage.py \
    --ignore=test_preload_dynamodb_integration.py
```

Expected: the fast suite stays deterministic, while the explicit integration
step owns service startup and failure reporting.

### Task 4: Verify and Commit the Test Gate

**Files:**
- Verify: `backend/conftest.py`
- Verify: `backend/test_dynamodb_storage.py`
- Verify: `backend/test_preload_dynamodb_integration.py`
- Verify: `.github/workflows/reading-assistant-ci.yml`

- [ ] **Step 1: Run all DynamoDB integration tests**

```bash
cd backend
DYNAMODB_INTEGRATION_ENDPOINT=http://localhost:18000 \
  .venv/bin/python -m pytest -q \
  test_dynamodb_storage.py \
  test_preload_dynamodb_integration.py
```

Expected: all tests pass and zero skip.

- [ ] **Step 2: Run the service-free backend suite**

```bash
cd backend
.venv/bin/python -m pytest -q \
  --ignore=test_dynamodb_storage.py \
  --ignore=test_preload_dynamodb_integration.py
```

Expected: all collected tests pass.

- [ ] **Step 3: Inspect the final diff**

```bash
git diff --check
git diff -- backend/conftest.py \
  backend/test_dynamodb_storage.py \
  backend/test_preload_dynamodb_integration.py \
  .github/workflows/reading-assistant-ci.yml
```

Expected: no whitespace errors and only focused test/CI changes.

- [ ] **Step 4: Commit**

```bash
git add backend/conftest.py \
  backend/test_dynamodb_storage.py \
  backend/test_preload_dynamodb_integration.py \
  .github/workflows/reading-assistant-ci.yml \
  docs/superpowers/plans/2026-07-18-preload-dynamodb-regression-tests.md
git commit -m "Add DynamoDB preload regression gate"
```

