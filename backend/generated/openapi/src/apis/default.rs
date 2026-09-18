use async_trait::async_trait;
use axum::extract::*;
use axum_extra::extract::CookieJar;
use bytes::Bytes;
use headers::Host;
use http::Method;
use serde::{Deserialize, Serialize};

use crate::{models, types::*};

#[derive(Debug, PartialEq, Serialize, Deserialize)]
#[must_use]
#[allow(clippy::large_enum_variant)]
pub enum GenerateExampleSentenceResponse {
    /// Personalized example sentence.
    Status200_PersonalizedExampleSentence
    (models::GenerateExampleSentence200Response)
    ,
    /// Authentication required.
    Status401_AuthenticationRequired
    (models::GenerateExampleSentence401Response)
}

#[derive(Debug, PartialEq, Serialize, Deserialize)]
#[must_use]
#[allow(clippy::large_enum_variant)]
pub enum GetAuthSessionResponse {
    /// Current authenticated application session.
    Status200_CurrentAuthenticatedApplicationSession
    (models::GetAuthSession200Response)
    ,
    /// Missing, invalid, or expired access token.
    Status401_Missing
    (models::GetAuthSession401Response)
}

#[derive(Debug, PartialEq, Serialize, Deserialize)]
#[must_use]
#[allow(clippy::large_enum_variant)]
pub enum GetLearnerProfileResponse {
    /// Current learner profile.
    Status200_CurrentLearnerProfile
    (models::GetLearnerProfile200Response)
    ,
    /// Missing, invalid, or expired access token.
    Status401_Missing
    (models::GenerateExampleSentence401Response)
}

#[derive(Debug, PartialEq, Serialize, Deserialize)]
#[must_use]
#[allow(clippy::large_enum_variant)]
pub enum GetLearningPathResponse {
    /// Learning path.
    Status200_LearningPath
    (models::GetLearningPath200Response)
    ,
    /// Learning path not found.
    Status404_LearningPathNotFound
}

#[derive(Debug, PartialEq, Serialize, Deserialize)]
#[must_use]
#[allow(clippy::large_enum_variant)]
pub enum GetLearningPathCourseResponse {
    /// Course.
    Status200_Course
    (models::GetLearningPathCourse200Response)
    ,
    /// Course not found.
    Status404_CourseNotFound
}

#[derive(Debug, PartialEq, Serialize, Deserialize)]
#[must_use]
#[allow(clippy::large_enum_variant)]
pub enum GetLearningPathsResponse {
    /// Learning paths.
    Status200_LearningPaths
    (Vec<models::GetLearningPaths200ResponseInner>)
}

#[derive(Debug, PartialEq, Serialize, Deserialize)]
#[must_use]
#[allow(clippy::large_enum_variant)]
pub enum GetPersonalizedExampleSentencesResponse {
    /// Stored personalized example sentences.
    Status200_StoredPersonalizedExampleSentences
    (Vec<models::GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner>)
    ,
    /// Missing, invalid, or expired access token.
    Status401_Missing
    (models::GenerateExampleSentence401Response)
}

#[derive(Debug, PartialEq, Serialize, Deserialize)]
#[must_use]
#[allow(clippy::large_enum_variant)]
pub enum PutLearnerProfileResponse {
    /// Saved learner profile.
    Status200_SavedLearnerProfile
    (models::PutLearnerProfileRequest)
    ,
    /// Missing, invalid, or expired access token.
    Status401_Missing
    (models::GenerateExampleSentence401Response)
}




/// Default
#[async_trait]
#[allow(clippy::ptr_arg)]
pub trait Default<E: std::fmt::Debug + Send + Sync + 'static = ()>: super::ErrorHandler<E> {
    type Claims;

    /// Generate a personalized example sentence.
    ///
    /// GenerateExampleSentence - POST /example-sentences
    async fn generate_example_sentence(
    &self,
    
    method: &Method,
    host: &Host,
    cookies: &CookieJar,
        claims: &Self::Claims,
            body: &models::GenerateExampleSentenceRequest,
    ) -> Result<GenerateExampleSentenceResponse, E>;

    /// Get the current auth session.
    ///
    /// GetAuthSession - GET /auth/session
    async fn get_auth_session(
    &self,
    
    method: &Method,
    host: &Host,
    cookies: &CookieJar,
        claims: &Self::Claims,
    ) -> Result<GetAuthSessionResponse, E>;

    /// Get the current learner profile.
    ///
    /// GetLearnerProfile - GET /me/learner-profile
    async fn get_learner_profile(
    &self,
    
    method: &Method,
    host: &Host,
    cookies: &CookieJar,
        claims: &Self::Claims,
    ) -> Result<GetLearnerProfileResponse, E>;

    /// Get a learning path.
    ///
    /// GetLearningPath - GET /learning-paths/{pathId}
    async fn get_learning_path(
    &self,
    
    method: &Method,
    host: &Host,
    cookies: &CookieJar,
      path_params: &models::GetLearningPathPathParams,
    ) -> Result<GetLearningPathResponse, E>;

    /// Get a course in a learning path.
    ///
    /// GetLearningPathCourse - GET /learning-paths/{pathId}/courses/{courseId}
    async fn get_learning_path_course(
    &self,
    
    method: &Method,
    host: &Host,
    cookies: &CookieJar,
      path_params: &models::GetLearningPathCoursePathParams,
    ) -> Result<GetLearningPathCourseResponse, E>;

    /// List learning paths.
    ///
    /// GetLearningPaths - GET /learning-paths
    async fn get_learning_paths(
    &self,
    
    method: &Method,
    host: &Host,
    cookies: &CookieJar,
    ) -> Result<GetLearningPathsResponse, E>;

    /// Get stored personalized example sentences for the current learner.
    ///
    /// GetPersonalizedExampleSentences - GET /me/personalized-example-sentences
    async fn get_personalized_example_sentences(
    &self,
    
    method: &Method,
    host: &Host,
    cookies: &CookieJar,
        claims: &Self::Claims,
    ) -> Result<GetPersonalizedExampleSentencesResponse, E>;

    /// Save the current learner profile.
    ///
    /// PutLearnerProfile - PUT /me/learner-profile
    async fn put_learner_profile(
    &self,
    
    method: &Method,
    host: &Host,
    cookies: &CookieJar,
        claims: &Self::Claims,
            body: &models::PutLearnerProfileRequest,
    ) -> Result<PutLearnerProfileResponse, E>;
}
