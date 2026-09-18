use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AiModelKey {
    ExampleSentenceFast,
    WritingFeedbackQuality,
}

impl AiModelKey {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::ExampleSentenceFast => "example_sentence_fast",
            Self::WritingFeedbackQuality => "writing_feedback_quality",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AiProvider {
    Dev,
    OpenAiCompatible,
    Anthropic,
    Bedrock,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
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
    #[error("AI model catalog is unavailable")]
    Unavailable,
}

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

    #[test]
    fn serializes_model_profile_for_database_document() {
        let profile = AiModelProfile {
            key: AiModelKey::ExampleSentenceFast,
            provider: AiProvider::OpenAiCompatible,
            provider_model_id: "gpt-4o-mini".to_string(),
        };

        let document = serde_json::to_string(&profile).expect("profile should serialize");

        assert_eq!(
            document,
            r#"{"key":"example_sentence_fast","provider":"open_ai_compatible","providerModelId":"gpt-4o-mini"}"#
        );
    }
}
