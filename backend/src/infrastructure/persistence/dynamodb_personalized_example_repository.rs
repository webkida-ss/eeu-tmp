use std::collections::HashMap;

use async_trait::async_trait;
use aws_sdk_dynamodb::{types::AttributeValue, Client};
use uuid::Uuid;

use crate::{
    application::ports::{PersonalizedExampleRepository, PersonalizedExampleRepositoryError},
    domain::personalized_example_sentence::PersonalizedExampleSentence,
};

const LEARNER_PK_PREFIX: &str = "LEARNER#";
const EXAMPLE_SK_PREFIX: &str = "PERSONALIZED_EXAMPLE#";
const DOCUMENT_ATTRIBUTE: &str = "document";

#[derive(Debug, Clone)]
pub struct DynamoDbPersonalizedExampleRepositoryConfig {
    pub table_name: String,
}

#[derive(Debug, Clone)]
pub struct DynamoDbPersonalizedExampleRepository {
    client: Client,
    table_name: String,
}

impl DynamoDbPersonalizedExampleRepository {
    pub fn new(client: Client, config: DynamoDbPersonalizedExampleRepositoryConfig) -> Self {
        Self {
            client,
            table_name: config.table_name,
        }
    }

    fn learner_pk(learner_id: Uuid) -> String {
        format!("{LEARNER_PK_PREFIX}{learner_id}")
    }

    fn example_key(example: &PersonalizedExampleSentence) -> HashMap<String, AttributeValue> {
        HashMap::from([
            (
                "pk".to_string(),
                AttributeValue::S(Self::learner_pk(example.learner_id)),
            ),
            (
                "sk".to_string(),
                AttributeValue::S(format!(
                    "{EXAMPLE_SK_PREFIX}{}#{}",
                    example.vocabulary_entry_id, example.profile_version
                )),
            ),
        ])
    }

    fn parse_item(
        item: HashMap<String, AttributeValue>,
    ) -> Result<PersonalizedExampleSentence, PersonalizedExampleRepositoryError> {
        let Some(AttributeValue::S(document)) = item.get(DOCUMENT_ATTRIBUTE) else {
            tracing::error!("DynamoDB personalized example item is missing document attribute");
            return Err(PersonalizedExampleRepositoryError::Unavailable);
        };

        serde_json::from_str(document).map_err(|source| {
            tracing::error!(%source, "failed to deserialize DynamoDB personalized example document");
            PersonalizedExampleRepositoryError::Unavailable
        })
    }
}

#[async_trait]
impl PersonalizedExampleRepository for DynamoDbPersonalizedExampleRepository {
    async fn list_by_learner_id(
        &self,
        learner_id: Uuid,
    ) -> Result<Vec<PersonalizedExampleSentence>, PersonalizedExampleRepositoryError> {
        let output = self
            .client
            .query()
            .table_name(&self.table_name)
            .key_condition_expression("pk = :pk AND begins_with(sk, :sk_prefix)")
            .expression_attribute_values(":pk", AttributeValue::S(Self::learner_pk(learner_id)))
            .expression_attribute_values(
                ":sk_prefix",
                AttributeValue::S(EXAMPLE_SK_PREFIX.to_string()),
            )
            .send()
            .await
            .map_err(|source| {
                tracing::error!(%source, %learner_id, "failed to query DynamoDB personalized examples");
                PersonalizedExampleRepositoryError::Unavailable
            })?;

        output
            .items
            .unwrap_or_default()
            .into_iter()
            .map(Self::parse_item)
            .collect()
    }

    async fn save_all(
        &self,
        examples: Vec<PersonalizedExampleSentence>,
    ) -> Result<(), PersonalizedExampleRepositoryError> {
        for example in examples {
            let document = serde_json::to_string(&example).map_err(|source| {
                tracing::error!(%source, "failed to serialize personalized example document");
                PersonalizedExampleRepositoryError::Unavailable
            })?;
            let mut item = Self::example_key(&example);
            item.insert(DOCUMENT_ATTRIBUTE.to_string(), AttributeValue::S(document));

            self.client
                .put_item()
                .table_name(&self.table_name)
                .set_item(Some(item))
                .send()
                .await
                .map_err(|source| {
                    tracing::error!(%source, learner_id = %example.learner_id, "failed to put DynamoDB personalized example");
                    PersonalizedExampleRepositoryError::Unavailable
                })?;
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::{TimeZone, Utc};

    #[test]
    fn builds_personalized_example_key() {
        let learner_id = Uuid::now_v7();
        let example = PersonalizedExampleSentence {
            id: "example-1".to_string(),
            learner_id,
            vocabulary_entry_id: "apply".to_string(),
            target_text: "apply".to_string(),
            target_sentence: "I applied for a job.".to_string(),
            source_translation: String::new(),
            context_summary: "Daily scenes: work.".to_string(),
            profile_version: "2026-06-13T08:00:00+00:00".to_string(),
            created_at: Utc.with_ymd_and_hms(2026, 6, 13, 8, 0, 0).unwrap(),
            updated_at: Utc.with_ymd_and_hms(2026, 6, 13, 8, 0, 0).unwrap(),
        };

        let key = DynamoDbPersonalizedExampleRepository::example_key(&example);

        assert_eq!(
            key.get("pk"),
            Some(&AttributeValue::S(format!("LEARNER#{learner_id}")))
        );
        assert_eq!(
            key.get("sk"),
            Some(&AttributeValue::S(
                "PERSONALIZED_EXAMPLE#apply#2026-06-13T08:00:00+00:00".to_string()
            ))
        );
    }
}
