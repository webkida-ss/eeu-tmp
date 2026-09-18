# ADR 0004: DynamoDB Learning Catalog Repository

## Status

Accepted

## Context

The backend currently reads the learning catalog from JSON through the `LearningCatalogRepository` port. The next persistence step should validate DynamoDB without changing the domain, application use cases, HTTP handlers, or OpenAPI contract.

## Decision

Add a DynamoDB-backed `LearningCatalogRepository` implementation and select it at the composition root with `CATALOG_REPOSITORY=dynamodb`. Keep `CATALOG_REPOSITORY=json` as the default local development mode.

Store one item per learning path using `pk=CATALOG`, `sk=PATH#{learningPathId}`, and a `document` attribute containing the full serialized `LearningPath` JSON.

## Consequences

- Daily local development remains zero setup with the JSON repository.
- DynamoDB can be tested by changing environment variables only.
- The current read APIs map directly to `Query` and `GetItem` operations.
- Seed scripts, table creation, and Terraform are separate follow-up work.
