use std::sync::Arc;

use async_trait::async_trait;
use axum::{routing::get, Router};
use axum_extra::extract::CookieJar;
use english_backend_openapi::{
    apis::{
        self,
        default::{
            GenerateExampleSentenceResponse, GetAuthSessionResponse, GetLearnerProfileResponse,
            GetLearningPathCourseResponse, GetLearningPathResponse, GetLearningPathsResponse,
            GetPersonalizedExampleSentencesResponse, PutLearnerProfileResponse,
        },
        ApiAuthBasic, BasicAuthKind, ErrorHandler,
    },
    models,
};
use headers::Host;
use http::{HeaderMap, Method};
use serde::{de::DeserializeOwned, Serialize};
use tracing::error;

use crate::{
    application::{
        auth::{CognitoTokenVerifier, VerifiedCognitoClaims},
        example_sentences::{ExampleSentenceService, GenerateExampleSentenceInput},
        personalized_examples::PersonalizedExampleQueries,
        ports::{
            LearnerProfileRepository, PersonalizationJobPublisher,
            RegeneratePersonalizedExamplesJob, UserRepository,
        },
        queries::LearningCatalogQueries,
    },
    domain::{
        learner_profile::{LearnerProfile, LearnerProfileInput},
        personalized_example_sentence::PersonalizedExampleSentence,
    },
    user_interface::http::handlers,
};

#[derive(Clone)]
struct OpenApiRouter {
    api: Arc<ApiImpl>,
}

impl AsRef<ApiImpl> for OpenApiRouter {
    fn as_ref(&self) -> &ApiImpl {
        &self.api
    }
}

struct ApiImpl {
    queries: LearningCatalogQueries,
    token_verifier: Arc<dyn CognitoTokenVerifier>,
    users: Arc<dyn UserRepository>,
    learner_profiles: Arc<dyn LearnerProfileRepository>,
    personalization_jobs: Arc<dyn PersonalizationJobPublisher>,
    personalized_examples: PersonalizedExampleQueries,
    example_sentences: ExampleSentenceService,
}

#[derive(Debug)]
struct ApiError;

#[derive(Debug)]
struct AuthClaims {
    cognito: VerifiedCognitoClaims,
}

pub fn router(
    queries: LearningCatalogQueries,
    token_verifier: Arc<dyn CognitoTokenVerifier>,
    users: Arc<dyn UserRepository>,
    learner_profiles: Arc<dyn LearnerProfileRepository>,
    personalization_jobs: Arc<dyn PersonalizationJobPublisher>,
    personalized_examples: PersonalizedExampleQueries,
    example_sentences: ExampleSentenceService,
) -> Router {
    router_with_auth_verifier(
        queries,
        token_verifier,
        users,
        learner_profiles,
        personalization_jobs,
        personalized_examples,
        example_sentences,
    )
}

pub fn router_with_auth_verifier(
    queries: LearningCatalogQueries,
    token_verifier: Arc<dyn CognitoTokenVerifier>,
    users: Arc<dyn UserRepository>,
    learner_profiles: Arc<dyn LearnerProfileRepository>,
    personalization_jobs: Arc<dyn PersonalizationJobPublisher>,
    personalized_examples: PersonalizedExampleQueries,
    example_sentences: ExampleSentenceService,
) -> Router {
    let api = OpenApiRouter {
        api: Arc::new(ApiImpl {
            queries,
            token_verifier,
            users,
            learner_profiles,
            personalization_jobs,
            personalized_examples,
            example_sentences,
        }),
    };
    english_backend_openapi::server::new(api).route("/healthz", get(handlers::healthz))
}

#[async_trait]
impl ErrorHandler<ApiError> for ApiImpl {}

#[async_trait]
impl ApiAuthBasic for ApiImpl {
    type Claims = AuthClaims;

    async fn extract_claims_from_auth_header(
        &self,
        kind: BasicAuthKind,
        headers: &HeaderMap,
        key: &str,
    ) -> Option<Self::Claims> {
        if kind != BasicAuthKind::Bearer {
            return None;
        }

        let value = headers.get(key)?.to_str().ok()?;
        let token = value.strip_prefix("Bearer ")?;

        self.token_verifier
            .verify_access_token(token)
            .await
            .ok()
            .map(|cognito| AuthClaims { cognito })
    }
}

#[async_trait]
impl apis::default::Default<ApiError> for ApiImpl {
    type Claims = AuthClaims;

    async fn generate_example_sentence(
        &self,
        _method: &Method,
        _host: &Host,
        _cookies: &CookieJar,
        claims: &Self::Claims,
        body: &models::GenerateExampleSentenceRequest,
    ) -> Result<GenerateExampleSentenceResponse, ApiError> {
        let user = self.find_or_create_user(claims).await?;
        let user_context_summary = self
            .learner_profiles
            .find_by_user_id(user.id)
            .await
            .map_err(|_| ApiError)?
            .map(|profile| {
                merge_context_summary(&body.user_context_summary, &profile.context_summary())
            })
            .unwrap_or_else(|| body.user_context_summary.clone());
        let generated = self
            .example_sentences
            .generate_personalized(GenerateExampleSentenceInput {
                target_text: body.target_text.clone(),
                user_context_summary: user_context_summary.clone(),
            })
            .await
            .map_err(|source| {
                error!(error = ?source, "failed to generate example sentence");
                ApiError
            })?;

        let mut personalization = models::GenerateExampleSentence200ResponsePersonalization::new();
        personalization.context_summary = Some(user_context_summary);

        let mut response = models::GenerateExampleSentence200Response::new(
            uuid::Uuid::now_v7().to_string(),
            generated.target_text,
            generated.target_sentence,
            String::new(),
            "personalized".to_string(),
        );
        response.personalization = Some(personalization);

        Ok(GenerateExampleSentenceResponse::Status200_PersonalizedExampleSentence(response))
    }

    async fn get_auth_session(
        &self,
        _method: &Method,
        _host: &Host,
        _cookies: &CookieJar,
        claims: &Self::Claims,
    ) -> Result<GetAuthSessionResponse, ApiError> {
        let user = match self
            .users
            .find_user_by_identity("cognito", &claims.cognito.sub)
            .await
            .map_err(|_| ApiError)?
        {
            Some(user) => user,
            None => self
                .users
                .create_user_for_identity("cognito", &claims.cognito.sub, &claims.cognito.email)
                .await
                .map_err(|_| ApiError)?,
        };

        Ok(
            GetAuthSessionResponse::Status200_CurrentAuthenticatedApplicationSession(
                models::GetAuthSession200Response::new(
                    true,
                    claims.cognito.sub.clone(),
                    user.id,
                    user.email,
                ),
            ),
        )
    }

    async fn get_learner_profile(
        &self,
        _method: &Method,
        _host: &Host,
        _cookies: &CookieJar,
        claims: &Self::Claims,
    ) -> Result<GetLearnerProfileResponse, ApiError> {
        let user = self.find_or_create_user(claims).await?;
        let profile = self
            .learner_profiles
            .find_by_user_id(user.id)
            .await
            .map_err(|_| ApiError)?
            .unwrap_or_else(|| LearnerProfile::new(user.id, LearnerProfileInput::default()));

        Ok(GetLearnerProfileResponse::Status200_CurrentLearnerProfile(
            convert_model(profile)?,
        ))
    }

    async fn get_learning_path(
        &self,
        _method: &Method,
        _host: &Host,
        _cookies: &CookieJar,
        path_params: &models::GetLearningPathPathParams,
    ) -> Result<GetLearningPathResponse, ApiError> {
        match self.queries.get_learning_path(&path_params.path_id).await {
            Ok(path) => Ok(GetLearningPathResponse::Status200_LearningPath(
                convert_model(path)?,
            )),
            Err(crate::application::queries::LearningCatalogQueryError::LearningPathNotFound {
                ..
            }) => Ok(GetLearningPathResponse::Status404_LearningPathNotFound),
            Err(_) => Err(ApiError),
        }
    }

    async fn get_learning_path_course(
        &self,
        _method: &Method,
        _host: &Host,
        _cookies: &CookieJar,
        path_params: &models::GetLearningPathCoursePathParams,
    ) -> Result<GetLearningPathCourseResponse, ApiError> {
        match self
            .queries
            .get_learning_path_course(&path_params.path_id, &path_params.course_id)
            .await
        {
            Ok(course) => Ok(GetLearningPathCourseResponse::Status200_Course(
                convert_model(course)?,
            )),
            Err(crate::application::queries::LearningCatalogQueryError::LearningPathNotFound {
                ..
            })
            | Err(crate::application::queries::LearningCatalogQueryError::CourseNotFound {
                ..
            }) => Ok(GetLearningPathCourseResponse::Status404_CourseNotFound),
            Err(_) => Err(ApiError),
        }
    }

    async fn get_learning_paths(
        &self,
        _method: &Method,
        _host: &Host,
        _cookies: &CookieJar,
    ) -> Result<GetLearningPathsResponse, ApiError> {
        self.queries
            .get_learning_paths()
            .await
            .map_err(|_| ApiError)
            .and_then(|paths| {
                paths
                    .into_iter()
                    .map(convert_model)
                    .collect::<Result<Vec<_>, _>>()
            })
            .map(GetLearningPathsResponse::Status200_LearningPaths)
    }

    async fn get_personalized_example_sentences(
        &self,
        _method: &Method,
        _host: &Host,
        _cookies: &CookieJar,
        claims: &Self::Claims,
    ) -> Result<GetPersonalizedExampleSentencesResponse, ApiError> {
        let user = self.find_or_create_user(claims).await?;
        let examples = self
            .personalized_examples
            .list_for_learner(user.id)
            .await
            .map_err(|_| ApiError)?
            .into_iter()
            .map(convert_personalized_example_model)
            .collect();

        Ok(
            GetPersonalizedExampleSentencesResponse::Status200_StoredPersonalizedExampleSentences(
                examples,
            ),
        )
    }

    async fn put_learner_profile(
        &self,
        _method: &Method,
        _host: &Host,
        _cookies: &CookieJar,
        claims: &Self::Claims,
        body: &models::PutLearnerProfileRequest,
    ) -> Result<PutLearnerProfileResponse, ApiError> {
        let user = self.find_or_create_user(claims).await?;
        let profile = self
            .learner_profiles
            .save(LearnerProfile::new(
                user.id,
                LearnerProfileInput {
                    learning_purpose: body.learning_purpose.clone(),
                    target_level: body.target_level.clone(),
                    deadline: body.deadline.clone(),
                    interests: body.interests.clone(),
                    favorite_content: body.favorite_content.clone(),
                    daily_scenes: body.daily_scenes.clone(),
                    english_use_cases: body.english_use_cases.clone(),
                    weak_points: body.weak_points.clone(),
                    vocabulary_focus: body.vocabulary_focus.clone(),
                },
            ))
            .await
            .map_err(|_| ApiError)?;
        self.personalization_jobs
            .publish(RegeneratePersonalizedExamplesJob::profile_updated(
                profile.user_id,
                profile.updated_at,
            ))
            .await
            .map_err(|_| ApiError)?;

        Ok(PutLearnerProfileResponse::Status200_SavedLearnerProfile(
            convert_model(profile)?,
        ))
    }
}

impl ApiImpl {
    async fn find_or_create_user(
        &self,
        claims: &AuthClaims,
    ) -> Result<crate::domain::user::User, ApiError> {
        match self
            .users
            .find_user_by_identity("cognito", &claims.cognito.sub)
            .await
            .map_err(|_| ApiError)?
        {
            Some(user) => Ok(user),
            None => self
                .users
                .create_user_for_identity("cognito", &claims.cognito.sub, &claims.cognito.email)
                .await
                .map_err(|_| ApiError),
        }
    }
}

fn convert_personalized_example_model(
    example: PersonalizedExampleSentence,
) -> models::GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner{
    let mut personalization = models::GenerateExampleSentence200ResponsePersonalization::new();
    personalization.context_summary = Some(example.context_summary);
    personalization.personalized_from_user_context_at = Some(example.updated_at);

    let mut model =
        models::GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner::new(
        example.id,
        example.target_text,
        example.target_sentence,
        example.source_translation,
        "personalized".to_string(),
    );
    model.personalization = Some(personalization);
    model
}

fn merge_context_summary(request_summary: &str, profile_summary: &str) -> String {
    match (request_summary.trim(), profile_summary.trim()) {
        ("", "") => String::new(),
        (request_summary, "") => request_summary.to_string(),
        ("", profile_summary) => profile_summary.to_string(),
        (request_summary, profile_summary) => {
            format!("{request_summary}\n\nSaved learner profile:\n{profile_summary}")
        }
    }
}

fn convert_model<T, U>(value: T) -> Result<U, ApiError>
where
    T: Serialize,
    U: DeserializeOwned,
{
    serde_json::from_value(serde_json::to_value(value).map_err(|_| ApiError)?).map_err(|_| ApiError)
}
