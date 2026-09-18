use std::sync::Arc;

use async_trait::async_trait;
use chrono::Utc;
use uuid::Uuid;

use crate::{
    application::{
        example_sentences::{ExampleSentenceService, GenerateExampleSentenceInput},
        ports::{
            LearnerProfileRepository, LearnerProfileRepositoryError, LearningCatalogRepository,
            LearningCatalogRepositoryError, PersonalizedExampleRepository,
            PersonalizedExampleRepositoryError, RegeneratePersonalizedExamplesJob,
        },
    },
    domain::{
        learner_profile::LearnerProfile, learning_catalog::VocabularyEntry,
        personalized_example_sentence::PersonalizedExampleSentence,
    },
};

pub struct PersonalizedExampleRegenerationService {
    profiles: Arc<dyn LearnerProfileRepository>,
    catalog: Arc<dyn LearningCatalogRepository>,
    personalized_examples: Arc<dyn PersonalizedExampleRepository>,
    generator: Arc<dyn PersonalizedExampleGenerator>,
}

impl PersonalizedExampleRegenerationService {
    pub fn new(
        profiles: Arc<dyn LearnerProfileRepository>,
        catalog: Arc<dyn LearningCatalogRepository>,
        personalized_examples: Arc<dyn PersonalizedExampleRepository>,
        generator: Arc<dyn PersonalizedExampleGenerator>,
    ) -> Self {
        Self {
            profiles,
            catalog,
            personalized_examples,
            generator,
        }
    }

    pub async fn regenerate(
        &self,
        job: RegeneratePersonalizedExamplesJob,
    ) -> Result<(), PersonalizedExampleRegenerationError> {
        let Some(profile) = self.profiles.find_by_user_id(job.learner_id).await? else {
            return Ok(());
        };
        let context_summary = profile.context_summary();
        let mut examples = Vec::new();

        for path in self.catalog.list_learning_paths().await? {
            for course in path.courses {
                for unit in course.units {
                    for vocabulary_entry in unit.vocabulary_entries {
                        examples.push(
                            self.personalized_example_for_entry(
                                job.learner_id,
                                &job.profile_version,
                                &profile,
                                &context_summary,
                                vocabulary_entry,
                            )
                            .await?,
                        );
                    }
                }
            }
        }

        self.personalized_examples.save_all(examples).await?;
        Ok(())
    }

    async fn personalized_example_for_entry(
        &self,
        learner_id: Uuid,
        profile_version: &str,
        profile: &LearnerProfile,
        context_summary: &str,
        vocabulary_entry: VocabularyEntry,
    ) -> Result<PersonalizedExampleSentence, PersonalizedExampleRegenerationError> {
        let generated = self
            .generator
            .generate(PersonalizedExampleGeneratorInput {
                target_text: vocabulary_entry.target_text.clone(),
                context_summary: context_summary.to_string(),
                profile: profile.clone(),
            })
            .await?;
        let now = Utc::now();

        Ok(PersonalizedExampleSentence {
            id: Uuid::now_v7().to_string(),
            learner_id,
            vocabulary_entry_id: vocabulary_entry.id,
            target_text: vocabulary_entry.target_text,
            target_sentence: generated.target_sentence,
            source_translation: generated.source_translation,
            context_summary: context_summary.to_string(),
            profile_version: profile_version.to_string(),
            created_at: now,
            updated_at: now,
        })
    }
}

#[derive(Debug, Clone)]
pub struct PersonalizedExampleGeneratorInput {
    pub target_text: String,
    pub context_summary: String,
    pub profile: LearnerProfile,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GeneratedPersonalizedExample {
    pub target_sentence: String,
    pub source_translation: String,
}

#[async_trait]
pub trait PersonalizedExampleGenerator: Send + Sync {
    async fn generate(
        &self,
        input: PersonalizedExampleGeneratorInput,
    ) -> Result<GeneratedPersonalizedExample, PersonalizedExampleGeneratorError>;
}

#[derive(Debug, Clone)]
pub struct PlaceholderPersonalizedExampleGenerator;

#[async_trait]
impl PersonalizedExampleGenerator for PlaceholderPersonalizedExampleGenerator {
    async fn generate(
        &self,
        input: PersonalizedExampleGeneratorInput,
    ) -> Result<GeneratedPersonalizedExample, PersonalizedExampleGeneratorError> {
        Ok(GeneratedPersonalizedExample {
            target_sentence: format!(
                "Personalized example for {}: {}",
                input.target_text, input.context_summary
            ),
            source_translation: String::new(),
        })
    }
}

#[derive(Clone)]
pub struct AiPersonalizedExampleGenerator {
    example_sentences: ExampleSentenceService,
}

impl AiPersonalizedExampleGenerator {
    pub fn new(example_sentences: ExampleSentenceService) -> Self {
        Self { example_sentences }
    }
}

#[async_trait]
impl PersonalizedExampleGenerator for AiPersonalizedExampleGenerator {
    async fn generate(
        &self,
        input: PersonalizedExampleGeneratorInput,
    ) -> Result<GeneratedPersonalizedExample, PersonalizedExampleGeneratorError> {
        let generated = self
            .example_sentences
            .generate_personalized(GenerateExampleSentenceInput {
                target_text: input.target_text,
                user_context_summary: input.context_summary,
            })
            .await
            .map_err(|source| {
                tracing::error!(%source, "failed to generate personalized example sentence");
                PersonalizedExampleGeneratorError::Unavailable
            })?;

        Ok(GeneratedPersonalizedExample {
            target_sentence: generated.target_sentence,
            source_translation: String::new(),
        })
    }
}

#[derive(Debug, thiserror::Error)]
pub enum PersonalizedExampleRegenerationError {
    #[error(transparent)]
    LearnerProfileRepository(#[from] LearnerProfileRepositoryError),
    #[error(transparent)]
    LearningCatalogRepository(#[from] LearningCatalogRepositoryError),
    #[error(transparent)]
    PersonalizedExampleRepository(#[from] PersonalizedExampleRepositoryError),
    #[error(transparent)]
    Generator(#[from] PersonalizedExampleGeneratorError),
}

#[derive(Debug, thiserror::Error)]
pub enum PersonalizedExampleGeneratorError {
    #[error("personalized example generation failed")]
    Unavailable,
}
