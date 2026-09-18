use std::collections::HashMap;

use async_trait::async_trait;
use aws_sdk_dynamodb::{types::AttributeValue, Client};
use uuid::Uuid;

use crate::{
    application::ports::{UserRepository, UserRepositoryError},
    domain::user::{User, UserIdentity},
};

const USER_SK: &str = "PROFILE";
const IDENTITY_SK: &str = "USER";
const DOCUMENT_ATTRIBUTE: &str = "document";
const USER_ID_ATTRIBUTE: &str = "userId";

#[derive(Debug, Clone)]
pub struct DynamoDbUserRepositoryConfig {
    pub table_name: String,
}

#[derive(Debug, Clone)]
pub struct DynamoDbUserRepository {
    client: Client,
    table_name: String,
}

impl DynamoDbUserRepository {
    pub fn new(client: Client, config: DynamoDbUserRepositoryConfig) -> Self {
        Self {
            client,
            table_name: config.table_name,
        }
    }

    fn user_key(user_id: &str) -> HashMap<String, AttributeValue> {
        HashMap::from([
            (
                "pk".to_string(),
                AttributeValue::S(format!("USER#{user_id}")),
            ),
            ("sk".to_string(), AttributeValue::S(USER_SK.to_string())),
        ])
    }

    fn identity_key(provider: &str, subject: &str) -> HashMap<String, AttributeValue> {
        HashMap::from([
            (
                "pk".to_string(),
                AttributeValue::S(format!("IDENTITY#{provider}#{subject}")),
            ),
            ("sk".to_string(), AttributeValue::S(IDENTITY_SK.to_string())),
        ])
    }

    fn parse_user(item: HashMap<String, AttributeValue>) -> Result<User, UserRepositoryError> {
        let Some(AttributeValue::S(document)) = item.get(DOCUMENT_ATTRIBUTE) else {
            tracing::error!("DynamoDB user item is missing document attribute");
            return Err(UserRepositoryError::Unavailable);
        };

        serde_json::from_str(document).map_err(|source| {
            tracing::error!(%source, "failed to deserialize DynamoDB user document");
            UserRepositoryError::Unavailable
        })
    }

    fn identity_item(
        identity: &UserIdentity,
    ) -> Result<HashMap<String, AttributeValue>, UserRepositoryError> {
        let document = serde_json::to_string(identity).map_err(|source| {
            tracing::error!(%source, "failed to serialize user identity document");
            UserRepositoryError::Unavailable
        })?;

        let mut item = Self::identity_key(&identity.provider, &identity.subject);
        item.insert(
            USER_ID_ATTRIBUTE.to_string(),
            AttributeValue::S(identity.user_id.to_string()),
        );
        item.insert(DOCUMENT_ATTRIBUTE.to_string(), AttributeValue::S(document));

        Ok(item)
    }

    fn user_item(user: &User) -> Result<HashMap<String, AttributeValue>, UserRepositoryError> {
        let document = serde_json::to_string(user).map_err(|source| {
            tracing::error!(%source, "failed to serialize user document");
            UserRepositoryError::Unavailable
        })?;

        let mut item = Self::user_key(&user.id.to_string());
        item.insert(DOCUMENT_ATTRIBUTE.to_string(), AttributeValue::S(document));

        Ok(item)
    }
}

#[async_trait]
impl UserRepository for DynamoDbUserRepository {
    async fn find_user_by_identity(
        &self,
        provider: &str,
        subject: &str,
    ) -> Result<Option<User>, UserRepositoryError> {
        let identity_output = self
            .client
            .get_item()
            .table_name(&self.table_name)
            .set_key(Some(Self::identity_key(provider, subject)))
            .send()
            .await
            .map_err(|source| {
                tracing::error!(%source, provider, subject, "failed to get DynamoDB user identity");
                UserRepositoryError::Unavailable
            })?;

        let Some(identity_item) = identity_output.item else {
            return Ok(None);
        };

        let Some(AttributeValue::S(user_id)) = identity_item.get(USER_ID_ATTRIBUTE) else {
            tracing::error!("DynamoDB user identity item is missing userId attribute");
            return Err(UserRepositoryError::Unavailable);
        };

        let user_output = self
            .client
            .get_item()
            .table_name(&self.table_name)
            .set_key(Some(Self::user_key(user_id)))
            .send()
            .await
            .map_err(|source| {
                tracing::error!(%source, user_id, "failed to get DynamoDB user");
                UserRepositoryError::Unavailable
            })?;

        user_output.item.map(Self::parse_user).transpose()
    }

    async fn create_user_for_identity(
        &self,
        provider: &str,
        subject: &str,
        email: &str,
    ) -> Result<User, UserRepositoryError> {
        if let Some(existing_user) = self.find_user_by_identity(provider, subject).await? {
            return Ok(existing_user);
        }

        let user = User {
            id: Uuid::now_v7(),
            email: email.to_string(),
        };
        let identity = UserIdentity {
            user_id: user.id,
            provider: provider.to_string(),
            subject: subject.to_string(),
        };

        self.client
            .put_item()
            .table_name(&self.table_name)
            .set_item(Some(Self::user_item(&user)?))
            .send()
            .await
            .map_err(|source| {
                tracing::error!(%source, user_id = %user.id, "failed to put DynamoDB user");
                UserRepositoryError::Unavailable
            })?;

        self.client
            .put_item()
            .table_name(&self.table_name)
            .set_item(Some(Self::identity_item(&identity)?))
            .send()
            .await
            .map_err(|source| {
                tracing::error!(%source, provider, subject, "failed to put DynamoDB user identity");
                UserRepositoryError::Unavailable
            })?;

        Ok(user)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn builds_user_and_identity_keys() {
        let user_key = DynamoDbUserRepository::user_key("0194fd38-7c2e-7a5a-8f2b-28b5d08a9f31");
        let identity_key = DynamoDbUserRepository::identity_key("cognito", "cognito-user-123");

        assert_eq!(
            user_key.get("pk"),
            Some(&AttributeValue::S(
                "USER#0194fd38-7c2e-7a5a-8f2b-28b5d08a9f31".to_string()
            ))
        );
        assert_eq!(
            user_key.get("sk"),
            Some(&AttributeValue::S("PROFILE".to_string()))
        );
        assert_eq!(
            identity_key.get("pk"),
            Some(&AttributeValue::S(
                "IDENTITY#cognito#cognito-user-123".to_string()
            ))
        );
        assert_eq!(
            identity_key.get("sk"),
            Some(&AttributeValue::S("USER".to_string()))
        );
    }
}
