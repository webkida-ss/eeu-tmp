# Backend

Rust + Axum backend for the English learning app.

## Run Locally

```sh
cargo run
```

The service listens on `0.0.0.0:8080` by default. Local Taskfile commands run it
on port `18080` to avoid common port conflicts. It reads learning catalog seed
data from `../frontend/src/features/learning/data/learningPaths.json`.

Configuration:

| Variable | Default | Description |
| --- | --- | --- |
| `APP_HOST` | `0.0.0.0` | Bind host for the ECS/Axum server. |
| `APP_PORT` | `8080` | Bind port. Local Taskfile default is `18080`. |
| `CATALOG_REPOSITORY` | `json` | Learning catalog repository implementation. Use `json` or `dynamodb`. |
| `CATALOG_DATA_PATH` | frontend JSON seed path | Learning catalog JSON file. |
| `DYNAMODB_TABLE_NAME` | none | Required when `CATALOG_REPOSITORY=dynamodb`. |
| `DYNAMODB_ENDPOINT` | none | Optional DynamoDB endpoint override, such as `http://localhost:18000` for DynamoDB Local. |
| `AWS_REGION` | `ap-northeast-1` | AWS region used by the DynamoDB client. |
| `USER_REPOSITORY` | `in_memory` | User repository implementation. Use `in_memory` or `dynamodb`. |
| `USER_DYNAMODB_TABLE_NAME` | `DYNAMODB_TABLE_NAME` | DynamoDB table for users and user identities when `USER_REPOSITORY=dynamodb`. |
| `COGNITO_REGION` | `AWS_REGION` | AWS region for the Cognito User Pool. |
| `COGNITO_USER_POOL_ID` | empty | Cognito User Pool ID for JWT verification. |
| `COGNITO_CLIENT_ID` | empty | Cognito app client ID expected in access tokens. |
| `COGNITO_HOSTED_UI_BASE_URL` | none | Cognito Hosted UI base URL. When set, the backend calls `/oauth2/userInfo` to load user profile claims such as email after access token verification. |
| `COGNITO_USERINFO_ENDPOINT` | derived from `COGNITO_HOSTED_UI_BASE_URL` | Optional full Cognito UserInfo endpoint override. |
| `RUST_LOG` | `info` | Tracing filter. |

## DynamoDB Mode

DynamoDB mode expects one item per learning path:

| Attribute | Value |
| --- | --- |
| `pk` | `CATALOG` |
| `sk` | `PATH#{learningPathId}` |
| `document` | JSON string matching the `LearningPath` response shape |

The same table can also store auth user records:

| Record | `pk` | `sk` | Attributes |
| --- | --- | --- | --- |
| User profile | `USER#{appUserId}` | `PROFILE` | `document` |
| User identity | `IDENTITY#{provider}#{subject}` | `USER` | `userId`, `document` |

For local development, `task run:backend` starts DynamoDB Local, creates and seeds
the local table, and runs the backend with DynamoDB repositories by default.

The equivalent manual command is:

```sh
CATALOG_REPOSITORY=dynamodb \
DYNAMODB_TABLE_NAME=english-local-learning-catalog \
DYNAMODB_ENDPOINT=http://localhost:18000 \
USER_REPOSITORY=dynamodb \
USER_DYNAMODB_TABLE_NAME=english-local-learning-catalog \
AWS_ACCESS_KEY_ID=dummy \
AWS_SECRET_ACCESS_KEY=dummy \
cargo run
```

## Checks

```sh
cargo fmt --check
cargo clippy --all-targets
cargo test
```

## API Contract

`contracts/openapi/openapi.yaml` is the source of truth. The build script reads the OpenAPI paths and generates route contract metadata into Cargo's `OUT_DIR`, which the Axum route assembly checks at startup.
