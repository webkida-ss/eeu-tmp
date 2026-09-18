# Local Admin Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the authorized local Next.js admin interface for overview metrics, users, alerts, audit history, account suspension, and end-to-end release gates.

**Architecture:** Use a Next.js App Router shell with thin pages and feature-owned components following Bulletproof React boundaries. Consume only the generated OpenAPI client, centralize session state and API configuration, and keep all authorization enforcement in the backend.

**Tech Stack:** Next.js, React, TypeScript, Tailwind CSS, pnpm, `@hey-api/openapi-ts`, Vitest, React Testing Library, Playwright.

---

## File Structure

```text
frontend/
  package.json
  pnpm-lock.yaml
  next.config.ts
  tsconfig.json
  postcss.config.mjs
  eslint.config.mjs
  vitest.config.ts
  playwright.config.ts
  src/
    app/
      globals.css
      layout.tsx
      login/page.tsx
      (admin)/layout.tsx
      (admin)/page.tsx
      (admin)/users/page.tsx
      (admin)/users/[id]/page.tsx
      (admin)/alerts/page.tsx
      (admin)/audit/page.tsx
    components/
      layout/admin-shell.tsx
      layout/sidebar.tsx
      ui/button.tsx
      ui/card.tsx
      ui/empty-state.tsx
      ui/error-state.tsx
      ui/input.tsx
      ui/modal.tsx
      ui/pagination.tsx
      ui/status-badge.tsx
    features/
      auth/
        api/session.ts
        components/login-form.tsx
        components/google-login-button.tsx
        components/session-gate.tsx
        hooks/use-session.ts
      overview/
        api/get-dashboard.ts
        components/overview-screen.tsx
        components/metric-card.tsx
        components/usage-trend.tsx
        components/plan-distribution.tsx
        components/top-users.tsx
      users/
        api/get-users.ts
        api/get-user.ts
        api/transition-user.ts
        components/users-screen.tsx
        components/user-detail-screen.tsx
        components/account-transition-dialog.tsx
      alerts/
        api/get-alerts.ts
        components/alerts-screen.tsx
      audit/
        api/get-audit-events.ts
        components/audit-screen.tsx
    lib/
      api/client.gen.ts
      api/sdk.gen.ts
      api/types.gen.ts
      env.ts
      format.ts
  e2e/
    admin.spec.ts
docs/FRONTEND.md
```

### Task 1: Scaffold Next.js, tests, Tailwind, and generated API client

**Files:**
- Create: `frontend/` configuration files
- Create: `frontend/src/app/layout.tsx`
- Create: `frontend/src/app/globals.css`
- Create: `frontend/src/lib/env.ts`
- Create: `frontend/src/lib/format.ts`
- Generate: `frontend/src/lib/api/*`
- Create: `frontend/src/lib/format.test.ts`
- Create: `frontend/src/app/page.test.tsx`
- Create: `docs/FRONTEND.md`
- Modify: `.gitignore`

- [ ] **Step 1: Scaffold with pnpm and install current dependencies**

Run:

```bash
pnpm create next-app frontend \
  --ts --tailwind --eslint --app --src-dir \
  --import-alias "@/*" --use-pnpm
cd frontend
pnpm add @hey-api/client-fetch
pnpm add -D @hey-api/openapi-ts vitest @vitejs/plugin-react jsdom \
  @testing-library/react @testing-library/jest-dom @testing-library/user-event \
  @playwright/test
```

Expected: `frontend/package.json` and `pnpm-lock.yaml` exist; no JavaScript source files are created.

- [ ] **Step 2: Write the failing formatting test**

```typescript
// frontend/src/lib/format.test.ts
import { describe, expect, it } from "vitest";

import { formatMicroUsd, formatTokens } from "./format";

describe("admin formatting", () => {
  it("formats integer micro-USD only at the UI boundary", () => {
    expect(formatMicroUsd(92_400_000)).toBe("$92.40");
  });

  it("formats token counts compactly", () => {
    expect(formatTokens(18_400_000)).toBe("18.4M");
  });
});
```

- [ ] **Step 3: Add Vitest configuration and verify failure**

```typescript
// frontend/vitest.config.ts
import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
  },
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
});
```

```typescript
// frontend/vitest.setup.ts
import "@testing-library/jest-dom/vitest";
```

Add `"test": "vitest run"` and `"typecheck": "tsc --noEmit"` scripts. Run `pnpm test`.

Expected: FAIL because `format.ts` does not exist.

- [ ] **Step 4: Implement environment and formatting utilities**

```typescript
// frontend/src/lib/env.ts
const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
  "http://localhost:18765";

export const env = { apiBaseUrl } as const;
```

```typescript
// frontend/src/lib/format.ts
const usd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const compact = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumFractionDigits: 1,
});

export const formatMicroUsd = (value: number): string =>
  usd.format(value / 1_000_000);

export const formatTokens = (value: number): string => compact.format(value);
```

- [ ] **Step 5: Generate the API client**

Add:

```json
{
  "scripts": {
    "generate:api": "openapi-ts -i ../contracts/openapi/openapi.yaml -o src/lib/api",
    "check:api": "pnpm generate:api && git diff --exit-code -- src/lib/api"
  }
}
```

Run:

```bash
cd frontend
pnpm generate:api
pnpm test
pnpm typecheck
pnpm build
```

Expected: generated API files compile and all commands pass.

- [ ] **Step 6: Document the page inventory**

Create `docs/FRONTEND.md` with a Pages table containing `/login`, `/`, `/users`, `/users/[id]`, `/alerts`, and `/audit`, plus their purpose and required admin authorization.

- [ ] **Step 7: Commit**

```bash
git add frontend docs/FRONTEND.md .gitignore
git commit -m "Scaffold generated admin frontend"
```

### Task 2: Implement login, session gate, and admin shell

**Files:**
- Create: `frontend/src/features/auth/api/session.ts`
- Create: `frontend/src/features/auth/hooks/use-session.ts`
- Create: `frontend/src/features/auth/components/login-form.tsx`
- Create: `frontend/src/features/auth/components/google-login-button.tsx`
- Create: `frontend/src/features/auth/components/session-gate.tsx`
- Create: `frontend/src/components/layout/admin-shell.tsx`
- Create: `frontend/src/components/layout/sidebar.tsx`
- Create: `frontend/src/components/ui/button.tsx`
- Create: `frontend/src/components/ui/error-state.tsx`
- Create: `frontend/src/app/login/page.tsx`
- Create: `frontend/src/app/(admin)/layout.tsx`
- Create: `frontend/src/features/auth/components/session-gate.test.tsx`

- [ ] **Step 1: Write failing session-gate tests**

```typescript
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SessionGate } from "./session-gate";

vi.mock("../hooks/use-session", () => ({
  useSession: vi.fn(() => ({
    status: "authenticated",
    session: {
      user_id: "admin-1",
      email: "admin@example.com",
      display_name: "Admin",
    },
  })),
}));

describe("SessionGate", () => {
  it("renders protected content for an authorized session", () => {
    render(<SessionGate><div>Protected</div></SessionGate>);
    expect(screen.getByText("Protected")).toBeInTheDocument();
  });
});
```

Add cases for loading, `401`, and `403 admin_forbidden`.

- [ ] **Step 2: Run the test and verify failure**

Run `cd frontend && pnpm test -- session-gate`.

Expected: FAIL because `SessionGate` does not exist.

- [ ] **Step 3: Configure the generated client**

At application startup, configure the generated fetch client with `env.apiBaseUrl`. Store the opaque bearer token in `sessionStorage`, not local storage or cookies. `getAdminSession` sends the bearer header and maps `401` to signed-out and `403` to unauthorized.

Call the generated `getAuthConfig` operation before rendering login controls:

- When `provider === "google"`, `GoogleLoginButton` loads `https://accounts.google.com/gsi/client`, initializes it with the returned `google_client_id`, and sends the callback's ID-token credential to the generated `login` operation.
- When `provider === "mock"`, `LoginForm` sends `{"credential":"mock:<normalized email>"}` to the generated `login` operation.
- On success, store the access token in `sessionStorage`, call `getAdminSession`, and navigate to `/`.
- Tests replace the Google script with a deterministic `window.google.accounts.id` fake; CI never contacts Google.

Add component tests proving both provider branches use generated operation wrappers and that a non-allowlisted authenticated login renders the unauthorized state.

- [ ] **Step 4: Implement shell components**

`AdminShell` renders the sidebar links Overview, Users, Alerts, and Audit Log, plus current administrator email and sign-out. All components use Tailwind classes, named exports, one component per file, and no inline styles.

- [ ] **Step 5: Run focused and build tests**

Run:

```bash
cd frontend
pnpm test -- session-gate
pnpm typecheck
pnpm lint
pnpm build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add contracts/openapi frontend/src docs/FRONTEND.md
git commit -m "Add authorized admin application shell"
```

### Task 3: Implement the overview dashboard with partial failures

**Files:**
- Create: `frontend/src/features/overview/api/get-dashboard.ts`
- Create: `frontend/src/features/overview/components/metric-card.tsx`
- Create: `frontend/src/features/overview/components/usage-trend.tsx`
- Create: `frontend/src/features/overview/components/plan-distribution.tsx`
- Create: `frontend/src/features/overview/components/top-users.tsx`
- Create: `frontend/src/features/overview/components/overview-screen.tsx`
- Create: `frontend/src/features/overview/components/overview-screen.test.tsx`
- Create: `frontend/src/components/ui/card.tsx`
- Create: `frontend/src/components/ui/empty-state.tsx`
- Modify: `frontend/src/app/(admin)/page.tsx`

- [ ] **Step 1: Write failing partial-dashboard tests**

```typescript
it("renders available metrics while marking a failed section unavailable", async () => {
  render(
    <OverviewScreen
      dashboard={{
        totals: { status: "ok", data: totals },
        daily: {
          status: "error",
          error: {
            code: "section_unavailable",
            correlation_id: "request-1",
          },
        },
        plans: { status: "ok", data: [] },
        top_users: { status: "ok", data: [] },
        alerts: { status: "ok", data: [] },
      }}
    />,
  );
  expect(screen.getByText("1,284")).toBeInTheDocument();
  expect(screen.getByText(/Usage trend is unavailable/)).toBeInTheDocument();
  expect(screen.getByText(/request-1/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test and verify failure**

Run `cd frontend && pnpm test -- overview-screen`.

Expected: FAIL because overview components do not exist.

- [ ] **Step 3: Implement date-range loading and cards**

Use generated `getAdminDashboard`. Default to rolling 30 days in UTC and support 7 days, 30 days, current month, and a validated custom range of at most 90 days. Render total users, active users, tokens, cost, daily trend, plan distribution, article/chat totals, alerts, and top users in the approved order.

Use accessible HTML tables or SVG for visualizations; do not add a chart dependency unless native rendering cannot satisfy the tests.

- [ ] **Step 4: Run focused quality gates**

Run:

```bash
cd frontend
pnpm test -- overview-screen
pnpm typecheck
pnpm lint
pnpm build
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/'(admin)'/page.tsx frontend/src/features/overview frontend/src/components/ui
git commit -m "Render admin usage overview"
```

### Task 4: Implement user list, detail, suspension, and reactivation

**Files:**
- Create: `frontend/src/features/users/api/get-users.ts`
- Create: `frontend/src/features/users/api/get-user.ts`
- Create: `frontend/src/features/users/api/transition-user.ts`
- Create: `frontend/src/features/users/components/users-screen.tsx`
- Create: `frontend/src/features/users/components/user-detail-screen.tsx`
- Create: `frontend/src/features/users/components/account-transition-dialog.tsx`
- Create: `frontend/src/features/users/components/account-transition-dialog.test.tsx`
- Create: `frontend/src/components/ui/input.tsx`
- Create: `frontend/src/components/ui/modal.tsx`
- Create: `frontend/src/components/ui/pagination.tsx`
- Create: `frontend/src/components/ui/status-badge.tsx`
- Create: `frontend/src/app/(admin)/users/page.tsx`
- Create: `frontend/src/app/(admin)/users/[id]/page.tsx`

- [ ] **Step 1: Write failing dialog tests**

```typescript
it("requires a reason before suspending a user", async () => {
  const user = userEvent.setup();
  const onConfirm = vi.fn();
  render(
    <AccountTransitionDialog
      action="suspend"
      email="learner@example.com"
      open
      onCancel={vi.fn()}
      onConfirm={onConfirm}
    />,
  );
  await user.click(screen.getByRole("button", { name: "Suspend user" }));
  expect(onConfirm).not.toHaveBeenCalled();
  expect(screen.getByText("A reason is required.")).toBeInTheDocument();
});
```

Add a success test that trims the reason and calls `onConfirm` once.

- [ ] **Step 2: Run the test and verify failure**

Run `cd frontend && pnpm test -- account-transition-dialog`.

Expected: FAIL because the dialog does not exist.

- [ ] **Step 3: Implement server-driven list and detail**

The list sends search, account-status, plan, sort, cursor, and limit through generated query types. The detail renders identity, account state, subscription, current usage, recent activity, and recent admin audit events.

Suspension/reactivation calls generated command functions. On success, replace displayed state with the response and refresh detail/audit data. On `changed=false`, show the current state without adding a duplicate success notification. On errors, display the backend correlation ID.

- [ ] **Step 4: Run focused quality gates**

Run:

```bash
cd frontend
pnpm test -- users
pnpm typecheck
pnpm lint
pnpm build
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/'(admin)'/users frontend/src/features/users frontend/src/components/ui
git commit -m "Add admin user account controls"
```

### Task 5: Implement alerts and audit log

**Files:**
- Create: `frontend/src/features/alerts/api/get-alerts.ts`
- Create: `frontend/src/features/alerts/components/alerts-screen.tsx`
- Create: `frontend/src/features/alerts/components/alerts-screen.test.tsx`
- Create: `frontend/src/features/audit/api/get-audit-events.ts`
- Create: `frontend/src/features/audit/components/audit-screen.tsx`
- Create: `frontend/src/features/audit/components/audit-screen.test.tsx`
- Create: `frontend/src/app/(admin)/alerts/page.tsx`
- Create: `frontend/src/app/(admin)/audit/page.tsx`

- [ ] **Step 1: Write failing alerts test**

```typescript
it("filters computed alerts by type and user", async () => {
  render(<AlertsScreen initialAlerts={alerts} />);
  await userEvent.selectOptions(
    screen.getByLabelText("Alert type"),
    "quota_pressure",
  );
  expect(screen.getByText("learner@example.com")).toBeInTheDocument();
  expect(screen.queryByText("Failure spike")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Write failing audit test**

```typescript
it("shows immutable transition details", () => {
  render(<AuditScreen initialPage={auditPage} />);
  expect(screen.getByText("user_suspended")).toBeInTheDocument();
  expect(screen.getByText("Abuse investigation")).toBeInTheDocument();
  expect(screen.getByText("admin@example.com")).toBeInTheDocument();
});
```

- [ ] **Step 3: Run focused tests and verify failure**

Run `cd frontend && pnpm test -- alerts-screen audit-screen`.

Expected: FAIL because screens do not exist.

- [ ] **Step 4: Implement generated-client loading**

Alerts support period, type, operation, and user filters. Audit supports opaque cursor pagination and user/action filters. Both provide loading, empty, error, and correlation-ID states. Neither screen mutates records.

- [ ] **Step 5: Run focused quality gates**

Run:

```bash
cd frontend
pnpm test -- alerts-screen audit-screen
pnpm typecheck
pnpm lint
pnpm build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/'(admin)'/alerts frontend/src/app/'(admin)'/audit frontend/src/features/alerts frontend/src/features/audit
git commit -m "Add admin alerts and audit views"
```

### Task 6: Add Playwright release gates and frontend CI

**Files:**
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/admin.spec.ts`
- Create: `frontend/e2e/fixtures/admin-data.ts`
- Modify: `frontend/package.json`
- Modify: `.github/workflows/reading-assistant-ci.yml`
- Modify: `README.md`
- Modify: `docs/FRONTEND.md`

- [ ] **Step 1: Add deterministic E2E fixtures**

Create fixture JSON in a temporary test data directory with:

- `admin@example.com` and `learner@example.com`;
- active account controls;
- a subscription and monthly usage for the learner;
- successful article/chat activity;
- quota-pressure and failure events.

Start the backend with `ADMIN_ENABLED=true`, `AUTH_PROVIDER=mock`, `ADMIN_EMAILS=admin@example.com`, `STORAGE_BACKEND=json`, and test-specific path overrides. Start Next.js with `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:18765`.

- [ ] **Step 2: Write the full release-gate E2E test**

```typescript
test("admin suspends and reactivates a learner", async ({ page, request }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@example.com");
  await page.getByRole("button", { name: "Sign in locally" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();

  await page.getByRole("link", { name: "Users" }).click();
  await page.getByPlaceholder("Search by email").fill("learner@example.com");
  await page.getByRole("link", { name: "learner@example.com" }).click();
  await page.getByRole("button", { name: "Suspend user" }).click();
  await page.getByLabel("Reason").fill("E2E suspension check");
  await page.getByRole("button", { name: "Confirm suspension" }).click();
  await expect(page.getByText("Suspended")).toBeVisible();

  await page.getByRole("link", { name: "Audit Log" }).click();
  await expect(page.getByText("E2E suspension check")).toBeVisible();

  await page.getByRole("link", { name: "Users" }).click();
  await page.getByRole("link", { name: "learner@example.com" }).click();
  await page.getByRole("button", { name: "Reactivate user" }).click();
  await page.getByLabel("Reason").fill("E2E check complete");
  await page.getByRole("button", { name: "Confirm reactivation" }).click();
  await expect(page.getByText("Active")).toBeVisible();
});
```

Add a second test proving a non-allowlisted authenticated user receives the unauthorized screen.

- [ ] **Step 3: Run the E2E suite**

Run:

```bash
cd frontend
pnpm exec playwright install chromium
pnpm exec playwright test
```

Expected: both tests pass.

- [ ] **Step 4: Add frontend CI**

Add a `frontend-test` job using Node 22 and `pnpm/action-setup`, then run:

```bash
pnpm install --frozen-lockfile
pnpm generate:api
git diff --exit-code -- src/lib/api
pnpm typecheck
pnpm lint
pnpm test
pnpm build
pnpm exec playwright install --with-deps chromium
pnpm exec playwright test
```

Keep the existing extension and backend jobs unchanged except for shared contract path triggers.

- [ ] **Step 5: Run all local release gates**

Run:

```bash
cd backend
.venv/bin/python -m pytest -q \
  --ignore=test_dynamodb_storage.py \
  --ignore=test_preload_dynamodb_integration.py
scripts/check_admin_openapi.sh
cd ../frontend
pnpm typecheck
pnpm lint
pnpm test
pnpm build
pnpm exec playwright test
cd ../extension
node --test test/shared.test.mjs
```

Expected: every command exits `0`.

- [ ] **Step 6: Request Opus 4.8 implementation review**

Ask Opus 4.8 to review the complete backend/frontend branch diff against the approved design, focusing on authentication token handling, accidental hand-written API calls, partial-failure rendering, destructive controls, missing page states, test determinism, and release-gate coverage. Resolve blocking findings and rerun Step 5.

- [ ] **Step 7: Commit**

```bash
git add frontend .github/workflows/reading-assistant-ci.yml README.md docs/FRONTEND.md
git commit -m "Complete local admin site release gates"
```
