use async_trait::async_trait;
use chrono::{TimeZone, Utc};
use english_backend::application::ports::{
    PersonalizationJobPublisher, PersonalizationJobPublisherError,
    RegeneratePersonalizedExamplesJob,
};
use std::sync::Mutex;
use uuid::Uuid;

#[tokio::test]
async fn publishes_profile_updated_personalization_job() {
    let publisher = RecordingPersonalizationJobPublisher::default();
    let learner_id = Uuid::now_v7();
    let profile_updated_at = Utc.with_ymd_and_hms(2026, 6, 13, 8, 0, 0).unwrap();
    let job = RegeneratePersonalizedExamplesJob::profile_updated(learner_id, profile_updated_at);

    publisher.publish(job.clone()).await.unwrap();

    assert_eq!(publisher.jobs.lock().unwrap().as_slice(), &[job.clone()]);
    assert_eq!(job.learner_id, learner_id);
    assert_eq!(job.profile_version, "2026-06-13T08:00:00+00:00");
    assert_eq!(
        job.idempotency_key,
        format!("{learner_id}:2026-06-13T08:00:00+00:00")
    );
    assert_eq!(job.reason, "profile_updated");
}

#[derive(Default)]
struct RecordingPersonalizationJobPublisher {
    jobs: Mutex<Vec<RegeneratePersonalizedExamplesJob>>,
}

#[async_trait]
impl PersonalizationJobPublisher for RecordingPersonalizationJobPublisher {
    async fn publish(
        &self,
        job: RegeneratePersonalizedExamplesJob,
    ) -> Result<(), PersonalizationJobPublisherError> {
        self.jobs.lock().unwrap().push(job);
        Ok(())
    }
}
