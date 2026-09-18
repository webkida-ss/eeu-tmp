use axum::{
    extract::{Path, State},
    Json,
};

use crate::{
    application::queries::LearningCatalogQueries,
    domain::learning_catalog::{Course, LearningPath},
    user_interface::http::error::HttpError,
};

pub async fn healthz() -> &'static str {
    "ok"
}

pub async fn get_learning_paths(
    State(queries): State<LearningCatalogQueries>,
) -> Result<Json<Vec<LearningPath>>, HttpError> {
    queries
        .get_learning_paths()
        .await
        .map(Json)
        .map_err(HttpError::from)
}

pub async fn get_learning_path(
    State(queries): State<LearningCatalogQueries>,
    Path(path_id): Path<String>,
) -> Result<Json<LearningPath>, HttpError> {
    queries
        .get_learning_path(&path_id)
        .await
        .map(Json)
        .map_err(HttpError::from)
}

pub async fn get_learning_path_course(
    State(queries): State<LearningCatalogQueries>,
    Path((path_id, course_id)): Path<(String, String)>,
) -> Result<Json<Course>, HttpError> {
    queries
        .get_learning_path_course(&path_id, &course_id)
        .await
        .map(Json)
        .map_err(HttpError::from)
}
