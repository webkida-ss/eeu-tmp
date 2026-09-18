use std::collections::HashMap;

use async_trait::async_trait;
use aws_sdk_dynamodb::{types::AttributeValue, Client};
use uuid::Uuid;

use crate::{
    application::ports::{LearnerProfileRepository, LearnerProfileRepositoryError},
    domain::learner_profile::LearnerProfile,
};

const PROFILE_SK: &str = "LEARNER_PROFILE";
const DOCUMENT_ATTRIBUTE: &str = "document";

#[derive(Debug, Clone)]
pub struct DynamoDbLearnerProfileRepositoryConfig {
    pub table_name: String,
}

#[derive(Debug, Clone)]
pub struct DynamoDbLearnerProfileRepository {
    client: Client,
    table_name: String,
}

impl DynamoDbLearnerProfileRepository {
    pub fn new(client: Client, config: DynamoDbLearnerProfileRepositoryConfig) -> Self {
        Self {
            client,
            table_name: config.table_name,
        }
    }

    fn profile_key(user_id: Uuid) -> HashMap<String, AttributeValue> {
        HashMap::from([
            (
                "pk".to_string(),
                AttributeValue::S(format!("USER#{user_id}")),
            ),
            ("sk".to_string(), AttributeValue::S(PROFILE_SK.to_string())),
        ])
    }

    fn profile_item(
        profile: &LearnerProfile,
    ) -> Result<HashMap<String, AttributeValue>, LearnerProfileRepositoryError> {
        let document = serde_json::to_string(profile).map_err(|source| {
            tracing::error!(%source, "failed to serialize learner profile document");
            LearnerProfileRepositoryError::Unavailable
        })?;
        let mut item = Self::profile_key(profile.user_id);
        item.insert(DOCUMENT_ATTRIBUTE.to_string(), AttributeValue::S(document));

        Ok(item)
    }

    fn parse_profile(
        item: HashMap<String, AttributeValue>,
    ) -> Result<LearnerProfile, LearnerProfileRepositoryError> {
        let Some(AttributeValue::S(document)) = item.get(DOCUMENT_ATTRIBUTE) else {
            tracing::error!("DynamoDB learner profile item is missing document attribute");
            return Err(LearnerProfileRepositoryError::Unavailable);
        };

        serde_json::from_str(document).map_err(|source| {
            tracing::error!(%source, "failed to deserialize DynamoDB learner profile document");
            LearnerProfileRepositoryError::Unavailable
        })
    }
}

#[async_trait]
impl LearnerProfileRepository for DynamoDbLearnerProfileRepository {
    async fn find_by_user_id(
        &self,
        user_id: Uuid,
    ) -> Result<Option<LearnerProfile>, LearnerProfileRepositoryError> {
        let output = self
            .client
            .get_item()
            .table_name(&self.table_name)
            .set_key(Some(Self::profile_key(user_id)))
            .send()
            .await
            .map_err(|source| {
                tracing::error!(%source, %user_id, "failed to get DynamoDB learner profile");
                LearnerProfileRepositoryError::Unavailable
            })?;

        output.item.map(Self::parse_profile).transpose()
    }

    async fn save(
        &self,
        profile: LearnerProfile,
    ) -> Result<LearnerProfile, LearnerProfileRepositoryError> {
        self.client
            .put_item()
            .table_name(&self.table_name)
            .set_item(Some(Self::profile_item(&profile)?))
            .send()
            .await
            .map_err(|source| {
                tracing::error!(%source, user_id = %profile.user_id, "failed to put DynamoDB learner profile");
                LearnerProfileRepositoryError::Unavailable
            })?;

        Ok(profile)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn builds_learner_profile_key() {
        let user_id = Uuid::parse_str("0194fd38-7c2e-7a5a-8f2b-28b5d08a9f31").unwrap();
        let key = DynamoDbLearnerProfileRepository::profile_key(user_id);

        assert_eq!(
            key.get("pk"),
            Some(&AttributeValue::S(format!("USER#{user_id}")))
        );
        assert_eq!(
            key.get("sk"),
            Some(&AttributeValue::S(PROFILE_SK.to_string()))
        );
    }
}
