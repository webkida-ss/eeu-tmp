# Tech

## Local Development Ports

The local development ports intentionally avoid common defaults such as `3000`,
`8000`, and `8080` because other validation apps are often running at the same
time.

| Service | Local URL | Started by | Notes |
| --- | --- | --- | --- |
| Frontend | `http://localhost:13000` | `task run:frontend:api` | Next.js dev server. Cognito callback/logout URLs must use this port. |
| Backend API | `http://localhost:18080` | `task run:backend` | Rust Axum API. OpenAPI local server URL also points here. |
| DynamoDB Local | `http://localhost:18000` | `task dynamodb:local` or `task run:backend` | Docker container `english-dynamodb-local`, mapped to container port `8000`. |

Authentication callback URLs for local development:

```text
http://localhost:13000/auth/callback
http://localhost:13000/auth/logout
```

When the frontend port changes, update the Cognito app client callback/logout
URLs and apply Terraform for the dev environment.

```sh
task infra:dev:apply
```

The Google Cloud Console redirect URI does not change when only the frontend
port changes, because Google redirects back to Cognito:

```text
https://vicente-calderon-dev-auth.auth.ap-northeast-1.amazoncognito.com/oauth2/idpresponse
```
