# Backend Common Rules

Follow **Explicit Architecture** and **Clean Architecture** for backend code.

## Core Principles

- Make the architecture explicit in package/module names instead of hiding responsibilities in generic folders.
- Keep business rules independent from frameworks, databases, cloud services, and delivery mechanisms.
- Dependencies must point inward: user interface and infrastructure depend on application/domain, not the other way around.
- Use ports/traits/interfaces for dependencies needed by use cases, and implement those ports in infrastructure.
- Wire concrete dependencies at the composition root only, such as `main`, `bootstrap`, or the application startup module.

## Layer Responsibilities

- `domain`: enterprise business rules, entities, value objects, domain services, and domain errors.
- `application`: use cases, commands, queries, interactors, application services, DTOs, and ports required by use cases.
- `infrastructure`: implementations for persistence, external services, configuration, logging, cloud SDKs, and other technical details.
- `user_interface`: delivery mechanisms such as HTTP, CLI, jobs, request parsing, response formatting, and controllers/handlers.

## Implementation Rules

- Keep handlers/controllers thin: translate input, call one application use case, and translate the result.
- Keep transaction boundaries in application services/use cases or dedicated infrastructure units, not in domain entities.
- Define repository/client abstractions from the application's needs, not from database tables or SDK shapes.
- Do not let ORM, SQL, HTTP, or cloud SDK types leak into `domain` or `application` unless they are intentionally part of a stable contract.

## API Server

- Generate API server code from the OpenAPI definition. Do not handwrite HTTP server contract code.
