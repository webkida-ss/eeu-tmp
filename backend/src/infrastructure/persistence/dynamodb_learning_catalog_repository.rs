use std::collections::HashMap;

use async_trait::async_trait;
use aws_sdk_dynamodb::{types::AttributeValue, Client};

use crate::{
    application::ports::{LearningCatalogRepository, LearningCatalogRepositoryError},
    domain::learning_catalog::{Course, LearningPath},
};

const CATALOG_PK: &str = "CATALOG";
const PATH_SK_PREFIX: &str = "PATH#";
const DOCUMENT_ATTRIBUTE: &str = "document";

#[derive(Debug, Clone)]
pub struct DynamoDbLearningCatalogRepositoryConfig {
    pub table_name: String,
}

#[derive(Debug, Clone)]
pub struct DynamoDbLearningCatalogRepository {
    client: Client,
    table_name: String,
}

impl DynamoDbLearningCatalogRepository {
    pub fn new(client: Client, config: DynamoDbLearningCatalogRepositoryConfig) -> Self {
        Self {
            client,
            table_name: config.table_name,
        }
    }

    fn path_key(path_id: &str) -> HashMap<String, AttributeValue> {
        HashMap::from([
            ("pk".to_string(), AttributeValue::S(CATALOG_PK.to_string())),
            (
                "sk".to_string(),
                AttributeValue::S(format!("{PATH_SK_PREFIX}{path_id}")),
            ),
        ])
    }

    fn parse_item(
        item: HashMap<String, AttributeValue>,
    ) -> Result<LearningPath, LearningCatalogRepositoryError> {
        let Some(AttributeValue::S(document)) = item.get(DOCUMENT_ATTRIBUTE) else {
            tracing::error!("DynamoDB learning catalog item is missing document attribute");
            return Err(LearningCatalogRepositoryError::Unavailable);
        };

        serde_json::from_str(document).map_err(|source| {
            tracing::error!(%source, "failed to deserialize DynamoDB learning catalog document");
            LearningCatalogRepositoryError::Unavailable
        })
    }
}

#[async_trait]
impl LearningCatalogRepository for DynamoDbLearningCatalogRepository {
    async fn list_learning_paths(
        &self,
    ) -> Result<Vec<LearningPath>, LearningCatalogRepositoryError> {
        let output = self
            .client
            .query()
            .table_name(&self.table_name)
            .key_condition_expression("pk = :pk AND begins_with(sk, :sk_prefix)")
            .expression_attribute_values(":pk", AttributeValue::S(CATALOG_PK.to_string()))
            .expression_attribute_values(
                ":sk_prefix",
                AttributeValue::S(PATH_SK_PREFIX.to_string()),
            )
            .send()
            .await
            .map_err(|source| {
                tracing::error!(%source, "failed to query DynamoDB learning catalog");
                LearningCatalogRepositoryError::Unavailable
            })?;

        output
            .items
            .unwrap_or_default()
            .into_iter()
            .map(Self::parse_item)
            .collect()
    }

    async fn find_learning_path(
        &self,
        path_id: &str,
    ) -> Result<Option<LearningPath>, LearningCatalogRepositoryError> {
        let output = self
            .client
            .get_item()
            .table_name(&self.table_name)
            .set_key(Some(Self::path_key(path_id)))
            .send()
            .await
            .map_err(|source| {
                tracing::error!(%source, path_id, "failed to get DynamoDB learning path");
                LearningCatalogRepositoryError::Unavailable
            })?;

        output.item.map(Self::parse_item).transpose()
    }

    async fn find_course(
        &self,
        path_id: &str,
        course_id: &str,
    ) -> Result<Option<Course>, LearningCatalogRepositoryError> {
        Ok(self.find_learning_path(path_id).await?.and_then(|path| {
            path.courses
                .into_iter()
                .find(|course| course.id == course_id)
        }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn builds_learning_path_key() {
        let key = DynamoDbLearningCatalogRepository::path_key("toeic");

        assert_eq!(
            key.get("pk"),
            Some(&AttributeValue::S(CATALOG_PK.to_string()))
        );
        assert_eq!(
            key.get("sk"),
            Some(&AttributeValue::S("PATH#toeic".to_string()))
        );
    }
}
