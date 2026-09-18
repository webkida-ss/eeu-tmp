use std::sync::{Arc, Mutex, MutexGuard};

use async_trait::async_trait;
use uuid::Uuid;

use crate::{
    application::ports::{PersonalizedExampleRepository, PersonalizedExampleRepositoryError},
    domain::personalized_example_sentence::PersonalizedExampleSentence,
};

#[derive(Debug, Clone, Default)]
pub struct InMemoryPersonalizedExampleRepository {
    examples: Arc<Mutex<Vec<PersonalizedExampleSentence>>>,
}

impl InMemoryPersonalizedExampleRepository {
    pub fn new() -> Self {
        Self::default()
    }

    pub async fn save_all(
        &self,
        examples: Vec<PersonalizedExampleSentence>,
    ) -> Result<(), PersonalizedExampleRepositoryError> {
        <Self as PersonalizedExampleRepository>::save_all(self, examples).await
    }

    fn lock_examples(
        &self,
    ) -> Result<MutexGuard<'_, Vec<PersonalizedExampleSentence>>, PersonalizedExampleRepositoryError>
    {
        self.examples
            .lock()
            .map_err(|_| PersonalizedExampleRepositoryError::Unavailable)
    }
}

#[async_trait]
impl PersonalizedExampleRepository for InMemoryPersonalizedExampleRepository {
    async fn list_by_learner_id(
        &self,
        learner_id: Uuid,
    ) -> Result<Vec<PersonalizedExampleSentence>, PersonalizedExampleRepositoryError> {
        let mut examples = self
            .lock_examples()?
            .iter()
            .filter(|example| example.learner_id == learner_id)
            .cloned()
            .collect::<Vec<_>>();
        examples.sort_by(|left, right| left.vocabulary_entry_id.cmp(&right.vocabulary_entry_id));
        Ok(examples)
    }

    async fn save_all(
        &self,
        examples: Vec<PersonalizedExampleSentence>,
    ) -> Result<(), PersonalizedExampleRepositoryError> {
        let mut stored = self.lock_examples()?;

        for example in examples {
            if let Some(existing) = stored.iter_mut().find(|stored| {
                stored.learner_id == example.learner_id
                    && stored.vocabulary_entry_id == example.vocabulary_entry_id
                    && stored.profile_version == example.profile_version
            }) {
                *existing = example;
            } else {
                stored.push(example);
            }
        }

        Ok(())
    }
}
