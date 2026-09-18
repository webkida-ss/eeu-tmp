use std::{collections::HashMap, sync::Arc};

use async_trait::async_trait;

use crate::application::ai::{
    model::AiProvider,
    ports::{AiClientError, AiCompletion, AiProviderGateway, ProviderCompletionRequest},
};

#[derive(Default)]
pub struct RoutingAiProviderGateway {
    gateways: HashMap<AiProvider, Arc<dyn AiProviderGateway>>,
}

impl RoutingAiProviderGateway {
    pub fn new(gateways: HashMap<AiProvider, Arc<dyn AiProviderGateway>>) -> Self {
        Self { gateways }
    }
}

#[async_trait]
impl AiProviderGateway for RoutingAiProviderGateway {
    async fn complete(
        &self,
        request: ProviderCompletionRequest,
    ) -> Result<AiCompletion, AiClientError> {
        let Some(gateway) = self.gateways.get(&request.provider) else {
            tracing::error!(
                provider = ?request.provider,
                "AI provider gateway is not configured"
            );
            return Err(AiClientError::ProviderUnavailable);
        };

        gateway.complete(request).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    #[tokio::test]
    async fn routes_request_by_provider() {
        let gateway = Arc::new(RecordingGateway::default());
        let routing = RoutingAiProviderGateway::new(HashMap::from([(
            AiProvider::Dev,
            gateway.clone() as Arc<dyn AiProviderGateway>,
        )]));

        let completion = routing
            .complete(ProviderCompletionRequest {
                provider: AiProvider::Dev,
                provider_model_id: "dev-example-sentence-fast".to_string(),
                system_prompt: "system".to_string(),
                user_prompt: "user".to_string(),
            })
            .await
            .expect("request should route");

        assert_eq!(completion.text, "routed completion");
        assert_eq!(gateway.requests.lock().unwrap().len(), 1);
    }

    #[tokio::test]
    async fn rejects_unconfigured_provider() {
        let routing = RoutingAiProviderGateway::default();

        let error = routing
            .complete(ProviderCompletionRequest {
                provider: AiProvider::OpenAiCompatible,
                provider_model_id: "gpt-4o-mini".to_string(),
                system_prompt: "system".to_string(),
                user_prompt: "user".to_string(),
            })
            .await
            .expect_err("missing provider gateway should fail");

        assert!(matches!(error, AiClientError::ProviderUnavailable));
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
                text: "routed completion".to_string(),
            })
        }
    }
}
