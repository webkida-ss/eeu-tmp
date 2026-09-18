# RM-08 implementation scope and validation contract

Parent Astra decision, September 13, 2026. Dispatch implementation only after
RM-07's source checkpoint has independent static acceptance. Runtime acceptance
still requires canonical container execution. No live IAM or infrastructure work.

## Policy consistency

Correct the general-purpose S3 encryption-read action to
`s3:GetEncryptionConfiguration`, preserving the current resource and condition
scope. The API operation name is GetBucketEncryption; it is not the IAM action.
[AWS API permission reference](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetBucketEncryption.html).

Align the policy's Project tag with the actual dev/prod provider default
`english-reading-assistant`; do not rename provisioned resources or widen tag
conditions. Preserve RM-07's exact plan/package object allowlists and KMS context.
Update the existing offline validator and regression expectations together.

## Environment merge boundary

Both overlay maps must reserve provider/security configuration owned by typed
inputs and the base map. Cover AUTH_PROVIDER, BILLING_PROVIDER, STORAGE_BACKEND,
and the associated identity/billing configuration; do not permit one map to undo
the other's protections. Keep the current typed usage/reservation protections.
The pricing map accepts documented tokenizer, rate-card and plan entries, not
arbitrary provider overrides. Extra nonreserved configuration stays supported.

Use blocking validation/preconditions on the final merged Lambda environment,
including production google/stripe and the intended storage backend, shared by
API and worker. A warning-only check block is insufficient. Inputs must be checked
before apply even if an overlay would coincidentally select the same value.

## Precisely authorized test extension

The existing `infra:validate` performs init and validate only, so it does not prove
the negative plan-time cases. RM-08 may add one canonical target named
`infra:test:provider-guards` in Taskfile.yaml, module-local
`infra/modules/reading-assistant-api/tests/provider-guards.tftest.hcl`, and a small
credential-free helper `scripts/test_terraform_provider_guards.sh` if necessary
to stage an isolated temporary module copy and the existing dev provider lock.
Do not edit or regenerate provider locks while offline inputs are unavailable.
The helper may copy only module configuration/test fixtures and the nonsecret
provider lock; never environment roots, state, tfvars, or credentials.

Use native Terraform tests with a mocked AWS provider, explicit `command = plan`
in every run, synthetic IDs/parameter names, and a local harmless package fixture.
No real provider configuration or cloud calls. Reuse already cached providers;
missing cache is a blocker, not permission to download or authenticate.
Terraform mocks still require provider schemas. Native expected failures must
name the relevant validation/precondition; unrelated parse/provider errors fail
the test. [Mocking](https://developer.hashicorp.com/terraform/language/tests/mocking),
[test semantics](https://developer.hashicorp.com/terraform/language/tests).

Cover direct production mock inputs; auth/billing/storage overrides through each
overlay; legitimate pricing and extra entries; and the resulting API/worker
environment in the successful case. Preserve PLAN's required IAM policy tests.
No new deployment target, environment, source language migration, or broad CI
restructuring is part of this scope. Parent records any additional necessary
seam before implementation. No RM-08 implementation or test execution yet.

## Separate parent dependency-preparation decision, September 13 manual continuation

The user explicitly requested Docker recovery and continued implementation.
Host cache inspection found only Darwin AWS binaries, which cannot supply the
required Linux schemas. Parent now scopes a separate public dependency preparation
step under that continued local-work authorization: fetch only the locked
hashicorp/aws 6.55.0 Linux arm64 distribution from HashiCorp, require its ZIP
SHA-256 to match the already committed zh lock entry, and copy it to the owned
container's filesystem mirror. This is the same separate preparation boundary used
for public pinned Python/tool/Lambda inputs during Docker recovery. It grants no
AWS API calls, credentials, provider upgrades, lock regeneration or deployment.
The native test/helper still cannot download; tests remain network-disconnected.
The earlier missing-cache rule continues to forbid opportunistic downloads from
inside validation. This recorded preparation decision supplies the missing input
explicitly instead of weakening that runtime boundary.
