use std::{
    collections::HashMap,
    sync::{Mutex, MutexGuard},
};

use async_trait::async_trait;
use uuid::Uuid;

use crate::{
    application::ports::{LearnerProfileRepository, LearnerProfileRepositoryError},
    domain::learner_profile::LearnerProfile,
};

#[derive(Debug, Default)]
pub struct InMemoryLearnerProfileRepository {
    profiles: Mutex<HashMap<Uuid, LearnerProfile>>,
}

impl InMemoryLearnerProfileRepository {
    pub fn new() -> Self {
        Self::default()
    }

    fn lock_profiles(
        &self,
    ) -> Result<MutexGuard<'_, HashMap<Uuid, LearnerProfile>>, LearnerProfileRepositoryError> {
        self.profiles
            .lock()
            .map_err(|_| LearnerProfileRepositoryError::Unavailable)
    }
}

#[async_trait]
impl LearnerProfileRepository for InMemoryLearnerProfileRepository {
    async fn find_by_user_id(
        &self,
        user_id: Uuid,
    ) -> Result<Option<LearnerProfile>, LearnerProfileRepositoryError> {
        Ok(self.lock_profiles()?.get(&user_id).cloned())
    }

    async fn save(
        &self,
        profile: LearnerProfile,
    ) -> Result<LearnerProfile, LearnerProfileRepositoryError> {
        self.lock_profiles()?
            .insert(profile.user_id, profile.clone());

        Ok(profile)
    }
}
