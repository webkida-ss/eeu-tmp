use std::sync::Arc;

use async_trait::async_trait;

use crate::application::ai::{
    model::AiModelCatalogError,
    ports::{
        AiClient, AiClientError, AiCompletion, AiCompletionRequest, AiModelCatalogRepository,
        AiProviderGateway, ProviderCompletionRequest,
    },
};

#[derive(Clone)]
pub struct AiService {
    catalog: Arc<dyn AiModelCatalogRepository>,
    gateway: Arc<dyn AiProviderGateway>,
}

impl AiService {
    pub fn new(
        catalog: Arc<dyn AiModelCatalogRepository>,
        gateway: Arc<dyn AiProviderGateway>,
    ) -> Self {
        Self { catalog, gateway }
    }
}

#[async_trait]
impl AiClient for AiService {
    async fn complete(&self, request: AiCompletionRequest) -> Result<AiCompletion, AiClientError> {
        let profile =
            self.catalog
                .resolve_model(request.model)
                .await
                .map_err(|source| match source {
                    AiModelCatalogError::ModelNotAllowed { .. } => {
                        AiClientError::ModelNotAllowed { source }
                    }
                    AiModelCatalogError::Unavailable => AiClientError::ModelCatalogUnavailable,
                })?;

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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::application::ai::{
        model::{AiModelCatalog, AiModelKey, AiModelProfile, AiProvider},
        ports::{
            AiClient, AiClientError, AiCompletion, AiCompletionRequest, AiProviderGateway,
            ProviderCompletionRequest,
        },
    };
    use async_trait::async_trait;
    use std::sync::{Arc, Mutex};

    #[tokio::test]
    async fn validates_model_key_and_routes_to_provider_gateway() {
        let gateway = Arc::new(RecordingGateway::default());
        let service = AiService::new(
            Arc::new(AiModelCatalog::new(vec![AiModelProfile {
                key: AiModelKey::ExampleSentenceFast,
                provider: AiProvider::Dev,
                provider_model_id: "dev-example-sentence-fast".to_string(),
            }])),
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
        let service = AiService::new(Arc::new(AiModelCatalog::new(Vec::new())), gateway.clone());

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
