use std::sync::Arc;

use thiserror::Error;
use uuid::Uuid;

use crate::{
    application::ports::{PersonalizedExampleRepository, PersonalizedExampleRepositoryError},
    domain::personalized_example_sentence::PersonalizedExampleSentence,
};

#[derive(Clone)]
pub struct PersonalizedExampleQueries {
    repository: Arc<dyn PersonalizedExampleRepository>,
}

impl PersonalizedExampleQueries {
    pub fn new(repository: Arc<dyn PersonalizedExampleRepository>) -> Self {
        Self { repository }
    }

    pub async fn list_for_learner(
        &self,
        learner_id: Uuid,
    ) -> Result<Vec<PersonalizedExampleSentence>, PersonalizedExampleQueryError> {
        self.repository
            .list_by_learner_id(learner_id)
            .await
            .map_err(PersonalizedExampleQueryError::Repository)
    }
}

#[derive(Debug, Error)]
pub enum PersonalizedExampleQueryError {
    #[error(transparent)]
    Repository(#[from] PersonalizedExampleRepositoryError),
}
