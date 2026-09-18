# RM-09C initial review: corrections required

Independent Astra verified ten source hashes. Finite-period/provenance resolver
and explicit mode propagation through account descriptions, HTTP guards/meters,
inline jobs and worker-created consumers are sound statically.

Medium: a successful mock activation leaves an activated pending session. After
switching configuration to Stripe, checkout can return its saved mock URL even
though entitlement correctly becomes Basic. Preserve provider origin and handle
cross-mode requests explicitly; never report mock evidence as a Stripe checkout.

Parent separately identified recovery after created-but-not-activated mock
persistence or activation CAS conflict: retry currently enters provider history
discovery that cannot recover the local mock activation. Add safe owned recovery
and terminal/cancellation regressions. Preserve real-provider recovery contracts.

Initial canonical lint/format passed; 10 tests failed, 886 passed, 6 skipped,
47 subtests. Failures are old no-expiry paid fixtures and webhook stubs using
default mock settings. Fixture corrections and consumer/recovery tests are in
progress. No C acceptance or release approval. Reviewer executed no runtime.
