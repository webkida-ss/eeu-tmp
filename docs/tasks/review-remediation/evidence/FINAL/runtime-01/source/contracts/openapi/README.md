# Canonical API contract workflow

`openapi.yaml` and its referenced YAML files are the source of truth. Do not
regenerate them from FastAPI. The checked-in runtime export under
`migration-evidence/` records the one-time 15-path, 17-operation, 26-schema
bootstrap required by ADR 0002; it is not generator input.

For an API change:

1. Edit the canonical path and schema YAML first, including security, complete
   statuses/media types, sanitized examples, and `x-contract-test` ownership.
2. Run `task schema:validate` and `task schema:compatibility`.
3. Run `task schema:generate`. Never hand-edit files under
   `extension/generated/` or `backend/generated/`.
4. Update the temporary FastAPI adapter and its local-only tests.
5. Run `task schema:check` and `task test:api:contract`.

Generic cases must be deterministic and safe with local repositories. Identity,
model, asynchronous preload, billing-provider, and webhook exchanges remain
manually owned and must use local fakes. Contract tests must never contact
Google, OpenAI, Stripe, AWS, or any other live service.

Named response `examples` and singular response `example` values are generated.
Safe success cases are invoked locally; documented generic error examples are
validated for request pairing, status, media type, and schema without inventing
an unsafe runtime trigger. Manual provider cases remain explicit references.

Compatibility exceptions are permitted only in
`compatibility-exceptions.yaml`. They require an exact eligible finding,
owner, approval, expiry, consumer rollout, monitoring, and rollback details.
Expired, broad, ownerless, or unknown entries fail closed.

Compatibility waivers identify one normalized oasdiff finding with a
`sha256:<64 lowercase hex>` fingerprint. The fingerprint covers category,
operation, path, section, message, severity, and source line/column while
excluding machine-specific file paths. A category or operation name alone
cannot waive multiple findings. Each entry must also repeat the finding's
reviewable `operationId` and exact changed `property`/location; both are checked
against the fingerprinted finding. Unused entries fail in comparison and
first-schema bootstrap modes.

Compatibility resolves `origin/main`, then local `main`, by default. Set
`SCHEMA_BASE_REF` to the exact fetched or local base ref when the repository
uses another branch. The command fails with fetch guidance when that ref or a
merge base is unavailable; shallow history and stale feature branches cannot
re-enter first-contract bootstrap mode.

An all-zero GitHub push baseline always fails closed; repository-history
inference is never used to reopen bootstrap. Establish the remote/default
branch before enabling the schema compatibility required check, then introduce
the canonical schema through a pull request with a non-zero trusted base SHA.
Alternatively, manually dispatch the CI workflow with a maintainer-approved
non-zero `trusted_base_sha`. Normal pull requests and pushes with a known
non-zero `before` SHA still support first-schema bootstrap when that trusted
base genuinely lacks the contract.

Schema checks write deterministic, path-sanitized reports to ignored
`output/schema/`. `oasdiff.json` preserves the raw tool output;
`oasdiff-normalized.json` contains path-sanitized fingerprints and waiver
metadata. Route-security reports list applied security exception IDs. CI
uploads these reports for 14 days, including reports produced before a failed
gate.
