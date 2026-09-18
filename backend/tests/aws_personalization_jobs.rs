use chrono::{TimeZone, Utc};
use english_backend::{
    application::ports::RegeneratePersonalizedExamplesJob,
    infrastructure::messaging::{
        SqsPersonalizationJobPublisher, SqsPersonalizationJobPublisherConfig,
    },
    user_interface::worker::parse_personalization_job_message,
};
use serde_json::Value;
use uuid::Uuid;

#[test]
fn serializes_personalization_job_as_sqs_message_body() {
    let learner_id = Uuid::now_v7();
    let job = RegeneratePersonalizedExamplesJob::profile_updated(
        learner_id,
        Utc.with_ymd_and_hms(2026, 6, 13, 8, 0, 0).unwrap(),
    );
    let publisher = SqsPersonalizationJobPublisher::new_for_message_format_tests(
        SqsPersonalizationJobPublisherConfig {
            queue_url: "https://sqs.ap-northeast-1.amazonaws.com/123/personalization-jobs"
                .to_string(),
        },
    );

    let body = publisher.message_body(&job).unwrap();
    let value: Value = serde_json::from_str(&body).unwrap();

    assert_eq!(value["learnerId"], learner_id.to_string());
    assert_eq!(value["profileVersion"], "2026-06-13T08:00:00+00:00");
    assert_eq!(value["reason"], "profile_updated");
}

#[test]
fn parses_personalization_job_from_sqs_message_body() {
    let learner_id = Uuid::now_v7();
    let job = RegeneratePersonalizedExamplesJob::profile_updated(
        learner_id,
        Utc.with_ymd_and_hms(2026, 6, 13, 8, 0, 0).unwrap(),
    );
    let body = serde_json::to_string(&job).unwrap();

    let parsed = parse_personalization_job_message(&body).unwrap();

    assert_eq!(parsed, job);
}
