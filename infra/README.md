# Infrastructure

Terraform code is organized into reusable modules and environment root modules.

## Structure

```text
infra/
├── modules/
│   ├── frontend/
│   ├── backend/
│   ├── auth/
│   ├── reading-assistant-api/       # API Lambda + HTTP API + SQS + worker Lambda + IAM + logs
│   ├── reading-assistant-data/      # DynamoDB single table
│   ├── reading-assistant-config/    # SSM SecureString secrets (placeholders)
│   └── reading-assistant-alerting/  # SNS + AWS Budgets + invocation alarm
└── envs/
    ├── dev/
    │   └── reading-assistant/       # reading-assistant dev stack (own state)
    └── prod/
        └── reading-assistant/       # reading-assistant prod stack (own state)
```

`infra/envs/dev/` and `infra/envs/prod/` are the root modules of the main app
stack (frontend, backend, Cognito auth). The reading-assistant backend is a
separate stack with its own state file under
`infra/envs/<env>/reading-assistant/`, so the two stacks can be planned and
applied independently while still living in the same two environments.

## Environments

| Environment | Purpose |
| --- | --- |
| `dev` | Low-cost development and verification environment. |
| `prod` | Production environment. |

## Modules

| Module | Purpose |
| --- | --- |
| `frontend` | SPA hosting resources such as S3 and CloudFront. |
| `backend` | Backend API, data store, queue, worker, IAM, and observability resources. |
| `auth` | Cognito User Pool, Google federation, Hosted UI domain, and app client. |
| `reading-assistant-api` | Backend Lambda (arm64/python3.12 + Mangum), API Gateway HTTP API, async preload SQS queue + DLQ + worker Lambda, least-privilege IAM, CloudWatch log groups. |
| `reading-assistant-data` | On-demand DynamoDB single table (`pk`/`sk`) and the private, auto-expiring S3 bucket for transient preload content. |
| `reading-assistant-config` | SSM SecureString parameters for secrets, created with placeholders. |
| `reading-assistant-alerting` | SNS alert topic, monthly AWS cost budget, Lambda invocation-volume alarm. |

## Cognito Auth (main app stack)

Copy the example variables file before planning or applying an environment:

```sh
cp infra/envs/dev/terraform.tfvars.example infra/envs/dev/terraform.tfvars
```

Then set the real Google OAuth client ID and secret in `terraform.tfvars`. Do not commit real `*.tfvars` files.

After applying, use the Terraform outputs to configure the application:

- Frontend: `NEXT_PUBLIC_COGNITO_AUTHORITY`, `NEXT_PUBLIC_COGNITO_CLIENT_ID`
- Backend: `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`, `COGNITO_REGION`

---

# Reading Assistant (Untangle) backend

Serverless deployment of the FastAPI backend in
`tools/reading-assistant/backend/`, optimized for lowest possible cost in
`ap-northeast-1`.

## Architecture

```text
Chrome extension (Bearer token, chrome-extension:// origin;
release packaging replaces DEFAULT_API_BASE_URL in extension/settings.js
with the deployed API URL — end users never configure it. Developers can
override per-profile via chrome.storage.local `apiBaseUrl`, no UI)
        |
        v
API Gateway HTTP API ($default route, pass-through, stage throttling)
        |                      Stripe webhooks also arrive here
        v                      (POST /billing/webhook, verified in-app)
Lambda  english-<env>-reading-assistant-api
  (arm64, python3.12, Mangum-wrapped FastAPI)
        |                |               |                     |
        |                v               v                     v
        |          DynamoDB          OpenAI API           Stripe API
        |          english-<env>-    (OPENAI_API_KEY     (STRIPE_SECRET_KEY
        |          reading-assistant  from SSM)           from SSM)
        |
        |  POST /pages/preload extracts text, writes it to the preload-content
        |  S3 bucket (transient handoff, PutObject), then enqueues a job
        |  (returns 202).
        |
        |        +--------------------------------------------------+
        |        |  S3  english-<env>-reading-assistant-             |
        |        |      preload-content-<account-id>                |
        |        |  Raw extracted article text, one object per       |
        |        |  (user, URL). Private, SSE-S3, 1-day lifecycle    |
        |        |  expiry. The worker GetObject + DeleteObject.     |
        |        +--------------------------------------------------+
        v
SQS  english-<env>-reading-assistant-preload-jobs   --(3 failures)--> DLQ
        |
        v
Lambda  english-<env>-reading-assistant-worker
  (arm64, python3.12, worker_handler.handler; batch_size 1; 600s+ timeout)
  reads the raw text from the preload-content bucket, runs split + analyze
  off the request path (no 30s cap), writes the ready record to DynamoDB,
  meters usage, and deletes the S3 payload. The client polls
  GET /pages/preload.

Observability / blast-radius capping:
  CloudWatch Logs (14d dev / 30d prod)
  CloudWatch alarm: Lambda invocations per hour  --> SNS --> email
  AWS Budgets: monthly cost budget (50/80/100%)  ------------^
```

Design decisions:

- **No Cognito.** Authentication is app-managed: the extension obtains a
  Google ID token and the backend verifies it directly
  (`AUTH_PROVIDER=google` + `GOOGLE_OAUTH_CLIENT_ID`). Cognito would add an
  extra hosted-UI hop and cost without adding value for this flow. This can
  be revisited if requirements grow (e.g. more IdPs, token refresh at the
  edge).
- **No CORS on API Gateway.** The FastAPI app already handles CORS
  (`ALLOWED_ORIGINS` plus a `chrome-extension://` origin regex). API Gateway
  is a pure pass-through so the two layers cannot disagree.
- **Secrets via SSM -> Lambda environment.** Terraform reads the
  SecureString parameters at apply time and injects them as Lambda
  environment variables (the app reads plain env vars today). Trade-off:
  anyone with `lambda:GetFunctionConfiguration` can see the values. That is
  acceptable at this project size and avoids per-invocation SSM calls or an
  extension layer; revisit if the team or account grows. After rotating a
  parameter, re-run `terraform apply` to roll the new value out.
- **30-second response cap (resolved for preloads).** API Gateway HTTP APIs
  cap the integration wait at 30 s regardless of the Lambda timeout. The
  preload path — the one long-running operation (15-70 s, see
  docs/PERFORMANCE.md) — no longer runs on the request path: `POST
  /pages/preload` only extracts text and enqueues an SQS job (returns 202),
  and the worker Lambda (timeout 600 s dev / 900 s prod) runs the analysis
  asynchronously. The client polls `GET /pages/preload` until the record is
  ready. All remaining synchronous endpoints (`/analyze`, `/chat`) are a
  single LLM call and comfortably fit inside 30 s.
- **Preload content kept out of DynamoDB.** The raw extracted article text
  (~50 KB) is a one-time submit -> worker handoff, not durable data: only the
  worker reads it, exactly once, and the `/analyze` and `/chat` paths never
  touch it. Storing it on the DynamoDB preload record would leave it there
  forever and, combined with the sentences + analysis, push the item toward
  the 400 KB limit. So the API writes it to a dedicated, private S3 bucket
  (`preload-content`) and the worker deletes it after consuming it. A 1-day
  lifecycle rule expires any straggler, so orphaned payloads self-clean. The
  app selects this store via `PRELOAD_CONTENT_BUCKET` (set by the api module);
  local development leaves it unset and uses a filesystem store instead.

## Bootstrap (one-time)

Terraform state lives in the shared S3 bucket `TODO-REPLACE-TF-STATE-BUCKET`
with stack-scoped keys (`02_english/reading-assistant/<env>/terraform.tfstate`)
and S3-native lock files (`use_lockfile = true`). No DynamoDB lock table is
used or needed.

If the bucket does not exist yet in the target account, create it once from
the CLI (never with local Terraform state):

```sh
aws s3api create-bucket \
  --bucket TODO-REPLACE-TF-STATE-BUCKET \
  --region ap-northeast-1 \
  --create-bucket-configuration LocationConstraint=ap-northeast-1

aws s3api put-bucket-versioning \
  --bucket TODO-REPLACE-TF-STATE-BUCKET \
  --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption \
  --bucket TODO-REPLACE-TF-STATE-BUCKET \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms"}}]}'

aws s3api put-public-access-block \
  --bucket TODO-REPLACE-TF-STATE-BUCKET \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```

## Secrets

Terraform creates the SSM parameters with the placeholder value
`REPLACE_ME` and ignores value changes afterwards. Populate the real values
out-of-band (they never appear in Terraform code or plans):

```sh
ENV=dev  # or prod
aws ssm put-parameter --overwrite --type SecureString \
  --name "/english/${ENV}/reading-assistant/OPENAI_API_KEY" --value "sk-..."
aws ssm put-parameter --overwrite --type SecureString \
  --name "/english/${ENV}/reading-assistant/STRIPE_SECRET_KEY" --value "sk_live_..."
aws ssm put-parameter --overwrite --type SecureString \
  --name "/english/${ENV}/reading-assistant/STRIPE_WEBHOOK_SECRET" --value "whsec_..."
```

Then run `terraform apply` so the Lambda environment picks up the values
(secret values are read from SSM at apply time). Note: they do end up in the
Terraform state file, which is why the state bucket is encrypted and private.

## Build and deploy runbook

```sh
# 1. Build the Lambda artifact (outside Terraform).
tools/reading-assistant/backend/scripts/build_lambda.sh
# -> tools/reading-assistant/backend/dist/reading-assistant-lambda.zip

# 2. First-time setup for an environment.
cd infra/envs/dev/reading-assistant
cp terraform.tfvars.example terraform.tfvars   # fill in real values
terraform init

# 3. Deploy.
terraform plan
terraform apply

# 4. Populate secrets (first deploy only, see "Secrets" above), then
#    re-apply so the Lambda environment gets the real values.
terraform apply

# 5. Set API_BASE_URL now that the endpoint exists (Stripe redirect URLs),
#    then re-apply.
terraform output api_endpoint
#    -> put it into app_extra_environment.API_BASE_URL in terraform.tfvars
terraform apply

# 6. Configure the Stripe webhook endpoint in the Stripe dashboard:
#    <api_endpoint>/billing/webhook
```

Redeploying app code = re-run `build_lambda.sh`, then `terraform apply`
(the zip hash change triggers a function update). Both the API and the
worker Lambda share the one zip, so a single `build_lambda.sh` +
`terraform apply` updates them together. Confirm the SNS email
subscription from your inbox after the first apply, or alarms will not
reach you.

### Async preload pipeline (SQS + worker)

`POST /pages/preload` enqueues a job on
`english-<env>-reading-assistant-preload-jobs`; the worker Lambda
(`worker_handler.handler`) consumes it and runs the analysis. To operate:

- **Watch a job.** Worker logs:
  `aws logs tail /aws/lambda/english-<env>-reading-assistant-worker --follow`.
  Each record logs `preload job url=... total=...s` on success or
  `preload job failed ...` (recorded on the record as `status: "failed"`).
- **Stuck / failing jobs.** After 3 delivery failures a message lands in the
  DLQ `...-preload-jobs-dlq` (14-day retention). Inspect it there; a
  successfully-processed *analysis* failure (bad HTML, OpenAI error) is NOT
  redelivered — it is recorded as `failed` and the client resubmits.
- **Tuning.** Worker timeout/memory are `worker_lambda_timeout` /
  `worker_lambda_memory_size` (dev 600 s/512 MB, prod 900 s/1024 MB). The SQS
  visibility timeout is derived as 6x the worker timeout; keep that invariant
  if you change the timeout.

## Security and abuse resistance

The main abuse scenario is OpenAI token burn: an attacker hammering the
AI-calling endpoints to run up the OpenAI bill. Defenses are layered,
cheapest first:

1. **API Gateway stage throttling** (infra): rate 10 rps / burst 20 in dev,
   rate 25 / burst 50 in prod (tfvars-tunable). Caps raw request volume
   before it reaches Lambda. Lambda reserved concurrency (5 dev / 20 prod)
   additionally caps parallel executions.
2. **App-layer authentication** (app): every AI-calling route requires an
   authenticated session (Google ID-token sign-in). Unauthenticated
   requests never reach OpenAI.
3. **App-layer quotas** (app): per-user monthly limits on articles, chats,
   sentences per article, and a hidden token budget per plan
   (`core/plans.py`, overridable via `PLAN_*` env vars). A single stolen
   token cannot burn more than one user's quota.
4. **Blast-radius alarms** (infra): a monthly AWS cost budget
   (notifications at 50/80/100%, account-wide by design so nothing escapes
   it) and a CloudWatch alarm on Lambda invocations per hour, both mailed
   via SNS. Important: AWS Budgets cannot see OpenAI spend — set a spend
   limit on the OpenAI platform as well; the in-app token quotas are the
   primary cap on that side.
5. **Prod guardrails** (infra): Terraform variable validation rejects
   `auth_provider != "google"` or `billing_provider != "stripe"` when the
   environment is `prod`, so the mock providers (auth bypass + free paid
   plans) can never run in production. The prod root module additionally
   hardcodes both values.

**Deliberately not used: CloudFront + WAF.** WAF web ACLs start around
$5-10/month plus per-request fees — more than this entire stack at PoC
traffic — and API Gateway throttling plus app auth/quotas already bound the
damage. If real abuse materializes (throttle alarms firing, budget
notifications), the documented upgrade path is CloudFront in front of the
API with AWS WAF rate-based rules and IP reputation lists.

Infra's job here is rate limiting and blast-radius capping; authentication
and per-user quotas are the app's job.

## Cost notes (PoC traffic, ap-northeast-1)

| Component | Pricing model | Expected monthly cost |
| --- | --- | --- |
| Lambda (arm64, 512 MB) | $0.20/M requests + GB-s; large free tier | ~$0 |
| API Gateway HTTP API | ~$1.29/M requests | ~$0 |
| DynamoDB on-demand | Per request + storage; free tier 25 GB | ~$0 (prod PITR adds per-GB backup cost, cents at this size) |
| S3 preload-content | Per request + storage; objects expire after 1 day | ~$0 (each payload is ~50 KB and lives for seconds to minutes) |
| CloudWatch Logs | $0.76/GB ingested; 14/30-day retention | <$1 |
| CloudWatch alarm | First 10 alarms free | $0 |
| SNS email | Free tier covers it | $0 |
| AWS Budgets | Notification-only budgets are free | $0 |
| SSM Parameter Store | Standard tier is free | $0 |
| **Total** | | **~$0-5/month** |

The dominant real cost is the OpenAI bill, which is external to AWS —
manage it with the in-app quotas and an OpenAI platform spend limit.
