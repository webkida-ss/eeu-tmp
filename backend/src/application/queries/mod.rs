use std::sync::Arc;

use thiserror::Error;

use crate::{
    application::ports::{LearningCatalogRepository, LearningCatalogRepositoryError},
    domain::learning_catalog::{Course, LearningPath},
};

#[derive(Clone)]
pub struct LearningCatalogQueries {
    repository: Arc<dyn LearningCatalogRepository>,
}

impl LearningCatalogQueries {
    pub fn new(repository: Arc<dyn LearningCatalogRepository>) -> Self {
        Self { repository }
    }

    pub async fn get_learning_paths(&self) -> Result<Vec<LearningPath>, LearningCatalogQueryError> {
        self.repository
            .list_learning_paths()
            .await
            .map_err(LearningCatalogQueryError::Repository)
    }

    pub async fn get_learning_path(
        &self,
        path_id: &str,
    ) -> Result<LearningPath, LearningCatalogQueryError> {
        self.repository
            .find_learning_path(path_id)
            .await
            .map_err(LearningCatalogQueryError::Repository)?
            .ok_or_else(|| LearningCatalogQueryError::LearningPathNotFound {
                path_id: path_id.to_string(),
            })
    }

    pub async fn get_learning_path_course(
        &self,
        path_id: &str,
        course_id: &str,
    ) -> Result<Course, LearningCatalogQueryError> {
        self.repository
            .find_course(path_id, course_id)
            .await
            .map_err(LearningCatalogQueryError::Repository)?
            .ok_or_else(|| LearningCatalogQueryError::CourseNotFound {
                path_id: path_id.to_string(),
                course_id: course_id.to_string(),
            })
    }
}

#[derive(Debug, Error)]
pub enum LearningCatalogQueryError {
    #[error("learning path not found: {path_id}")]
    LearningPathNotFound { path_id: String },
    #[error("course not found: {path_id}/{course_id}")]
    CourseNotFound { path_id: String, course_id: String },
    #[error(transparent)]
    Repository(#[from] LearningCatalogRepositoryError),
}

#[cfg(test)]
mod tests {
    use super::*;
    use async_trait::async_trait;

    #[derive(Clone)]
    struct InMemoryLearningCatalogRepository {
        paths: Vec<LearningPath>,
    }

    #[async_trait]
    impl LearningCatalogRepository for InMemoryLearningCatalogRepository {
        async fn list_learning_paths(
            &self,
        ) -> Result<Vec<LearningPath>, LearningCatalogRepositoryError> {
            Ok(self.paths.clone())
        }

        async fn find_learning_path(
            &self,
            path_id: &str,
        ) -> Result<Option<LearningPath>, LearningCatalogRepositoryError> {
            Ok(self.paths.iter().find(|path| path.id == path_id).cloned())
        }

        async fn find_course(
            &self,
            path_id: &str,
            course_id: &str,
        ) -> Result<Option<Course>, LearningCatalogRepositoryError> {
            Ok(self
                .paths
                .iter()
                .find(|path| path.id == path_id)
                .and_then(|path| path.courses.iter().find(|course| course.id == course_id))
                .cloned())
        }
    }

    #[tokio::test]
    async fn returns_not_found_for_missing_path() {
        let queries = LearningCatalogQueries::new(Arc::new(InMemoryLearningCatalogRepository {
            paths: Vec::new(),
        }));

        let error = queries.get_learning_path("missing").await.unwrap_err();

        assert!(matches!(
            error,
            LearningCatalogQueryError::LearningPathNotFound { .. }
        ));
    }
}
