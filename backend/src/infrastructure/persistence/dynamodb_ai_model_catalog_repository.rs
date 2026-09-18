use std::collections::HashMap;

use async_trait::async_trait;
use aws_sdk_dynamodb::{types::AttributeValue, Client};

use crate::application::ai::{
    model::{AiModelCatalogError, AiModelKey, AiModelProfile},
    ports::AiModelCatalogRepository,
};

const CATALOG_PK: &str = "AI_MODEL_CATALOG";
const MODEL_SK_PREFIX: &str = "MODEL#";
const DOCUMENT_ATTRIBUTE: &str = "document";

#[derive(Debug, Clone)]
pub struct DynamoDbAiModelCatalogRepositoryConfig {
    pub table_name: String,
}

#[derive(Debug, Clone)]
pub struct DynamoDbAiModelCatalogRepository {
    client: Client,
    table_name: String,
}

impl DynamoDbAiModelCatalogRepository {
    pub fn new(client: Client, config: DynamoDbAiModelCatalogRepositoryConfig) -> Self {
        Self {
            client,
            table_name: config.table_name,
        }
    }

    fn model_key(model_key: AiModelKey) -> HashMap<String, AttributeValue> {
        HashMap::from([
            ("pk".to_string(), AttributeValue::S(CATALOG_PK.to_string())),
            (
                "sk".to_string(),
                AttributeValue::S(format!("{MODEL_SK_PREFIX}{}", model_key.as_str())),
            ),
        ])
    }

    fn parse_item(
        item: HashMap<String, AttributeValue>,
    ) -> Result<AiModelProfile, AiModelCatalogError> {
        let Some(AttributeValue::S(document)) = item.get(DOCUMENT_ATTRIBUTE) else {
            tracing::error!("DynamoDB AI model catalog item is missing document attribute");
            return Err(AiModelCatalogError::Unavailable);
        };

        serde_json::from_str(document).map_err(|source| {
            tracing::error!(%source, "failed to deserialize DynamoDB AI model catalog document");
            AiModelCatalogError::Unavailable
        })
    }
}

#[async_trait]
impl AiModelCatalogRepository for DynamoDbAiModelCatalogRepository {
    async fn resolve_model(&self, key: AiModelKey) -> Result<AiModelProfile, AiModelCatalogError> {
        let output = self
            .client
            .get_item()
            .table_name(&self.table_name)
            .set_key(Some(Self::model_key(key)))
            .send()
            .await
            .map_err(|source| {
                tracing::error!(%source, ?key, "failed to get DynamoDB AI model catalog item");
                AiModelCatalogError::Unavailable
            })?;

        output
            .item
            .map(Self::parse_item)
            .transpose()?
            .ok_or(AiModelCatalogError::ModelNotAllowed { key })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn builds_ai_model_catalog_key() {
        let key = DynamoDbAiModelCatalogRepository::model_key(AiModelKey::ExampleSentenceFast);

        assert_eq!(
            key.get("pk"),
            Some(&AttributeValue::S(CATALOG_PK.to_string()))
        );
        assert_eq!(
            key.get("sk"),
            Some(&AttributeValue::S(
                "MODEL#example_sentence_fast".to_string()
            ))
        );
    }
}
