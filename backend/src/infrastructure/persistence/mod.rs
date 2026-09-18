mod dynamodb_ai_model_catalog_repository;
mod dynamodb_learner_profile_repository;
mod dynamodb_learning_catalog_repository;
mod dynamodb_personalized_example_repository;
mod dynamodb_user_repository;
mod in_memory_learner_profile_repository;
mod in_memory_personalization_job_publisher;
mod in_memory_personalized_example_repository;
mod in_memory_user_repository;
mod json_learning_catalog_repository;

pub use dynamodb_ai_model_catalog_repository::{
    DynamoDbAiModelCatalogRepository, DynamoDbAiModelCatalogRepositoryConfig,
};
pub use dynamodb_learner_profile_repository::{
    DynamoDbLearnerProfileRepository, DynamoDbLearnerProfileRepositoryConfig,
};
pub use dynamodb_learning_catalog_repository::{
    DynamoDbLearningCatalogRepository, DynamoDbLearningCatalogRepositoryConfig,
};
pub use dynamodb_personalized_example_repository::{
    DynamoDbPersonalizedExampleRepository, DynamoDbPersonalizedExampleRepositoryConfig,
};
pub use dynamodb_user_repository::{DynamoDbUserRepository, DynamoDbUserRepositoryConfig};
pub use in_memory_learner_profile_repository::InMemoryLearnerProfileRepository;
pub use in_memory_personalization_job_publisher::InMemoryPersonalizationJobPublisher;
pub use in_memory_personalized_example_repository::InMemoryPersonalizedExampleRepository;
pub use in_memory_user_repository::InMemoryUserRepository;
pub use json_learning_catalog_repository::{
    JsonLearningCatalogError, JsonLearningCatalogRepository,
};

#[cfg(test)]
mod tests {
    use super::*;
    use crate::application::ports::LearningCatalogRepository;

    #[tokio::test]
    async fn loads_frontend_learning_catalog_seed() {
        let path = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../frontend/src/features/learning/data/learningPaths.json");

        let repository = JsonLearningCatalogRepository::load(path).await.unwrap();
        let paths = repository.list_learning_paths().await.unwrap();

        assert_eq!(paths[0].id, "toeic");
        assert!(paths[0].courses.iter().any(|course| course.id == "starter"));
    }
}
