use async_trait::async_trait;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use tracing::{error, info};

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

        info!(
            provider = "openai_compatible",
            model = %request.provider_model_id,
            "AI completion request"
        );

        let response = self
            .client
            .post(&self.endpoint)
            .bearer_auth(&self.api_key)
            .json(&OpenAiCompatiblePayload::from_request(&request))
            .send()
            .await
            .map_err(|source| {
                error!(error = ?source, "OpenAI-compatible provider request failed");
                AiClientError::ProviderUnavailable
            })?;

        let status = response.status();

        if !status.is_success() {
            let body = response
                .text()
                .await
                .unwrap_or_else(|_| "<failed to read provider error body>".to_string());
            let body = truncate_provider_body(&body);

            error!(
                status = status.as_u16(),
                body = %body,
                "OpenAI-compatible provider returned error status"
            );

            return Err(AiClientError::ProviderHttpStatus {
                status: status.as_u16(),
                body,
            });
        }

        let body = response
            .json::<OpenAiCompatibleResponse>()
            .await
            .map_err(|source| {
                error!(
                    error = ?source,
                    "OpenAI-compatible provider returned invalid response"
                );
                AiClientError::InvalidProviderResponse
            })?;

        body.choices
            .first()
            .map(|choice| AiCompletion {
                text: choice.message.content.clone(),
            })
            .ok_or(AiClientError::InvalidProviderResponse)
    }
}

fn truncate_provider_body(body: &str) -> String {
    const MAX_PROVIDER_ERROR_BODY_LENGTH: usize = 512;

    if body.chars().count() <= MAX_PROVIDER_ERROR_BODY_LENGTH {
        return body.to_string();
    }

    body.chars()
        .take(MAX_PROVIDER_ERROR_BODY_LENGTH)
        .collect::<String>()
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

    #[test]
    fn truncates_provider_error_body_for_logs() {
        let body = "x".repeat(600);

        let truncated = truncate_provider_body(&body);

        assert_eq!(truncated.len(), 512);
    }
}
