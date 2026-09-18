# Infrastructure

## Frontend Assumption

The frontend is SPA-first for the MVP. Static assets are served from object storage and CDN, while learning data, user data, authentication state, and AI-related operations are handled through backend APIs.

This means the first version should not require a frontend server runtime. SSR-capable hosting remains a future option only when the product needs public SEO pages, dynamic OGP metadata, or server-side session rendering.

## Frontend Deployment Patterns

| Pattern | AWS services | Cost profile | Best fit | Trade-offs |
| --- | --- | --- | --- | --- |
| S3 + CloudFront static hosting | S3, CloudFront, Route 53, ACM | Lowest baseline cost. Main cost drivers are bandwidth, requests, and cache invalidation. | MVP frontend, SPA delivery, landing pages, and authenticated screens that fetch data from APIs. | Requires static export compatibility. SSR, server actions, and frontend server runtime features are out of scope for the MVP. |
| Amplify Hosting for static SPA | Amplify Hosting, CloudFront managed by Amplify, Route 53, ACM | Low to moderate. Build minutes and bandwidth can increase cost. | Faster setup for a SPA when GitHub-based deployment and preview environments are valuable. | More managed abstraction than direct S3 + CloudFront. Less direct control over CDN details. |
| CloudFront + OpenNext serverless | CloudFront, S3, Lambda, Route 53, ACM | Low when traffic is light, but adds Lambda, logs, and runtime costs. | Future option if SSR becomes necessary without always-on compute. | Not needed for the MVP SPA. More moving parts and Next.js compatibility checks are required. |
| ECS Fargate Next.js server | ECS Fargate, ALB, CloudFront, ECR, Route 53, ACM | Higher baseline cost because ALB and tasks run continuously. | Future option if the frontend becomes a server-rendered app or BFF. | Too heavy for the MVP SPA. Requires container build, deployment, scaling, and monitoring setup. |
| Vercel | Vercel, optional Route 53 DNS | Low entry cost, but may grow with team usage, bandwidth, and commercial requirements. | Maximum Next.js velocity outside AWS. | Not AWS all-in. Less aligned with the low-cost AWS SPA direction. |

## Backend Deployment Patterns

| Pattern | AWS services | Cost profile | Best fit | Trade-offs |
| --- | --- | --- | --- | --- |
| Lambda + API Gateway | Lambda, API Gateway, CloudWatch, IAM | Very low idle cost. Cost scales per request, execution duration, logs, and API Gateway usage. | Early API development, low traffic, simple request/response workloads, and lightweight services. | Cold starts and Lambda constraints. Axum can run on Lambda, but the deployment model is less direct than a long-running server. |
| ECS Fargate + ALB | ECS Fargate, ALB, ECR, CloudWatch, IAM | Moderate to high baseline cost due to ALB and always-on tasks. | Rust + Axum services, predictable web APIs, and workloads that benefit from long-running processes. | More expensive at low traffic. Requires container operations, health checks, scaling, and service deployment. |
| App Runner | App Runner, ECR or GitHub source, CloudWatch | Moderate. Simpler than ECS, with managed runtime and scaling. | Containerized APIs where operational simplicity matters more than fine-grained control. | Less flexible than ECS for networking and advanced runtime settings. Pricing can be less efficient than Lambda at very low traffic. |
| Lambda worker + SQS | Lambda, SQS, CloudWatch, IAM | Low idle cost. Cost scales with queued jobs and processing duration. | Background jobs such as personalized example sentence generation, profile-triggered regeneration, and lightweight AI orchestration. | Not ideal for long-running or resource-heavy jobs. External AI latency can increase execution duration. |
| ECS worker + SQS | ECS Fargate, SQS, ECR, CloudWatch, IAM | Higher baseline if workers are always running. Can be optimized with scheduled or autoscaled capacity. | Longer AI jobs, batch processing, and workloads that need more control over runtime, memory, or dependencies. | More operational work than Lambda workers. Needs queue scaling and failure handling. |
| Elastic Beanstalk | Elastic Beanstalk, EC2, ALB, CloudWatch | Moderate baseline cost depending on EC2 and ALB configuration. | Traditional web service deployment with less manual ECS setup. | Older operational model. Less aligned with container-first AWS architecture than ECS or App Runner. |

## Initial Recommendation

For the MVP, prefer the lowest-cost path that still keeps the backend replaceable:

| Area | Recommended first choice | Reason |
| --- | --- | --- |
| Frontend | S3 + CloudFront static hosting | The frontend is SPA-first, so static hosting keeps the MVP simple and low cost. |
| Backend API | Lambda + API Gateway or ECS Fargate + ALB | Choose Lambda for lowest idle cost. Choose ECS Fargate if the Rust + Axum server shape is more important than minimizing early cost. |
| Background jobs | SQS + Lambda worker | Personalized learning content should be generated asynchronously and stored before display. Lambda keeps idle cost low for the first version. |

## GitHub Actions and AWS OIDC

Use GitHub Actions OIDC federation to deploy from GitHub to AWS. Do not store long-lived AWS access keys in GitHub Secrets.

### Flow

```text
GitHub Actions workflow
  -> requests a GitHub OIDC token
  -> AWS IAM OIDC provider verifies the token
  -> AWS STS AssumeRoleWithWebIdentity
  -> temporary AWS credentials are issued
  -> workflow deploys infrastructure, frontend, or backend resources
```

### AWS Setup

| Item | Purpose |
| --- | --- |
| IAM OIDC provider | Trusts GitHub's OIDC issuer, `https://token.actions.githubusercontent.com`. |
| IAM deploy role | Role assumed by GitHub Actions for each environment. |
| Trust policy | Restricts which repository, branch, tag, or GitHub Environment can assume the role. |
| Permission policy | Grants only the deployment permissions needed by the workflow. |

Create separate deploy roles for `dev` and `prod` so production permissions can be stricter.

| Environment | Example role | Trust boundary |
| --- | --- | --- |
| `dev` | `github-actions-dev-deploy` | Repository and development branch or `dev` GitHub Environment. |
| `prod` | `github-actions-prod-deploy` | Repository and `prod` GitHub Environment, preferably with manual approval. |

### GitHub Setup

GitHub workflow permissions must allow OIDC token issuance:

```yaml
permissions:
  contents: read
  id-token: write
```

Store non-secret deployment values in GitHub Environment variables when possible.

| Value | Example |
| --- | --- |
| AWS role ARN | `arn:aws:iam::<account-id>:role/github-actions-dev-deploy` |
| AWS region | `ap-northeast-1` |
| Terraform environment | `dev` or `prod` |
| Frontend bucket | S3 bucket name created by Terraform |
| CloudFront distribution ID | Distribution ID created by Terraform |

### Deployment Responsibilities

| Workflow | Main AWS permissions |
| --- | --- |
| Infra deploy | Terraform-managed permissions for the target environment. |
| Frontend deploy | Upload static files to S3 and create CloudFront invalidations. |
| Backend deploy | Update Lambda functions or push images to ECR and update ECS services, depending on the backend runtime. |

### Bootstrap Note

OIDC itself and the Terraform remote state S3 bucket need an initial bootstrap step. This can be done once from a trusted local AWS administrator session or from a small bootstrap Terraform stack. After that, regular deployments should use GitHub Actions OIDC.

Use Terraform's S3 native lock file instead of a DynamoDB lock table. The environment backend should set `use_lockfile = true` after the state bucket exists.

```hcl
terraform {
  backend "s3" {
    bucket       = "english-dev-terraform-state"
    key          = "envs/dev/terraform.tfstate"
    region       = "ap-northeast-1"
    encrypt      = true
    use_lockfile = true
  }
}
```

The state bucket should still enable versioning, encryption, and restricted access. A DynamoDB table is not needed for Terraform state locking.

