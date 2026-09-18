use aws_lambda_events::event::sqs::{SqsBatchResponse, SqsEvent};
use english_backend::{bootstrap, user_interface::worker::parse_personalization_job_message};
use lambda_runtime::{run, service_fn, Error, LambdaEvent};

#[tokio::main]
async fn main() -> Result<(), Error> {
    run(service_fn(handle_event)).await
}

async fn handle_event(event: LambdaEvent<SqsEvent>) -> Result<SqsBatchResponse, Error> {
    let service = bootstrap::build_personalized_example_regeneration_service().await?;
    let mut response = SqsBatchResponse::default();

    for record in event.payload.records {
        let message_id = record.message_id.unwrap_or_default();
        let result = match record.body {
            Some(body) => match parse_personalization_job_message(&body) {
                Ok(job) => service
                    .regenerate(job)
                    .await
                    .map_err(|error| error.to_string()),
                Err(error) => Err(error.to_string()),
            },
            None => Err("missing SQS message body".to_string()),
        };

        if let Err(error) = result {
            tracing::error!(%error, %message_id, "failed to process personalization job");
            response.add_failure(message_id);
        }
    }

    Ok(response)
}
