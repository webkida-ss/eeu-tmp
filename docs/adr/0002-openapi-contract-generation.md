# ADR 0002: OpenAPI Contract Generation

## Status

Accepted

## Context

The project keeps API documentation in OpenAPI and requires backend HTTP contract code to come from the OpenAPI definition rather than being hand-maintained.

## Decision

Treat `contracts/openapi/openapi.yaml` as the API source of truth. For the first backend slice, `backend/build.rs` reads the OpenAPI paths and generates route contract metadata into Cargo's `OUT_DIR`. Axum route assembly checks the generated contract metadata for the implemented endpoints.

## Consequences

- OpenAPI path changes are visible at backend build time.
- Handwritten handlers remain thin adapters that call application queries.
- If the API surface grows, this generation step should evolve into fuller generated models and server traits/stubs while keeping generated code isolated from handwritten application code.
