use async_trait::async_trait;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::domain::{
    learner_profile::LearnerProfile,
    learning_catalog::{Course, LearningPath},
    personalized_example_sentence::PersonalizedExampleSentence,
    user::User,
};

#[async_trait]
pub trait LearningCatalogRepository: Send + Sync {
    async fn list_learning_paths(
        &self,
    ) -> Result<Vec<LearningPath>, LearningCatalogRepositoryError>;

    async fn find_learning_path(
        &self,
        path_id: &str,
    ) -> Result<Option<LearningPath>, LearningCatalogRepositoryError>;

    async fn find_course(
        &self,
        path_id: &str,
        course_id: &str,
    ) -> Result<Option<Course>, LearningCatalogRepositoryError>;
}

#[derive(Debug, thiserror::Error)]
pub enum LearningCatalogRepositoryError {
    #[error("learning catalog repository failed")]
    Unavailable,
}

#[async_trait]
pub trait UserRepository: Send + Sync {
    async fn find_user_by_identity(
        &self,
        provider: &str,
        subject: &str,
    ) -> Result<Option<User>, UserRepositoryError>;

    async fn create_user_for_identity(
        &self,
        provider: &str,
        subject: &str,
        email: &str,
    ) -> Result<User, UserRepositoryError>;
}

#[derive(Debug, thiserror::Error)]
pub enum UserRepositoryError {
    #[error("user repository failed")]
    Unavailable,
}

#[async_trait]
pub trait LearnerProfileRepository: Send + Sync {
    async fn find_by_user_id(
        &self,
        user_id: uuid::Uuid,
    ) -> Result<Option<LearnerProfile>, LearnerProfileRepositoryError>;

    async fn save(
        &self,
        profile: LearnerProfile,
    ) -> Result<LearnerProfile, LearnerProfileRepositoryError>;
}

#[derive(Debug, thiserror::Error)]
pub enum LearnerProfileRepositoryError {
    #[error("learner profile repository failed")]
    Unavailable,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RegeneratePersonalizedExamplesJob {
    pub learner_id: Uuid,
    pub profile_version: String,
    pub idempotency_key: String,
    pub reason: String,
}

impl RegeneratePersonalizedExamplesJob {
    pub fn profile_updated(learner_id: Uuid, profile_updated_at: DateTime<Utc>) -> Self {
        let profile_version = profile_updated_at.to_rfc3339();
        Self {
            learner_id,
            profile_version: profile_version.clone(),
            idempotency_key: format!("{learner_id}:{profile_version}"),
            reason: "profile_updated".to_string(),
        }
    }
}

#[async_trait]
pub trait PersonalizationJobPublisher: Send + Sync {
    async fn publish(
        &self,
        job: RegeneratePersonalizedExamplesJob,
    ) -> Result<(), PersonalizationJobPublisherError>;
}

#[derive(Debug, thiserror::Error)]
pub enum PersonalizationJobPublisherError {
    #[error("personalization job publisher failed")]
    Unavailable,
}

#[async_trait]
pub trait PersonalizedExampleRepository: Send + Sync {
    async fn list_by_learner_id(
        &self,
        learner_id: Uuid,
    ) -> Result<Vec<PersonalizedExampleSentence>, PersonalizedExampleRepositoryError>;

    async fn save_all(
        &self,
        examples: Vec<PersonalizedExampleSentence>,
    ) -> Result<(), PersonalizedExampleRepositoryError>;
}

#[derive(Debug, thiserror::Error)]
pub enum PersonalizedExampleRepositoryError {
    #[error("personalized example repository failed")]
    Unavailable,
}
