use crate::application::ports::RegeneratePersonalizedExamplesJob;

pub fn parse_personalization_job_message(
    body: &str,
) -> Result<RegeneratePersonalizedExamplesJob, WorkerError> {
    serde_json::from_str(body).map_err(|source| {
        tracing::error!(%source, "failed to parse personalization job message");
        WorkerError::InvalidMessage
    })
}

#[derive(Debug, thiserror::Error)]
pub enum WorkerError {
    #[error("invalid worker message")]
    InvalidMessage,
}
