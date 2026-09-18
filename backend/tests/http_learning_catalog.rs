use std::sync::Arc;

use async_trait::async_trait;
use axum::{
    body::{to_bytes, Body},
    http::{header::CONTENT_TYPE, Request, StatusCode},
};
use english_backend::{
    application::{
        ai::{model::AiModelCatalog, service::AiService},
        auth::{CognitoTokenVerifier, TokenVerificationError, VerifiedCognitoClaims},
        example_sentences::ExampleSentenceService,
        personalized_examples::PersonalizedExampleQueries,
        ports::UserRepository,
        queries::LearningCatalogQueries,
    },
    domain::personalized_example_sentence::PersonalizedExampleSentence,
    infrastructure::{
        ai::DevAiProviderGateway,
        persistence::{
            InMemoryLearnerProfileRepository, InMemoryPersonalizationJobPublisher,
            InMemoryPersonalizedExampleRepository, InMemoryUserRepository,
            JsonLearningCatalogRepository,
        },
    },
    user_interface::http::routes,
};
use serde_json::Value;
use tower::ServiceExt;

const TEST_HOST: &str = "localhost:18080";
const VALID_TEST_TOKEN: &str = "header.payload.signature";

#[tokio::test]
async fn lists_learning_paths() {
    let app = english_backend::bootstrap::build_app()
        .await
        .unwrap()
        .router;

    let response = app
        .oneshot(
            Request::builder()
                .uri("/learning-paths")
                .header("host", TEST_HOST)
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);

    let body = to_json(response.into_body()).await;
    assert_eq!(body[0]["id"], "toeic");
    assert_eq!(body[0]["courses"][0]["id"], "starter");
}

#[tokio::test]
async fn gets_a_learning_path_course() {
    let app = english_backend::bootstrap::build_app()
        .await
        .unwrap()
        .router;

    let response = app
        .oneshot(
            Request::builder()
                .uri("/learning-paths/toeic/courses/starter")
                .header("host", TEST_HOST)
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);

    let body = to_json(response.into_body()).await;
    assert_eq!(body["id"], "starter");
    assert_eq!(
        body["units"][0]["vocabularyEntries"][0]["targetText"],
        "apply"
    );
}

#[tokio::test]
async fn returns_404_for_missing_learning_path() {
    let app = english_backend::bootstrap::build_app()
        .await
        .unwrap()
        .router;

    let response = app
        .oneshot(
            Request::builder()
                .uri("/learning-paths/missing")
                .header("host", TEST_HOST)
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn exposes_health_check() {
    let app = english_backend::bootstrap::build_app()
        .await
        .unwrap()
        .router;

    let response = app
        .oneshot(
            Request::builder()
                .uri("/healthz")
                .header("host", TEST_HOST)
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);
}

#[tokio::test]
async fn rejects_auth_session_without_access_token() {
    let app = english_backend::bootstrap::build_app()
        .await
        .unwrap()
        .router;

    let response = app
        .oneshot(
            Request::builder()
                .uri("/auth/session")
                .header("host", TEST_HOST)
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn rejects_auth_session_with_malformed_access_token() {
    let app = english_backend::bootstrap::build_app()
        .await
        .unwrap()
        .router;

    let response = app
        .oneshot(
            Request::builder()
                .uri("/auth/session")
                .header("host", TEST_HOST)
                .header("authorization", "Bearer not-a-jwt")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn returns_auth_session_from_verified_access_token_claims() {
    let queries = build_learning_catalog_queries().await;
    let users = Arc::new(InMemoryUserRepository::new());
    let app = routes::router_with_auth_verifier(
        queries,
        Arc::new(TestCognitoTokenVerifier {
            claims: VerifiedCognitoClaims {
                sub: "cognito-user-123".to_string(),
                email: "verified@example.com".to_string(),
            },
        }),
        users.clone(),
        Arc::new(InMemoryLearnerProfileRepository::new()),
        Arc::new(InMemoryPersonalizationJobPublisher::new()),
        build_personalized_example_queries(),
        build_example_sentence_service(),
    );

    let response = app
        .oneshot(
            Request::builder()
                .uri("/auth/session")
                .header("host", TEST_HOST)
                .header("authorization", format!("Bearer {VALID_TEST_TOKEN}"))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);

    let body = to_json(response.into_body()).await;
    assert_eq!(body["authenticated"], true);
    assert_eq!(body["cognitoSub"], "cognito-user-123");
    assert_eq!(body["email"], "verified@example.com");

    let app_user_id = body["appUserId"]
        .as_str()
        .expect("appUserId should be string");
    let user = users
        .find_user_by_identity("cognito", "cognito-user-123")
        .await
        .unwrap()
        .expect("user should be created for Cognito identity");
    assert_eq!(app_user_id, user.id.to_string());
}

#[tokio::test]
async fn saves_and_returns_learner_profile_for_authenticated_user() {
    let queries = build_learning_catalog_queries().await;
    let users = Arc::new(InMemoryUserRepository::new());
    let app = routes::router_with_auth_verifier(
        queries,
        Arc::new(TestCognitoTokenVerifier {
            claims: VerifiedCognitoClaims {
                sub: "cognito-user-123".to_string(),
                email: "verified@example.com".to_string(),
            },
        }),
        users,
        Arc::new(InMemoryLearnerProfileRepository::new()),
        Arc::new(InMemoryPersonalizationJobPublisher::new()),
        build_personalized_example_queries(),
        build_example_sentence_service(),
    );
    let profile_body = r#"{
        "learningPurpose": "Speak more naturally while traveling.",
        "targetLevel": "CEFR B1",
        "deadline": "Before my summer trip",
        "interests": "Coffee shops, baseball, and indie games.",
        "favoriteContent": "Travel videos and casual podcasts.",
        "dailyScenes": "Commuting, shopping, and short work chats.",
        "englishUseCases": "Ordering food and casual small talk.",
        "weakPoints": "Prepositions and tense.",
        "vocabularyFocus": "Phrasal verbs and travel adjectives."
    }"#;

    let save_response = app
        .clone()
        .oneshot(
            Request::builder()
                .method("PUT")
                .uri("/me/learner-profile")
                .header("host", TEST_HOST)
                .header("authorization", format!("Bearer {VALID_TEST_TOKEN}"))
                .header(CONTENT_TYPE, "application/json")
                .body(Body::from(profile_body))
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(save_response.status(), StatusCode::OK);

    let get_response = app
        .clone()
        .oneshot(
            Request::builder()
                .uri("/me/learner-profile")
                .header("host", TEST_HOST)
                .header("authorization", format!("Bearer {VALID_TEST_TOKEN}"))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(get_response.status(), StatusCode::OK);

    let body = to_json(get_response.into_body()).await;
    assert_eq!(
        body["learningPurpose"],
        "Speak more naturally while traveling."
    );
    assert_eq!(
        body["dailyScenes"],
        "Commuting, shopping, and short work chats."
    );
    assert_eq!(body["weakPoints"], "Prepositions and tense.");
    assert!(body["updatedAt"].as_str().is_some());

    let example_response = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/example-sentences")
                .header("host", TEST_HOST)
                .header("authorization", format!("Bearer {VALID_TEST_TOKEN}"))
                .header(CONTENT_TYPE, "application/json")
                .body(Body::from(
                    r#"{"targetText":"apply","userContextSummary":"The learner is practicing apply."}"#,
                ))
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(example_response.status(), StatusCode::OK);

    let example_body = to_json(example_response.into_body()).await;
    let context_summary = example_body["personalization"]["contextSummary"]
        .as_str()
        .expect("context summary should be returned");
    assert!(context_summary.contains("Daily scenes: Commuting, shopping, and short work chats."));
    assert!(context_summary.contains("Weak points: Prepositions and tense."));
}

#[tokio::test]
async fn publishes_personalization_job_after_saving_learner_profile() {
    let queries = build_learning_catalog_queries().await;
    let users = Arc::new(InMemoryUserRepository::new());
    let jobs = Arc::new(InMemoryPersonalizationJobPublisher::new());
    let app = routes::router_with_auth_verifier(
        queries,
        Arc::new(TestCognitoTokenVerifier {
            claims: VerifiedCognitoClaims {
                sub: "cognito-user-123".to_string(),
                email: "verified@example.com".to_string(),
            },
        }),
        users,
        Arc::new(InMemoryLearnerProfileRepository::new()),
        jobs.clone(),
        build_personalized_example_queries(),
        build_example_sentence_service(),
    );
    let profile_body = r#"{
        "learningPurpose": "Speak more naturally while traveling.",
        "targetLevel": "CEFR B1",
        "deadline": "Before my summer trip",
        "interests": "Coffee shops, baseball, and indie games.",
        "favoriteContent": "Travel videos and casual podcasts.",
        "dailyScenes": "Commuting, shopping, and short work chats.",
        "englishUseCases": "Ordering food and casual small talk.",
        "weakPoints": "Prepositions and tense.",
        "vocabularyFocus": "Phrasal verbs and travel adjectives."
    }"#;

    let save_response = app
        .oneshot(
            Request::builder()
                .method("PUT")
                .uri("/me/learner-profile")
                .header("host", TEST_HOST)
                .header("authorization", format!("Bearer {VALID_TEST_TOKEN}"))
                .header(CONTENT_TYPE, "application/json")
                .body(Body::from(profile_body))
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(save_response.status(), StatusCode::OK);
    let published_jobs = jobs.published_jobs().unwrap();
    assert_eq!(published_jobs.len(), 1);
    assert_eq!(published_jobs[0].reason, "profile_updated");
    assert_eq!(
        published_jobs[0].idempotency_key,
        format!(
            "{}:{}",
            published_jobs[0].learner_id, published_jobs[0].profile_version
        )
    );
}

#[tokio::test]
async fn lists_personalized_examples_for_authenticated_user() {
    let queries = build_learning_catalog_queries().await;
    let users = Arc::new(InMemoryUserRepository::new());
    let personalized_examples = InMemoryPersonalizedExampleRepository::new();
    let learner_id = users
        .create_user_for_identity("cognito", "cognito-user-123", "verified@example.com")
        .await
        .unwrap()
        .id;
    personalized_examples
        .save_all(vec![PersonalizedExampleSentence {
            id: "personalized-apply-1".to_string(),
            learner_id,
            vocabulary_entry_id: "apply".to_string(),
            target_text: "apply".to_string(),
            target_sentence: "I applied for a cafe job near my station.".to_string(),
            source_translation: String::new(),
            context_summary: "Daily scenes: commuting.".to_string(),
            profile_version: "2026-06-13T08:00:00+00:00".to_string(),
            created_at: chrono::Utc::now(),
            updated_at: chrono::Utc::now(),
        }])
        .await
        .unwrap();
    let app = routes::router_with_auth_verifier(
        queries,
        Arc::new(TestCognitoTokenVerifier {
            claims: VerifiedCognitoClaims {
                sub: "cognito-user-123".to_string(),
                email: "verified@example.com".to_string(),
            },
        }),
        users,
        Arc::new(InMemoryLearnerProfileRepository::new()),
        Arc::new(InMemoryPersonalizationJobPublisher::new()),
        PersonalizedExampleQueries::new(Arc::new(personalized_examples)),
        build_example_sentence_service(),
    );

    let response = app
        .oneshot(
            Request::builder()
                .uri("/me/personalized-example-sentences")
                .header("host", TEST_HOST)
                .header("authorization", format!("Bearer {VALID_TEST_TOKEN}"))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);
    let body = to_json(response.into_body()).await;
    assert_eq!(body[0]["id"], "personalized-apply-1");
    assert_eq!(
        body[0]["targetSentence"],
        "I applied for a cafe job near my station."
    );
    assert_eq!(
        body[0]["personalization"]["contextSummary"],
        "Daily scenes: commuting."
    );
}

async fn to_json(body: Body) -> Value {
    let bytes = to_bytes(body, usize::MAX).await.unwrap();
    serde_json::from_slice(&bytes).unwrap()
}

async fn build_learning_catalog_queries() -> LearningCatalogQueries {
    let repository = JsonLearningCatalogRepository::load(
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../frontend/src/features/learning/data/learningPaths.json"),
    )
    .await
    .unwrap();

    LearningCatalogQueries::new(Arc::new(repository))
}

fn build_example_sentence_service() -> ExampleSentenceService {
    ExampleSentenceService::new(Arc::new(AiService::new(
        Arc::new(AiModelCatalog::default()),
        Arc::new(DevAiProviderGateway),
    )))
}

fn build_personalized_example_queries() -> PersonalizedExampleQueries {
    PersonalizedExampleQueries::new(Arc::new(InMemoryPersonalizedExampleRepository::new()))
}

struct TestCognitoTokenVerifier {
    claims: VerifiedCognitoClaims,
}

#[async_trait]
impl CognitoTokenVerifier for TestCognitoTokenVerifier {
    async fn verify_access_token(
        &self,
        token: &str,
    ) -> Result<VerifiedCognitoClaims, TokenVerificationError> {
        if token == VALID_TEST_TOKEN {
            Ok(self.claims.clone())
        } else {
            Err(TokenVerificationError::InvalidToken)
        }
    }
}
