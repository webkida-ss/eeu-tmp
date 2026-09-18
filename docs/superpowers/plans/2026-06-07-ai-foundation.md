# AI Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Rust backend AI foundation that supports approved model selection by feature clients and can later be extracted behind the same port.

**Architecture:** Keep AI inside the existing Rust backend first, matching ADR 0005. Feature services call an application-owned `AiClient` port with a typed model key; the AI foundation validates that key against an application model catalog and routes the request to provider adapters hidden in `infrastructure/ai`. Start with a deterministic dev adapter plus one real provider adapter shape so app features can be tested before provider credentials are required.

**Tech Stack:** Rust 2021, Axum 0.8, async-trait, reqwest, serde, thiserror, tokio, OpenAPI contract generation.

---

## Scope

This plan intentionally builds one complete vertical slice:

- AI model catalog and typed model requests.
- Application-level `AiClient` port and `AiService`.
- Infrastructure adapters that can be swapped without changing feature code.
- First feature client: personalized example sentence generation.
- Optional HTTP exposure through OpenAPI after the application service is proven.

This plan does not add a separate AI microservice, queue worker, prompt evaluation system, or UI model picker. Those are future split criteria from ADR 0005.

Current production hardening direction: move the AI model catalog from
hard-coded or environment-backed wiring into application data storage. The
database catalog owns model routing metadata, while provider API keys stay out
of the database and remain environment configuration until a secret store is
available.

## File Map

- Create `backend/src/application/ai/mod.rs`: module exports for the AI foundation.
- Create `backend/src/application/ai/model.rs`: model keys, providers, model catalog, and validation errors.
- Create `backend/src/application/ai/ports.rs`: `AiClient`, provider gateway traits, request/response DTOs, and shared errors.
- Create `backend/src/application/ai/prompts.rs`: prompt builders owned by the application layer.
- Create `backend/src/application/ai/service.rs`: `AiService` implementation that validates model keys and routes requests.
- Modify `backend/src/application/mod.rs`: export the `ai` module.
- Create `backend/src/application/example_sentences.rs`: first feature client with its own default model.
- Create `backend/src/infrastructure/ai/mod.rs`: infrastructure AI exports.
- Create `backend/src/infrastructure/ai/dev.rs`: deterministic dev adapter for tests and local development.
- Create `backend/src/infrastructure/ai/openai_compatible.rs`: HTTP adapter shape for OpenAI-compatible chat completion APIs.
- Modify `backend/src/infrastructure/mod.rs`: export the `ai` module.
- Modify `backend/src/bootstrap.rs`: load AI config and wire the selected adapter.
- Later HTTP slice: modify `contracts/openapi/openapi.yaml`, create `contracts/openapi/paths/example-sentences.yaml`, create request schema, and wire generated backend route code.
- Create an `AiModelCatalogRepository` port and database-backed implementation
  so allowed model mappings are operational data, not code.

## Task 1: AI Model Catalog

**Files:**
- Create: `backend/src/application/ai/mod.rs`
- Create: `backend/src/application/ai/model.rs`
- Modify: `backend/src/application/mod.rs`

- [ ] **Step 1: Write model catalog tests**

Add tests in `backend/src/application/ai/model.rs`:

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolves_allowed_model_key_to_provider_model() {
        let catalog = AiModelCatalog::default();

        let profile = catalog
            .resolve(AiModelKey::ExampleSentenceFast)
            .expect("model key should be allowed");

        assert_eq!(profile.provider, AiProvider::Dev);
        assert_eq!(profile.provider_model_id, "dev-example-sentence-fast");
    }

    #[test]
    fn rejects_model_key_when_catalog_does_not_allow_it() {
        let catalog = AiModelCatalog::new(vec![AiModelProfile {
            key: AiModelKey::WritingFeedbackQuality,
            provider: AiProvider::Dev,
            provider_model_id: "dev-writing-feedback-quality".to_string(),
        }]);

        let error = catalog
            .resolve(AiModelKey::ExampleSentenceFast)
            .expect_err("missing model key should be rejected");

        assert!(matches!(
            error,
            AiModelCatalogError::ModelNotAllowed {
                key: AiModelKey::ExampleSentenceFast
            }
        ));
    }
}
```

- [ ] **Step 2: Run the failing test**

Run from `backend/`:

```bash
cargo test application::ai::model --lib
```

Expected: fail because `application::ai` and catalog types do not exist.

- [ ] **Step 3: Implement the model catalog**

Create `backend/src/application/ai/mod.rs`:

```rust
pub mod model;
pub mod ports;
pub mod prompts;
pub mod service;
```

Create `backend/src/application/ai/model.rs`:

```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum AiModelKey {
    ExampleSentenceFast,
    WritingFeedbackQuality,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum AiProvider {
    Dev,
    OpenAiCompatible,
    Anthropic,
    Bedrock,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AiModelProfile {
    pub key: AiModelKey,
    pub provider: AiProvider,
    pub provider_model_id: String,
}

#[derive(Debug, Clone)]
pub struct AiModelCatalog {
    profiles: Vec<AiModelProfile>,
}

impl AiModelCatalog {
    pub fn new(profiles: Vec<AiModelProfile>) -> Self {
        Self { profiles }
    }

    pub fn resolve(&self, key: AiModelKey) -> Result<AiModelProfile, AiModelCatalogError> {
        self.profiles
            .iter()
            .find(|profile| profile.key == key)
            .cloned()
            .ok_or(AiModelCatalogError::ModelNotAllowed { key })
    }
}

impl Default for AiModelCatalog {
    fn default() -> Self {
        Self::new(vec![
            AiModelProfile {
                key: AiModelKey::ExampleSentenceFast,
                provider: AiProvider::Dev,
                provider_model_id: "dev-example-sentence-fast".to_string(),
            },
            AiModelProfile {
                key: AiModelKey::WritingFeedbackQuality,
                provider: AiProvider::Dev,
                provider_model_id: "dev-writing-feedback-quality".to_string(),
            },
        ])
    }
}

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum AiModelCatalogError {
    #[error("AI model is not allowed: {key:?}")]
    ModelNotAllowed { key: AiModelKey },
}
```

Modify `backend/src/application/mod.rs`:

```rust
pub mod ai;
pub mod auth;
pub mod ports;
pub mod queries;
```

- [ ] **Step 4: Run the passing test**

Run from `backend/`:

```bash
cargo test application::ai::model --lib
```

Expected: pass.

## Task 2: AI Client Port and Application Service

**Files:**
- Create: `backend/src/application/ai/ports.rs`
- Create: `backend/src/application/ai/service.rs`

- [ ] **Step 1: Write service routing tests**

Add tests in `backend/src/application/ai/service.rs`:

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use crate::application::ai::{
        model::{AiModelCatalog, AiModelKey, AiModelProfile, AiProvider},
        ports::{AiClient, AiClientError, AiCompletion, AiCompletionRequest, AiProviderGateway, ProviderCompletionRequest},
    };
    use async_trait::async_trait;
    use std::sync::{Arc, Mutex};

    #[tokio::test]
    async fn validates_model_key_and_routes_to_provider_gateway() {
        let gateway = Arc::new(RecordingGateway::default());
        let service = AiService::new(
            AiModelCatalog::new(vec![AiModelProfile {
                key: AiModelKey::ExampleSentenceFast,
                provider: AiProvider::Dev,
                provider_model_id: "dev-example-sentence-fast".to_string(),
            }]),
            gateway.clone(),
        );

        let completion = service
            .complete(AiCompletionRequest {
                model: AiModelKey::ExampleSentenceFast,
                system_prompt: "You write clear English examples.".to_string(),
                user_prompt: "Create a sentence for apply.".to_string(),
            })
            .await
            .expect("completion should succeed");

        assert_eq!(completion.text, "recorded completion");
        let requests = gateway.requests.lock().unwrap();
        assert_eq!(requests[0].provider, AiProvider::Dev);
        assert_eq!(requests[0].provider_model_id, "dev-example-sentence-fast");
    }

    #[tokio::test]
    async fn rejects_unapproved_model_before_calling_gateway() {
        let gateway = Arc::new(RecordingGateway::default());
        let service = AiService::new(AiModelCatalog::new(Vec::new()), gateway.clone());

        let error = service
            .complete(AiCompletionRequest {
                model: AiModelKey::ExampleSentenceFast,
                system_prompt: "system".to_string(),
                user_prompt: "user".to_string(),
            })
            .await
            .expect_err("unapproved model should fail");

        assert!(matches!(error, AiClientError::ModelNotAllowed { .. }));
        assert!(gateway.requests.lock().unwrap().is_empty());
    }

    #[derive(Default)]
    struct RecordingGateway {
        requests: Mutex<Vec<ProviderCompletionRequest>>,
    }

    #[async_trait]
    impl AiProviderGateway for RecordingGateway {
        async fn complete(
            &self,
            request: ProviderCompletionRequest,
        ) -> Result<AiCompletion, AiClientError> {
            self.requests.lock().unwrap().push(request);
            Ok(AiCompletion {
                text: "recorded completion".to_string(),
            })
        }
    }
}
```

- [ ] **Step 2: Run the failing test**

Run from `backend/`:

```bash
cargo test application::ai::service --lib
```

Expected: fail because `AiClient`, request DTOs, and `AiService` do not exist.

- [ ] **Step 3: Implement ports and service**

Create `backend/src/application/ai/ports.rs`:

```rust
use async_trait::async_trait;

use crate::application::ai::model::{AiModelCatalogError, AiModelKey, AiProvider};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AiCompletionRequest {
    pub model: AiModelKey,
    pub system_prompt: String,
    pub user_prompt: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProviderCompletionRequest {
    pub provider: AiProvider,
    pub provider_model_id: String,
    pub system_prompt: String,
    pub user_prompt: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AiCompletion {
    pub text: String,
}

#[async_trait]
pub trait AiClient: Send + Sync {
    async fn complete(&self, request: AiCompletionRequest) -> Result<AiCompletion, AiClientError>;
}

#[async_trait]
pub trait AiProviderGateway: Send + Sync {
    async fn complete(
        &self,
        request: ProviderCompletionRequest,
    ) -> Result<AiCompletion, AiClientError>;
}

#[derive(Debug, thiserror::Error)]
pub enum AiClientError {
    #[error(transparent)]
    ModelCatalog(#[from] AiModelCatalogError),
    #[error("AI model is not allowed")]
    ModelNotAllowed { source: AiModelCatalogError },
    #[error("AI provider failed")]
    ProviderUnavailable,
    #[error("AI provider returned an invalid response")]
    InvalidProviderResponse,
}
```

Create `backend/src/application/ai/service.rs`:

```rust
use std::sync::Arc;

use async_trait::async_trait;

use crate::application::ai::{
    model::AiModelCatalog,
    ports::{
        AiClient, AiClientError, AiCompletion, AiCompletionRequest, AiProviderGateway,
        ProviderCompletionRequest,
    },
};

#[derive(Clone)]
pub struct AiService {
    catalog: AiModelCatalog,
    gateway: Arc<dyn AiProviderGateway>,
}

impl AiService {
    pub fn new(catalog: AiModelCatalog, gateway: Arc<dyn AiProviderGateway>) -> Self {
        Self { catalog, gateway }
    }
}

#[async_trait]
impl AiClient for AiService {
    async fn complete(&self, request: AiCompletionRequest) -> Result<AiCompletion, AiClientError> {
        let profile = self
            .catalog
            .resolve(request.model)
            .map_err(|source| AiClientError::ModelNotAllowed { source })?;

        self.gateway
            .complete(ProviderCompletionRequest {
                provider: profile.provider,
                provider_model_id: profile.provider_model_id,
                system_prompt: request.system_prompt,
                user_prompt: request.user_prompt,
            })
            .await
    }
}
```

- [ ] **Step 4: Run the passing test**

Run from `backend/`:

```bash
cargo test application::ai::service --lib
```

Expected: pass.

## Task 3: Deterministic Dev Adapter

**Files:**
- Create: `backend/src/infrastructure/ai/mod.rs`
- Create: `backend/src/infrastructure/ai/dev.rs`
- Modify: `backend/src/infrastructure/mod.rs`

- [ ] **Step 1: Write dev adapter tests**

Add tests in `backend/src/infrastructure/ai/dev.rs`:

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use crate::application::ai::{
        model::AiProvider,
        ports::{AiProviderGateway, ProviderCompletionRequest},
    };

    #[tokio::test]
    async fn returns_deterministic_completion_for_local_development() {
        let gateway = DevAiProviderGateway;

        let completion = gateway
            .complete(ProviderCompletionRequest {
                provider: AiProvider::Dev,
                provider_model_id: "dev-example-sentence-fast".to_string(),
                system_prompt: "system".to_string(),
                user_prompt: "Create a sentence for apply.".to_string(),
            })
            .await
            .expect("dev gateway should complete");

        assert!(completion.text.contains("apply"));
    }
}
```

- [ ] **Step 2: Run the failing test**

Run from `backend/`:

```bash
cargo test infrastructure::ai::dev --lib
```

Expected: fail because the infrastructure AI module does not exist.

- [ ] **Step 3: Implement the dev adapter**

Create `backend/src/infrastructure/ai/mod.rs`:

```rust
mod dev;

pub use dev::DevAiProviderGateway;
```

Create `backend/src/infrastructure/ai/dev.rs`:

```rust
use async_trait::async_trait;

use crate::application::ai::{
    model::AiProvider,
    ports::{AiClientError, AiCompletion, AiProviderGateway, ProviderCompletionRequest},
};

#[derive(Debug, Clone)]
pub struct DevAiProviderGateway;

#[async_trait]
impl AiProviderGateway for DevAiProviderGateway {
    async fn complete(
        &self,
        request: ProviderCompletionRequest,
    ) -> Result<AiCompletion, AiClientError> {
        if request.provider != AiProvider::Dev {
            return Err(AiClientError::ProviderUnavailable);
        }

        Ok(AiCompletion {
            text: format!(
                "Dev AI response for model {}: {}",
                request.provider_model_id, request.user_prompt
            ),
        })
    }
}
```

Modify `backend/src/infrastructure/mod.rs`:

```rust
pub mod ai;
pub mod auth;
pub mod persistence;
```

- [ ] **Step 4: Run the passing test**

Run from `backend/`:

```bash
cargo test infrastructure::ai::dev --lib
```

Expected: pass.

## Task 4: Example Sentence Feature Client

**Files:**
- Create: `backend/src/application/ai/prompts.rs`
- Create: `backend/src/application/example_sentences.rs`
- Modify: `backend/src/application/mod.rs`

- [ ] **Step 1: Write feature service tests**

Add tests in `backend/src/application/example_sentences.rs`:

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use crate::application::ai::ports::{AiClient, AiClientError, AiCompletion, AiCompletionRequest};
    use async_trait::async_trait;
    use std::sync::{Arc, Mutex};

    #[tokio::test]
    async fn uses_feature_default_model_for_personalized_example_sentence() {
        let ai = Arc::new(RecordingAiClient::new("I applied for a new job yesterday."));
        let service = ExampleSentenceService::new(ai.clone());

        let sentence = service
            .generate_personalized(GenerateExampleSentenceInput {
                target_text: "apply".to_string(),
                user_context_summary: "The learner works in an office.".to_string(),
            })
            .await
            .expect("example sentence should be generated");

        assert_eq!(sentence.target_text, "apply");
        assert_eq!(sentence.target_sentence, "I applied for a new job yesterday.");
        assert_eq!(sentence.variant, ExampleSentenceVariant::Personalized);
        assert_eq!(
            ai.requests.lock().unwrap()[0].model,
            ExampleSentenceService::DEFAULT_MODEL
        );
    }

    struct RecordingAiClient {
        response: String,
        requests: Mutex<Vec<AiCompletionRequest>>,
    }

    impl RecordingAiClient {
        fn new(response: &str) -> Self {
            Self {
                response: response.to_string(),
                requests: Mutex::new(Vec::new()),
            }
        }
    }

    #[async_trait]
    impl AiClient for RecordingAiClient {
        async fn complete(
            &self,
            request: AiCompletionRequest,
        ) -> Result<AiCompletion, AiClientError> {
            self.requests.lock().unwrap().push(request);
            Ok(AiCompletion {
                text: self.response.clone(),
            })
        }
    }
}
```

- [ ] **Step 2: Run the failing test**

Run from `backend/`:

```bash
cargo test application::example_sentences --lib
```

Expected: fail because the feature service does not exist.

- [ ] **Step 3: Implement prompt builder and feature service**

Create `backend/src/application/ai/prompts.rs`:

```rust
pub fn personalized_example_sentence_system_prompt() -> String {
    "You create one natural English example sentence for a learner. Return only the sentence."
        .to_string()
}

pub fn personalized_example_sentence_user_prompt(
    target_text: &str,
    user_context_summary: &str,
) -> String {
    format!(
        "Target text: {target_text}\nLearner context: {user_context_summary}\nCreate one useful sentence."
    )
}
```

Create `backend/src/application/example_sentences.rs`:

```rust
use std::sync::Arc;

use crate::application::ai::{
    model::AiModelKey,
    ports::{AiClient, AiClientError, AiCompletionRequest},
    prompts::{
        personalized_example_sentence_system_prompt,
        personalized_example_sentence_user_prompt,
    },
};

#[derive(Clone)]
pub struct ExampleSentenceService {
    ai: Arc<dyn AiClient>,
}

impl ExampleSentenceService {
    pub const DEFAULT_MODEL: AiModelKey = AiModelKey::ExampleSentenceFast;

    pub fn new(ai: Arc<dyn AiClient>) -> Self {
        Self { ai }
    }

    pub async fn generate_personalized(
        &self,
        input: GenerateExampleSentenceInput,
    ) -> Result<GeneratedExampleSentence, ExampleSentenceError> {
        let completion = self
            .ai
            .complete(AiCompletionRequest {
                model: Self::DEFAULT_MODEL,
                system_prompt: personalized_example_sentence_system_prompt(),
                user_prompt: personalized_example_sentence_user_prompt(
                    &input.target_text,
                    &input.user_context_summary,
                ),
            })
            .await?;

        Ok(GeneratedExampleSentence {
            target_text: input.target_text,
            target_sentence: completion.text,
            variant: ExampleSentenceVariant::Personalized,
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GenerateExampleSentenceInput {
    pub target_text: String,
    pub user_context_summary: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GeneratedExampleSentence {
    pub target_text: String,
    pub target_sentence: String,
    pub variant: ExampleSentenceVariant,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExampleSentenceVariant {
    Personalized,
}

#[derive(Debug, thiserror::Error)]
pub enum ExampleSentenceError {
    #[error(transparent)]
    Ai(#[from] AiClientError),
}
```

Modify `backend/src/application/mod.rs`:

```rust
pub mod ai;
pub mod auth;
pub mod example_sentences;
pub mod ports;
pub mod queries;
```

- [ ] **Step 4: Run the passing test**

Run from `backend/`:

```bash
cargo test application::example_sentences --lib
```

Expected: pass.

## Task 5: Bootstrap Wiring

**Files:**
- Modify: `backend/src/bootstrap.rs`

- [ ] **Step 1: Write configuration tests**

Add tests in the existing `#[cfg(test)] mod tests` in `backend/src/bootstrap.rs`:

```rust
#[test]
fn reads_ai_model_catalog_config_from_environment_values() {
    let env = HashMap::from([
        ("AI_MODEL_CATALOG_REPOSITORY", "dynamodb"),
        ("AI_MODEL_CATALOG_DYNAMODB_TABLE_NAME", "english-local-learning-catalog"),
    ]);

    let config = AppConfig::from_env_values(|key| env.get(key).copied().map(str::to_string))
        .expect("config should load");

    assert_eq!(config.ai_model_catalog_repository, AiModelCatalogRepositoryKind::DynamoDb);
    assert_eq!(
        config.ai_model_catalog_dynamodb_table_name.as_deref(),
        Some("english-local-learning-catalog")
    );
}
```

- [ ] **Step 2: Run the failing test**

Run from `backend/`:

```bash
cargo test bootstrap::tests::reads_ai_model_catalog_config_from_environment_values --lib
```

Expected: fail because `AiModelCatalogRepositoryKind` and catalog repository config do not exist.

- [ ] **Step 3: Add config structs and parser**

Modify `backend/src/bootstrap.rs` imports:

```rust
use crate::{
    application::{
        ai::{model::{AiModelCatalog, AiModelKey, AiModelProfile, AiProvider}, service::AiService},
        // existing imports...
    },
    infrastructure::{
        ai::DevAiProviderGateway,
        // existing imports...
    },
    // existing imports...
};
```

Add fields:

```rust
#[derive(Debug, Clone)]
pub struct AppConfig {
    // existing fields...
    pub ai_model_catalog_repository: AiModelCatalogRepositoryKind,
    pub ai_model_catalog_dynamodb_table_name: Option<String>,
    pub ai: AiConfig,
}

#[derive(Debug, Clone)]
pub struct AiConfig {
    pub openai_compatible_endpoint: Option<String>,
    pub openai_compatible_api_key: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AiModelCatalogRepositoryKind {
    InMemory,
    DynamoDb,
}
```

Add parsing in `from_env_values`:

```rust
let ai_model_catalog_repository = get_env("AI_MODEL_CATALOG_REPOSITORY")
    .unwrap_or_else(|| "in_memory".to_string())
    .parse()?;
let ai_model_catalog_dynamodb_table_name =
    get_env("AI_MODEL_CATALOG_DYNAMODB_TABLE_NAME").or_else(|| dynamodb_table_name.clone());
let ai = AiConfig {
    openai_compatible_endpoint: get_env("AI_OPENAI_COMPATIBLE_ENDPOINT"),
    openai_compatible_api_key: get_env("AI_OPENAI_COMPATIBLE_API_KEY"),
};
```

Add `ai` to the returned `AppConfig`.

Add parser and error:

```rust
impl std::str::FromStr for AiModelCatalogRepositoryKind {
    type Err = BootstrapError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "in_memory" => Ok(Self::InMemory),
            "dynamodb" => Ok(Self::DynamoDb),
            _ => Err(BootstrapError::InvalidAiModelCatalogRepository {
                value: value.to_string(),
            }),
        }
    }
}

#[derive(Debug, Error)]
pub enum BootstrapError {
    // existing variants...
    #[error("invalid AI_MODEL_CATALOG_REPOSITORY: {value}")]
    InvalidAiModelCatalogRepository { value: String },
}
```

- [ ] **Step 4: Wire an `AiService` builder**

Add helper functions in `backend/src/bootstrap.rs`:

```rust
fn build_ai_client(config: &AppConfig) -> Arc<dyn crate::application::ai::ports::AiClient> {
    let catalog = AiModelCatalog::new(vec![AiModelProfile {
        key: AiModelKey::ExampleSentenceFast,
        provider: match config.ai.provider {
            AiProviderKind::Dev => AiProvider::Dev,
        },
        provider_model_id: config.ai.example_sentence_model_id.clone(),
    }]);

    let gateway: Arc<dyn crate::application::ai::ports::AiProviderGateway> =
        match config.ai.provider {
            AiProviderKind::Dev => Arc::new(DevAiProviderGateway),
        };

    Arc::new(AiService::new(catalog, gateway))
}
```

Do not expose this through HTTP yet. This task only proves DI and config.

- [ ] **Step 5: Run config and full backend tests**

Run from `backend/`:

```bash
cargo test
```

Expected: all tests pass.

## Task 6: OpenAI-Compatible Adapter Shape

**Files:**
- Create: `backend/src/infrastructure/ai/openai_compatible.rs`
- Modify: `backend/src/infrastructure/ai/mod.rs`
- Modify: `backend/src/bootstrap.rs`

- [ ] **Step 1: Write request mapping test**

Add tests in `backend/src/infrastructure/ai/openai_compatible.rs`:

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use crate::application::ai::{model::AiProvider, ports::ProviderCompletionRequest};

    #[test]
    fn builds_chat_completion_payload_without_leaking_feature_model_key() {
        let request = ProviderCompletionRequest {
            provider: AiProvider::OpenAiCompatible,
            provider_model_id: "gpt-4o-mini".to_string(),
            system_prompt: "system prompt".to_string(),
            user_prompt: "user prompt".to_string(),
        };

        let payload = OpenAiCompatiblePayload::from_request(&request);

        assert_eq!(payload.model, "gpt-4o-mini");
        assert_eq!(payload.messages[0].role, "system");
        assert_eq!(payload.messages[1].role, "user");
    }
}
```

- [ ] **Step 2: Run the failing test**

Run from `backend/`:

```bash
cargo test infrastructure::ai::openai_compatible --lib
```

Expected: fail because the adapter module does not exist.

- [ ] **Step 3: Implement adapter payload and gateway**

Create `backend/src/infrastructure/ai/openai_compatible.rs`:

```rust
use async_trait::async_trait;
use reqwest::Client;
use serde::{Deserialize, Serialize};

use crate::application::ai::{
    model::AiProvider,
    ports::{AiClientError, AiCompletion, AiProviderGateway, ProviderCompletionRequest},
};

#[derive(Clone)]
pub struct OpenAiCompatibleGateway {
    client: Client,
    endpoint: String,
    api_key: String,
}

impl OpenAiCompatibleGateway {
    pub fn new(endpoint: String, api_key: String) -> Self {
        Self {
            client: Client::new(),
            endpoint,
            api_key,
        }
    }
}

#[async_trait]
impl AiProviderGateway for OpenAiCompatibleGateway {
    async fn complete(
        &self,
        request: ProviderCompletionRequest,
    ) -> Result<AiCompletion, AiClientError> {
        if request.provider != AiProvider::OpenAiCompatible {
            return Err(AiClientError::ProviderUnavailable);
        }

        let response = self
            .client
            .post(&self.endpoint)
            .bearer_auth(&self.api_key)
            .json(&OpenAiCompatiblePayload::from_request(&request))
            .send()
            .await
            .map_err(|_| AiClientError::ProviderUnavailable)?;

        let body = response
            .error_for_status()
            .map_err(|_| AiClientError::ProviderUnavailable)?
            .json::<OpenAiCompatibleResponse>()
            .await
            .map_err(|_| AiClientError::InvalidProviderResponse)?;

        body.choices
            .first()
            .map(|choice| AiCompletion {
                text: choice.message.content.clone(),
            })
            .ok_or(AiClientError::InvalidProviderResponse)
    }
}

#[derive(Debug, Serialize, PartialEq, Eq)]
struct OpenAiCompatiblePayload {
    model: String,
    messages: Vec<OpenAiCompatibleMessage>,
}

impl OpenAiCompatiblePayload {
    fn from_request(request: &ProviderCompletionRequest) -> Self {
        Self {
            model: request.provider_model_id.clone(),
            messages: vec![
                OpenAiCompatibleMessage {
                    role: "system".to_string(),
                    content: request.system_prompt.clone(),
                },
                OpenAiCompatibleMessage {
                    role: "user".to_string(),
                    content: request.user_prompt.clone(),
                },
            ],
        }
    }
}

#[derive(Debug, Serialize, PartialEq, Eq)]
struct OpenAiCompatibleMessage {
    role: String,
    content: String,
}

#[derive(Debug, Deserialize)]
struct OpenAiCompatibleResponse {
    choices: Vec<OpenAiCompatibleChoice>,
}

#[derive(Debug, Deserialize)]
struct OpenAiCompatibleChoice {
    message: OpenAiCompatibleResponseMessage,
}

#[derive(Debug, Deserialize)]
struct OpenAiCompatibleResponseMessage {
    content: String,
}
```

Modify `backend/src/infrastructure/ai/mod.rs`:

```rust
mod dev;
mod openai_compatible;

pub use dev::DevAiProviderGateway;
pub use openai_compatible::OpenAiCompatibleGateway;
```

- [ ] **Step 4: Run adapter tests**

Run from `backend/`:

```bash
cargo test infrastructure::ai::openai_compatible --lib
```

Expected: pass.

- [ ] **Step 5: Extend bootstrap config without making it default**

Add `openai_compatible` parsing only when explicitly configured:

```rust
pub enum AiProviderKind {
    Dev,
    OpenAiCompatible,
}
```

Use catalog seed values plus provider credentials:

- `AI_MODEL_CATALOG_EXAMPLE_SENTENCE_PROVIDER=open_ai_compatible`
- `AI_MODEL_CATALOG_EXAMPLE_SENTENCE_PROVIDER_MODEL_ID=gpt-4o-mini`
- `AI_OPENAI_COMPATIBLE_ENDPOINT`
- `AI_OPENAI_COMPATIBLE_API_KEY`

Expected behavior:

- Missing endpoint or API key returns `BootstrapError`.
- Default local development remains catalog provider `dev`.

## Task 7: HTTP Contract for Personalized Example Sentences

**Files:**
- Create: `contracts/openapi/components/schemas/GenerateExampleSentenceRequest.yaml`
- Create: `contracts/openapi/paths/example-sentences.yaml`
- Modify: `contracts/openapi/openapi.yaml`
- Modify: `backend/src/user_interface/http/routes.rs`
- Add or modify generated OpenAPI artifacts according to the repository generation workflow.
- Test: `backend/tests/http_example_sentences.rs`

- [ ] **Step 1: Add OpenAPI request schema**

Create `contracts/openapi/components/schemas/GenerateExampleSentenceRequest.yaml`:

```yaml
type: object
required:
  - targetText
  - userContextSummary
properties:
  targetText:
    type: string
    minLength: 1
  userContextSummary:
    type: string
    minLength: 1
additionalProperties: false
```

- [ ] **Step 2: Add OpenAPI path**

Create `contracts/openapi/paths/example-sentences.yaml`:

```yaml
post:
  summary: Generate a personalized example sentence
  operationId: generateExampleSentence
  security:
    - BearerAuth: []
  requestBody:
    required: true
    content:
      application/json:
        schema:
          $ref: "../components/schemas/GenerateExampleSentenceRequest.yaml"
  responses:
    "200":
      description: Personalized example sentence
      content:
        application/json:
          schema:
            $ref: "../components/schemas/ExampleSentence.yaml"
          examples:
            office:
              value:
                id: "018f3f9c-7d3b-7a8a-b4e2-8f4a4a0b0001"
                targetText: "apply"
                targetSentence: "I applied for a new job yesterday."
                sourceTranslation: "私は昨日、新しい仕事に応募しました。"
                variant: "personalized"
                personalization:
                  contextSummary: "The learner works in an office."
                usageNote: "Use apply for jobs, schools, and programs."
    "401":
      description: Authentication required
      content:
        application/json:
          schema:
            $ref: "../components/schemas/AuthErrorResponse.yaml"
```

Modify `contracts/openapi/openapi.yaml`:

```yaml
paths:
  /auth/session:
    $ref: "./paths/auth-session.yaml"
  /example-sentences:
    $ref: "./paths/example-sentences.yaml"
  /learning-paths:
    $ref: "./paths/learning-paths.yaml"
components:
  schemas:
    GenerateExampleSentenceRequest:
      $ref: "./components/schemas/GenerateExampleSentenceRequest.yaml"
```

- [ ] **Step 3: Regenerate OpenAPI backend artifacts**

Run from repository root:

```bash
task generate:backend:openapi
```

Expected: `scripts/generate-backend-openapi.sh` regenerates `backend/generated/openapi` from `contracts/openapi/openapi.yaml`. The generated backend types include `GenerateExampleSentenceRequest`, `GenerateExampleSentenceResponse`, and the `Default` server trait requires `generate_example_sentence`.

- [ ] **Step 4: Write HTTP integration test**

Create `backend/tests/http_example_sentences.rs` following `backend/tests/http_learning_catalog.rs`:

```rust
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
};
use english_backend::bootstrap;
use serde_json::Value;
use tower::ServiceExt;

const TEST_HOST: &str = "localhost:18080";

#[tokio::test]
async fn generates_personalized_example_sentence_with_dev_ai() {
    let app = bootstrap::build_app().await.unwrap().router;

    let response = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/example-sentences")
                .header("host", TEST_HOST)
                .header("authorization", "Bearer header.payload.signature")
                .header("content-type", "application/json")
                .body(Body::from(
                    r#"{"targetText":"apply","userContextSummary":"The learner works in an office."}"#,
                ))
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);

    let body = to_json(response.into_body()).await;
    assert_eq!(body["targetText"], "apply");
    assert_eq!(body["variant"], "personalized");
}

async fn to_json(body: Body) -> Value {
    let bytes = to_bytes(body, usize::MAX).await.unwrap();
    serde_json::from_slice(&bytes).unwrap()
}
```

- [ ] **Step 5: Wire route implementation**

Modify `backend/src/user_interface/http/routes.rs`:

- Add `ExampleSentenceService` to `ApiImpl`.
- Add it to `router` and `router_with_auth_verifier`.
- Implement the generated `generate_example_sentence` method.
- Convert application output to generated OpenAPI models.
- Generate a UUID v7 for the response `id`.
- Keep authentication behavior consistent with `get_auth_session`.

Use this response mapping shape:

```rust
models::ExampleSentence {
    id: uuid::Uuid::now_v7().to_string(),
    target_text: generated.target_text,
    target_sentence: generated.target_sentence,
    source_translation: String::new(),
    variant: models::ExampleSentenceVariant::Personalized,
    personalization: Some(Box::new(models::ExampleSentencePersonalization {
        context_summary: Some(request.user_context_summary.clone()),
        personalized_from_user_context_at: None,
    })),
    usage_note: None,
}
```

- [ ] **Step 6: Run HTTP tests**

Run from `backend/`:

```bash
cargo test --test http_example_sentences
```

Expected: pass.

## Task 8: Documentation and Extraction Notes

**Files:**
- Modify: `docs/BACKEND.md`
- Modify: `docs/adr/0005-ai-integration-inside-rust-backend-first.md` only if implementation reveals a changed decision.

- [ ] **Step 1: Document environment variables**

Add to `docs/BACKEND.md`:

```markdown
## AI Configuration

The backend starts with AI integration inside the Rust service. Feature clients request typed model keys, and the AI foundation validates those keys against the application-owned AI model catalog.

Local deterministic AI:

- `AI_MODEL_CATALOG_REPOSITORY=dynamodb`
- `AI_MODEL_CATALOG_EXAMPLE_SENTENCE_PROVIDER=dev`
- `AI_MODEL_CATALOG_EXAMPLE_SENTENCE_PROVIDER_MODEL_ID=dev-example-sentence-fast`

OpenAI-compatible provider:

- `AI_MODEL_CATALOG_REPOSITORY=dynamodb`
- `AI_MODEL_CATALOG_EXAMPLE_SENTENCE_PROVIDER=open_ai_compatible`
- `AI_MODEL_CATALOG_EXAMPLE_SENTENCE_PROVIDER_MODEL_ID=gpt-4o-mini`
- `AI_OPENAI_COMPATIBLE_ENDPOINT=https://api.openai.com/v1/chat/completions`
- `AI_OPENAI_COMPATIBLE_API_KEY=<secret>`

UI users do not choose AI models. Feature services own default model choices.
```

- [ ] **Step 2: Document extraction boundary**

Add to `docs/BACKEND.md`:

```markdown
### AI Extraction Boundary

If AI processing later moves to SQS workers or a separate service, keep feature services dependent on the same `AiClient` request shape. Replace the current provider gateway with an adapter that publishes jobs or calls the external AI service. Do not move provider-specific model names into feature services.
```

- [ ] **Step 3: Run final verification**

Run from `backend/`:

```bash
cargo test
```

Expected: all backend tests pass.

Run from repository root:

```bash
git diff -- docs/adr/0005-ai-integration-inside-rust-backend-first.md docs/UBIQUITOUS.md docs/BACKEND.md backend/src contracts/openapi
```

Expected: changes are limited to the AI foundation, first example sentence feature, OpenAPI contract, and docs.

## Self-Review

- ADR 0005 coverage: the plan keeps AI inside Rust, defines application AI ports, hides provider details in infrastructure adapters, and avoids a separate microservice.
- Model switching coverage: each feature client requests a typed model key, the AI foundation owns the accepted model catalog, and provider model identifiers stay outside feature code.
- Current app coverage: the first vertical slice supports personalized example sentences, which is already part of the app's learning content model.
- Extraction coverage: `AiClient` is the stable application boundary; future SQS or external-service extraction can replace the gateway without changing feature clients.
- Placeholder scan: no `TBD` or unbounded "add appropriate" steps remain.
