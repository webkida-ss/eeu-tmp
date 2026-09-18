use std::{fs, path::Path};

use async_trait::async_trait;
use thiserror::Error;

use crate::{
    application::ports::{LearningCatalogRepository, LearningCatalogRepositoryError},
    domain::learning_catalog::{Course, LearningPath},
};

#[derive(Debug, Clone)]
pub struct JsonLearningCatalogRepository {
    paths: Vec<LearningPath>,
}

impl JsonLearningCatalogRepository {
    pub async fn load(path: impl AsRef<Path>) -> Result<Self, JsonLearningCatalogError> {
        let content =
            fs::read_to_string(path.as_ref()).map_err(|source| JsonLearningCatalogError::Read {
                path: path.as_ref().display().to_string(),
                source,
            })?;
        let paths = serde_json::from_str(&content).map_err(JsonLearningCatalogError::Parse)?;

        Ok(Self { paths })
    }
}

#[async_trait]
impl LearningCatalogRepository for JsonLearningCatalogRepository {
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

#[derive(Debug, Error)]
pub enum JsonLearningCatalogError {
    #[error("failed to read learning catalog seed at {path}")]
    Read {
        path: String,
        #[source]
        source: std::io::Error,
    },
    #[error("failed to parse learning catalog seed")]
    Parse(#[from] serde_json::Error),
}
