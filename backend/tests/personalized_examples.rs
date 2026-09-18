use chrono::{TimeZone, Utc};
use english_backend::{
    application::{
        ai::ports::{AiClient, AiClientError, AiCompletion, AiCompletionRequest},
        example_sentences::ExampleSentenceService,
        personalization::{
            AiPersonalizedExampleGenerator, PersonalizedExampleGenerator,
            PersonalizedExampleGeneratorInput, PersonalizedExampleRegenerationService,
            PlaceholderPersonalizedExampleGenerator,
        },
        personalized_examples::PersonalizedExampleQueries,
        ports::{
            LearnerProfileRepository, PersonalizedExampleRepository,
            RegeneratePersonalizedExamplesJob,
        },
    },
    domain::{
        learner_profile::{LearnerProfile, LearnerProfileInput},
        personalized_example_sentence::PersonalizedExampleSentence,
    },
    infrastructure::persistence::{
        InMemoryLearnerProfileRepository, InMemoryPersonalizedExampleRepository,
        JsonLearningCatalogRepository,
    },
};
use uuid::Uuid;

#[tokio::test]
async fn stores_and_lists_personalized_examples_for_learner() {
    let learner_id = Uuid::now_v7();
    let other_learner_id = Uuid::now_v7();
    let repository = InMemoryPersonalizedExampleRepository::new();
    let queries = PersonalizedExampleQueries::new(std::sync::Arc::new(repository.clone()));

    repository
        .save_all(vec![
            example(
                learner_id,
                "apply",
                "I applied for a cafe job near my station.",
            ),
            example(
                learner_id,
                "confirm",
                "I confirmed my travel plan before work.",
            ),
            example(other_learner_id, "apply", "She applied for a scholarship."),
        ])
        .await
        .unwrap();

    let examples = queries.list_for_learner(learner_id).await.unwrap();

    assert_eq!(examples.len(), 2);
    assert_eq!(examples[0].vocabulary_entry_id, "apply");
    assert_eq!(
        examples[0].target_sentence,
        "I applied for a cafe job near my station."
    );
    assert_eq!(examples[1].vocabulary_entry_id, "confirm");
}

#[tokio::test]
async fn regenerates_placeholder_examples_from_profile_update_job() {
    let learner_id = Uuid::now_v7();
    let profile_repository = InMemoryLearnerProfileRepository::new();
    let catalog_repository = JsonLearningCatalogRepository::load(
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../frontend/src/features/learning/data/learningPaths.json"),
    )
    .await
    .unwrap();
    let personalized_repository = InMemoryPersonalizedExampleRepository::new();
    let profile = LearnerProfile::new(
        learner_id,
        LearnerProfileInput {
            daily_scenes: "Commuting and cafe ordering.".to_string(),
            vocabulary_focus: "Job applications.".to_string(),
            ..LearnerProfileInput::default()
        },
    );
    profile_repository.save(profile.clone()).await.unwrap();
    let service = PersonalizedExampleRegenerationService::new(
        std::sync::Arc::new(profile_repository),
        std::sync::Arc::new(catalog_repository),
        std::sync::Arc::new(personalized_repository.clone()),
        std::sync::Arc::new(PlaceholderPersonalizedExampleGenerator),
    );

    service
        .regenerate(RegeneratePersonalizedExamplesJob::profile_updated(
            learner_id,
            profile.updated_at,
        ))
        .await
        .unwrap();

    let examples = personalized_repository
        .list_by_learner_id(learner_id)
        .await
        .unwrap();
    assert!(examples.iter().any(|example| {
        example.vocabulary_entry_id == "apply"
            && example
                .target_sentence
                .contains("Commuting and cafe ordering")
    }));
}

#[tokio::test]
async fn ai_generator_uses_example_sentence_service() {
    let learner_id = Uuid::now_v7();
    let generator = AiPersonalizedExampleGenerator::new(ExampleSentenceService::new(
        std::sync::Arc::new(StaticAiClient {
            response: "I applied for a cafe job near my station.".to_string(),
        }),
    ));

    let generated = generator
        .generate(PersonalizedExampleGeneratorInput {
            target_text: "apply".to_string(),
            context_summary: "Daily scenes: commuting.".to_string(),
            profile: LearnerProfile::new(learner_id, LearnerProfileInput::default()),
        })
        .await
        .unwrap();

    assert_eq!(
        generated.target_sentence,
        "I applied for a cafe job near my station."
    );
    assert_eq!(generated.source_translation, "");
}

fn example(
    learner_id: Uuid,
    vocabulary_entry_id: &str,
    target_sentence: &str,
) -> PersonalizedExampleSentence {
    PersonalizedExampleSentence {
        id: Uuid::now_v7().to_string(),
        learner_id,
        vocabulary_entry_id: vocabulary_entry_id.to_string(),
        target_text: vocabulary_entry_id.to_string(),
        target_sentence: target_sentence.to_string(),
        source_translation: String::new(),
        context_summary: "Daily scenes: commuting.".to_string(),
        profile_version: "2026-06-13T08:00:00+00:00".to_string(),
        created_at: Utc.with_ymd_and_hms(2026, 6, 13, 8, 0, 0).unwrap(),
        updated_at: Utc.with_ymd_and_hms(2026, 6, 13, 8, 0, 0).unwrap(),
    }
}

struct StaticAiClient {
    response: String,
}

#[async_trait::async_trait]
impl AiClient for StaticAiClient {
    async fn complete(&self, _request: AiCompletionRequest) -> Result<AiCompletion, AiClientError> {
        Ok(AiCompletion {
            text: self.response.clone(),
        })
    }
}
