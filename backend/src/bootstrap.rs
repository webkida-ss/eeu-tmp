use std::{collections::HashMap, env, net::SocketAddr, path::PathBuf, sync::Arc};

use aws_config::BehaviorVersion;
use aws_sdk_dynamodb::{config::Region, Client as DynamoDbClient};
use aws_sdk_sqs::Client as SqsClient;
use axum::Router;
use thiserror::Error;
use tower_http::{
    cors::CorsLayer,
    trace::{DefaultOnRequest, DefaultOnResponse, TraceLayer},
};
use tracing::Level;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter};

use crate::{
    application::{
        ai::{
            model::{AiModelCatalog, AiProvider},
            ports::{AiClient, AiModelCatalogRepository, AiProviderGateway},
            service::AiService,
        },
        auth::{
            CognitoJwtVerifier, CognitoTokenVerifier, CognitoVerifierConfig,
            DevCognitoTokenVerifier,
        },
        example_sentences::ExampleSentenceService,
        personalization::{AiPersonalizedExampleGenerator, PersonalizedExampleRegenerationService},
        personalized_examples::PersonalizedExampleQueries,
        ports::{
            LearnerProfileRepository, LearningCatalogRepository, PersonalizationJobPublisher,
            PersonalizedExampleRepository, UserRepository,
        },
        queries::LearningCatalogQueries,
    },
    infrastructure::{
        ai::{DevAiProviderGateway, OpenAiCompatibleGateway, RoutingAiProviderGateway},
        auth::{HttpCognitoJwksProvider, HttpCognitoUserInfoProvider},
        messaging::{SqsPersonalizationJobPublisher, SqsPersonalizationJobPublisherConfig},
        persistence::{
            DynamoDbAiModelCatalogRepository, DynamoDbAiModelCatalogRepositoryConfig,
            DynamoDbLearnerProfileRepository, DynamoDbLearnerProfileRepositoryConfig,
            DynamoDbLearningCatalogRepository, DynamoDbLearningCatalogRepositoryConfig,
            DynamoDbPersonalizedExampleRepository, DynamoDbPersonalizedExampleRepositoryConfig,
            DynamoDbUserRepository, DynamoDbUserRepositoryConfig, InMemoryLearnerProfileRepository,
            InMemoryPersonalizationJobPublisher, InMemoryPersonalizedExampleRepository,
            InMemoryUserRepository, JsonLearningCatalogRepository,
        },
    },
    user_interface::http,
};

#[derive(Debug, Clone)]
pub struct AppConfig {
    pub host: String,
    pub port: u16,
    pub catalog_data_path: PathBuf,
    pub catalog_repository: CatalogRepositoryKind,
    pub dynamodb_table_name: Option<String>,
    pub dynamodb_endpoint: Option<String>,
    pub aws_region: String,
    pub cognito: CognitoVerifierConfig,
    pub cognito_userinfo_endpoint: Option<String>,
    pub user_repository: UserRepositoryKind,
    pub user_dynamodb_table_name: Option<String>,
    pub ai_model_catalog_repository: AiModelCatalogRepositoryKind,
    pub ai_model_catalog_dynamodb_table_name: Option<String>,
    pub personalization_job_publisher: PersonalizationJobPublisherKind,
    pub personalization_jobs_queue_url: Option<String>,
    pub personalized_example_repository: PersonalizedExampleRepositoryKind,
    pub personalized_example_dynamodb_table_name: Option<String>,
    pub ai: AiConfig,
}

#[derive(Debug, Clone)]
pub struct AiConfig {
    pub openai_compatible_endpoint: Option<String>,
    pub openai_compatible_api_key: Option<String>,
}

impl AppConfig {
    pub fn from_env() -> Result<Self, BootstrapError> {
        Self::from_env_values(|key| env::var(key).ok())
    }

    fn from_env_values(get_env: impl Fn(&str) -> Option<String>) -> Result<Self, BootstrapError> {
        let host = get_env("APP_HOST").unwrap_or_else(|| "0.0.0.0".to_string());
        let port = get_env("APP_PORT")
            .map(|value| value.parse::<u16>())
            .transpose()
            .map_err(|source| BootstrapError::InvalidPort { source })?
            .unwrap_or(8080);
        let catalog_data_path = get_env("CATALOG_DATA_PATH")
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                    .join("../frontend/src/features/learning/data/learningPaths.json")
            });
        let catalog_repository = get_env("CATALOG_REPOSITORY")
            .unwrap_or_else(|| "json".to_string())
            .parse()?;
        let dynamodb_table_name = get_env("DYNAMODB_TABLE_NAME");
        let dynamodb_endpoint = get_env("DYNAMODB_ENDPOINT");
        let aws_region = get_env("AWS_REGION").unwrap_or_else(|| "ap-northeast-1".to_string());
        let user_repository = get_env("USER_REPOSITORY")
            .unwrap_or_else(|| "in_memory".to_string())
            .parse()?;
        let user_dynamodb_table_name =
            get_env("USER_DYNAMODB_TABLE_NAME").or_else(|| dynamodb_table_name.clone());
        let ai_model_catalog_repository = get_env("AI_MODEL_CATALOG_REPOSITORY")
            .unwrap_or_else(|| "in_memory".to_string())
            .parse()?;
        let ai_model_catalog_dynamodb_table_name =
            get_env("AI_MODEL_CATALOG_DYNAMODB_TABLE_NAME").or_else(|| dynamodb_table_name.clone());
        let personalization_job_publisher = get_env("PERSONALIZATION_JOB_PUBLISHER")
            .unwrap_or_else(|| "in_memory".to_string())
            .parse()?;
        let personalization_jobs_queue_url = get_env("PERSONALIZATION_JOBS_QUEUE_URL");
        let personalized_example_repository = get_env("PERSONALIZED_EXAMPLE_REPOSITORY")
            .unwrap_or_else(|| "in_memory".to_string())
            .parse()?;
        let personalized_example_dynamodb_table_name =
            get_env("PERSONALIZED_EXAMPLE_DYNAMODB_TABLE_NAME")
                .or_else(|| dynamodb_table_name.clone());
        let cognito_region = get_env("COGNITO_REGION").unwrap_or_else(|| aws_region.clone());
        let cognito = CognitoVerifierConfig {
            region: cognito_region,
            user_pool_id: get_env("COGNITO_USER_POOL_ID").unwrap_or_default(),
            client_id: get_env("COGNITO_CLIENT_ID").unwrap_or_default(),
        };
        let cognito_userinfo_endpoint = get_env("COGNITO_USERINFO_ENDPOINT").or_else(|| {
            get_env("COGNITO_HOSTED_UI_BASE_URL")
                .map(|base_url| format!("{}/oauth2/userInfo", base_url.trim_end_matches('/')))
        });
        let ai = AiConfig {
            openai_compatible_endpoint: get_env("AI_OPENAI_COMPATIBLE_ENDPOINT"),
            openai_compatible_api_key: get_env("AI_OPENAI_COMPATIBLE_API_KEY"),
        };

        Ok(Self {
            host,
            port,
            catalog_data_path,
            catalog_repository,
            dynamodb_table_name,
            dynamodb_endpoint,
            aws_region,
            cognito,
            cognito_userinfo_endpoint,
            user_repository,
            user_dynamodb_table_name,
            ai_model_catalog_repository,
            ai_model_catalog_dynamodb_table_name,
            personalization_job_publisher,
            personalization_jobs_queue_url,
            personalized_example_repository,
            personalized_example_dynamodb_table_name,
            ai,
        })
    }

    pub fn listen_addr(&self) -> String {
        format!("{}:{}", self.host, self.port)
    }
}

pub struct App {
    pub config: AppConfig,
    pub router: Router,
}

pub async fn build_app() -> Result<App, BootstrapError> {
    init_tracing();

    let config = AppConfig::from_env()?;
    let repository = build_learning_catalog_repository(&config).await?;
    let queries = LearningCatalogQueries::new(repository);
    let token_verifier = build_cognito_token_verifier(&config);
    let users = build_user_repository(&config).await?;
    let learner_profiles = build_learner_profile_repository(&config).await?;
    let personalization_jobs = build_personalization_job_publisher(&config).await?;
    let personalized_examples_repository = build_personalized_example_repository(&config).await?;
    let personalized_examples = PersonalizedExampleQueries::new(personalized_examples_repository);
    let ai = build_ai_client(&config).await?;
    let example_sentences = ExampleSentenceService::new(ai);
    let router = http::routes::router(
        queries,
        token_verifier,
        users,
        learner_profiles,
        personalization_jobs,
        personalized_examples,
        example_sentences,
    )
    .layer(CorsLayer::permissive())
    .layer(
        TraceLayer::new_for_http()
            .on_request(DefaultOnRequest::new().level(Level::INFO))
            .on_response(DefaultOnResponse::new().level(Level::INFO)),
    );

    Ok(App { config, router })
}

pub async fn build_personalized_example_regeneration_service(
) -> Result<PersonalizedExampleRegenerationService, BootstrapError> {
    init_tracing();

    let config = AppConfig::from_env()?;
    let profiles = build_learner_profile_repository(&config).await?;
    let catalog = build_learning_catalog_repository(&config).await?;
    let personalized_examples = build_personalized_example_repository(&config).await?;
    let ai = build_ai_client(&config).await?;
    let example_sentences = ExampleSentenceService::new(ai);

    Ok(PersonalizedExampleRegenerationService::new(
        profiles,
        catalog,
        personalized_examples,
        Arc::new(AiPersonalizedExampleGenerator::new(example_sentences)),
    ))
}

async fn build_personalization_job_publisher(
    config: &AppConfig,
) -> Result<Arc<dyn PersonalizationJobPublisher>, BootstrapError> {
    match config.personalization_job_publisher {
        PersonalizationJobPublisherKind::InMemory => {
            Ok(Arc::new(InMemoryPersonalizationJobPublisher::new()))
        }
        PersonalizationJobPublisherKind::Sqs => {
            let queue_url = config
                .personalization_jobs_queue_url
                .clone()
                .ok_or(BootstrapError::MissingPersonalizationJobsQueueUrl)?;
            Ok(Arc::new(SqsPersonalizationJobPublisher::new(
                build_sqs_client(config).await,
                SqsPersonalizationJobPublisherConfig { queue_url },
            )))
        }
    }
}

async fn build_personalized_example_repository(
    config: &AppConfig,
) -> Result<Arc<dyn PersonalizedExampleRepository>, BootstrapError> {
    match config.personalized_example_repository {
        PersonalizedExampleRepositoryKind::InMemory => {
            Ok(Arc::new(InMemoryPersonalizedExampleRepository::new()))
        }
        PersonalizedExampleRepositoryKind::DynamoDb => {
            let table_name = config
                .personalized_example_dynamodb_table_name
                .clone()
                .ok_or(BootstrapError::MissingPersonalizedExampleDynamoDbTableName)?;
            Ok(Arc::new(DynamoDbPersonalizedExampleRepository::new(
                build_dynamodb_client(config).await,
                DynamoDbPersonalizedExampleRepositoryConfig { table_name },
            )))
        }
    }
}

async fn build_user_repository(
    config: &AppConfig,
) -> Result<Arc<dyn UserRepository>, BootstrapError> {
    match config.user_repository {
        UserRepositoryKind::InMemory => Ok(Arc::new(InMemoryUserRepository::new())),
        UserRepositoryKind::DynamoDb => {
            let table_name = config
                .user_dynamodb_table_name
                .clone()
                .ok_or(BootstrapError::MissingUserDynamoDbTableName)?;
            let client = build_dynamodb_client(config).await;

            Ok(Arc::new(DynamoDbUserRepository::new(
                client,
                DynamoDbUserRepositoryConfig { table_name },
            )))
        }
    }
}

async fn build_learner_profile_repository(
    config: &AppConfig,
) -> Result<Arc<dyn LearnerProfileRepository>, BootstrapError> {
    match config.user_repository {
        UserRepositoryKind::InMemory => Ok(Arc::new(InMemoryLearnerProfileRepository::new())),
        UserRepositoryKind::DynamoDb => {
            let table_name = config
                .user_dynamodb_table_name
                .clone()
                .ok_or(BootstrapError::MissingUserDynamoDbTableName)?;
            let client = build_dynamodb_client(config).await;

            Ok(Arc::new(DynamoDbLearnerProfileRepository::new(
                client,
                DynamoDbLearnerProfileRepositoryConfig { table_name },
            )))
        }
    }
}

fn build_cognito_token_verifier(config: &AppConfig) -> Arc<dyn CognitoTokenVerifier> {
    if config.cognito.user_pool_id.is_empty() || config.cognito.client_id.is_empty() {
        return Arc::new(DevCognitoTokenVerifier);
    }

    match &config.cognito_userinfo_endpoint {
        Some(userinfo_endpoint) => Arc::new(CognitoJwtVerifier::with_jwks_and_userinfo_provider(
            config.cognito.clone(),
            Arc::new(HttpCognitoJwksProvider::new()),
            userinfo_endpoint.clone(),
            Arc::new(HttpCognitoUserInfoProvider::new()),
        )),
        None => Arc::new(CognitoJwtVerifier::with_jwks_provider(
            config.cognito.clone(),
            Arc::new(HttpCognitoJwksProvider::new()),
        )),
    }
}

async fn build_ai_client(config: &AppConfig) -> Result<Arc<dyn AiClient>, BootstrapError> {
    let catalog = build_ai_model_catalog_repository(config).await?;
    let gateway = build_ai_provider_gateway(config)?;

    Ok(Arc::new(AiService::new(catalog, gateway)))
}

async fn build_ai_model_catalog_repository(
    config: &AppConfig,
) -> Result<Arc<dyn AiModelCatalogRepository>, BootstrapError> {
    match config.ai_model_catalog_repository {
        AiModelCatalogRepositoryKind::InMemory => Ok(Arc::new(AiModelCatalog::default())),
        AiModelCatalogRepositoryKind::DynamoDb => {
            let table_name = config
                .ai_model_catalog_dynamodb_table_name
                .clone()
                .ok_or(BootstrapError::MissingAiModelCatalogDynamoDbTableName)?;
            let client = build_dynamodb_client(config).await;

            Ok(Arc::new(DynamoDbAiModelCatalogRepository::new(
                client,
                DynamoDbAiModelCatalogRepositoryConfig { table_name },
            )))
        }
    }
}

fn build_ai_provider_gateway(
    config: &AppConfig,
) -> Result<Arc<dyn AiProviderGateway>, BootstrapError> {
    let mut gateways: HashMap<AiProvider, Arc<dyn AiProviderGateway>> = HashMap::from([(
        AiProvider::Dev,
        Arc::new(DevAiProviderGateway) as Arc<dyn AiProviderGateway>,
    )]);

    match (
        &config.ai.openai_compatible_endpoint,
        &config.ai.openai_compatible_api_key,
    ) {
        (Some(endpoint), Some(api_key)) => {
            gateways.insert(
                AiProvider::OpenAiCompatible,
                Arc::new(OpenAiCompatibleGateway::new(
                    endpoint.clone(),
                    api_key.clone(),
                )),
            );
        }
        (Some(_), None) => return Err(BootstrapError::MissingOpenAiCompatibleApiKey),
        (None, Some(_)) => return Err(BootstrapError::MissingOpenAiCompatibleEndpoint),
        (None, None) => {}
    }

    Ok(Arc::new(RoutingAiProviderGateway::new(gateways)))
}

async fn build_learning_catalog_repository(
    config: &AppConfig,
) -> Result<Arc<dyn LearningCatalogRepository>, BootstrapError> {
    match config.catalog_repository {
        CatalogRepositoryKind::Json => Ok(Arc::new(
            JsonLearningCatalogRepository::load(&config.catalog_data_path).await?,
        )),
        CatalogRepositoryKind::DynamoDb => {
            let table_name = config
                .dynamodb_table_name
                .clone()
                .ok_or(BootstrapError::MissingDynamoDbTableName)?;
            let client = build_dynamodb_client(config).await;

            Ok(Arc::new(DynamoDbLearningCatalogRepository::new(
                client,
                DynamoDbLearningCatalogRepositoryConfig { table_name },
            )))
        }
    }
}

async fn build_dynamodb_client(config: &AppConfig) -> DynamoDbClient {
    let mut aws_config = aws_config::defaults(BehaviorVersion::latest())
        .region(Region::new(config.aws_region.clone()));

    if let Some(endpoint) = &config.dynamodb_endpoint {
        aws_config = aws_config.endpoint_url(endpoint);
    }

    let shared_config = aws_config.load().await;
    DynamoDbClient::new(&shared_config)
}

async fn build_sqs_client(config: &AppConfig) -> SqsClient {
    let mut aws_config = aws_config::defaults(BehaviorVersion::latest())
        .region(Region::new(config.aws_region.clone()));

    if let Some(endpoint) = &config.dynamodb_endpoint {
        aws_config = aws_config.endpoint_url(endpoint);
    }

    let shared_config = aws_config.load().await;
    SqsClient::new(&shared_config)
}

fn init_tracing() {
    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info"));
    let _ = tracing_subscriber::registry()
        .with(filter)
        .with(tracing_subscriber::fmt::layer())
        .try_init();
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CatalogRepositoryKind {
    Json,
    DynamoDb,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UserRepositoryKind {
    InMemory,
    DynamoDb,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AiModelCatalogRepositoryKind {
    InMemory,
    DynamoDb,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PersonalizationJobPublisherKind {
    InMemory,
    Sqs,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PersonalizedExampleRepositoryKind {
    InMemory,
    DynamoDb,
}

impl std::str::FromStr for PersonalizedExampleRepositoryKind {
    type Err = BootstrapError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "in_memory" => Ok(Self::InMemory),
            "dynamodb" => Ok(Self::DynamoDb),
            _ => Err(BootstrapError::InvalidPersonalizedExampleRepository {
                value: value.to_string(),
            }),
        }
    }
}

impl std::str::FromStr for PersonalizationJobPublisherKind {
    type Err = BootstrapError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "in_memory" => Ok(Self::InMemory),
            "sqs" => Ok(Self::Sqs),
            _ => Err(BootstrapError::InvalidPersonalizationJobPublisher {
                value: value.to_string(),
            }),
        }
    }
}

impl std::str::FromStr for AiModelCatalogRepositoryKind {
    type Err = BootstrapError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "in_memory" => Ok(Self::InMemory),
            "dynamodb" => Ok(Self::DynamoDb),
            _ => Err(BootstrapError::InvalidAiModelCatalogRepository {
                value: value.to_string(),
            }),
        }
    }
}

impl std::str::FromStr for UserRepositoryKind {
    type Err = BootstrapError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "in_memory" => Ok(Self::InMemory),
            "dynamodb" => Ok(Self::DynamoDb),
            _ => Err(BootstrapError::InvalidUserRepository {
                value: value.to_string(),
            }),
        }
    }
}

impl std::str::FromStr for CatalogRepositoryKind {
    type Err = BootstrapError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "json" => Ok(Self::Json),
            "dynamodb" => Ok(Self::DynamoDb),
            _ => Err(BootstrapError::InvalidCatalogRepository {
                value: value.to_string(),
            }),
        }
    }
}

#[derive(Debug, Error)]
pub enum BootstrapError {
    #[error("invalid APP_PORT")]
    InvalidPort {
        #[source]
        source: std::num::ParseIntError,
    },
    #[error("failed to load learning catalog")]
    Catalog(#[from] crate::infrastructure::persistence::JsonLearningCatalogError),
    #[error("invalid CATALOG_REPOSITORY: {value}")]
    InvalidCatalogRepository { value: String },
    #[error("DYNAMODB_TABLE_NAME is required when CATALOG_REPOSITORY=dynamodb")]
    MissingDynamoDbTableName,
    #[error("invalid USER_REPOSITORY: {value}")]
    InvalidUserRepository { value: String },
    #[error("invalid AI_MODEL_CATALOG_REPOSITORY: {value}")]
    InvalidAiModelCatalogRepository { value: String },
    #[error("invalid PERSONALIZATION_JOB_PUBLISHER: {value}")]
    InvalidPersonalizationJobPublisher { value: String },
    #[error("invalid PERSONALIZED_EXAMPLE_REPOSITORY: {value}")]
    InvalidPersonalizedExampleRepository { value: String },
    #[error(
        "AI_MODEL_CATALOG_DYNAMODB_TABLE_NAME or DYNAMODB_TABLE_NAME is required when AI_MODEL_CATALOG_REPOSITORY=dynamodb"
    )]
    MissingAiModelCatalogDynamoDbTableName,
    #[error("AI_OPENAI_COMPATIBLE_ENDPOINT is required when AI_OPENAI_COMPATIBLE_API_KEY is set")]
    MissingOpenAiCompatibleEndpoint,
    #[error("AI_OPENAI_COMPATIBLE_API_KEY is required when AI_OPENAI_COMPATIBLE_ENDPOINT is set")]
    MissingOpenAiCompatibleApiKey,
    #[error(
        "USER_DYNAMODB_TABLE_NAME or DYNAMODB_TABLE_NAME is required when USER_REPOSITORY=dynamodb"
    )]
    MissingUserDynamoDbTableName,
    #[error("PERSONALIZATION_JOBS_QUEUE_URL is required when PERSONALIZATION_JOB_PUBLISHER=sqs")]
    MissingPersonalizationJobsQueueUrl,
    #[error(
        "PERSONALIZED_EXAMPLE_DYNAMODB_TABLE_NAME or DYNAMODB_TABLE_NAME is required when PERSONALIZED_EXAMPLE_REPOSITORY=dynamodb"
    )]
    MissingPersonalizedExampleDynamoDbTableName,
    #[error("invalid socket address")]
    SocketAddress(#[from] std::net::AddrParseError),
    #[error("io error")]
    Io(#[from] std::io::Error),
}

impl AppConfig {
    #[allow(dead_code)]
    pub fn socket_addr(&self) -> Result<SocketAddr, std::net::AddrParseError> {
        self.listen_addr().parse()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    #[test]
    fn reads_cognito_verifier_config_from_environment_values() {
        let env = HashMap::from([
            ("COGNITO_REGION", "ap-northeast-1"),
            ("COGNITO_USER_POOL_ID", "ap-northeast-1_example"),
            ("COGNITO_CLIENT_ID", "example-client-id"),
        ]);

        let config = AppConfig::from_env_values(|key| env.get(key).copied().map(str::to_string))
            .expect("config should load");

        assert_eq!(config.cognito.region, "ap-northeast-1");
        assert_eq!(config.cognito.user_pool_id, "ap-northeast-1_example");
        assert_eq!(config.cognito.client_id, "example-client-id");
    }

    #[test]
    fn reads_ai_model_catalog_config_from_environment_values() {
        let env = HashMap::from([
            ("AI_MODEL_CATALOG_REPOSITORY", "dynamodb"),
            (
                "AI_MODEL_CATALOG_DYNAMODB_TABLE_NAME",
                "english-local-ai-model-catalog",
            ),
        ]);

        let config = AppConfig::from_env_values(|key| env.get(key).copied().map(str::to_string))
            .expect("config should load");

        assert_eq!(
            config.ai_model_catalog_repository,
            AiModelCatalogRepositoryKind::DynamoDb
        );
        assert_eq!(
            config.ai_model_catalog_dynamodb_table_name.as_deref(),
            Some("english-local-ai-model-catalog")
        );
    }

    #[test]
    fn reads_sqs_personalization_job_publisher_config_from_environment_values() {
        let env = HashMap::from([
            ("PERSONALIZATION_JOB_PUBLISHER", "sqs"),
            (
                "PERSONALIZATION_JOBS_QUEUE_URL",
                "https://sqs.ap-northeast-1.amazonaws.com/123/personalization-jobs",
            ),
        ]);

        let config = AppConfig::from_env_values(|key| env.get(key).copied().map(str::to_string))
            .expect("config should load");

        assert_eq!(
            config.personalization_job_publisher,
            PersonalizationJobPublisherKind::Sqs
        );
        assert_eq!(
            config.personalization_jobs_queue_url.as_deref(),
            Some("https://sqs.ap-northeast-1.amazonaws.com/123/personalization-jobs")
        );
    }

    #[test]
    fn reads_dynamodb_personalized_example_repository_config_from_environment_values() {
        let env = HashMap::from([
            ("PERSONALIZED_EXAMPLE_REPOSITORY", "dynamodb"),
            (
                "PERSONALIZED_EXAMPLE_DYNAMODB_TABLE_NAME",
                "english-local-personalized-examples",
            ),
        ]);

        let config = AppConfig::from_env_values(|key| env.get(key).copied().map(str::to_string))
            .expect("config should load");

        assert_eq!(
            config.personalized_example_repository,
            PersonalizedExampleRepositoryKind::DynamoDb
        );
        assert_eq!(
            config.personalized_example_dynamodb_table_name.as_deref(),
            Some("english-local-personalized-examples")
        );
    }

    #[tokio::test]
    async fn builds_dev_ai_client_from_config() {
        let env: HashMap<&str, &str> = HashMap::new();
        let config = AppConfig::from_env_values(|key| env.get(key).copied().map(str::to_string))
            .expect("config should load");

        let ai = build_ai_client(&config)
            .await
            .expect("dev AI client should build");
        let completion = ai
            .complete(crate::application::ai::ports::AiCompletionRequest {
                model: crate::application::ai::model::AiModelKey::ExampleSentenceFast,
                system_prompt: "system".to_string(),
                user_prompt: "Create a sentence for apply.".to_string(),
            })
            .await
            .expect("dev AI client should complete");

        assert!(completion.text.contains("apply"));
    }

    #[test]
    fn reads_openai_compatible_ai_provider_config_from_environment_values() {
        let env = HashMap::from([
            (
                "AI_OPENAI_COMPATIBLE_ENDPOINT",
                "https://api.openai.example/v1/chat/completions",
            ),
            ("AI_OPENAI_COMPATIBLE_API_KEY", "test-api-key"),
        ]);

        let config = AppConfig::from_env_values(|key| env.get(key).copied().map(str::to_string))
            .expect("config should load");

        assert_eq!(
            config.ai.openai_compatible_endpoint.as_deref(),
            Some("https://api.openai.example/v1/chat/completions")
        );
        assert_eq!(
            config.ai.openai_compatible_api_key.as_deref(),
            Some("test-api-key")
        );
    }

    #[tokio::test]
    async fn rejects_openai_compatible_ai_gateway_without_endpoint() {
        let env = HashMap::from([("AI_OPENAI_COMPATIBLE_API_KEY", "test-api-key")]);
        let config = AppConfig::from_env_values(|key| env.get(key).copied().map(str::to_string))
            .expect("config should load");

        let error = match build_ai_client(&config).await {
            Ok(_) => panic!("endpoint should be required"),
            Err(error) => error,
        };

        assert!(matches!(
            error,
            BootstrapError::MissingOpenAiCompatibleEndpoint
        ));
    }

    #[tokio::test]
    async fn rejects_openai_compatible_ai_gateway_without_api_key() {
        let env = HashMap::from([(
            "AI_OPENAI_COMPATIBLE_ENDPOINT",
            "https://api.openai.example/v1/chat/completions",
        )]);
        let config = AppConfig::from_env_values(|key| env.get(key).copied().map(str::to_string))
            .expect("config should load");

        let error = match build_ai_client(&config).await {
            Ok(_) => panic!("api key should be required"),
            Err(error) => error,
        };

        assert!(matches!(
            error,
            BootstrapError::MissingOpenAiCompatibleApiKey
        ));
    }
}
