# ADR 0003: JSON-First Learning Catalog Persistence

## Status

Accepted

## Context

The first backend phase only serves read-only learning catalog APIs. The frontend already has realistic JSON seed data, and the project approach favors local JSON reads before real API and persistence integration.

## Decision

Use a JSON-backed learning catalog repository for the first backend slice. Define the repository trait in the application layer and implement JSON loading in infrastructure.

## Consequences

- The first API can be verified quickly without provisioning a database.
- The application layer depends on a repository port, not on JSON or file-system details.
- Future DynamoDB, RDS, or other persistence can replace only the infrastructure implementation and bootstrap wiring.
