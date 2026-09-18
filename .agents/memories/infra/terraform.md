## Module Strategy

Use reusable Terraform modules under `infra/modules/` and reference them from environment root modules.

Keep only two environments by default:

- `infra/envs/dev/`: low-cost development and verification environment.
- `infra/envs/prod/`: production environment.

Do not create a separate `stg` environment until there is a clear release or QA need.

## Structure

```text
infra/
├── modules/
│   └── <module-name>/
└── envs/
    ├── dev/
    └── prod/
```

Environment directories should contain only environment-specific composition and values. Shared AWS resources, naming patterns, IAM policies, and deployment primitives should live in modules.

## Remote State

Manage Terraform state remotely by default. Do not use local state for normal environment operations such as `dev` or `prod`.

Use S3 backend native lock files with `use_lockfile = true` for Terraform state locking.

Do not create a DynamoDB lock table for Terraform state unless a future Terraform compatibility requirement makes it necessary.

Local state is allowed only for explicit bootstrap or throwaway validation work. If local state is used temporarily, document why and migrate to remote S3 state before treating the environment as managed.

Prefer the current stable Terraform minor line for new infrastructure. Pin root modules with an upper major-version bound, such as `>= 1.15.0, < 2.0.0`, rather than only using the minimum version that supports a feature.
