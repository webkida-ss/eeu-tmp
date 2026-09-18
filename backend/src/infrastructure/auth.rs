use async_trait::async_trait;

use crate::application::auth::{
    CognitoJwks, CognitoJwksProvider, CognitoUserInfo, CognitoUserInfoProvider,
    TokenVerificationError,
};

#[derive(Clone)]
pub struct HttpCognitoJwksProvider {
    client: reqwest::Client,
}

impl HttpCognitoJwksProvider {
    pub fn new() -> Self {
        Self {
            client: reqwest::Client::new(),
        }
    }
}

#[async_trait]
impl CognitoJwksProvider for HttpCognitoJwksProvider {
    async fn fetch_jwks(&self, jwks_uri: &str) -> Result<CognitoJwks, TokenVerificationError> {
        self.client
            .get(jwks_uri)
            .send()
            .await
            .map_err(|_| TokenVerificationError::InvalidToken)?
            .error_for_status()
            .map_err(|_| TokenVerificationError::InvalidToken)?
            .json::<CognitoJwks>()
            .await
            .map_err(|_| TokenVerificationError::InvalidToken)
    }
}

#[derive(Clone)]
pub struct HttpCognitoUserInfoProvider {
    client: reqwest::Client,
}

impl HttpCognitoUserInfoProvider {
    pub fn new() -> Self {
        Self {
            client: reqwest::Client::new(),
        }
    }
}

#[async_trait]
impl CognitoUserInfoProvider for HttpCognitoUserInfoProvider {
    async fn fetch_user_info(
        &self,
        userinfo_endpoint: &str,
        access_token: &str,
    ) -> Result<CognitoUserInfo, TokenVerificationError> {
        self.client
            .get(userinfo_endpoint)
            .bearer_auth(access_token)
            .send()
            .await
            .map_err(|_| TokenVerificationError::InvalidToken)?
            .error_for_status()
            .map_err(|_| TokenVerificationError::InvalidToken)?
            .json::<CognitoUserInfo>()
            .await
            .map_err(|_| TokenVerificationError::InvalidToken)
    }
}

#[cfg(test)]
mod tests {
    use axum::{routing::get, Json, Router};

    use super::*;
    use crate::application::auth::{CognitoJwk, CognitoJwksProvider, CognitoUserInfoProvider};

    #[tokio::test]
    async fn fetches_cognito_jwks_over_http() {
        let jwks_uri = spawn_jwks_server().await;
        let provider = HttpCognitoJwksProvider::new();

        let jwks = provider
            .fetch_jwks(&jwks_uri)
            .await
            .expect("JWKS should be fetched");

        assert_eq!(jwks.keys[0].kid, "test-key");
        assert_eq!(jwks.keys[0].e, "AQAB");
    }

    #[tokio::test]
    async fn fetches_cognito_user_info_over_http() {
        let userinfo_endpoint = spawn_userinfo_server().await;
        let provider = HttpCognitoUserInfoProvider::new();

        let user_info = provider
            .fetch_user_info(&userinfo_endpoint, "access-token")
            .await
            .expect("user info should be fetched");

        assert_eq!(user_info.email, Some("verified@example.com".to_string()));
    }

    async fn spawn_jwks_server() -> String {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let app = Router::new().route(
            "/.well-known/jwks.json",
            get(|| async {
                Json(CognitoJwks {
                    keys: vec![CognitoJwk {
                        kid: "test-key".to_string(),
                        n: "test-modulus".to_string(),
                        e: "AQAB".to_string(),
                    }],
                })
            }),
        );

        tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });

        format!("http://{address}/.well-known/jwks.json")
    }

    async fn spawn_userinfo_server() -> String {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let app = Router::new().route(
            "/oauth2/userInfo",
            get(|| async {
                Json(CognitoUserInfo {
                    email: Some("verified@example.com".to_string()),
                })
            }),
        );

        tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });

        format!("http://{address}/oauth2/userInfo")
    }
}
