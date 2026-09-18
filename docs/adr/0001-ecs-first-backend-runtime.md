# ADR 0001: ECS-First Backend Runtime

## Status

Accepted

## Context

The backend needs to start as a Rust + Axum API while staying portable enough to move between AWS runtime models. The first implementation target is an ECS-style long-running HTTP server, but Lambda remains a future option.

## Decision

Start with an ECS-first Axum server on port `8080`. Keep the runtime entrypoint in `backend/src/main.rs` and keep dependency wiring plus router construction in `backend/src/bootstrap.rs`.

## Consequences

- ECS and local development use the same long-running HTTP server shape.
- A future Lambda adapter can reuse the same router and application layers.
- Runtime-specific concerns must stay outside `domain` and `application`.
