use async_trait::async_trait;
use aws_sdk_sqs::Client as SqsClient;

use crate::application::ports::{
    PersonalizationJobPublisher, PersonalizationJobPublisherError,
    RegeneratePersonalizedExamplesJob,
};

#[derive(Debug, Clone)]
pub struct SqsPersonalizationJobPublisherConfig {
    pub queue_url: String,
}

#[derive(Debug, Clone)]
pub struct SqsPersonalizationJobPublisher {
    client: Option<SqsClient>,
    queue_url: String,
}

impl SqsPersonalizationJobPublisher {
    pub fn new(client: SqsClient, config: SqsPersonalizationJobPublisherConfig) -> Self {
        Self {
            client: Some(client),
            queue_url: config.queue_url,
        }
    }

    pub fn new_for_message_format_tests(config: SqsPersonalizationJobPublisherConfig) -> Self {
        Self {
            client: None,
            queue_url: config.queue_url,
        }
    }

    pub fn message_body(
        &self,
        job: &RegeneratePersonalizedExamplesJob,
    ) -> Result<String, PersonalizationJobPublisherError> {
        serde_json::to_string(job).map_err(|source| {
            tracing::error!(%source, "failed to serialize personalization job");
            PersonalizationJobPublisherError::Unavailable
        })
    }
}

#[async_trait]
impl PersonalizationJobPublisher for SqsPersonalizationJobPublisher {
    async fn publish(
        &self,
        job: RegeneratePersonalizedExamplesJob,
    ) -> Result<(), PersonalizationJobPublisherError> {
        let client = self
            .client
            .as_ref()
            .ok_or(PersonalizationJobPublisherError::Unavailable)?;

        client
            .send_message()
            .queue_url(&self.queue_url)
            .message_body(self.message_body(&job)?)
            .send()
            .await
            .map_err(|source| {
                tracing::error!(%source, "failed to publish personalization job to SQS");
                PersonalizationJobPublisherError::Unavailable
            })?;

        Ok(())
    }
}
