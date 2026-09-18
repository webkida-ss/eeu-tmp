use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
};
use serde_json::Value;
use tower::ServiceExt;

const TEST_HOST: &str = "localhost:18080";

#[tokio::test]
async fn generates_personalized_example_sentence_with_dev_ai() {
    let app = english_backend::bootstrap::build_app()
        .await
        .unwrap()
        .router;

    let response = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/example-sentences")
                .header("host", TEST_HOST)
                .header("authorization", "Bearer header.payload.signature")
                .header("content-type", "application/json")
                .body(Body::from(
                    r#"{"targetText":"apply","userContextSummary":"The learner works in an office."}"#,
                ))
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);

    let body = to_json(response.into_body()).await;
    assert_eq!(body["targetText"], "apply");
    assert_eq!(body["variant"], "personalized");
    assert!(body["targetSentence"].as_str().unwrap().contains("apply"));
}

async fn to_json(body: Body) -> Value {
    let bytes = to_bytes(body, usize::MAX).await.unwrap();
    serde_json::from_slice(&bytes).unwrap()
}
