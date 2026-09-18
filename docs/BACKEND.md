# Backend

## AI Configuration

The backend starts with AI integration inside the Rust service. Feature clients
request typed model keys, and the AI foundation validates those keys against the
application-owned AI model catalog.

Pattern 1: local deterministic AI, no external API call:

- `AI_MODEL_CATALOG_REPOSITORY=dynamodb`
- `AI_MODEL_CATALOG_EXAMPLE_SENTENCE_PROVIDER=dev`
- `AI_MODEL_CATALOG_EXAMPLE_SENTENCE_PROVIDER_MODEL_ID=dev-example-sentence-fast`

This repository uses `direnv` for local environment loading. Create a local
secret file from the example file:

```bash
cp .env.example .env.local
direnv allow
```

Pattern 2: real OpenAI-compatible API call:

- `AI_MODEL_CATALOG_REPOSITORY=dynamodb`
- `AI_MODEL_CATALOG_EXAMPLE_SENTENCE_PROVIDER=open_ai_compatible`
- `AI_MODEL_CATALOG_EXAMPLE_SENTENCE_PROVIDER_MODEL_ID=gpt-4o-mini`
- `AI_OPENAI_COMPATIBLE_ENDPOINT=https://api.openai.com/v1/chat/completions`
- `AI_OPENAI_COMPATIBLE_API_KEY=<secret>`

Do not use provider-specific generic names such as `OPENAI_API_KEY` for backend
configuration. The backend reads `AI_OPENAI_COMPATIBLE_API_KEY`.

UI users do not choose AI models. Feature services own default model choices.

### AI Model Catalog Storage

The current implementation can run from the in-memory default for tests, but
local and production-like model selection should be backed by DynamoDB catalog
data. `task dynamodb:seed` writes the local `example_sentence_fast` entry using
the `AI_MODEL_CATALOG_EXAMPLE_SENTENCE_*` seed values. Store model catalog data
such as:

- model key requested by feature services
- provider name
- provider model identifier
- enabled status
- default temperature or token limits
- purpose or feature ownership

Do not store provider API keys or other secrets in the model catalog. Keep local
credentials in environment variables and move production credentials to AWS
Secrets Manager when centralized rotation and access control are needed.

### AI Extraction Boundary

If AI processing later moves to SQS workers or a separate service, keep feature
services dependent on the same `AiClient` request shape. Replace the current
provider gateway with an adapter that publishes jobs or calls the external AI
service. Do not move provider-specific model names into feature services.