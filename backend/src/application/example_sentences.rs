use std::sync::Arc;

use crate::application::ai::{
    model::AiModelKey,
    ports::{AiClient, AiClientError, AiCompletionRequest},
    prompts::{
        personalized_example_sentence_system_prompt, personalized_example_sentence_user_prompt,
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::application::ai::ports::{
        AiClient, AiClientError, AiCompletion, AiCompletionRequest,
    };
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
        assert_eq!(
            sentence.target_sentence,
            "I applied for a new job yesterday."
        );
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
