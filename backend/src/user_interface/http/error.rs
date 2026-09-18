use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::Serialize;

use crate::application::queries::LearningCatalogQueryError;

#[derive(Debug)]
pub struct HttpError {
    status: StatusCode,
    code: &'static str,
    message: String,
}

impl From<LearningCatalogQueryError> for HttpError {
    fn from(error: LearningCatalogQueryError) -> Self {
        match error {
            LearningCatalogQueryError::LearningPathNotFound { .. }
            | LearningCatalogQueryError::CourseNotFound { .. } => Self {
                status: StatusCode::NOT_FOUND,
                code: "not_found",
                message: error.to_string(),
            },
            LearningCatalogQueryError::Repository(_) => Self {
                status: StatusCode::INTERNAL_SERVER_ERROR,
                code: "catalog_unavailable",
                message: "Learning catalog is unavailable.".to_string(),
            },
        }
    }
}

impl IntoResponse for HttpError {
    fn into_response(self) -> Response {
        let status = self.status;
        let body = Json(ErrorResponse {
            code: self.code,
            message: self.message,
        });

        (status, body).into_response()
    }
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct ErrorResponse {
    code: &'static str,
    message: String,
}
