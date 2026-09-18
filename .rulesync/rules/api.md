---
root: false
targets:
  - '*'
description: API documentation conventions
globs:
  - contracts/openapi/**/*.yaml
cursor:
  alwaysApply: false
  description: API documentation conventions
  globs:
    - contracts/openapi/**/*.yaml
---
## API Documentation

Write API documentation in OpenAPI format.

## Schema Organization

- Split reusable schemas into separate files.
- Keep request and response schemas explicit.
- Use shared schemas only for concepts that are truly reused across endpoints.
- Prefer clear domain names over transport-oriented names.

## Mock Examples

- Add realistic response examples to OpenAPI responses so Prism mock servers return usable frontend data.
- Keep examples aligned with the frontend screens that consume the endpoint.
- Update examples whenever response schemas or user-facing mock flows change.

## File Structure

```text
contracts/openapi/
├── openapi.yaml
├── components/
│   └── schemas/
│       └── *.yaml
└── paths/
    └── *.yaml
```

- `contracts/openapi/openapi.yaml`: OpenAPI entry file.
- `contracts/openapi/components/schemas/`: Reusable schema files.
- `contracts/openapi/paths/`: Endpoint path definitions when the API grows.
