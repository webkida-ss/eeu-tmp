use std::{
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};

use async_trait::async_trait;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CognitoVerifierConfig {
    pub region: String,
    pub user_pool_id: String,
    pub client_id: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VerifiedCognitoClaims {
    pub sub: String,
    pub email: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CognitoAccessTokenClaims {
    pub iss: String,
    pub sub: String,
    pub client_id: String,
    pub token_use: String,
    pub exp: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CognitoJwks {
    pub keys: Vec<CognitoJwk>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CognitoJwk {
    pub kid: String,
    pub n: String,
    pub e: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CognitoUserInfo {
    pub email: Option<String>,
}

#[derive(Debug, thiserror::Error)]
pub enum TokenVerificationError {
    #[error("invalid access token")]
    InvalidToken,
}

#[async_trait]
pub trait CognitoTokenVerifier: Send + Sync {
    async fn verify_access_token(
        &self,
        token: &str,
    ) -> Result<VerifiedCognitoClaims, TokenVerificationError>;
}

#[async_trait]
pub trait CognitoJwksProvider: Send + Sync {
    async fn fetch_jwks(&self, jwks_uri: &str) -> Result<CognitoJwks, TokenVerificationError>;
}

#[async_trait]
pub trait CognitoUserInfoProvider: Send + Sync {
    async fn fetch_user_info(
        &self,
        userinfo_endpoint: &str,
        access_token: &str,
    ) -> Result<CognitoUserInfo, TokenVerificationError>;
}

#[derive(Clone)]
pub struct CognitoJwtVerifier {
    config: CognitoVerifierConfig,
    jwks_provider: Option<Arc<dyn CognitoJwksProvider>>,
    userinfo_endpoint: Option<String>,
    userinfo_provider: Option<Arc<dyn CognitoUserInfoProvider>>,
}

impl CognitoJwtVerifier {
    pub fn new(config: CognitoVerifierConfig) -> Self {
        Self {
            config,
            jwks_provider: None,
            userinfo_endpoint: None,
            userinfo_provider: None,
        }
    }

    pub fn with_jwks_provider(
        config: CognitoVerifierConfig,
        jwks_provider: Arc<dyn CognitoJwksProvider>,
    ) -> Self {
        Self {
            config,
            jwks_provider: Some(jwks_provider),
            userinfo_endpoint: None,
            userinfo_provider: None,
        }
    }

    pub fn with_jwks_and_userinfo_provider(
        config: CognitoVerifierConfig,
        jwks_provider: Arc<dyn CognitoJwksProvider>,
        userinfo_endpoint: String,
        userinfo_provider: Arc<dyn CognitoUserInfoProvider>,
    ) -> Self {
        Self {
            config,
            jwks_provider: Some(jwks_provider),
            userinfo_endpoint: Some(userinfo_endpoint),
            userinfo_provider: Some(userinfo_provider),
        }
    }

    pub fn issuer(&self) -> String {
        format!(
            "https://cognito-idp.{}.amazonaws.com/{}",
            self.config.region, self.config.user_pool_id
        )
    }

    pub fn jwks_uri(&self) -> String {
        format!("{}/.well-known/jwks.json", self.issuer())
    }

    pub fn validate_access_token_claims(
        &self,
        claims: &CognitoAccessTokenClaims,
        now_epoch_seconds: u64,
    ) -> Result<(), TokenVerificationError> {
        if claims.iss != self.issuer() {
            return Err(TokenVerificationError::InvalidToken);
        }

        if claims.client_id != self.config.client_id {
            return Err(TokenVerificationError::InvalidToken);
        }

        if claims.token_use != "access" {
            return Err(TokenVerificationError::InvalidToken);
        }

        if claims.sub.is_empty() || claims.exp <= now_epoch_seconds {
            return Err(TokenVerificationError::InvalidToken);
        }

        Ok(())
    }

    pub fn decode_verified_access_token_claims(
        &self,
        token: &str,
        decoding_key: &jsonwebtoken::DecodingKey,
        now_epoch_seconds: u64,
    ) -> Result<CognitoAccessTokenClaims, TokenVerificationError> {
        let mut validation = jsonwebtoken::Validation::new(jsonwebtoken::Algorithm::RS256);
        validation.validate_aud = false;
        validation.validate_exp = false;

        let token_data =
            jsonwebtoken::decode::<CognitoAccessTokenClaims>(token, decoding_key, &validation)
                .map_err(|_| TokenVerificationError::InvalidToken)?;

        self.validate_access_token_claims(&token_data.claims, now_epoch_seconds)?;

        Ok(token_data.claims)
    }

    pub fn select_jwk_for_token<'a>(
        &self,
        token: &str,
        jwks: &'a CognitoJwks,
    ) -> Result<&'a CognitoJwk, TokenVerificationError> {
        let key_id = self.token_key_id(token)?;

        jwks.keys
            .iter()
            .find(|key| key.kid == key_id)
            .ok_or(TokenVerificationError::InvalidToken)
    }

    pub fn decoding_key_from_jwk(
        &self,
        jwk: &CognitoJwk,
    ) -> Result<jsonwebtoken::DecodingKey, TokenVerificationError> {
        jsonwebtoken::DecodingKey::from_rsa_components(&jwk.n, &jwk.e)
            .map_err(|_| TokenVerificationError::InvalidToken)
    }

    pub fn verify_access_token_with_jwks(
        &self,
        token: &str,
        jwks: &CognitoJwks,
        now_epoch_seconds: u64,
    ) -> Result<CognitoAccessTokenClaims, TokenVerificationError> {
        let jwk = self.select_jwk_for_token(token, jwks)?;
        let decoding_key = self.decoding_key_from_jwk(jwk)?;

        self.decode_verified_access_token_claims(token, &decoding_key, now_epoch_seconds)
    }

    fn token_key_id(&self, token: &str) -> Result<String, TokenVerificationError> {
        jsonwebtoken::decode_header(token)
            .map_err(|_| TokenVerificationError::InvalidToken)?
            .kid
            .ok_or(TokenVerificationError::InvalidToken)
    }
}

#[async_trait]
impl CognitoTokenVerifier for CognitoJwtVerifier {
    async fn verify_access_token(
        &self,
        token: &str,
    ) -> Result<VerifiedCognitoClaims, TokenVerificationError> {
        let jwks_provider = self
            .jwks_provider
            .as_ref()
            .ok_or(TokenVerificationError::InvalidToken)?;
        let jwks = jwks_provider.fetch_jwks(&self.jwks_uri()).await?;
        let claims = self.verify_access_token_with_jwks(token, &jwks, current_epoch_seconds()?)?;
        let email = match (&self.userinfo_endpoint, &self.userinfo_provider) {
            (Some(userinfo_endpoint), Some(userinfo_provider)) => userinfo_provider
                .fetch_user_info(userinfo_endpoint, token)
                .await?
                .email
                .unwrap_or_default(),
            _ => String::new(),
        };

        Ok(VerifiedCognitoClaims {
            sub: claims.sub,
            email,
        })
    }
}

#[derive(Debug, Clone)]
pub struct DevCognitoTokenVerifier;

#[async_trait]
impl CognitoTokenVerifier for DevCognitoTokenVerifier {
    async fn verify_access_token(
        &self,
        token: &str,
    ) -> Result<VerifiedCognitoClaims, TokenVerificationError> {
        if !is_jwt_like(token) {
            return Err(TokenVerificationError::InvalidToken);
        }

        Ok(VerifiedCognitoClaims {
            sub: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee".to_string(),
            email: "user@example.com".to_string(),
        })
    }
}

fn is_jwt_like(token: &str) -> bool {
    let mut segments = token.split('.');

    matches!(
        (segments.next(), segments.next(), segments.next(), segments.next()),
        (Some(header), Some(payload), Some(signature), None)
            if !header.is_empty() && !payload.is_empty() && !signature.is_empty()
    )
}

fn current_epoch_seconds() -> Result<u64, TokenVerificationError> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .map_err(|_| TokenVerificationError::InvalidToken)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn builds_cognito_issuer_and_jwks_uri_from_config() {
        let verifier = CognitoJwtVerifier::new(CognitoVerifierConfig {
            region: "ap-northeast-1".to_string(),
            user_pool_id: "ap-northeast-1_example".to_string(),
            client_id: "example-client-id".to_string(),
        });

        assert_eq!(
            verifier.issuer(),
            "https://cognito-idp.ap-northeast-1.amazonaws.com/ap-northeast-1_example"
        );
        assert_eq!(
            verifier.jwks_uri(),
            "https://cognito-idp.ap-northeast-1.amazonaws.com/ap-northeast-1_example/.well-known/jwks.json"
        );
    }

    #[tokio::test]
    async fn cognito_jwt_verifier_rejects_tokens_until_signature_verification_is_implemented() {
        let verifier = CognitoJwtVerifier::new(CognitoVerifierConfig {
            region: "ap-northeast-1".to_string(),
            user_pool_id: "ap-northeast-1_example".to_string(),
            client_id: "example-client-id".to_string(),
        });

        let result = verifier
            .verify_access_token("header.payload.signature")
            .await;

        assert!(matches!(result, Err(TokenVerificationError::InvalidToken)));
    }

    #[test]
    fn validates_cognito_access_token_claims() {
        let verifier = CognitoJwtVerifier::new(CognitoVerifierConfig {
            region: "ap-northeast-1".to_string(),
            user_pool_id: "ap-northeast-1_example".to_string(),
            client_id: "example-client-id".to_string(),
        });

        let claims = CognitoAccessTokenClaims {
            iss: verifier.issuer(),
            sub: "cognito-user-123".to_string(),
            client_id: "example-client-id".to_string(),
            token_use: "access".to_string(),
            exp: 4_102_444_800,
        };

        verifier
            .validate_access_token_claims(&claims, 1_767_225_600)
            .expect("claims should be valid");
    }

    #[test]
    fn rejects_cognito_claims_for_wrong_client_id() {
        let verifier = CognitoJwtVerifier::new(CognitoVerifierConfig {
            region: "ap-northeast-1".to_string(),
            user_pool_id: "ap-northeast-1_example".to_string(),
            client_id: "example-client-id".to_string(),
        });

        let claims = CognitoAccessTokenClaims {
            iss: verifier.issuer(),
            sub: "cognito-user-123".to_string(),
            client_id: "other-client-id".to_string(),
            token_use: "access".to_string(),
            exp: 4_102_444_800,
        };

        let result = verifier.validate_access_token_claims(&claims, 1_767_225_600);

        assert!(matches!(result, Err(TokenVerificationError::InvalidToken)));
    }

    #[test]
    fn decodes_rs256_signed_access_token_claims_with_public_key() {
        let verifier = CognitoJwtVerifier::new(CognitoVerifierConfig {
            region: "ap-northeast-1".to_string(),
            user_pool_id: "ap-northeast-1_example".to_string(),
            client_id: "example-client-id".to_string(),
        });
        let claims = CognitoAccessTokenClaims {
            iss: verifier.issuer(),
            sub: "cognito-user-123".to_string(),
            client_id: "example-client-id".to_string(),
            token_use: "access".to_string(),
            exp: 4_102_444_800,
        };
        let token = jsonwebtoken::encode(
            &jsonwebtoken::Header::new(jsonwebtoken::Algorithm::RS256),
            &claims,
            &jsonwebtoken::EncodingKey::from_rsa_pem(TEST_RSA_PRIVATE_KEY.as_bytes()).unwrap(),
        )
        .unwrap();

        let decoded_claims = verifier
            .decode_verified_access_token_claims(
                &token,
                &jsonwebtoken::DecodingKey::from_rsa_pem(TEST_RSA_PUBLIC_KEY.as_bytes()).unwrap(),
                1_767_225_600,
            )
            .expect("token should verify");

        assert_eq!(decoded_claims.sub, "cognito-user-123");
        assert_eq!(decoded_claims.client_id, "example-client-id");
    }

    #[test]
    fn selects_jwk_matching_token_kid() {
        let verifier = CognitoJwtVerifier::new(CognitoVerifierConfig {
            region: "ap-northeast-1".to_string(),
            user_pool_id: "ap-northeast-1_example".to_string(),
            client_id: "example-client-id".to_string(),
        });
        let claims = CognitoAccessTokenClaims {
            iss: verifier.issuer(),
            sub: "cognito-user-123".to_string(),
            client_id: "example-client-id".to_string(),
            token_use: "access".to_string(),
            exp: 4_102_444_800,
        };
        let mut header = jsonwebtoken::Header::new(jsonwebtoken::Algorithm::RS256);
        header.kid = Some("matching-key".to_string());
        let token = jsonwebtoken::encode(
            &header,
            &claims,
            &jsonwebtoken::EncodingKey::from_rsa_pem(TEST_RSA_PRIVATE_KEY.as_bytes()).unwrap(),
        )
        .unwrap();
        let jwks = CognitoJwks {
            keys: vec![
                CognitoJwk {
                    kid: "other-key".to_string(),
                    n: "other-modulus".to_string(),
                    e: "AQAB".to_string(),
                },
                CognitoJwk {
                    kid: "matching-key".to_string(),
                    n: "matching-modulus".to_string(),
                    e: "AQAB".to_string(),
                },
            ],
        };

        let jwk = verifier
            .select_jwk_for_token(&token, &jwks)
            .expect("matching JWK should be selected");

        assert_eq!(jwk.kid, "matching-key");
        assert_eq!(jwk.n, "matching-modulus");
    }

    #[test]
    fn builds_decoding_key_from_selected_jwk() {
        let verifier = CognitoJwtVerifier::new(CognitoVerifierConfig {
            region: "ap-northeast-1".to_string(),
            user_pool_id: "ap-northeast-1_example".to_string(),
            client_id: "example-client-id".to_string(),
        });
        let jwk = CognitoJwk {
            kid: "matching-key".to_string(),
            n: "yRE6rHuNR0QbHO3H3Kt2pOKGVhQqGZXInOduQNxXzuKlvQTLUTv4l4sggh5_CYYi_cvI-SXVT9kPWSKXxJXBXd_4LkvcPuUakBoAkfh-eiFVMh2VrUyWyj3MFl0HTVF9KwRXLAcwkREiS3npThHRyIxuy0ZMeZfxVL5arMhw1SRELB8HoGfG_AtH89BIE9jDBHZ9dLelK9a184zAf8LwoPLxvJb3Il5nncqPcSfKDDodMFBIMc4lQzDKL5gvmiXLXB1AGLm8KBjfE8s3L5xqi-yUod-j8MtvIj812dkS4QMiRVN_by2h3ZY8LYVGrqZXZTcgn2ujn8uKjXLZVD5TdQ".to_string(),
            e: "AQAB".to_string(),
        };

        verifier
            .decoding_key_from_jwk(&jwk)
            .expect("JWK components should produce a decoding key");
    }

    #[test]
    fn verifies_signed_access_token_using_matching_jwks_key() {
        let verifier = CognitoJwtVerifier::new(CognitoVerifierConfig {
            region: "ap-northeast-1".to_string(),
            user_pool_id: "ap-northeast-1_example".to_string(),
            client_id: "example-client-id".to_string(),
        });
        let claims = CognitoAccessTokenClaims {
            iss: verifier.issuer(),
            sub: "cognito-user-123".to_string(),
            client_id: "example-client-id".to_string(),
            token_use: "access".to_string(),
            exp: 4_102_444_800,
        };
        let mut header = jsonwebtoken::Header::new(jsonwebtoken::Algorithm::RS256);
        header.kid = Some("matching-key".to_string());
        let token = jsonwebtoken::encode(
            &header,
            &claims,
            &jsonwebtoken::EncodingKey::from_rsa_pem(TEST_RSA_PRIVATE_KEY.as_bytes()).unwrap(),
        )
        .unwrap();
        let jwks = CognitoJwks {
            keys: vec![test_rsa_jwk("matching-key")],
        };

        let verified = verifier
            .verify_access_token_with_jwks(&token, &jwks, 1_767_225_600)
            .expect("token should verify with matching JWKS key");

        assert_eq!(verified.sub, "cognito-user-123");
    }

    #[tokio::test]
    async fn verifies_access_token_using_injected_jwks_provider() {
        let verifier = CognitoJwtVerifier::with_jwks_provider(
            CognitoVerifierConfig {
                region: "ap-northeast-1".to_string(),
                user_pool_id: "ap-northeast-1_example".to_string(),
                client_id: "example-client-id".to_string(),
            },
            std::sync::Arc::new(TestCognitoJwksProvider {
                jwks: CognitoJwks {
                    keys: vec![test_rsa_jwk("matching-key")],
                },
            }),
        );
        let claims = CognitoAccessTokenClaims {
            iss: verifier.issuer(),
            sub: "cognito-user-123".to_string(),
            client_id: "example-client-id".to_string(),
            token_use: "access".to_string(),
            exp: 4_102_444_800,
        };
        let mut header = jsonwebtoken::Header::new(jsonwebtoken::Algorithm::RS256);
        header.kid = Some("matching-key".to_string());
        let token = jsonwebtoken::encode(
            &header,
            &claims,
            &jsonwebtoken::EncodingKey::from_rsa_pem(TEST_RSA_PRIVATE_KEY.as_bytes()).unwrap(),
        )
        .unwrap();

        let verified = verifier
            .verify_access_token(&token)
            .await
            .expect("token should verify with injected JWKS provider");

        assert_eq!(verified.sub, "cognito-user-123");
    }

    #[tokio::test]
    async fn verifies_access_token_and_loads_email_from_userinfo() {
        let verifier = CognitoJwtVerifier::with_jwks_and_userinfo_provider(
            CognitoVerifierConfig {
                region: "ap-northeast-1".to_string(),
                user_pool_id: "ap-northeast-1_example".to_string(),
                client_id: "example-client-id".to_string(),
            },
            std::sync::Arc::new(TestCognitoJwksProvider {
                jwks: CognitoJwks {
                    keys: vec![test_rsa_jwk("matching-key")],
                },
            }),
            "https://example.auth.ap-northeast-1.amazoncognito.com/oauth2/userInfo".to_string(),
            std::sync::Arc::new(TestCognitoUserInfoProvider {
                user_info: CognitoUserInfo {
                    email: Some("verified@example.com".to_string()),
                },
            }),
        );
        let claims = CognitoAccessTokenClaims {
            iss: verifier.issuer(),
            sub: "cognito-user-123".to_string(),
            client_id: "example-client-id".to_string(),
            token_use: "access".to_string(),
            exp: 4_102_444_800,
        };
        let mut header = jsonwebtoken::Header::new(jsonwebtoken::Algorithm::RS256);
        header.kid = Some("matching-key".to_string());
        let token = jsonwebtoken::encode(
            &header,
            &claims,
            &jsonwebtoken::EncodingKey::from_rsa_pem(TEST_RSA_PRIVATE_KEY.as_bytes()).unwrap(),
        )
        .unwrap();

        let verified = verifier
            .verify_access_token(&token)
            .await
            .expect("token should verify and load user info");

        assert_eq!(verified.sub, "cognito-user-123");
        assert_eq!(verified.email, "verified@example.com");
    }

    const TEST_RSA_PRIVATE_KEY: &str = r#"-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEAyRE6rHuNR0QbHO3H3Kt2pOKGVhQqGZXInOduQNxXzuKlvQTL
UTv4l4sggh5/CYYi/cvI+SXVT9kPWSKXxJXBXd/4LkvcPuUakBoAkfh+eiFVMh2V
rUyWyj3MFl0HTVF9KwRXLAcwkREiS3npThHRyIxuy0ZMeZfxVL5arMhw1SRELB8H
oGfG/AtH89BIE9jDBHZ9dLelK9a184zAf8LwoPLxvJb3Il5nncqPcSfKDDodMFBI
Mc4lQzDKL5gvmiXLXB1AGLm8KBjfE8s3L5xqi+yUod+j8MtvIj812dkS4QMiRVN/
by2h3ZY8LYVGrqZXZTcgn2ujn8uKjXLZVD5TdQIDAQABAoIBAHREk0I0O9DvECKd
WUpAmF3mY7oY9PNQiu44Yaf+AoSuyRpRUGTMIgc3u3eivOE8ALX0BmYUO5JtuRNZ
Dpvt4SAwqCnVUinIf6C+eH/wSurCpapSM0BAHp4aOA7igptyOMgMPYBHNA1e9A7j
E0dCxKWMl3DSWNyjQTk4zeRGEAEfbNjHrq6YCtjHSZSLmWiG80hnfnYos9hOr5Jn
LnyS7ZmFE/5P3XVrxLc/tQ5zum0R4cbrgzHiQP5RgfxGJaEi7XcgherCCOgurJSS
bYH29Gz8u5fFbS+Yg8s+OiCss3cs1rSgJ9/eHZuzGEdUZVARH6hVMjSuwvqVTFaE
8AgtleECgYEA+uLMn4kNqHlJS2A5uAnCkj90ZxEtNm3E8hAxUrhssktY5XSOAPBl
xyf5RuRGIImGtUVIr4HuJSa5TX48n3Vdt9MYCprO/iYl6moNRSPt5qowIIOJmIjY
2mqPDfDt/zw+fcDD3lmCJrFlzcnh0uea1CohxEbQnL3cypeLt+WbU6kCgYEAzSp1
9m1ajieFkqgoB0YTpt/OroDx38vvI5unInJlEeOjQ+oIAQdN2wpxBvTrRorMU6P0
7mFUbt1j+Co6CbNiw+X8HcCaqYLR5clbJOOWNR36PuzOpQLkfK8woupBxzW9B8gZ
mY8rB1mbJ+/WTPrEJy6YGmIEBkWylQ2VpW8O4O0CgYEApdbvvfFBlwD9YxbrcGz7
MeNCFbMz+MucqQntIKoKJ91ImPxvtc0y6e/Rhnv0oyNlaUOwJVu0yNgNG117w0g4
t/+Q38mvVC5xV7/cn7x9UMFk6MkqVir3dYGEqIl/OP1grY2Tq9HtB5iyG9L8NIam
QOLMyUqqMUILxdthHyFmiGkCgYEAn9+PjpjGMPHxL0gj8Q8VbzsFtou6b1deIRRA
2CHmSltltR1gYVTMwXxQeUhPMmgkMqUXzs4/WijgpthY44hK1TaZEKIuoxrS70nJ
4WQLf5a9k1065fDsFZD6yGjdGxvwEmlGMZgTwqV7t1I4X0Ilqhav5hcs5apYL7gn
PYPeRz0CgYALHCj/Ji8XSsDoF/MhVhnGdIs2P99NNdmo3R2Pv0CuZbDKMU559LJH
UvrKS8WkuWRDuKrz1W/EQKApFjDGpdqToZqriUFQzwy7mR3ayIiogzNtHcvbDHx8
oFnGY0OFksX/ye0/XGpy2SFxYRwGU98HPYeBvAQQrVjdkzfy7BmXQQ==
-----END RSA PRIVATE KEY-----"#;

    const TEST_RSA_PUBLIC_KEY: &str = r#"-----BEGIN RSA PUBLIC KEY-----
MIIBCgKCAQEAyRE6rHuNR0QbHO3H3Kt2pOKGVhQqGZXInOduQNxXzuKlvQTLUTv4
l4sggh5/CYYi/cvI+SXVT9kPWSKXxJXBXd/4LkvcPuUakBoAkfh+eiFVMh2VrUyW
yj3MFl0HTVF9KwRXLAcwkREiS3npThHRyIxuy0ZMeZfxVL5arMhw1SRELB8HoGfG
/AtH89BIE9jDBHZ9dLelK9a184zAf8LwoPLxvJb3Il5nncqPcSfKDDodMFBIMc4l
QzDKL5gvmiXLXB1AGLm8KBjfE8s3L5xqi+yUod+j8MtvIj812dkS4QMiRVN/by2h
3ZY8LYVGrqZXZTcgn2ujn8uKjXLZVD5TdQIDAQAB
-----END RSA PUBLIC KEY-----"#;

    fn test_rsa_jwk(kid: &str) -> CognitoJwk {
        CognitoJwk {
            kid: kid.to_string(),
            n: "yRE6rHuNR0QbHO3H3Kt2pOKGVhQqGZXInOduQNxXzuKlvQTLUTv4l4sggh5_CYYi_cvI-SXVT9kPWSKXxJXBXd_4LkvcPuUakBoAkfh-eiFVMh2VrUyWyj3MFl0HTVF9KwRXLAcwkREiS3npThHRyIxuy0ZMeZfxVL5arMhw1SRELB8HoGfG_AtH89BIE9jDBHZ9dLelK9a184zAf8LwoPLxvJb3Il5nncqPcSfKDDodMFBIMc4lQzDKL5gvmiXLXB1AGLm8KBjfE8s3L5xqi-yUod-j8MtvIj812dkS4QMiRVN_by2h3ZY8LYVGrqZXZTcgn2ujn8uKjXLZVD5TdQ".to_string(),
            e: "AQAB".to_string(),
        }
    }

    struct TestCognitoJwksProvider {
        jwks: CognitoJwks,
    }

    #[async_trait]
    impl CognitoJwksProvider for TestCognitoJwksProvider {
        async fn fetch_jwks(&self, _jwks_uri: &str) -> Result<CognitoJwks, TokenVerificationError> {
            Ok(self.jwks.clone())
        }
    }

    struct TestCognitoUserInfoProvider {
        user_info: CognitoUserInfo,
    }

    #[async_trait]
    impl CognitoUserInfoProvider for TestCognitoUserInfoProvider {
        async fn fetch_user_info(
            &self,
            _userinfo_endpoint: &str,
            _access_token: &str,
        ) -> Result<CognitoUserInfo, TokenVerificationError> {
            Ok(self.user_info.clone())
        }
    }
}
