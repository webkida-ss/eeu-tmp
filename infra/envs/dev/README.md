# Dev Infrastructure

This environment provisions low-cost development resources, including Cognito auth.

## Terraform Version

Use Terraform `1.15.5`.

```sh
tfenv install 1.15.5
tfenv use 1.15.5
terraform version
```

The repository also includes `.terraform-version`, so `tfenv` should select the expected version from the workspace root.

## Variables

Create a local variables file from the example:

```sh
cp infra/envs/dev/terraform.tfvars.example infra/envs/dev/terraform.tfvars
```

Set real Google OAuth credentials in `terraform.tfvars`:

```hcl
google_client_id     = "..."
google_client_secret = "..."
```

Do not commit `terraform.tfvars`.

## Validate

```sh
task infra:dev:validate
```

## Plan And Apply

```sh
task infra:dev:init
task infra:dev:plan
task infra:dev:apply
```

## App Configuration

After apply, copy Terraform outputs into frontend/backend environment variables.

Frontend:

```env
AUTH_PROVIDER=cognito
NEXT_PUBLIC_COGNITO_AUTHORITY=<cognito_authority>
NEXT_PUBLIC_COGNITO_CLIENT_ID=<cognito_app_client_id>
NEXT_PUBLIC_COGNITO_REDIRECT_URI=http://localhost:13000/auth/callback
NEXT_PUBLIC_COGNITO_POST_LOGOUT_REDIRECT_URI=http://localhost:13000/auth/logout
```

Backend:

```env
COGNITO_REGION=ap-northeast-1
COGNITO_USER_POOL_ID=<cognito_user_pool_id>
COGNITO_CLIENT_ID=<cognito_app_client_id>
```

## Google OAuth Redirects

For Cognito federation with Google, configure Google OAuth to allow Cognito's Hosted UI callback URL after the Cognito domain exists:

```text
https://<cognito_domain_prefix>.auth.ap-northeast-1.amazoncognito.com/oauth2/idpresponse
```
