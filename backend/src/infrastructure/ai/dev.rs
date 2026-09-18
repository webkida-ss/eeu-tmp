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
