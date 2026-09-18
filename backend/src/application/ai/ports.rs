use async_trait::async_trait;

use crate::application::ai::model::{
    AiModelCatalog, AiModelCatalogError, AiModelKey, AiModelProfile, AiProvider,
};

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

#[async_trait]
pub trait AiModelCatalogRepository: Send + Sync {
    async fn resolve_model(&self, key: AiModelKey) -> Result<AiModelProfile, AiModelCatalogError>;
}

#[async_trait]
impl AiModelCatalogRepository for AiModelCatalog {
    async fn resolve_model(&self, key: AiModelKey) -> Result<AiModelProfile, AiModelCatalogError> {
        self.resolve(key)
    }
}

#[derive(Debug, thiserror::Error)]
pub enum AiClientError {
    #[error("AI model is not allowed")]
    ModelNotAllowed { source: AiModelCatalogError },
    #[error("AI model catalog is unavailable")]
    ModelCatalogUnavailable,
    #[error("AI provider failed")]
    ProviderUnavailable,
    #[error("AI provider returned an error status {status}: {body}")]
    ProviderHttpStatus { status: u16, body: String },
    #[error("AI provider returned an invalid response")]
    InvalidProviderResponse,
}
