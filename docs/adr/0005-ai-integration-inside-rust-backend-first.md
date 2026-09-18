# ADR 0005: AI Integration Inside Rust Backend First

## Status

Accepted

## Context

The application will need AI-assisted learning features such as generated
example sentences, writing feedback, and personalized practice content.

Two design questions are open:

- Whether to keep AI integration in Rust or introduce another runtime for SDK
  convenience.
- Whether to create a separate AI microservice from the beginning.

The current backend already uses a layered Rust architecture with application
ports, infrastructure adapters, repositories, and dependency wiring in the
composition root. The AI boundary is not stable enough yet to justify a separate
service boundary.

## Decision

Start AI integration inside the existing Rust backend.

Define an application-level AI port, such as `AiClient`, and keep provider
details behind infrastructure adapters. Application services should depend on
the port, not on a specific vendor SDK or HTTP implementation.

Initial shape:

```text
backend/src/application/ai/
  model.rs
  ports.rs
  prompts.rs
  service.rs

backend/src/infrastructure/ai/
  openai.rs / anthropic.rs / bedrock.rs
```

The first implementation may call provider APIs directly with Rust HTTP clients
instead of relying on a vendor SDK if the Rust SDK surface is weak or unstable.

Model selection should also stay behind the application AI boundary. The AI
foundation should define the set of accepted AI models and reject requests for
models outside that catalog. Feature-level clients may request a model for their
use case, and each feature client should define its own default model so UI
users do not need to choose models directly.

For example, writing feedback and generated example sentences may request
different default model profiles while still calling the same `AiClient` port.
The application AI service resolves the requested model to a provider adapter,
validates that the model is allowed, and keeps provider-specific model names out
of feature services.

For production operation, the AI model catalog should be backed by application
data storage instead of hard-coded model lists. The database catalog should store
allowed model keys, providers, provider model identifiers, enabled status, and
model tuning defaults such as temperature or token limits. It must not store
provider API keys or other secrets. Provider credentials remain environment
configuration locally and should move to a secret store such as AWS Secrets
Manager when production operations require rotation and centralized access
control.

Do not create a separate AI microservice at the start.

## Consequences

- The backend remains simpler to run, test, and deploy while AI requirements are
  still forming.
- AI provider selection remains replaceable through an application port.
- AI model selection remains explicit for feature clients while constrained by
  an application-owned model catalog.
- AI model operations can change allowed provider/model mappings without a
  redeploy once the catalog is backed by storage.
- Provider secrets stay outside the model catalog and can move independently to
  AWS Secrets Manager.
- Prompt construction, response parsing, and persistence can evolve close to the
  domain model.
- Rust SDK limitations are contained in infrastructure adapters and do not leak
  into application code.
- If AI work becomes long-running, expensive, or independently scalable, the
  next step should be an asynchronous worker, likely behind SQS.
- A separate AI service is a later option when there is a clear need for
  independent scaling, deployment cadence, runtime choice, prompt/evaluation
  operations, or SDK ecosystem support.

## Future Split Criteria

Consider extracting AI processing from the backend when one or more of these
conditions become true:

- AI requests are slow enough that they should not run in the request/response
  API path.
- AI traffic needs to scale independently from normal backend API traffic.
- A TypeScript or Python SDK provides meaningful capabilities that are hard to
  reproduce in Rust.
- Prompt versioning, evaluation, or experimentation needs a separate operational
  lifecycle.
- The system needs queue-based retries, dead-letter handling, or batch
  processing for AI jobs.

Until then, keep AI integration as a Rust backend module with clear ports and
replaceable infrastructure adapters.
