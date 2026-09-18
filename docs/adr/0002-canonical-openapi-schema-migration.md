# ADR 0002: Canonical OpenAPI Schema Migration

Status: Accepted

## Context

The repository requires a single schema to be the source of truth and requires
contract artifacts to be generated where practical
(`.cursor/rules/basic-strategy.mdc`). API documentation belongs in OpenAPI,
with an entry document, split path files, split reusable schemas, and realistic
Prism examples (`.cursor/rules/api.mdc`). Architectural decisions belong in
`docs/adr/` (`.cursor/rules/documentation.mdc`), and domain entity identifiers
default to opaque UUID v7 values named `id`
(`.cursor/rules/data-model.mdc`).

The implementation predates those rules. `backend/main.py` contains
hand-written FastAPI route adapters, while `backend/schemas.py` and
`backend/models/user.py` contain hand-written Pydantic transport models.
Importing `backend/main.py` and evaluating `app.openapi()` currently produces
OpenAPI 3.1.0 with 15 paths, 17 operations, and 26 component schemas. This is
useful evidence of the deployed adapter, but it is code-first output and cannot
be the canonical contract.

The current extension is vanilla JavaScript. `extension/background.js` embeds
API path and method strings and directly reads response objects. It consumes 11
of the 17 operations: auth configuration, login, logout, preload read and
submit, vocabulary, analyze, chat, billing summary, checkout, and portal.
There is no TypeScript compiler or frontend build step that could make a
generated TypeScript-only client useful.

The runtime export also omits important behavior that is enforced outside
Pydantic:

- It declares no security schemes, although most routes require a bearer
  session through `get_current_user`.
- `POST /billing/webhook` reads raw request bytes and verifies
  `Stripe-Signature` in the billing provider, but neither input appears in the
  runtime document.
- `GET /billing/done` returns `text/html`, not JSON.
- Application and entitlement handlers return JSON errors with `detail` and,
  for quota errors, `code`; these responses are not fully described by the
  runtime export.
- Existing persisted and nested IDs are strings. New operation IDs are UUID
  v7, but some user, preload, phrase, sentence, and study-item creation paths
  still use UUID v4. Existing records and fixtures therefore cannot honestly
  be described as UUID v7-only yet.

`docs/TEST_AUTOMATION_PLAN.md` permits `app.openapi()` only as migration
evidence and requires this decision before generated contract tests are added.

## Decision

### Canonical contract and organization

The canonical contract will be OpenAPI 3.1 YAML rooted at:

```text
contracts/openapi/
├── openapi.yaml
├── components/
│   └── schemas/
│       └── *.yaml
└── paths/
    └── *.yaml
```

`contracts/openapi/openapi.yaml` and every referenced YAML file are the only
source of truth for HTTP paths, methods, parameters, media types, security,
request bodies, responses, and transport schemas. Path files will be split by
cohesive resource, and schemas will be split by clear domain concept as
required by `.cursor/rules/api.mdc`. Generated bundles and FastAPI's runtime
document are not authoritative.

The API contract is jointly owned by the backend and extension maintainers.
The author of a behavioral API change owns the canonical schema change,
examples, generated artifacts, compatibility result, adapter change, and
consumer tests in the same pull request. Review requires one maintainer able to
assess the provider/security boundary when auth, billing, webhook, or sensitive
content changes.

### One-time bootstrap

Migration will start with a one-time, deterministic export of the current
`app.openapi()` into a temporary build location. The export will run with local
mock identity, billing, model, and JSON storage configuration and must not start
a server, call Stripe, call Google, call a model provider, or read production
data. The export records the observed 15-path, 17-operation, 26-schema baseline.

That JSON is migration evidence only. Maintainers will review it against
`backend/main.py`, `backend/schemas.py`, `backend/models/user.py`,
`extension/background.js`, and existing TestClient tests; add missing security,
error, raw-body, HTML, status, and example semantics; then split the reviewed
contract into the canonical YAML layout. The temporary export will not be
checked in as a generator input. Once the canonical YAML is reviewed and
checked in, bootstrap export is removed from the normal workflow and
`app.openapi()` is used only as adapter-drift evidence.

### Required generated and derived artifacts

The first schema implementation after this ADR must create all of the
following:

1. A deterministic JSON bundle produced from
   `contracts/openapi/openapi.yaml`. Redocly CLI will lint and resolve the
   multi-file OpenAPI 3.1 document. The bundle is an ephemeral build artifact
   used by generators and checks, not a second source of truth.
2. `extension/generated/api-contract.js`, generated from that bundle. It will
   install a deeply frozen, non-writable `globalThis.UntangleApiContract`
   namespace for classic scripts. Its operation map is keyed by the canonical
   `operationId` and contains only the 11 operations consumed by the extension,
   with paths, HTTP methods, declared query-parameter serialization metadata,
   every declared response status and its media types, and a separate set of
   declared success statuses. Generated object maps use null prototypes and
   all reachable generated values are frozen. The generated file
   also publishes a frozen operation-field list derived from the emitted
   records themselves. The classic runtime declares its exact consumed field
   set, rejects any field-set mismatch at load, and the schema consumer check
   dynamically exercises every declared field through the runtime.
   Response media enforcement uses a strict single-value `Content-Type`
   parser, API errors expose only allowlisted localized machine codes, and
   idempotent retries are limited to explicitly classified fetch failures or
   declared retryable server responses whose prior bodies are released.
   Contract trust decisions use initialization-time captured intrinsics so
   later mutation of built-in globals or prototypes cannot change validation.
   The service-worker message boundary owns public API error sanitization:
   quota codes may select their localized allowlisted messages, contract
   failures use a localized contract message, and every other API failure uses
   one localized generic message while safe diagnostics remain internal.
   The generated file
   is loaded with `importScripts` before a small hand-written classic contract
   runtime and `background.js` API calls. An ESM export is not used because the
   existing MV3 service worker is classic and already composes its scripts with
   `importScripts`; converting the complete extension script graph to modules
   is outside this schema-consumer migration.
   `extension/background.js` must consume these operation symbols instead of
   duplicating endpoint and method literals. Its response handling must look up
   the actual status in the generated response map, require the actual
   `Content-Type` to match a media type declared for that status, and then use
   the generated success-status set to choose success parsing. A declared error
   status follows the extension's normal API-error parsing path. An undeclared
   status, a missing content type, or a media type not declared for that status
   fails closed. All generated response and success fields must be consumed and
   verified; none may be decorative. This is more useful to the current vanilla
   JavaScript extension than an unconsumed TypeScript client. Existing
   hand-written orchestration remains responsible for Chrome storage, bearer
   token retrieval, retries, idempotency, polling, and localized errors.
3. `backend/generated/openapi-contract-cases.json`, generated from that bundle.
   In stable `operationId` and example-name order, it will enumerate every
   canonical operation and every named request and response example that can be
   exercised generically. Each case records `operationId`, method, expanded
   example path and parameters, request media type and body, expected response
   status and media type, response example, and required local auth fixture.
   Operations without a request body still receive a case for each response
   example. The generator fails if an operation or JSON example has no case
   unless it names a permitted manual exception.
4. A hand-written generic pytest harness parameterized only by
   `backend/generated/openapi-contract-cases.json`. First it uses
   `openapi-core` to validate every generated request and expected response
   against the canonical bundle. Where a case is safe to invoke, it sends the
   request through TestClient with local dependency overrides and validates the
   actual response against the same operation. This provides deterministic
   schema-derived tests without generating a second test implementation per
   endpoint.
5. Manually authored exception tests for behavior that examples alone cannot
   safely or accurately drive. These cover missing, malformed, and expired
   bearer sessions; mock identity-provider login success and failure; checkout
   and portal behavior with the mock billing provider; webhook verification
   over exact synthetic raw bytes with missing, invalid, and valid local
   signatures; and analyze, chat, and preload behavior with fake model, storage,
   and job-runner dependencies. Each manual case must name its canonical
   `operationId` and pass its request and actual response through
   `openapi-core`. No exception may call Stripe, Google, a model provider, or
   another live service.
6. A deterministic adapter-surface check comparing normalized
   `app.openapi()` evidence with the canonical bundle for operations, explicit
   `operationId` values, parameters, request/response media types, status codes,
   and schema shapes. Canonical-only documentation, examples, and known FastAPI
   representation differences will be handled by a small, reviewed
   normalization allowlist. OpenAPI security fields are excluded from this
   normalized runtime comparison because the current FastAPI dependency graph
   does not emit them. They are verified by the separate fail-closed route
   security check below. The normalization allowlist cannot suppress an entire
   operation, `operationId`, or schema and must explain every exception.
7. Prism-compatible examples in the canonical source. Each JSON request,
   success response, and documented error response must have a deterministic,
   non-secret example suitable for local mock flows. Asynchronous preload
   examples must cover processing, ready, and failed states.

Canonical operations and examples control test generation with the following
vendor extensions:

- Every operation has `x-contract-test` with `mode` (`generic` or `manual`),
  `owner`, `auth`, and `setup`. `auth` names an anonymous or local bearer
  fixture; `setup` names a deterministic repository/dependency fixture or
  `none`.
- Every named request and response example used by a generic test has the same
  stable `x-contract-test-case` value. The generator pairs only matching case
  values within one `operationId`; it never guesses pairings by list position
  or example name similarity.
- A manual operation additionally supplies `reason` and `test`, where `test`
  is the checked-in test path owned by `owner`. Its examples remain subject to
  schema validation, but the generator emits a manual-case reference instead
  of an executable generic request.

The identity-provider login, page-preload submission, analyze, chat, billing
checkout, billing portal, and billing webhook operations are `mode: manual`.
They cross a provider, execute asynchronous work, or depend on exact signed
bytes and are never generic, even when local fakes make their manual tests safe.
The generator rejects provider/webhook operations marked `generic`, an unknown
fixture name, an unowned manual case, duplicate case IDs, or an unpaired
generic request/response example.

For every invoked generic or manual exchange, the harness must assert the
actual status code equals the case's declared status and the parsed
`Content-Type` media type equals the declared response media type before schema
validation. An unexpected success status, an undeclared error status, a missing
content type, or a wrong media type fails even if the body happens to validate.

Redocly CLI and Prism CLI will be pinned through the repository's Node lock
process when this decision is implemented. `openapi-core` will be added to
`backend/requirements-dev.in` and pinned with the existing
`task deps:backend:lock` hash-locked process. `oasdiff` will be installed as an
exact-version release binary by a repository installer. The version and
SHA-256 for each supported OS/architecture will be checked in under
`scripts/tool-locks/oasdiff/`; the installer will download only that release
through the existing bootstrap path, verify the matching checksum before
execution, and install it under the repository-managed `.tools` directory.
Local and CI checks use that installer. Floating tags, `latest`, an unverified
binary, and an independently installed PATH version are forbidden. `oasdiff`
will compare the pull request contract with the merge-base contract and fail on
unapproved breaking changes. These tools are selected for focused lint/bundle,
mock, validation, and compatibility roles. Java and OpenAPI Generator are not
introduced.

Generated Pydantic server models and a generated FastAPI server are deferred.
The current models include custom UUID v7 validation/default generation,
inheritance, constrained fields, compatibility defaults, and service-facing
construction behavior. Replacing all of that in one migration would combine a
contract move with a risky runtime rewrite. A large generated server would also
duplicate the existing thin adapter and dependency-injection wiring without
improving the vanilla JavaScript consumer.

### Temporary hand-written backend adapter

`backend/main.py`, `backend/schemas.py`, and `backend/models/user.py` remain
temporarily. They are compatibility adapters, not contract owners. New HTTP
behavior must be designed in canonical YAML first; hand-written route or model
changes without the preceding schema change are prohibited. The adapter-surface
check and TestClient validation block drift in both directions:

- a code-only route, `operationId`, field, status, or media-type change fails;
- a canonical operation not implemented by FastAPI fails;
- an implementation response that violates the canonical schema fails; and
- a generated extension or contract-case artifact that is stale fails the
  regeneration check.

The hand-written transport definitions may be replaced incrementally only when
a generated model or route interface can be consumed without moving business
logic into generated code. Exit criteria are:

1. every canonical JSON operation has contract validation for representative
   success and error exchanges;
2. all custom defaults and validators have an explicit generated extension
   point or a documented application-layer location;
3. generated transport models can be imported by FastAPI and the worker/Lambda
   adapters without changing service semantics;
4. mixed legacy ID data has been migrated or deliberately versioned;
5. generated output is deterministic and reviewable; and
6. the replacement passes the full backend, Lambda package, extension, Prism,
   drift, and compatibility checks.

Until all criteria are met, claiming a fully generated FastAPI server would be
incorrect.

### Contract content

The canonical contract will preserve all current paths during bootstrap and
make implicit behavior explicit:

- every operation has a unique, explicit, stable `operationId`;
- bearer authentication is declared once and applied to protected operations;
- `/health`, `/auth/config`, `/auth/login`, `/billing/done`, and the billing
  webhook have explicit operation-level security appropriate to their actual
  behavior;
- the webhook declares the `Stripe-Signature` header and raw JSON body, and its
  tests use only synthetic signed fixtures with a mock/local provider;
- the webhook declares `x-max-body-bytes: 262144` and an explicit JSON `413`
  response;
- the HTML landing response declares `text/html`;
- every JSON operation declares explicit request, success, and error schemas;
- common errors describe the existing `detail` field and optional stable
  `code`, including examples for validation, authentication, authorization,
  conflict/idempotency, quota, and server failures where applicable; and
- examples contain fake tokens, fake provider IDs, and public sample article
  text only.

There are currently no file-upload or binary-download operations. Any future
binary operation must declare its exact media type and limits and must not be
fed through a JSON-only generator. The webhook remains security-sensitive even
though its payload is JSON because signature verification depends on the exact
raw bytes. The adapter must reject a declared `Content-Length` over 262,144
bytes before reading and, because that header can be absent or false, consume
the ASGI request stream while counting bytes and stop with `413` as soon as the
limit is exceeded. It may retain at most the bounded bytes needed for signature
verification. ASGI servers or gateways may enforce a lower/equivalent limit,
but their configuration cannot replace the application-side stream count.

Webhook cases are always manual. Tests cover the exact limit, one byte over,
oversized `Content-Length`, absent or misleading `Content-Length`, and the
canonical `413` status/media/error body. Missing, invalid, and valid signature
tests sign and submit the same synthetic byte sequence. The harness and adapter
must not parse and reserialize JSON before signature verification. Contract
tests must never replay a real event or contact Stripe. Auth tests likewise use
mock credentials and never contact Google.

### Operation identifiers

Every canonical operation must declare `operationId` explicitly. Bootstrap
identifiers synthesized by FastAPI are evidence only and are not adopted
without review. Canonical identifiers use lower camel case and match
`^[a-z][A-Za-z0-9]*$`, with a semantic
`<action><Resource><OptionalQualifier>` form such as `getAuthConfig`,
`createPagePreload`, or `openBillingPortal`. They describe the stable API
operation rather than a Python function name or generated path spelling.

An `operationId` is a public compatibility identifier. It is the exact property
name in the generated classic global operation map, the key in generated
contract cases, and the identifier reported by contract-test failures. It does
not change when a handler is renamed, code is moved, or documentation wording
changes. Reusing an identifier for another method or meaning is prohibited.
Renaming or removing one is a breaking contract change and follows the same
versioning, deprecation, exception, and rollback process as removing an
endpoint.

Lint and generation fail on a missing, duplicate, or invalid identifier. The
adapter-surface check requires FastAPI's runtime evidence to expose the same
identifier for the same method and path. Compatibility CI compares the
merge-base and proposed canonical maps in both directions: an existing
`operationId` must retain its method, path, and semantic operation unless an
approved breaking change applies, and an existing method/path must retain its
`operationId`. `oasdiff` remains the general compatibility check; this explicit
map check covers identifier stability even if a diff tool does not classify a
rename as breaking.

### Fail-closed compatibility

Compatibility checks fail closed. A tool error, unreadable schema, unresolved
reference, missing merge base, missing expected base contract, failed bundle,
or unavailable pinned tool is a failure, not a warning or skipped success.

The first canonical-schema pull request is the only special case. If a trusted,
non-zero pull-request base SHA or push `before` SHA has no
`contracts/openapi/openapi.yaml`, the check enters explicit bootstrap mode,
requires this ADR plus the reviewed `app.openapi()` evidence, and runs canonical
lint, generation, operation-map, adapter-surface, example, and contract tests.
It reports that no canonical-to-canonical compatibility comparison exists.
After canonical YAML is established, a missing or invalid base bundle is always
an error; bootstrap mode cannot be selected again by deleting or moving the base
schema.

An all-zero push baseline always fails closed without repository-history
inference. Establish the remote/default branch first without enabling the
schema compatibility required check, then introduce the canonical schema
through a pull request with a non-zero trusted base SHA. When that is impossible,
a maintainer may use the manually dispatched workflow with an explicitly
approved non-zero prior commit SHA. An all-zero value is never accepted by that
manual path.

Approved compatibility and normalization exceptions are checked in at
`contracts/openapi/compatibility-exceptions.yaml`. Each entry has a unique ID,
owner, reason, exact operation and changed property, a fingerprint of the full
normalized finding, approval reference, and ISO expiry date. Unknown, broad,
ownerless, expired, mismatched, or unused entries fail CI.
Pull-request text, command-line flags, and inline code comments cannot waive a
finding.

Normalization is deliberately narrow: it may remove ordering, descriptions,
examples, documented reference-path spelling differences, and OpenAPI security
fields from the `app.openapi()`-to-canonical comparison only.
Normalization and exceptions may not erase or coalesce paths, methods,
`operationId` values, parameters, request bodies, response status codes,
response media types, error response schemas, requiredness, enum values, or
validation constraints. The normalized comparison therefore continues to
detect status, media-type, and error-contract drift.

Security is checked separately and fail closed. The checked-in
`contracts/openapi/route-security.yaml` map enumerates every canonical
`operationId` and either:

- maps `bearerAuth` to the required transitive FastAPI dependency
  `deps.get_current_user`;
- maps another canonical security scheme to its concrete verifier and manual
  test, including `stripeSignature` for the billing webhook; or
- marks an operation as intentionally public with an owner and reason matching
  the canonical operation-level security declaration.

The checker walks each FastAPI route's dependency graph recursively, associates
it by explicit `operationId`, and requires the mapped auth dependency for every
protected operation. It also rejects an unexpected auth dependency on a public
operation, an unmapped operation, a canonical/route security mismatch, a
missing verifier test, or a duplicate mapping. Runtime OpenAPI normalization,
the general normalization allowlist, and ordinary compatibility exceptions
cannot waive this gate. The only permitted waiver is an exact
`kind: security` entry in
`contracts/openapi/compatibility-exceptions.yaml` naming the operation and
security property, with owner, reason, approval reference, and unexpired ISO
expiry date; expired or broad security waivers fail CI.

The raw `oasdiff` report, normalization report, applied exception IDs, strict
operation-map result, and route-security result are retained as CI artifacts.

### Identifiers

New domain entity and persisted model IDs will be UUID v7, named `id`, treated
as opaque, and kept consistent across the schema, adapter, extension, mocks,
fixtures, and tests. Request idempotency `operation_id` remains UUID v7.
Provider-owned identifiers such as Stripe IDs are external strings and are not
renamed or rewritten as domain IDs.

The initial canonical contract must not falsely reject existing UUID v4 or
historical nested IDs. During transition, affected response fields use
`format: uuid` where all stored values are UUIDs and otherwise retain a
documented opaque-string compatibility schema. Examples use UUID v7.
Implementation work must stop creating new UUID v4 domain IDs and inventory
legacy user, preload, phrase, sentence, and study-item data. Once stored data
and fixtures are migrated, the canonical schemas will tighten those fields to
UUID v7 using a shared schema with an RFC 9562-compatible version constraint.
That tightening is a reviewed compatibility change, not an undocumented
generator side effect.

### Change and compatibility workflow

An API change follows this order:

1. edit canonical YAML, including examples, security, and errors;
2. lint and bundle it;
3. check `operationId` syntax, uniqueness, and merge-base stability;
4. run `oasdiff` against the merge-base canonical bundle;
5. regenerate the extension contract module and parameterized contract cases,
   and fail if regeneration leaves a diff;
6. update the FastAPI compatibility adapter and application behavior;
7. run canonical-schema TestClient validation and the adapter-surface check;
8. run extension unit tests against Prism examples and backend tests against
   local mocks; and
9. review the contract and implementation together.

Additive optional fields and new operations may remain in the current unversioned
API. Existing clients must ignore unknown response fields, and servers must not
make a formerly optional request field required without a version boundary.
Breaking changes require a new path major version such as `/v2`, or a new
versioned media type when path versioning is unsuitable, plus an overlap and
deprecation period. An eligible compatibility finding can be waived only by an
explicit entry in `contracts/openapi/compatibility-exceptions.yaml` that names
the operation and property and includes owner, reason, approval reference,
affected consumers, rollout, monitoring, rollback, and unexpired ISO expiry
date. Pull-request prose does not grant an exception.

### Generated-file policy

Canonical YAML, `extension/generated/api-contract.js`, and
`backend/generated/openapi-contract-cases.json` are committed. Generated files
carry a generated-file header or metadata marker and must never be hand-edited.
Temporary bundles, bootstrap exports, Prism state, and test reports are ignored
build artifacts. Generation is stable across machines: paths, `operationId`
values, and example names are sorted, output has fixed formatting and line
endings, timestamps and machine paths are forbidden, and running the generator
twice must produce no diff.

Implementation will expose these repository commands:

- `task api:generate` lints and bundles the canonical schema, checks
  `operationId` rules, and writes both committed generated files;
- `task api:check` performs lint/bundle and compatibility checks, generates both
  files into a temporary directory, byte-compares them with the committed
  files, runs the canonical-to-route dependency security check, verifies
  extension call sites consume the generated path, method, complete
  response-status/media map, and separate success-status set, and fails on any
  difference or unused exposed field; and
- `task test:api:contract` runs generated parameterized validation plus the
  manually authored security/provider exception cases.

CI runs `task api:check` and `task test:api:contract`. A pull request is not
allowed to rely on CI-generated modifications: after `task api:generate`,
`git diff --exit-code -- extension/generated/api-contract.js
backend/generated/openapi-contract-cases.json` must succeed. This no-diff rule
also runs after a second generation to detect nondeterminism.

CI will run schema lint/bundle, breaking-change analysis, deterministic
regeneration, adapter-surface drift, route-dependency security, canonical
request/response validation, Prism mock tests, existing backend tests, Lambda
packaging checks, and extension tests. Extension behavior tests inject an
unexpected `2xx`, a declared non-2xx
error, an undeclared non-2xx error, a missing `Content-Type`, and a media type
incompatible with the actual status. They prove that declared errors use normal
API-error parsing while undeclared statuses and media types fail closed, and
that the generated success set controls success parsing. Contract checks run
when canonical files, backend adapters, generated extension files, generation
scripts, consumers, or dependency locks change.

### Transition sequence

1. Capture and review the one-time runtime evidence.
2. Pin Redocly, Prism, and `openapi-core` through their existing lock processes,
   and pin the checksum-verified `oasdiff` release binary before using any tool
   output as a gate.
3. Add and lint the canonical split OpenAPI 3.1 YAML with all 15 existing paths
   and corrected security, webhook size and `413`, HTML, error,
   `x-contract-test`, `operationId`, and example details.
4. Generate the extension operation map and parameterized backend contract
   cases, and prove deterministic no-diff regeneration.
5. Update compatibility adapters and add generated/manual contract tests,
   strict drift checks, and local-only provider fixtures.
6. Change extension consumers to use generated paths, methods, complete
   response-status/media maps, and separate success sets through the classic
   immutable global and contract runtime, then run their declared-error and
   fail-closed enforcement tests.
7. Make the complete schema, compatibility, generation, backend, extension, and
   package checks required in CI; only then stop accepting code-first API
   changes.
8. Replace hand-written transport definitions incrementally after the exit
   criteria are met.
9. Remove migration normalization exceptions as each discrepancy is resolved.

### Exceptions

The following are deliberate exceptions to immediate full generation:

- Chrome extension orchestration remains hand-written because it integrates
  Chrome APIs, session storage, retry/idempotency behavior, and preload polling;
  only its HTTP contract constants are generated now.
- FastAPI route adapters and Pydantic models remain temporarily for migration
  safety, under mandatory drift and runtime contract checks.
- HTML and raw webhook handling remain explicit adapters because JSON model
  generation does not represent their runtime semantics safely.
- External provider payloads are reduced to the minimum stable boundary the
  application consumes; complete Stripe or Google schemas are not copied into
  the public contract.

Every new exception to immediate generation requires rationale, owner, scope,
expiry or exit criterion, and a CI assertion that keeps it from silently
widening. It does not waive a compatibility or route-security finding; those
waivers exist only as eligible entries in
`contracts/openapi/compatibility-exceptions.yaml`.

## Alternatives considered

- Keep `app.openapi()` canonical: rejected because it preserves code-first
  ownership and omits security, webhook, and application-error behavior.
- Generate tests from `app.openapi()`: rejected as schema-first compliance;
  allowed only for the one-time baseline and continuing adapter-drift evidence.
- Introduce OpenAPI Generator and a generated FastAPI server immediately:
  rejected because of Java/tooling cost, a large generated surface, and unsafe
  migration of existing validators, defaults, DI, HTML, and raw webhook logic.
- Generate only TypeScript types: rejected because the extension is vanilla
  JavaScript and would not consume them.
- Keep all schema in one YAML file: rejected because it conflicts with the
  repository's required organization and makes ownership and review harder.
- Rewrite the backend before recording the contract: rejected because it
  combines behavioral migration with source-of-truth migration and increases
  rollback risk.

## Security and rollback

The contract contains no credentials, real identity tokens, webhook secrets,
private article content, or production payloads. Mock examples and tests are
deterministic and synthetic. Security-sensitive changes receive explicit
review; schema validation supplements but does not replace authorization,
signature verification, content-size limits, or output filtering.

Before the canonical gate becomes required, rollback is deletion of the
unconsumed generated artifacts and tooling while retaining the existing
adapter. Once any generated contract is consumed, the schema, compatibility
adapter, generated files, backend tests, extension consumers, and deployment
configuration form one atomic release and rollback set. A rollback restores all
of them from the same last-known-good revision and redeploys them together; it
must not restore old YAML while leaving newer adapters or consumers, regenerate
from mixed revisions, or hand-edit generated files.

Contract changes that need persisted-data migration use expand-and-contract so
the previous release remains readable until rollback expires. If an irreversible
or already-consumed data migration makes the prior adapter unsafe, rollback is
prohibited: the incident plan must forward-fix the canonical schema, adapters,
generated artifacts, consumers, and tests as another atomic set. During a
versioned rollout, the old path remains available until extension adoption and
monitoring satisfy the deprecation plan. If contract checks produce false
positives, only the narrow checked-in normalization or named compatibility
exception may be reverted; canonical ownership must not fall back to
`app.openapi()`.

## Consequences

API intent becomes reviewable before implementation, Prism can serve realistic
local flows, and CI blocks schema, adapter, and extension drift. The migration
adds tooling and requires contract examples and compatibility review in every
API change. Hand-written FastAPI transport code remains technical debt, but it
is bounded by explicit checks and measurable exit criteria rather than being
misrepresented as generated or schema-first.
