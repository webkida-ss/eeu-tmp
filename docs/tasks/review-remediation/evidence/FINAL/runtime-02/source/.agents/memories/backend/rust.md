# Rust Backend

Use **Axum** as the default Rust web framework.

This rule specializes the common backend architecture rules for Rust/Axum implementations.

## Directory Structure

When applying Explicit Architecture and Clean Architecture in Rust, prefer this module structure:

```text
src/
├── main.rs
├── bootstrap.rs
├── domain/
│   ├── entities/
│   ├── value_objects/
│   ├── domain_services/
│   └── errors.rs
├── application/
│   ├── commands/
│   ├── queries/
│   ├── handlers/
│   ├── services/
│   ├── ports/
│   └── dto/
├── infrastructure/
│   ├── persistence/
│   ├── external_services/
│   ├── config/
│   └── logging/
└── user_interface/
    └── http/
        ├── routes/
        ├── handlers/
        ├── extractors/
        ├── requests/
        └── responses/
```

## Axum Placement

- Put Axum routers under `user_interface/http/routes/`.
- Put Axum handlers under `user_interface/http/handlers/`.
- Put custom Axum extractors under `user_interface/http/extractors/`.
- Put HTTP request DTOs under `user_interface/http/requests/`.
- Put HTTP response DTOs under `user_interface/http/responses/`.

## Rust Implementation Rules

- Keep `main.rs` small and use `bootstrap.rs` for dependency wiring, router assembly, configuration, and startup concerns.
- Use `application/ports/` for repository/client traits required by use cases.
- Implement those ports under `infrastructure/`, such as `infrastructure/persistence/` or `infrastructure/external_services/`.
- Keep Axum, SQLx, AWS SDK, and tracing setup out of `domain/`.
- Convert application errors to HTTP responses in `user_interface/http/`, not inside use cases.
