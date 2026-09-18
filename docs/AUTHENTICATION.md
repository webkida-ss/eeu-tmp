# Authentication

This document compares two authentication architecture patterns.

- Pattern A: The application backend verifies Google authentication and issues
  its own application access token.
- Pattern B: Amazon Cognito handles authentication and token issuance, while the
  Backend API verifies Cognito tokens.

In both patterns, external identity provider tokens must not be confused with
authorization for application APIs. The backend must validate the token that the
frontend sends before serving protected data.

## Initial Implementation Decision

The first implementation will use Cognito-managed tokens with an ECS backend.

Decisions:

| Topic | Decision |
| --- | --- |
| Authentication owner | Amazon Cognito |
| Social provider | Google through Cognito federation |
| Frontend sign-in | Cognito Hosted UI |
| OIDC flow | Authorization Code Flow with PKCE |
| Frontend token handling | SPA-managed Cognito tokens, stored with the OIDC client using `sessionStorage`-oriented configuration |
| Backend runtime | ECS first |
| API entry point | ALB for the ECS service |
| Token verifier | Backend application verifies Cognito JWTs |
| First protected API | `GET /auth/session` |
| User persistence | DynamoDB |
| User model | Separate `users` and `user_identities` records |
| Infrastructure management | Terraform |

Initial scope:

1. Create the Cognito user pool, app client, hosted UI domain, and Google
   identity provider configuration with Terraform.
2. Register both local and dev callback/logout URLs in the Cognito app client.
3. Add frontend Cognito Hosted UI sign-in with `oidc-client-ts`.
4. Add `/auth/callback` and `/auth/logout` frontend routes.
5. Store Cognito tokens using the selected OIDC client storage configuration.
6. Send API requests with `Authorization: Bearer <cognito-access-token>`.
7. Add OpenAPI contract for `GET /auth/session`.
8. Add backend Cognito JWT verification behind an `AuthVerifier` interface.
9. Add DynamoDB-backed application user and identity mapping.
10. Return `authenticated`, `cognitoSub`, `appUserId`, and `email` from
    `GET /auth/session`.

For a beginner-friendly explanation of how Cognito and Google OAuth settings are
used during sign-in, see [Cognito and Google OAuth Flow](./COGNITO_GOOGLE_OAUTH_FLOW.md).

Google OAuth secret handling:

Use Terraform sensitive variables and GitHub Environment Secrets for the Google
OAuth client secret in the first implementation. This keeps the workflow simple,
but the team must understand that Terraform state can still contain sensitive
provider configuration values.

## Pattern A: Self-Managed Application Tokens

In this pattern, Google authentication is only the identity proof. The
application backend owns the final login state and issues the application access
token and refresh token.

### Target Flow

```mermaid
sequenceDiagram
  participant learner as Learner
  participant frontend as Frontend
  participant google as Google
  participant backend as Backend
  participant database as Database

  learner->>frontend: Click "Sign in with Google"
  frontend->>google: Start Google Sign-In
  google-->>frontend: Return Google ID token
  frontend->>backend: POST /auth/providers/google/login with Google ID token
  backend->>google: Verify ID token signature and claims
  google-->>backend: Token is valid
  backend->>database: Find user by Google subject
  alt Existing user
    database-->>backend: Return application user
  else New user
    backend->>database: Create application user
    database-->>backend: Return application user
  end
  backend->>backend: Issue application access token
  backend->>backend: Issue application refresh token
  backend-->>frontend: Return user and access token
  backend-->>frontend: Set HttpOnly refresh token cookie
  frontend-->>learner: Show authenticated state
  frontend->>backend: Call APIs with Authorization Bearer token
```



1. The learner clicks "Sign in with Google" in the frontend.
2. The frontend opens Google Sign-In and receives a Google ID token.
3. The frontend sends the Google ID token to the backend.
4. The backend verifies the Google ID token with Google's public keys and
  validates the token claims.
5. The backend finds or creates the application user.
6. The backend issues an application access token.
7. The frontend uses the application access token for authenticated API calls.

```text
Browser
  -> Google Sign-In
  -> Frontend receives Google ID token
  -> POST /auth/providers/google/login
  -> Backend verifies Google ID token
  -> Backend finds or creates application user
  -> Backend issues application access token
  -> Frontend calls APIs with Authorization: Bearer <access-token>
```

### Google Session and Application Session

Google sign-in state and application sign-in state are separate.

Google determines whether the browser is already signed in to Google by using
Google-owned browser cookies, such as cookies for `accounts.google.com`. The
application frontend cannot read those cookies directly.

The frontend should not decide that the user is signed in to Google because an
old Google ID token exists in application state or storage. A Google ID token is
a proof returned by Google for a specific authentication event. It is not the
source of truth for the browser's Google session.

Application sign-in state is owned by the backend. On application startup, the
frontend should restore the application session through application auth
endpoints, such as `GET /auth/me` or `POST /auth/refresh`, rather than by
checking for a saved Google ID token.

### Token Responsibilities


| Token                     | Issuer  | Consumer       | Purpose                                                                |
| ------------------------- | ------- | -------------- | ---------------------------------------------------------------------- |
| Google ID token           | Google  | Backend        | Prove that Google authenticated the user.                              |
| Application access token  | Backend | Backend APIs   | Authorize access to application APIs.                                  |
| Application refresh token | Backend | Auth endpoints | Issue a new application access token without repeating Google Sign-In. |


### Backend Login Endpoint

The first backend authentication endpoint should be provider-specific:

```text
POST /auth/providers/google/login
```

Use provider-specific login endpoints so each external identity provider can
keep its own request shape while the backend still issues the same application
tokens.

Request:

```json
{
  "idToken": "google-id-token"
}
```

Backend responsibilities:

1. Verify the Google ID token signature.
2. Validate the expected issuer.
3. Validate the expected audience against the configured Google OAuth client ID.
4. Validate expiration.
5. Require a verified email address.
6. Use Google's stable subject identifier to find an existing user.
7. Create a new application user when no matching user exists.
8. Issue an application access token.
9. Issue an application refresh token.

Response:

```json
{
  "user": {
    "id": "0194fd38-7c2e-7a5a-8f2b-28b5d08a9f31",
    "name": "Example User",
    "email": "user@example.com",
    "avatarUrl": "https://example.com/avatar.png"
  },
  "accessToken": "application-access-token",
  "expiresIn": 900
}
```

The refresh token should be returned as a secure `HttpOnly` cookie rather than
being exposed to application JavaScript.

```text
Set-Cookie: refresh_token=<refresh-token>; HttpOnly; Secure; SameSite=Lax; Path=/auth
```

### Supporting Auth Endpoints


| Endpoint             | Purpose                                                  |
| -------------------- | -------------------------------------------------------- |
| `GET /auth/me`       | Return the current authenticated application user.       |
| `POST /auth/refresh` | Exchange a valid refresh token for a new access token.   |
| `POST /auth/logout`  | Revoke or expire the refresh token and clear the cookie. |


### Access Token Policy

Application access tokens should be short-lived. The initial default is 15
minutes.

The token subject should be the application user ID, not the Google user ID.

Example claims:

```json
{
  "sub": "0194fd38-7c2e-7a5a-8f2b-28b5d08a9f31",
  "email": "user@example.com",
  "iat": 1780700000,
  "exp": 1780700900
}
```

Authenticated API requests should use the application access token:

```http
Authorization: Bearer application-access-token
```

### Implementation Plan

Implement authentication in small steps. Keep the frontend experience working
with mocks first, then connect it to the backend through the OpenAPI contract.

### 1. Define the API Contract

Update the OpenAPI definition before wiring the real implementation.

Required endpoints:


| Endpoint                       | Method | Responsibility                                                      |
| ------------------------------ | ------ | ------------------------------------------------------------------- |
| `/auth/providers/google/login` | `POST` | Accept a Google ID token and create an application login session.   |
| `/auth/me`                     | `GET`  | Return the authenticated application user.                          |
| `/auth/refresh`                | `POST` | Issue a new application access token from the refresh token cookie. |
| `/auth/logout`                 | `POST` | Revoke or expire the refresh token and clear the cookie.            |


Required schemas:


| Schema                | Purpose                                                                         |
| --------------------- | ------------------------------------------------------------------------------- |
| `AuthUser`            | Public user fields returned to the frontend.                                    |
| `GoogleLoginRequest`  | Request body containing the Google ID token.                                    |
| `AuthSessionResponse` | Response containing the user, access token, and expiration.                     |
| `AuthErrorResponse`   | Error response for invalid tokens, expired sessions, and unauthorized requests. |


Future providers should follow the same endpoint shape:

```text
POST /auth/providers/{provider}/login
```

Examples:

```text
POST /auth/providers/google/login
POST /auth/providers/github/login
POST /auth/providers/apple/login
```

### 2. Frontend: Keep the Auth Boundary Small

The frontend should call an auth repository instead of embedding auth API calls
directly inside React components.

Frontend tasks:

1. Keep `AuthProvider` as the application-level auth state boundary.
2. Add an auth repository interface with `loginWithGoogle`, `getCurrentUser`,
  `refreshSession`, and `logout`.
3. Provide a mock auth repository so the UI can be verified without Google or
  backend dependencies.
4. Provide an API auth repository that uses the generated OpenAPI client.
5. Store the application access token only in frontend runtime state at first.
6. Send the access token with API requests using the `Authorization` header.
7. Restore the application session on startup by calling `/auth/refresh` or
  `/auth/me`.
8. Do not persist or reuse Google ID tokens for application session restoration.

Google Sign-In frontend tasks:

1. Configure the Google OAuth client ID through frontend environment variables.
2. Load Google Identity Services only in client-side code.
3. Start Google Sign-In from the sign-in button.
4. Receive the Google ID token from Google.
5. Immediately send the Google ID token to
  `POST /auth/providers/google/login`.
6. Treat the backend response as the source of the application login state.

### 3. Backend: Verify Google Before Issuing App Tokens

The backend must never trust a Google ID token until it has verified the token
signature and claims.

Backend tasks:

1. Add auth request and response DTOs under the HTTP interface layer.
2. Add an auth application service that handles Google login, refresh, logout,
  and current-user lookup.
3. Add a Google token verifier port in the application layer.
4. Implement the Google token verifier in the infrastructure layer.
5. Validate the Google ID token signature using Google's public keys.
6. Validate issuer, audience, expiration, and verified email claims.
7. Map Google's stable subject identifier to an application user.
8. Create a new application user when no existing user is linked to the Google
  subject.
9. Issue a short-lived application access token.
10. Issue a refresh token and return it as a secure `HttpOnly` cookie.

### 4. Backend: Persist User and Refresh Token State

The backend should be able to revoke refresh tokens and identify which user owns
each session.

Persistence tasks:

1. Add an application user model with a UUID v7 `id`.
2. Store the user's Google subject identifier separately from the application
  user ID.
3. Store user profile fields needed by the frontend, such as name, email, and
  avatar URL.
4. Store refresh token records with user ID, token hash, expiration, created
  time, and revoked time.
5. Hash refresh tokens before storing them.
6. Rotate refresh tokens when `/auth/refresh` is called.
7. Revoke the active refresh token when `/auth/logout` is called.

### 5. Backend: Protect Application APIs

After login works, protect user-specific API routes with the application access
token.

Protected API tasks:

1. Add an HTTP auth extractor or middleware that reads the `Authorization`
  header.
2. Validate the application access token signature and expiration.
3. Resolve the authenticated application user ID from the token `sub` claim.
4. Pass the authenticated user ID into handlers that need user-specific data.
5. Return `401 Unauthorized` when the access token is missing, invalid, or
  expired.
6. Return `403 Forbidden` only when the user is authenticated but not allowed to
  access a resource.

### 6. Frontend: Handle Session Expiration

The frontend should treat access token expiration as a normal state transition,
not as a hard application failure.

Session handling tasks:

1. If an API call returns `401`, call `/auth/refresh` once.
2. If refresh succeeds, retry the original API call with the new access token.
3. If refresh fails, clear the frontend auth state and show the signed-out UI.
4. Keep refresh token handling inside cookies and backend endpoints.
5. Do not expose the refresh token to frontend JavaScript.

### 7. Configuration and Secrets

Use environment variables for values that differ by environment.

Frontend configuration:


| Variable                       | Purpose                                                  |
| ------------------------------ | -------------------------------------------------------- |
| `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | Google OAuth client ID used by Google Identity Services. |
| `NEXT_PUBLIC_API_BASE_URL`     | Backend API base URL.                                    |
| `NEXT_PUBLIC_DATA_MODE`        | Select `json`, `mock`, or `api` repository mode.         |


Backend configuration:


| Variable                    | Purpose                                                |
| --------------------------- | ------------------------------------------------------ |
| `GOOGLE_CLIENT_ID`          | Expected audience for Google ID token verification.    |
| `ACCESS_TOKEN_SIGNING_KEY`  | Key used to sign application access tokens.            |
| `REFRESH_TOKEN_SECRET`      | Secret used when generating or hashing refresh tokens. |
| `ACCESS_TOKEN_TTL_SECONDS`  | Access token lifetime. Default: `900`.                 |
| `REFRESH_TOKEN_TTL_SECONDS` | Refresh token lifetime.                                |


### 8. Verification Checklist

Use this checklist before treating authentication as complete.

1. A first-time Google user can sign in and an application user is created.
2. A returning Google user signs in to the same application user.
3. The backend rejects ID tokens with the wrong audience.
4. The backend rejects expired Google ID tokens.
5. The frontend receives an application access token, not a Google token, for
  API calls.
6. `/auth/me` returns the current user when the access token is valid.
7. `/auth/refresh` issues a new access token from the refresh token cookie.
8. `/auth/logout` clears or revokes the refresh token.
9. Protected APIs reject missing, invalid, and expired access tokens.
10. The frontend does not persist Google ID tokens.

## Pattern B: Cognito-Managed Tokens with Backend API

In this pattern, Amazon Cognito owns user authentication and token issuance. The
backend runtime is an implementation detail: it can run on ECS, Lambda, or
another API runtime. The backend does not issue the primary API access token.
Instead, the Backend API verifies Cognito JWTs and maps Cognito users to
application users.

### Target Flow

```mermaid
sequenceDiagram
  participant learner as Learner
  participant frontend as Frontend
  participant cognito as Cognito
  participant google as Google
  participant backend as Backend API
  participant database as Database

  learner->>frontend: Click "Sign in"
  frontend->>cognito: Start Cognito Hosted UI or SDK sign-in
  cognito->>google: Federate to Google provider
  google-->>cognito: Return Google authentication result
  cognito-->>frontend: Return Cognito ID, access, and refresh tokens
  frontend->>backend: Call APIs with Cognito access token
  backend->>cognito: Fetch JWKS when cache is empty or expired
  cognito-->>backend: Return public keys
  backend->>backend: Verify Cognito JWT locally
  backend->>database: Find or create application user by Cognito subject
  database-->>backend: Return application user
  backend-->>frontend: Return protected application data
```



1. The learner starts sign-in from the frontend.
2. The frontend uses Cognito Hosted UI or Cognito SDK.
3. Cognito federates to Google as the external identity provider.
4. Cognito issues Cognito tokens to the frontend.
5. The frontend calls Backend API endpoints with the Cognito access token.
6. The Backend API verifies the Cognito JWT signature and claims.
7. The backend maps the Cognito subject to an application user.
8. Protected APIs use the authenticated application user ID for authorization.

```text
Browser
  -> Cognito Hosted UI or Cognito SDK
  -> Google authentication through Cognito
  -> Frontend receives Cognito tokens
  -> Frontend calls Backend API with Authorization: Bearer <cognito-access-token>
  -> Backend API verifies Cognito JWT
  -> Backend API maps Cognito user to application user
```

### Token Responsibilities


| Token                        | Issuer  | Consumer                                            | Purpose                                                  |
| ---------------------------- | ------- | --------------------------------------------------- | -------------------------------------------------------- |
| Google authentication result | Google  | Cognito                                             | Prove the user authenticated with Google.                |
| Cognito ID token             | Cognito | Frontend and backend when profile claims are needed | Represent the authenticated user identity.               |
| Cognito access token         | Cognito | Backend APIs                                        | Authorize access to application APIs.                    |
| Cognito refresh token        | Cognito | Frontend auth SDK or Hosted UI session              | Refresh Cognito tokens without repeating Google Sign-In. |


The backend should normally verify the Cognito access token for API
authorization. The ID token is useful for identity/profile claims, but protected
API access should be based on the access token unless there is a deliberate
reason to use ID tokens.

### Backend Token Verification

The Backend API should verify Cognito tokens locally using the user pool's JWKS.
The backend should not call Cognito on every API request.

Issuer format:

```text
https://cognito-idp.<region>.amazonaws.com/<user-pool-id>
```

JWKS endpoint:

```text
https://cognito-idp.<region>.amazonaws.com/<user-pool-id>/.well-known/jwks.json
```

Backend verification responsibilities:

1. Decode the JWT header and select the matching public key by `kid`.
2. Verify the JWT signature.
3. Validate the issuer.
4. Validate expiration.
5. Validate `token_use = "access"` for API authorization.
6. Validate the expected Cognito app client ID or audience claim.
7. Read the Cognito `sub` claim as the external identity subject.
8. Map the Cognito subject to an application user.
9. Reject missing, invalid, expired, or wrong-token-use tokens with
  `401 Unauthorized`.

### Application User Mapping

Cognito owns authentication, but the application should still own its domain
user model.

Recommended application tables:

```text
users
  id
  name
  email
  avatar_url

user_identities
  id
  user_id
  provider
  provider_subject
  email
```

For Cognito:

```text
provider = "cognito"
provider_subject = Cognito sub
```

If the application needs to keep the original social provider, store it as
additional identity metadata rather than using it as the application user ID.
The application user ID remains the stable domain ID.

### Frontend Responsibilities

Frontend tasks:

1. Configure Cognito user pool ID, app client ID, domain, and redirect URLs.
2. Use Cognito Hosted UI or Cognito SDK for sign-in and token refresh.
3. Configure Google as a Cognito identity provider.
4. Store Cognito tokens according to the selected frontend auth library's
  security model.
5. Send the Cognito access token to backend APIs using the `Authorization`
  header.
6. Let Cognito handle refresh token exchange.
7. Clear Cognito session state on sign-out.

The frontend should not call Google directly in this pattern. Google federation
is handled through Cognito.

### OIDC Flow for SPA

The frontend should use Authorization Code Flow with PKCE when signing in
through Cognito Hosted UI.

```text
Frontend
  -> Redirect to Cognito Hosted UI with code_challenge
  -> Cognito authenticates the user through Google
  -> Cognito redirects back with an authorization code
  -> Frontend exchanges the code with code_verifier
  -> Frontend receives Cognito tokens
```

PKCE means "Proof Key for Code Exchange". It lets a public client, such as a
browser SPA, prove that the app exchanging the authorization code is the same app
that started the login flow. This is important because a SPA cannot safely keep a
client secret.

Do not use implicit flow for new implementations.

```text
Implicit flow
  -> tokens are returned directly through the browser redirect
  -> older SPA pattern
  -> weaker than authorization code with PKCE for modern OAuth/OIDC usage
```

Use this rule of thumb:

| Flow | Use for this project | Reason |
| --- | --- | --- |
| Authorization Code with PKCE | Yes | Current standard for browser SPAs using OIDC. |
| Implicit flow | No | Older SPA pattern that exposes tokens directly in the redirect flow. |
| Backend-only code flow with client secret | Not for the SPA-first path | Requires a backend/BFF to own the callback and token exchange. |

### Backend Responsibilities

Backend tasks:

1. Add a Cognito JWT verifier component.
2. Cache the Cognito JWKS according to key cache headers or verifier library
  behavior.
3. Add an HTTP auth extractor or middleware that verifies Cognito access tokens.
4. Add a user identity repository for Cognito subject to application user
  mapping.
5. Create an application user when a valid Cognito user signs in for the first
  time.
6. Pass the application user ID into protected handlers.
7. Implement authorization with application user IDs and domain roles, not raw
  Cognito token strings.

### API Contract

With Cognito-managed tokens, the backend does not need a login endpoint that
accepts Google ID tokens.

Required backend endpoints:


| Endpoint                   | Method | Responsibility                                             |
| -------------------------- | ------ | ---------------------------------------------------------- |
| `/auth/me`                 | `GET`  | Return the application user mapped from the Cognito token. |
| Protected application APIs | varies | Require `Authorization: Bearer <cognito-access-token>`.    |


Optional backend endpoints:


| Endpoint        | Method | Responsibility                                                                                                        |
| --------------- | ------ | --------------------------------------------------------------------------------------------------------------------- |
| `/auth/logout`  | `POST` | Perform application-side logout cleanup if needed. Cognito session cleanup remains a frontend/Cognito responsibility. |
| `/auth/session` | `GET`  | Return application session metadata derived from the Cognito token.                                                   |


### Configuration

Frontend configuration:


| Variable                            | Purpose                     |
| ----------------------------------- | --------------------------- |
| `NEXT_PUBLIC_COGNITO_USER_POOL_ID`  | Cognito user pool ID.       |
| `NEXT_PUBLIC_COGNITO_APP_CLIENT_ID` | Cognito app client ID.      |
| `NEXT_PUBLIC_COGNITO_DOMAIN`        | Cognito Hosted UI domain.   |
| `NEXT_PUBLIC_COGNITO_REDIRECT_URI`  | Redirect URI after sign-in. |
| `NEXT_PUBLIC_API_BASE_URL`          | Backend API base URL.       |


Backend configuration:


| Variable                | Purpose                               |
| ----------------------- | ------------------------------------- |
| `COGNITO_REGION`        | AWS region for the Cognito user pool. |
| `COGNITO_USER_POOL_ID`  | Expected Cognito user pool ID.        |
| `COGNITO_APP_CLIENT_ID` | Expected Cognito app client ID.       |
| `COGNITO_ISSUER`        | Expected token issuer.                |
| `COGNITO_JWKS_URI`      | JWKS URL used for token verification. |


### Verification Checklist

Use this checklist before treating the Cognito pattern as complete.

1. A first-time Google user can sign in through Cognito.
2. Cognito returns access, ID, and refresh tokens to the frontend.
3. The frontend calls Backend API endpoints with the Cognito access token.
4. The Backend API verifies Cognito JWTs without calling Cognito on every
  request.
5. The backend rejects tokens with the wrong issuer.
6. The backend rejects expired tokens.
7. The backend rejects ID tokens when an access token is required.
8. The backend rejects tokens from the wrong user pool or app client.
9. A Cognito user maps to one stable application user.
10. Protected APIs use the application user ID for domain authorization.

## Common AWS Runtime Patterns

When using Cognito with Google sign-in, the common AWS pattern differs by backend
runtime. Cognito remains the token issuer in both cases.

### ECS Backend Pattern

The common ECS pattern is Cognito plus an HTTP load balancer, with the backend
application verifying Cognito JWTs.

```text
Frontend
  -> Cognito Hosted UI or SDK
  -> Google sign-in through Cognito
  -> Cognito access token
  -> ALB
  -> ECS backend
  -> Backend verifies Cognito JWT
```

Responsibilities:

1. Cognito handles Google federation and token issuance.
2. ALB acts as the HTTP entry point for the ECS service.
3. The ECS backend receives `Authorization: Bearer <cognito-access-token>`.
4. The backend verifies the Cognito JWT using the user pool JWKS.
5. The backend maps the Cognito `sub` claim to an application user.
6. The backend performs application authorization with domain user IDs and roles.

This pattern keeps the infrastructure simple for a containerized API. It also
keeps auth verification in application code, which makes local development and
future runtime changes easier than relying on ALB-specific authentication.

Implementation plan:

1. Create a Cognito user pool, app client, and hosted UI domain.
2. Configure Google as a Cognito identity provider.
3. Configure frontend callback and logout URLs in the Cognito app client.
4. Update the frontend to start sign-in through Cognito Hosted UI or SDK.
5. Store the Cognito session using the selected frontend auth library.
6. Send API requests with `Authorization: Bearer <cognito-access-token>`.
7. Create an ECR repository for the backend container image.
8. Build and push the backend image to ECR.
9. Create an ECS cluster, task definition, and service.
10. Put the ECS service behind an ALB and target group.
11. Configure the backend with Cognito issuer, user pool ID, app client ID, and
  JWKS URI.
12. Implement Cognito JWT verification in the backend application.
13. Add an HTTP auth extractor or middleware that rejects invalid tokens.
14. Map Cognito `sub` values to application users in the database.
15. Keep domain authorization in application code after authentication succeeds.
16. Add health check endpoints that do not require authentication.
17. Verify that protected endpoints reject missing, expired, or invalid Cognito
  access tokens.

Backend implementation details:

1. Read the `Authorization` header.
2. Extract the bearer token.
3. Decode the JWT header and find the matching JWKS key by `kid`.
4. Verify signature, issuer, expiration, `token_use = "access"`, and app client
  claim.
5. Convert the verified token claims into an authenticated application user
  context.
6. Pass the user context into handlers that require authentication.
7. Keep Cognito-specific code behind an auth verifier interface so another API
  entry point can reuse or replace it later.

### Lambda Backend Pattern

The common Lambda pattern is Cognito plus API Gateway, with API Gateway verifying
the Cognito token before invoking Lambda.

```text
Frontend
  -> Cognito Hosted UI or SDK
  -> Google sign-in through Cognito
  -> Cognito access token
  -> API Gateway
  -> Cognito authorizer
  -> Lambda
```

Responsibilities:

1. Cognito handles Google federation and token issuance.
2. API Gateway acts as the public API entry point.
3. API Gateway Cognito authorizer verifies the Cognito token.
4. Lambda receives an authenticated request context.
5. Lambda maps the Cognito `sub` claim to an application user.
6. Lambda performs application authorization with domain user IDs and roles.

This pattern is common because API Gateway and Lambda integrate directly, and
the Cognito authorizer removes most JWT verification code from the function.

Implementation plan:

1. Create a Cognito user pool, app client, and hosted UI domain.
2. Configure Google as a Cognito identity provider.
3. Configure frontend callback and logout URLs in the Cognito app client.
4. Update the frontend to start sign-in through Cognito Hosted UI or SDK.
5. Store the Cognito session using the selected frontend auth library.
6. Send API requests with `Authorization: Bearer <cognito-access-token>`.
7. Create an API Gateway HTTP API or REST API.
8. Configure a Cognito authorizer for the API Gateway.
9. Attach the authorizer to protected routes.
10. Leave public routes, such as health checks or public catalog reads, without
  the authorizer when appropriate.
11. Create Lambda functions for backend route handlers.
12. Wire API Gateway routes to Lambda integrations.
13. Read authenticated claims from the API Gateway request context inside Lambda.
14. Map Cognito `sub` values to application users in the database.
15. Keep domain authorization inside Lambda handler or application service code.
16. Verify that API Gateway rejects missing, expired, or invalid Cognito access
  tokens before Lambda is invoked.

Lambda implementation details:

1. Treat API Gateway as the token verifier for protected routes.
2. Read Cognito claims from the authorizer context rather than re-verifying the
  JWT in every handler.
3. Convert the Cognito `sub` claim into an application user ID.
4. Pass the application user context into the route handler or use case.
5. Keep route authorization decisions in application code when they depend on
  domain data.
6. Avoid coupling use cases to API Gateway event shapes by mapping request
  events into application DTOs at the boundary.

### Runtime Comparison


| Runtime | Common entry point | Token verifier                 | Best fit                                           |
| ------- | ------------------ | ------------------------------ | -------------------------------------------------- |
| ECS     | ALB                | Backend application            | Containerized HTTP APIs and long-running services. |
| Lambda  | API Gateway        | API Gateway Cognito authorizer | Serverless APIs and route-level API management.    |


If the backend runtime is still being evaluated, keep the frontend contract
stable:

```http
Authorization: Bearer <cognito-access-token>
```

The runtime can then change behind the Backend API boundary without changing how
the frontend signs in or sends authenticated API requests.

## Pattern Choice Summary


| Topic                   | Pattern A: Self-managed tokens           | Pattern B: Cognito + Backend API |
| ----------------------- | ---------------------------------------- | -------------------------------- |
| Token issuer            | Application backend                      | Cognito                          |
| Backend role            | Verify Google token and issue app tokens | Verify Cognito tokens            |
| Frontend login          | Google Identity Services                 | Cognito Hosted UI or SDK         |
| Refresh token ownership | Application backend                      | Cognito                          |
| Implementation speed    | Slower                                   | Faster                           |
| Operational control     | Higher                                   | Lower                            |
| AWS alignment           | Good                                     | Very good                        |
| Best fit                | Custom auth/session control              | Faster AWS-native authentication |


For the first production-oriented AWS implementation, Pattern B is often the
simpler operational choice. Choose Pattern A only when the application must own
token issuance, refresh token rotation, and session revocation directly.