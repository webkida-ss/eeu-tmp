use std::sync::{Mutex, MutexGuard};

use async_trait::async_trait;

use crate::application::ports::{
    PersonalizationJobPublisher, PersonalizationJobPublisherError,
    RegeneratePersonalizedExamplesJob,
};

#[derive(Debug, Default)]
pub struct InMemoryPersonalizationJobPublisher {
    jobs: Mutex<Vec<RegeneratePersonalizedExamplesJob>>,
}

impl InMemoryPersonalizationJobPublisher {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn published_jobs(
        &self,
    ) -> Result<Vec<RegeneratePersonalizedExamplesJob>, PersonalizationJobPublisherError> {
        Ok(self.lock_jobs()?.clone())
    }

    fn lock_jobs(
        &self,
    ) -> Result<
        MutexGuard<'_, Vec<RegeneratePersonalizedExamplesJob>>,
        PersonalizationJobPublisherError,
    > {
        self.jobs
            .lock()
            .map_err(|_| PersonalizationJobPublisherError::Unavailable)
    }
}

#[async_trait]
impl PersonalizationJobPublisher for InMemoryPersonalizationJobPublisher {
    async fn publish(
        &self,
        job: RegeneratePersonalizedExamplesJob,
    ) -> Result<(), PersonalizationJobPublisherError> {
        self.lock_jobs()?.push(job);
        Ok(())
    }
}
