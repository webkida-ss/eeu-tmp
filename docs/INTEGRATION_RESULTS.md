# Local Consolidation Completion

Date: 2026-09-08 (JST).

## Outcome

The five original feature branches, consolidation repairs, and reading lifecycle
refactor are consolidated into local `main` through a fast-forward from
`codex/reading-refactor`. All six original worktrees and all branch references
are retained. The five other worktrees were clean when checked. No remote is
configured; no push, cloud state change, deployment, or publication occurred.

The full canonical `task check` now exits successfully. Earlier Lambda download
and provider-registry blockers are resolved through explicit local dependency
inputs, not by bypassing checks or allowing external traffic during tests.
The four previously outstanding DynamoDB Local integration tests also pass.

## Final validation support change

Base: `5e58b41a375d265ebf2fabb33f150d0cf05b70ec`.

- `LAMBDA_WHEELHOUSE` selects a local wheel directory and disables indexes.
  Required hashes, both Linux arm64 wheel tags, CPython 3.12, and binary-only
  requirements remain unchanged. An invalid input fails before build cleanup.
- `TERRAFORM_PROVIDER_MIRROR` selects local packages for lock reproduction.
  Read-only initialization, all four target platforms, and byte-for-byte lock
  comparison remain unchanged. A separate dedicated Terraform CLI configuration
  controls initialization without a direct-registry fallback.
- Both input paths support relative paths and spaces by validating and resolving
  them before subprocess directory changes. Default online behavior is unchanged.
- Ten service-free boundary tests protect source selection, required flags,
  invalid inputs, path handling, and lock-mismatch failures in both modes.

See [network-denied validation](CLOUD_DEVELOPMENT.md#network-denied-validation)
for reproducible preparation and execution. No dependency versions, hashes,
Terraform resources, product APIs, or usage limits changed in this final step.

## Environment and evidence

Public dependency preparation ran in a separate credential-free container.
Lambda wheels were verified against the committed hash lock. All four AWS
provider archives were authenticated as signed by HashiCorp during mirror
preparation. Verified inputs were copied into the existing isolated Linux arm64
test container. Its attached network map remained `{}`; it had no host
credentials or Docker socket. All acceptance tests were parent-executed there.
Delegated host-only checks were excluded from acceptance evidence and rerun
under the required isolation.

The pinned DynamoDB Local sidecar shared only that container's loopback network
namespace, stored data in memory, and used explicit dummy test credentials.
The canonical `test:backend:integration` task passed all four cases without
skips. This verifies service integration, not a rerun of the host Compose
lifecycle wrapper. The owned sidecar and provisioning container were stopped
after use; no unrelated container or user data was removed.

| Final check | Result |
| --- | --- |
| Complete canonical `task check` | Exit 0 |
| Backend coverage suite | 799 passed, 6 expected admin-disabled skips, 33 subtests passed; 83% coverage |
| Default API contracts | 46 passed |
| Admin-enabled authorization and learner/contract compatibility | 102 passed |
| Extension unit/coverage tests | 170 passed |
| Extension ZIP dependency tests | 8 passed, 14 subtests passed |
| Lambda package construction and target-native imports | Build passed; 2 tests passed |
| Terraform locks | Both environments reproduce unchanged locks for all four platforms |
| Terraform validation | Dev and prod passed with backend initialization disabled |
| Agent/policy, schema, lint, format, and automation static checks | Passed as part of the full gate |
| DynamoDB Local integration | 4 passed, none skipped |

The previously passing source/ZIP browser smoke, 18-fixture fidelity, and
three-case browser lifecycle evidence remains applicable: browser/application
code did not change in this final validation-support step.

Final reviewed/tested source snapshot SHA-256:
`48eb4594c7e4aeb3e37d508d7b5223e2f0651ddc1b9839e07fb23e15ad714b0f`.
Independent correctness and security reviewers inspected those exact bytes and
the final canonical evidence. Neither reported an actionable new finding.
Only narrative result/plan updates followed the reviewed source snapshot.

The ignored local `output/refactor/check-complete.log` records the complete
successful gate, with SHA-256
`3c5ab3e1cd6824a9e9dd4e77fa90893cc53fb2766825f82cf9b9bfa1ffd0ea14`.
Other retained logs include `dynamodb.log`, `provider-provision.log`,
`wheel-provision.log`, `infra-validate.log`, and the RED/GREEN offline-input
checks. The final test-built Lambda ZIP has SHA-256
`bab2cccdfb17e4f356853192851bc556572438e011a8f2850fdd0cba30f774fd`;
it is a validation artifact, not an approved release.

## Remaining non-blocking or release-specific work

- Normal macOS Chrome user-gesture/unpacked reload behavior still needs the
  release-oriented manual check; managed Linux Chromium is not identical.
- The unfinished admin endpoints/frontend remain separate feature work.
- Existing preload exception/URL logging and user-independent activity source
  deduplication remain separately recorded security-design concerns, not newly
  introduced regressions.
- The TestClient/httpx deprecation warning remains. No tests failed because of it.
- Any remote publication, deployment, production validation, or deletion of
  retained branches/worktrees requires separate authorization.
