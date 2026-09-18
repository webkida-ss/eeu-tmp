#![allow(unused_qualifications)]

use http::HeaderValue;
use validator::Validate;

#[cfg(feature = "server")]
use crate::header;
use crate::{models, types::*};

#[allow(dead_code)]
fn from_validation_error(e: validator::ValidationError) -> validator::ValidationErrors {
  let mut errs = validator::ValidationErrors::new();
  errs.add("na", e);
  errs
}

#[allow(dead_code)]
pub fn check_xss_string(v: &str) -> std::result::Result<(), validator::ValidationError> {
    if ammonia::is_html(v) {
        std::result::Result::Err(validator::ValidationError::new("xss detected"))
    } else {
        std::result::Result::Ok(())
    }
}

#[allow(dead_code)]
pub fn check_xss_vec_string(v: &[String]) -> std::result::Result<(), validator::ValidationError> {
    if v.iter().any(|i| ammonia::is_html(i)) {
        std::result::Result::Err(validator::ValidationError::new("xss detected"))
    } else {
        std::result::Result::Ok(())
    }
}

#[allow(dead_code)]
pub fn check_xss_map_string(
    v: &std::collections::HashMap<String, String>,
) -> std::result::Result<(), validator::ValidationError> {
    if v.keys().any(|k| ammonia::is_html(k)) || v.values().any(|v| ammonia::is_html(v)) {
        std::result::Result::Err(validator::ValidationError::new("xss detected"))
    } else {
        std::result::Result::Ok(())
    }
}

#[allow(dead_code)]
pub fn check_xss_map_nested<T>(
    v: &std::collections::HashMap<String, T>,
) -> std::result::Result<(), validator::ValidationError>
where
    T: validator::Validate,
{
    if v.keys().any(|k| ammonia::is_html(k)) || v.values().any(|v| v.validate().is_err()) {
        std::result::Result::Err(validator::ValidationError::new("xss detected"))
    } else {
        std::result::Result::Ok(())
    }
}

#[allow(dead_code)]
pub fn check_xss_map<T>(v: &std::collections::HashMap<String, T>) -> std::result::Result<(), validator::ValidationError> {
    if v.keys().any(|k| ammonia::is_html(k)) {
        std::result::Result::Err(validator::ValidationError::new("xss detected"))
    } else {
        std::result::Result::Ok(())
    }
}





    #[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, validator::Validate)]
    #[cfg_attr(feature = "conversion", derive(frunk::LabelledGeneric))]
    pub struct GetLearningPathPathParams {
                pub path_id: String,
    }



    #[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, validator::Validate)]
    #[cfg_attr(feature = "conversion", derive(frunk::LabelledGeneric))]
    pub struct GetLearningPathCoursePathParams {
                pub path_id: String,
                pub course_id: String,
    }







#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, validator::Validate)]
#[cfg_attr(feature = "conversion", derive(frunk::LabelledGeneric))]
pub struct AuthErrorResponse {
    #[serde(rename = "message")]
          #[validate(custom(function = "check_xss_string"))]
    pub message: String,

}



impl AuthErrorResponse {
    #[allow(clippy::new_without_default, clippy::too_many_arguments)]
    pub fn new(message: String, ) -> AuthErrorResponse {
        AuthErrorResponse {
 message,
        }
    }
}

/// Converts the AuthErrorResponse value to the Query Parameters representation (style=form, explode=false)
/// specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde serializer
impl std::fmt::Display for AuthErrorResponse {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let params: Vec<Option<String>> = vec![

            Some("message".to_string()),
            Some(self.message.to_string()),

        ];

        write!(f, "{}", params.into_iter().flatten().collect::<Vec<_>>().join(","))
    }
}

/// Converts Query Parameters representation (style=form, explode=false) to a AuthErrorResponse value
/// as specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde deserializer
impl std::str::FromStr for AuthErrorResponse {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        /// An intermediate representation of the struct to use for parsing.
        #[derive(Default)]
        #[allow(dead_code)]
        struct IntermediateRep {
            pub message: Vec<String>,
        }

        let mut intermediate_rep = IntermediateRep::default();

        // Parse into intermediate representation
        let mut string_iter = s.split(',');
        let mut key_result = string_iter.next();

        while key_result.is_some() {
            let val = match string_iter.next() {
                Some(x) => x,
                None => return std::result::Result::Err("Missing value while parsing AuthErrorResponse".to_string())
            };

            if let Some(key) = key_result {
                #[allow(clippy::match_single_binding)]
                match key {
                    #[allow(clippy::redundant_clone)]
                    "message" => intermediate_rep.message.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    _ => return std::result::Result::Err("Unexpected key while parsing AuthErrorResponse".to_string())
                }
            }

            // Get the next key
            key_result = string_iter.next();
        }

        // Use the intermediate representation to return the struct
        std::result::Result::Ok(AuthErrorResponse {
            message: intermediate_rep.message.into_iter().next().ok_or_else(|| "message missing in AuthErrorResponse".to_string())?,
        })
    }
}

// Methods for converting between header::IntoHeaderValue<AuthErrorResponse> and HeaderValue

#[cfg(feature = "server")]
impl std::convert::TryFrom<header::IntoHeaderValue<AuthErrorResponse>> for HeaderValue {
    type Error = String;

    fn try_from(hdr_value: header::IntoHeaderValue<AuthErrorResponse>) -> std::result::Result<Self, Self::Error> {
        let hdr_value = hdr_value.to_string();
        match HeaderValue::from_str(&hdr_value) {
             std::result::Result::Ok(value) => std::result::Result::Ok(value),
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Invalid header value for AuthErrorResponse - value: {hdr_value} is invalid {e}"#))
        }
    }
}

#[cfg(feature = "server")]
impl std::convert::TryFrom<HeaderValue> for header::IntoHeaderValue<AuthErrorResponse> {
    type Error = String;

    fn try_from(hdr_value: HeaderValue) -> std::result::Result<Self, Self::Error> {
        match hdr_value.to_str() {
             std::result::Result::Ok(value) => {
                    match <AuthErrorResponse as std::str::FromStr>::from_str(value) {
                        std::result::Result::Ok(value) => std::result::Result::Ok(header::IntoHeaderValue(value)),
                        std::result::Result::Err(err) => std::result::Result::Err(format!(r#"Unable to convert header value '{value}' into AuthErrorResponse - {err}"#))
                    }
             },
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Unable to convert header: {hdr_value:?} to string: {e}"#))
        }
    }
}



#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, validator::Validate)]
#[cfg_attr(feature = "conversion", derive(frunk::LabelledGeneric))]
pub struct AuthSession {
    #[serde(rename = "authenticated")]
    pub authenticated: bool,

    #[serde(rename = "cognitoSub")]
          #[validate(custom(function = "check_xss_string"))]
    pub cognito_sub: String,

    #[serde(rename = "appUserId")]
    pub app_user_id: uuid::Uuid,

    #[serde(rename = "email")]
          #[validate(custom(function = "check_xss_string"))]
    pub email: String,

}



impl AuthSession {
    #[allow(clippy::new_without_default, clippy::too_many_arguments)]
    pub fn new(authenticated: bool, cognito_sub: String, app_user_id: uuid::Uuid, email: String, ) -> AuthSession {
        AuthSession {
 authenticated,
 cognito_sub,
 app_user_id,
 email,
        }
    }
}

/// Converts the AuthSession value to the Query Parameters representation (style=form, explode=false)
/// specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde serializer
impl std::fmt::Display for AuthSession {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let params: Vec<Option<String>> = vec![

            Some("authenticated".to_string()),
            Some(self.authenticated.to_string()),


            Some("cognitoSub".to_string()),
            Some(self.cognito_sub.to_string()),

            // Skipping appUserId in query parameter serialization


            Some("email".to_string()),
            Some(self.email.to_string()),

        ];

        write!(f, "{}", params.into_iter().flatten().collect::<Vec<_>>().join(","))
    }
}

/// Converts Query Parameters representation (style=form, explode=false) to a AuthSession value
/// as specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde deserializer
impl std::str::FromStr for AuthSession {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        /// An intermediate representation of the struct to use for parsing.
        #[derive(Default)]
        #[allow(dead_code)]
        struct IntermediateRep {
            pub authenticated: Vec<bool>,
            pub cognito_sub: Vec<String>,
            pub app_user_id: Vec<uuid::Uuid>,
            pub email: Vec<String>,
        }

        let mut intermediate_rep = IntermediateRep::default();

        // Parse into intermediate representation
        let mut string_iter = s.split(',');
        let mut key_result = string_iter.next();

        while key_result.is_some() {
            let val = match string_iter.next() {
                Some(x) => x,
                None => return std::result::Result::Err("Missing value while parsing AuthSession".to_string())
            };

            if let Some(key) = key_result {
                #[allow(clippy::match_single_binding)]
                match key {
                    #[allow(clippy::redundant_clone)]
                    "authenticated" => intermediate_rep.authenticated.push(<bool as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "cognitoSub" => intermediate_rep.cognito_sub.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "appUserId" => intermediate_rep.app_user_id.push(<uuid::Uuid as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "email" => intermediate_rep.email.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    _ => return std::result::Result::Err("Unexpected key while parsing AuthSession".to_string())
                }
            }

            // Get the next key
            key_result = string_iter.next();
        }

        // Use the intermediate representation to return the struct
        std::result::Result::Ok(AuthSession {
            authenticated: intermediate_rep.authenticated.into_iter().next().ok_or_else(|| "authenticated missing in AuthSession".to_string())?,
            cognito_sub: intermediate_rep.cognito_sub.into_iter().next().ok_or_else(|| "cognitoSub missing in AuthSession".to_string())?,
            app_user_id: intermediate_rep.app_user_id.into_iter().next().ok_or_else(|| "appUserId missing in AuthSession".to_string())?,
            email: intermediate_rep.email.into_iter().next().ok_or_else(|| "email missing in AuthSession".to_string())?,
        })
    }
}

// Methods for converting between header::IntoHeaderValue<AuthSession> and HeaderValue

#[cfg(feature = "server")]
impl std::convert::TryFrom<header::IntoHeaderValue<AuthSession>> for HeaderValue {
    type Error = String;

    fn try_from(hdr_value: header::IntoHeaderValue<AuthSession>) -> std::result::Result<Self, Self::Error> {
        let hdr_value = hdr_value.to_string();
        match HeaderValue::from_str(&hdr_value) {
             std::result::Result::Ok(value) => std::result::Result::Ok(value),
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Invalid header value for AuthSession - value: {hdr_value} is invalid {e}"#))
        }
    }
}

#[cfg(feature = "server")]
impl std::convert::TryFrom<HeaderValue> for header::IntoHeaderValue<AuthSession> {
    type Error = String;

    fn try_from(hdr_value: HeaderValue) -> std::result::Result<Self, Self::Error> {
        match hdr_value.to_str() {
             std::result::Result::Ok(value) => {
                    match <AuthSession as std::str::FromStr>::from_str(value) {
                        std::result::Result::Ok(value) => std::result::Result::Ok(header::IntoHeaderValue(value)),
                        std::result::Result::Err(err) => std::result::Result::Err(format!(r#"Unable to convert header value '{value}' into AuthSession - {err}"#))
                    }
             },
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Unable to convert header: {hdr_value:?} to string: {e}"#))
        }
    }
}



#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, validator::Validate)]
#[cfg_attr(feature = "conversion", derive(frunk::LabelledGeneric))]
pub struct Course {
    #[serde(rename = "id")]
          #[validate(custom(function = "check_xss_string"))]
    pub id: String,

    #[serde(rename = "title")]
          #[validate(custom(function = "check_xss_string"))]
    pub title: String,

    #[serde(rename = "levelLabel")]
          #[validate(custom(function = "check_xss_string"))]
    pub level_label: String,

    #[serde(rename = "description")]
          #[validate(custom(function = "check_xss_string"))]
    pub description: String,

    #[serde(rename = "outcome")]
          #[validate(custom(function = "check_xss_string"))]
    pub outcome: String,

    #[serde(rename = "estimatedHours")]
    #[validate(
            range(min = 0u32),
    )]
    pub estimated_hours: u32,

    #[serde(rename = "units")]
          #[validate(nested)]
    pub units: Vec<models::GetLearningPaths200ResponseInnerCoursesInnerUnitsInner>,

}



impl Course {
    #[allow(clippy::new_without_default, clippy::too_many_arguments)]
    pub fn new(id: String, title: String, level_label: String, description: String, outcome: String, estimated_hours: u32, units: Vec<models::GetLearningPaths200ResponseInnerCoursesInnerUnitsInner>, ) -> Course {
        Course {
 id,
 title,
 level_label,
 description,
 outcome,
 estimated_hours,
 units,
        }
    }
}

/// Converts the Course value to the Query Parameters representation (style=form, explode=false)
/// specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde serializer
impl std::fmt::Display for Course {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let params: Vec<Option<String>> = vec![

            Some("id".to_string()),
            Some(self.id.to_string()),


            Some("title".to_string()),
            Some(self.title.to_string()),


            Some("levelLabel".to_string()),
            Some(self.level_label.to_string()),


            Some("description".to_string()),
            Some(self.description.to_string()),


            Some("outcome".to_string()),
            Some(self.outcome.to_string()),


            Some("estimatedHours".to_string()),
            Some(self.estimated_hours.to_string()),

            // Skipping units in query parameter serialization

        ];

        write!(f, "{}", params.into_iter().flatten().collect::<Vec<_>>().join(","))
    }
}

/// Converts Query Parameters representation (style=form, explode=false) to a Course value
/// as specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde deserializer
impl std::str::FromStr for Course {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        /// An intermediate representation of the struct to use for parsing.
        #[derive(Default)]
        #[allow(dead_code)]
        struct IntermediateRep {
            pub id: Vec<String>,
            pub title: Vec<String>,
            pub level_label: Vec<String>,
            pub description: Vec<String>,
            pub outcome: Vec<String>,
            pub estimated_hours: Vec<u32>,
            pub units: Vec<Vec<models::GetLearningPaths200ResponseInnerCoursesInnerUnitsInner>>,
        }

        let mut intermediate_rep = IntermediateRep::default();

        // Parse into intermediate representation
        let mut string_iter = s.split(',');
        let mut key_result = string_iter.next();

        while key_result.is_some() {
            let val = match string_iter.next() {
                Some(x) => x,
                None => return std::result::Result::Err("Missing value while parsing Course".to_string())
            };

            if let Some(key) = key_result {
                #[allow(clippy::match_single_binding)]
                match key {
                    #[allow(clippy::redundant_clone)]
                    "id" => intermediate_rep.id.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "title" => intermediate_rep.title.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "levelLabel" => intermediate_rep.level_label.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "description" => intermediate_rep.description.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "outcome" => intermediate_rep.outcome.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "estimatedHours" => intermediate_rep.estimated_hours.push(<u32 as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    "units" => return std::result::Result::Err("Parsing a container in this style is not supported in Course".to_string()),
                    _ => return std::result::Result::Err("Unexpected key while parsing Course".to_string())
                }
            }

            // Get the next key
            key_result = string_iter.next();
        }

        // Use the intermediate representation to return the struct
        std::result::Result::Ok(Course {
            id: intermediate_rep.id.into_iter().next().ok_or_else(|| "id missing in Course".to_string())?,
            title: intermediate_rep.title.into_iter().next().ok_or_else(|| "title missing in Course".to_string())?,
            level_label: intermediate_rep.level_label.into_iter().next().ok_or_else(|| "levelLabel missing in Course".to_string())?,
            description: intermediate_rep.description.into_iter().next().ok_or_else(|| "description missing in Course".to_string())?,
            outcome: intermediate_rep.outcome.into_iter().next().ok_or_else(|| "outcome missing in Course".to_string())?,
            estimated_hours: intermediate_rep.estimated_hours.into_iter().next().ok_or_else(|| "estimatedHours missing in Course".to_string())?,
            units: intermediate_rep.units.into_iter().next().ok_or_else(|| "units missing in Course".to_string())?,
        })
    }
}

// Methods for converting between header::IntoHeaderValue<Course> and HeaderValue

#[cfg(feature = "server")]
impl std::convert::TryFrom<header::IntoHeaderValue<Course>> for HeaderValue {
    type Error = String;

    fn try_from(hdr_value: header::IntoHeaderValue<Course>) -> std::result::Result<Self, Self::Error> {
        let hdr_value = hdr_value.to_string();
        match HeaderValue::from_str(&hdr_value) {
             std::result::Result::Ok(value) => std::result::Result::Ok(value),
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Invalid header value for Course - value: {hdr_value} is invalid {e}"#))
        }
    }
}

#[cfg(feature = "server")]
impl std::convert::TryFrom<HeaderValue> for header::IntoHeaderValue<Course> {
    type Error = String;

    fn try_from(hdr_value: HeaderValue) -> std::result::Result<Self, Self::Error> {
        match hdr_value.to_str() {
             std::result::Result::Ok(value) => {
                    match <Course as std::str::FromStr>::from_str(value) {
                        std::result::Result::Ok(value) => std::result::Result::Ok(header::IntoHeaderValue(value)),
                        std::result::Result::Err(err) => std::result::Result::Err(format!(r#"Unable to convert header value '{value}' into Course - {err}"#))
                    }
             },
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Unable to convert header: {hdr_value:?} to string: {e}"#))
        }
    }
}



#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, validator::Validate)]
#[cfg_attr(feature = "conversion", derive(frunk::LabelledGeneric))]
pub struct ExampleSentence {
    #[serde(rename = "id")]
          #[validate(custom(function = "check_xss_string"))]
    pub id: String,

    #[serde(rename = "targetText")]
          #[validate(custom(function = "check_xss_string"))]
    pub target_text: String,

    #[serde(rename = "targetSentence")]
          #[validate(custom(function = "check_xss_string"))]
    pub target_sentence: String,

    #[serde(rename = "sourceTranslation")]
          #[validate(custom(function = "check_xss_string"))]
    pub source_translation: String,

    /// Note: inline enums are not fully supported by openapi-generator
    #[serde(rename = "variant")]
          #[validate(custom(function = "check_xss_string"))]
    pub variant: String,

    #[serde(rename = "personalization")]
          #[validate(nested)]
    #[serde(skip_serializing_if="Option::is_none")]
    pub personalization: Option<models::GenerateExampleSentence200ResponsePersonalization>,

    #[serde(rename = "usageNote")]
          #[validate(custom(function = "check_xss_string"))]
    #[serde(skip_serializing_if="Option::is_none")]
    pub usage_note: Option<String>,

}



impl ExampleSentence {
    #[allow(clippy::new_without_default, clippy::too_many_arguments)]
    pub fn new(id: String, target_text: String, target_sentence: String, source_translation: String, variant: String, ) -> ExampleSentence {
        ExampleSentence {
 id,
 target_text,
 target_sentence,
 source_translation,
 variant,
 personalization: None,
 usage_note: None,
        }
    }
}

/// Converts the ExampleSentence value to the Query Parameters representation (style=form, explode=false)
/// specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde serializer
impl std::fmt::Display for ExampleSentence {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let params: Vec<Option<String>> = vec![

            Some("id".to_string()),
            Some(self.id.to_string()),


            Some("targetText".to_string()),
            Some(self.target_text.to_string()),


            Some("targetSentence".to_string()),
            Some(self.target_sentence.to_string()),


            Some("sourceTranslation".to_string()),
            Some(self.source_translation.to_string()),


            Some("variant".to_string()),
            Some(self.variant.to_string()),

            // Skipping personalization in query parameter serialization


            self.usage_note.as_ref().map(|usage_note| {
                [
                    "usageNote".to_string(),
                    usage_note.to_string(),
                ].join(",")
            }),

        ];

        write!(f, "{}", params.into_iter().flatten().collect::<Vec<_>>().join(","))
    }
}

/// Converts Query Parameters representation (style=form, explode=false) to a ExampleSentence value
/// as specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde deserializer
impl std::str::FromStr for ExampleSentence {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        /// An intermediate representation of the struct to use for parsing.
        #[derive(Default)]
        #[allow(dead_code)]
        struct IntermediateRep {
            pub id: Vec<String>,
            pub target_text: Vec<String>,
            pub target_sentence: Vec<String>,
            pub source_translation: Vec<String>,
            pub variant: Vec<String>,
            pub personalization: Vec<models::GenerateExampleSentence200ResponsePersonalization>,
            pub usage_note: Vec<String>,
        }

        let mut intermediate_rep = IntermediateRep::default();

        // Parse into intermediate representation
        let mut string_iter = s.split(',');
        let mut key_result = string_iter.next();

        while key_result.is_some() {
            let val = match string_iter.next() {
                Some(x) => x,
                None => return std::result::Result::Err("Missing value while parsing ExampleSentence".to_string())
            };

            if let Some(key) = key_result {
                #[allow(clippy::match_single_binding)]
                match key {
                    #[allow(clippy::redundant_clone)]
                    "id" => intermediate_rep.id.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "targetText" => intermediate_rep.target_text.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "targetSentence" => intermediate_rep.target_sentence.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "sourceTranslation" => intermediate_rep.source_translation.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "variant" => intermediate_rep.variant.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "personalization" => intermediate_rep.personalization.push(<models::GenerateExampleSentence200ResponsePersonalization as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "usageNote" => intermediate_rep.usage_note.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    _ => return std::result::Result::Err("Unexpected key while parsing ExampleSentence".to_string())
                }
            }

            // Get the next key
            key_result = string_iter.next();
        }

        // Use the intermediate representation to return the struct
        std::result::Result::Ok(ExampleSentence {
            id: intermediate_rep.id.into_iter().next().ok_or_else(|| "id missing in ExampleSentence".to_string())?,
            target_text: intermediate_rep.target_text.into_iter().next().ok_or_else(|| "targetText missing in ExampleSentence".to_string())?,
            target_sentence: intermediate_rep.target_sentence.into_iter().next().ok_or_else(|| "targetSentence missing in ExampleSentence".to_string())?,
            source_translation: intermediate_rep.source_translation.into_iter().next().ok_or_else(|| "sourceTranslation missing in ExampleSentence".to_string())?,
            variant: intermediate_rep.variant.into_iter().next().ok_or_else(|| "variant missing in ExampleSentence".to_string())?,
            personalization: intermediate_rep.personalization.into_iter().next(),
            usage_note: intermediate_rep.usage_note.into_iter().next(),
        })
    }
}

// Methods for converting between header::IntoHeaderValue<ExampleSentence> and HeaderValue

#[cfg(feature = "server")]
impl std::convert::TryFrom<header::IntoHeaderValue<ExampleSentence>> for HeaderValue {
    type Error = String;

    fn try_from(hdr_value: header::IntoHeaderValue<ExampleSentence>) -> std::result::Result<Self, Self::Error> {
        let hdr_value = hdr_value.to_string();
        match HeaderValue::from_str(&hdr_value) {
             std::result::Result::Ok(value) => std::result::Result::Ok(value),
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Invalid header value for ExampleSentence - value: {hdr_value} is invalid {e}"#))
        }
    }
}

#[cfg(feature = "server")]
impl std::convert::TryFrom<HeaderValue> for header::IntoHeaderValue<ExampleSentence> {
    type Error = String;

    fn try_from(hdr_value: HeaderValue) -> std::result::Result<Self, Self::Error> {
        match hdr_value.to_str() {
             std::result::Result::Ok(value) => {
                    match <ExampleSentence as std::str::FromStr>::from_str(value) {
                        std::result::Result::Ok(value) => std::result::Result::Ok(header::IntoHeaderValue(value)),
                        std::result::Result::Err(err) => std::result::Result::Err(format!(r#"Unable to convert header value '{value}' into ExampleSentence - {err}"#))
                    }
             },
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Unable to convert header: {hdr_value:?} to string: {e}"#))
        }
    }
}



#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, validator::Validate)]
#[cfg_attr(feature = "conversion", derive(frunk::LabelledGeneric))]
pub struct ExampleSentencePersonalization {
    #[serde(rename = "contextSummary")]
          #[validate(custom(function = "check_xss_string"))]
    #[serde(skip_serializing_if="Option::is_none")]
    pub context_summary: Option<String>,

    #[serde(rename = "personalizedFromUserContextAt")]
    #[serde(skip_serializing_if="Option::is_none")]
    pub personalized_from_user_context_at: Option<chrono::DateTime::<chrono::Utc>>,

}



impl ExampleSentencePersonalization {
    #[allow(clippy::new_without_default, clippy::too_many_arguments)]
    pub fn new() -> ExampleSentencePersonalization {
        ExampleSentencePersonalization {
 context_summary: None,
 personalized_from_user_context_at: None,
        }
    }
}

/// Converts the ExampleSentencePersonalization value to the Query Parameters representation (style=form, explode=false)
/// specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde serializer
impl std::fmt::Display for ExampleSentencePersonalization {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let params: Vec<Option<String>> = vec![

            self.context_summary.as_ref().map(|context_summary| {
                [
                    "contextSummary".to_string(),
                    context_summary.to_string(),
                ].join(",")
            }),

            // Skipping personalizedFromUserContextAt in query parameter serialization

        ];

        write!(f, "{}", params.into_iter().flatten().collect::<Vec<_>>().join(","))
    }
}

/// Converts Query Parameters representation (style=form, explode=false) to a ExampleSentencePersonalization value
/// as specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde deserializer
impl std::str::FromStr for ExampleSentencePersonalization {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        /// An intermediate representation of the struct to use for parsing.
        #[derive(Default)]
        #[allow(dead_code)]
        struct IntermediateRep {
            pub context_summary: Vec<String>,
            pub personalized_from_user_context_at: Vec<chrono::DateTime::<chrono::Utc>>,
        }

        let mut intermediate_rep = IntermediateRep::default();

        // Parse into intermediate representation
        let mut string_iter = s.split(',');
        let mut key_result = string_iter.next();

        while key_result.is_some() {
            let val = match string_iter.next() {
                Some(x) => x,
                None => return std::result::Result::Err("Missing value while parsing ExampleSentencePersonalization".to_string())
            };

            if let Some(key) = key_result {
                #[allow(clippy::match_single_binding)]
                match key {
                    #[allow(clippy::redundant_clone)]
                    "contextSummary" => intermediate_rep.context_summary.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "personalizedFromUserContextAt" => intermediate_rep.personalized_from_user_context_at.push(<chrono::DateTime::<chrono::Utc> as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    _ => return std::result::Result::Err("Unexpected key while parsing ExampleSentencePersonalization".to_string())
                }
            }

            // Get the next key
            key_result = string_iter.next();
        }

        // Use the intermediate representation to return the struct
        std::result::Result::Ok(ExampleSentencePersonalization {
            context_summary: intermediate_rep.context_summary.into_iter().next(),
            personalized_from_user_context_at: intermediate_rep.personalized_from_user_context_at.into_iter().next(),
        })
    }
}

// Methods for converting between header::IntoHeaderValue<ExampleSentencePersonalization> and HeaderValue

#[cfg(feature = "server")]
impl std::convert::TryFrom<header::IntoHeaderValue<ExampleSentencePersonalization>> for HeaderValue {
    type Error = String;

    fn try_from(hdr_value: header::IntoHeaderValue<ExampleSentencePersonalization>) -> std::result::Result<Self, Self::Error> {
        let hdr_value = hdr_value.to_string();
        match HeaderValue::from_str(&hdr_value) {
             std::result::Result::Ok(value) => std::result::Result::Ok(value),
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Invalid header value for ExampleSentencePersonalization - value: {hdr_value} is invalid {e}"#))
        }
    }
}

#[cfg(feature = "server")]
impl std::convert::TryFrom<HeaderValue> for header::IntoHeaderValue<ExampleSentencePersonalization> {
    type Error = String;

    fn try_from(hdr_value: HeaderValue) -> std::result::Result<Self, Self::Error> {
        match hdr_value.to_str() {
             std::result::Result::Ok(value) => {
                    match <ExampleSentencePersonalization as std::str::FromStr>::from_str(value) {
                        std::result::Result::Ok(value) => std::result::Result::Ok(header::IntoHeaderValue(value)),
                        std::result::Result::Err(err) => std::result::Result::Err(format!(r#"Unable to convert header value '{value}' into ExampleSentencePersonalization - {err}"#))
                    }
             },
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Unable to convert header: {hdr_value:?} to string: {e}"#))
        }
    }
}



#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, validator::Validate)]
#[cfg_attr(feature = "conversion", derive(frunk::LabelledGeneric))]
pub struct GenerateExampleSentence200Response {
    #[serde(rename = "id")]
          #[validate(custom(function = "check_xss_string"))]
    pub id: String,

    #[serde(rename = "targetText")]
          #[validate(custom(function = "check_xss_string"))]
    pub target_text: String,

    #[serde(rename = "targetSentence")]
          #[validate(custom(function = "check_xss_string"))]
    pub target_sentence: String,

    #[serde(rename = "sourceTranslation")]
          #[validate(custom(function = "check_xss_string"))]
    pub source_translation: String,

    /// Note: inline enums are not fully supported by openapi-generator
    #[serde(rename = "variant")]
          #[validate(custom(function = "check_xss_string"))]
    pub variant: String,

    #[serde(rename = "personalization")]
          #[validate(nested)]
    #[serde(skip_serializing_if="Option::is_none")]
    pub personalization: Option<models::GenerateExampleSentence200ResponsePersonalization>,

    #[serde(rename = "usageNote")]
          #[validate(custom(function = "check_xss_string"))]
    #[serde(skip_serializing_if="Option::is_none")]
    pub usage_note: Option<String>,

}



impl GenerateExampleSentence200Response {
    #[allow(clippy::new_without_default, clippy::too_many_arguments)]
    pub fn new(id: String, target_text: String, target_sentence: String, source_translation: String, variant: String, ) -> GenerateExampleSentence200Response {
        GenerateExampleSentence200Response {
 id,
 target_text,
 target_sentence,
 source_translation,
 variant,
 personalization: None,
 usage_note: None,
        }
    }
}

/// Converts the GenerateExampleSentence200Response value to the Query Parameters representation (style=form, explode=false)
/// specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde serializer
impl std::fmt::Display for GenerateExampleSentence200Response {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let params: Vec<Option<String>> = vec![

            Some("id".to_string()),
            Some(self.id.to_string()),


            Some("targetText".to_string()),
            Some(self.target_text.to_string()),


            Some("targetSentence".to_string()),
            Some(self.target_sentence.to_string()),


            Some("sourceTranslation".to_string()),
            Some(self.source_translation.to_string()),


            Some("variant".to_string()),
            Some(self.variant.to_string()),

            // Skipping personalization in query parameter serialization


            self.usage_note.as_ref().map(|usage_note| {
                [
                    "usageNote".to_string(),
                    usage_note.to_string(),
                ].join(",")
            }),

        ];

        write!(f, "{}", params.into_iter().flatten().collect::<Vec<_>>().join(","))
    }
}

/// Converts Query Parameters representation (style=form, explode=false) to a GenerateExampleSentence200Response value
/// as specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde deserializer
impl std::str::FromStr for GenerateExampleSentence200Response {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        /// An intermediate representation of the struct to use for parsing.
        #[derive(Default)]
        #[allow(dead_code)]
        struct IntermediateRep {
            pub id: Vec<String>,
            pub target_text: Vec<String>,
            pub target_sentence: Vec<String>,
            pub source_translation: Vec<String>,
            pub variant: Vec<String>,
            pub personalization: Vec<models::GenerateExampleSentence200ResponsePersonalization>,
            pub usage_note: Vec<String>,
        }

        let mut intermediate_rep = IntermediateRep::default();

        // Parse into intermediate representation
        let mut string_iter = s.split(',');
        let mut key_result = string_iter.next();

        while key_result.is_some() {
            let val = match string_iter.next() {
                Some(x) => x,
                None => return std::result::Result::Err("Missing value while parsing GenerateExampleSentence200Response".to_string())
            };

            if let Some(key) = key_result {
                #[allow(clippy::match_single_binding)]
                match key {
                    #[allow(clippy::redundant_clone)]
                    "id" => intermediate_rep.id.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "targetText" => intermediate_rep.target_text.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "targetSentence" => intermediate_rep.target_sentence.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "sourceTranslation" => intermediate_rep.source_translation.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "variant" => intermediate_rep.variant.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "personalization" => intermediate_rep.personalization.push(<models::GenerateExampleSentence200ResponsePersonalization as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "usageNote" => intermediate_rep.usage_note.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    _ => return std::result::Result::Err("Unexpected key while parsing GenerateExampleSentence200Response".to_string())
                }
            }

            // Get the next key
            key_result = string_iter.next();
        }

        // Use the intermediate representation to return the struct
        std::result::Result::Ok(GenerateExampleSentence200Response {
            id: intermediate_rep.id.into_iter().next().ok_or_else(|| "id missing in GenerateExampleSentence200Response".to_string())?,
            target_text: intermediate_rep.target_text.into_iter().next().ok_or_else(|| "targetText missing in GenerateExampleSentence200Response".to_string())?,
            target_sentence: intermediate_rep.target_sentence.into_iter().next().ok_or_else(|| "targetSentence missing in GenerateExampleSentence200Response".to_string())?,
            source_translation: intermediate_rep.source_translation.into_iter().next().ok_or_else(|| "sourceTranslation missing in GenerateExampleSentence200Response".to_string())?,
            variant: intermediate_rep.variant.into_iter().next().ok_or_else(|| "variant missing in GenerateExampleSentence200Response".to_string())?,
            personalization: intermediate_rep.personalization.into_iter().next(),
            usage_note: intermediate_rep.usage_note.into_iter().next(),
        })
    }
}

// Methods for converting between header::IntoHeaderValue<GenerateExampleSentence200Response> and HeaderValue

#[cfg(feature = "server")]
impl std::convert::TryFrom<header::IntoHeaderValue<GenerateExampleSentence200Response>> for HeaderValue {
    type Error = String;

    fn try_from(hdr_value: header::IntoHeaderValue<GenerateExampleSentence200Response>) -> std::result::Result<Self, Self::Error> {
        let hdr_value = hdr_value.to_string();
        match HeaderValue::from_str(&hdr_value) {
             std::result::Result::Ok(value) => std::result::Result::Ok(value),
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Invalid header value for GenerateExampleSentence200Response - value: {hdr_value} is invalid {e}"#))
        }
    }
}

#[cfg(feature = "server")]
impl std::convert::TryFrom<HeaderValue> for header::IntoHeaderValue<GenerateExampleSentence200Response> {
    type Error = String;

    fn try_from(hdr_value: HeaderValue) -> std::result::Result<Self, Self::Error> {
        match hdr_value.to_str() {
             std::result::Result::Ok(value) => {
                    match <GenerateExampleSentence200Response as std::str::FromStr>::from_str(value) {
                        std::result::Result::Ok(value) => std::result::Result::Ok(header::IntoHeaderValue(value)),
                        std::result::Result::Err(err) => std::result::Result::Err(format!(r#"Unable to convert header value '{value}' into GenerateExampleSentence200Response - {err}"#))
                    }
             },
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Unable to convert header: {hdr_value:?} to string: {e}"#))
        }
    }
}



#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, validator::Validate)]
#[cfg_attr(feature = "conversion", derive(frunk::LabelledGeneric))]
pub struct GenerateExampleSentence200ResponsePersonalization {
    #[serde(rename = "contextSummary")]
          #[validate(custom(function = "check_xss_string"))]
    #[serde(skip_serializing_if="Option::is_none")]
    pub context_summary: Option<String>,

    #[serde(rename = "personalizedFromUserContextAt")]
    #[serde(skip_serializing_if="Option::is_none")]
    pub personalized_from_user_context_at: Option<chrono::DateTime::<chrono::Utc>>,

}



impl GenerateExampleSentence200ResponsePersonalization {
    #[allow(clippy::new_without_default, clippy::too_many_arguments)]
    pub fn new() -> GenerateExampleSentence200ResponsePersonalization {
        GenerateExampleSentence200ResponsePersonalization {
 context_summary: None,
 personalized_from_user_context_at: None,
        }
    }
}

/// Converts the GenerateExampleSentence200ResponsePersonalization value to the Query Parameters representation (style=form, explode=false)
/// specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde serializer
impl std::fmt::Display for GenerateExampleSentence200ResponsePersonalization {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let params: Vec<Option<String>> = vec![

            self.context_summary.as_ref().map(|context_summary| {
                [
                    "contextSummary".to_string(),
                    context_summary.to_string(),
                ].join(",")
            }),

            // Skipping personalizedFromUserContextAt in query parameter serialization

        ];

        write!(f, "{}", params.into_iter().flatten().collect::<Vec<_>>().join(","))
    }
}

/// Converts Query Parameters representation (style=form, explode=false) to a GenerateExampleSentence200ResponsePersonalization value
/// as specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde deserializer
impl std::str::FromStr for GenerateExampleSentence200ResponsePersonalization {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        /// An intermediate representation of the struct to use for parsing.
        #[derive(Default)]
        #[allow(dead_code)]
        struct IntermediateRep {
            pub context_summary: Vec<String>,
            pub personalized_from_user_context_at: Vec<chrono::DateTime::<chrono::Utc>>,
        }

        let mut intermediate_rep = IntermediateRep::default();

        // Parse into intermediate representation
        let mut string_iter = s.split(',');
        let mut key_result = string_iter.next();

        while key_result.is_some() {
            let val = match string_iter.next() {
                Some(x) => x,
                None => return std::result::Result::Err("Missing value while parsing GenerateExampleSentence200ResponsePersonalization".to_string())
            };

            if let Some(key) = key_result {
                #[allow(clippy::match_single_binding)]
                match key {
                    #[allow(clippy::redundant_clone)]
                    "contextSummary" => intermediate_rep.context_summary.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "personalizedFromUserContextAt" => intermediate_rep.personalized_from_user_context_at.push(<chrono::DateTime::<chrono::Utc> as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    _ => return std::result::Result::Err("Unexpected key while parsing GenerateExampleSentence200ResponsePersonalization".to_string())
                }
            }

            // Get the next key
            key_result = string_iter.next();
        }

        // Use the intermediate representation to return the struct
        std::result::Result::Ok(GenerateExampleSentence200ResponsePersonalization {
            context_summary: intermediate_rep.context_summary.into_iter().next(),
            personalized_from_user_context_at: intermediate_rep.personalized_from_user_context_at.into_iter().next(),
        })
    }
}

// Methods for converting between header::IntoHeaderValue<GenerateExampleSentence200ResponsePersonalization> and HeaderValue

#[cfg(feature = "server")]
impl std::convert::TryFrom<header::IntoHeaderValue<GenerateExampleSentence200ResponsePersonalization>> for HeaderValue {
    type Error = String;

    fn try_from(hdr_value: header::IntoHeaderValue<GenerateExampleSentence200ResponsePersonalization>) -> std::result::Result<Self, Self::Error> {
        let hdr_value = hdr_value.to_string();
        match HeaderValue::from_str(&hdr_value) {
             std::result::Result::Ok(value) => std::result::Result::Ok(value),
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Invalid header value for GenerateExampleSentence200ResponsePersonalization - value: {hdr_value} is invalid {e}"#))
        }
    }
}

#[cfg(feature = "server")]
impl std::convert::TryFrom<HeaderValue> for header::IntoHeaderValue<GenerateExampleSentence200ResponsePersonalization> {
    type Error = String;

    fn try_from(hdr_value: HeaderValue) -> std::result::Result<Self, Self::Error> {
        match hdr_value.to_str() {
             std::result::Result::Ok(value) => {
                    match <GenerateExampleSentence200ResponsePersonalization as std::str::FromStr>::from_str(value) {
                        std::result::Result::Ok(value) => std::result::Result::Ok(header::IntoHeaderValue(value)),
                        std::result::Result::Err(err) => std::result::Result::Err(format!(r#"Unable to convert header value '{value}' into GenerateExampleSentence200ResponsePersonalization - {err}"#))
                    }
             },
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Unable to convert header: {hdr_value:?} to string: {e}"#))
        }
    }
}



#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, validator::Validate)]
#[cfg_attr(feature = "conversion", derive(frunk::LabelledGeneric))]
pub struct GenerateExampleSentence401Response {
    #[serde(rename = "message")]
          #[validate(custom(function = "check_xss_string"))]
    pub message: String,

}



impl GenerateExampleSentence401Response {
    #[allow(clippy::new_without_default, clippy::too_many_arguments)]
    pub fn new(message: String, ) -> GenerateExampleSentence401Response {
        GenerateExampleSentence401Response {
 message,
        }
    }
}

/// Converts the GenerateExampleSentence401Response value to the Query Parameters representation (style=form, explode=false)
/// specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde serializer
impl std::fmt::Display for GenerateExampleSentence401Response {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let params: Vec<Option<String>> = vec![

            Some("message".to_string()),
            Some(self.message.to_string()),

        ];

        write!(f, "{}", params.into_iter().flatten().collect::<Vec<_>>().join(","))
    }
}

/// Converts Query Parameters representation (style=form, explode=false) to a GenerateExampleSentence401Response value
/// as specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde deserializer
impl std::str::FromStr for GenerateExampleSentence401Response {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        /// An intermediate representation of the struct to use for parsing.
        #[derive(Default)]
        #[allow(dead_code)]
        struct IntermediateRep {
            pub message: Vec<String>,
        }

        let mut intermediate_rep = IntermediateRep::default();

        // Parse into intermediate representation
        let mut string_iter = s.split(',');
        let mut key_result = string_iter.next();

        while key_result.is_some() {
            let val = match string_iter.next() {
                Some(x) => x,
                None => return std::result::Result::Err("Missing value while parsing GenerateExampleSentence401Response".to_string())
            };

            if let Some(key) = key_result {
                #[allow(clippy::match_single_binding)]
                match key {
                    #[allow(clippy::redundant_clone)]
                    "message" => intermediate_rep.message.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    _ => return std::result::Result::Err("Unexpected key while parsing GenerateExampleSentence401Response".to_string())
                }
            }

            // Get the next key
            key_result = string_iter.next();
        }

        // Use the intermediate representation to return the struct
        std::result::Result::Ok(GenerateExampleSentence401Response {
            message: intermediate_rep.message.into_iter().next().ok_or_else(|| "message missing in GenerateExampleSentence401Response".to_string())?,
        })
    }
}

// Methods for converting between header::IntoHeaderValue<GenerateExampleSentence401Response> and HeaderValue

#[cfg(feature = "server")]
impl std::convert::TryFrom<header::IntoHeaderValue<GenerateExampleSentence401Response>> for HeaderValue {
    type Error = String;

    fn try_from(hdr_value: header::IntoHeaderValue<GenerateExampleSentence401Response>) -> std::result::Result<Self, Self::Error> {
        let hdr_value = hdr_value.to_string();
        match HeaderValue::from_str(&hdr_value) {
             std::result::Result::Ok(value) => std::result::Result::Ok(value),
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Invalid header value for GenerateExampleSentence401Response - value: {hdr_value} is invalid {e}"#))
        }
    }
}

#[cfg(feature = "server")]
impl std::convert::TryFrom<HeaderValue> for header::IntoHeaderValue<GenerateExampleSentence401Response> {
    type Error = String;

    fn try_from(hdr_value: HeaderValue) -> std::result::Result<Self, Self::Error> {
        match hdr_value.to_str() {
             std::result::Result::Ok(value) => {
                    match <GenerateExampleSentence401Response as std::str::FromStr>::from_str(value) {
                        std::result::Result::Ok(value) => std::result::Result::Ok(header::IntoHeaderValue(value)),
                        std::result::Result::Err(err) => std::result::Result::Err(format!(r#"Unable to convert header value '{value}' into GenerateExampleSentence401Response - {err}"#))
                    }
             },
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Unable to convert header: {hdr_value:?} to string: {e}"#))
        }
    }
}



#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, validator::Validate)]
#[cfg_attr(feature = "conversion", derive(frunk::LabelledGeneric))]
pub struct GenerateExampleSentenceRequest {
    #[serde(rename = "targetText")]
    #[validate(
            length(min = 1),
          custom(function = "check_xss_string"),
    )]
    pub target_text: String,

    #[serde(rename = "userContextSummary")]
    #[validate(
            length(min = 1),
          custom(function = "check_xss_string"),
    )]
    pub user_context_summary: String,

}



impl GenerateExampleSentenceRequest {
    #[allow(clippy::new_without_default, clippy::too_many_arguments)]
    pub fn new(target_text: String, user_context_summary: String, ) -> GenerateExampleSentenceRequest {
        GenerateExampleSentenceRequest {
 target_text,
 user_context_summary,
        }
    }
}

/// Converts the GenerateExampleSentenceRequest value to the Query Parameters representation (style=form, explode=false)
/// specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde serializer
impl std::fmt::Display for GenerateExampleSentenceRequest {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let params: Vec<Option<String>> = vec![

            Some("targetText".to_string()),
            Some(self.target_text.to_string()),


            Some("userContextSummary".to_string()),
            Some(self.user_context_summary.to_string()),

        ];

        write!(f, "{}", params.into_iter().flatten().collect::<Vec<_>>().join(","))
    }
}

/// Converts Query Parameters representation (style=form, explode=false) to a GenerateExampleSentenceRequest value
/// as specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde deserializer
impl std::str::FromStr for GenerateExampleSentenceRequest {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        /// An intermediate representation of the struct to use for parsing.
        #[derive(Default)]
        #[allow(dead_code)]
        struct IntermediateRep {
            pub target_text: Vec<String>,
            pub user_context_summary: Vec<String>,
        }

        let mut intermediate_rep = IntermediateRep::default();

        // Parse into intermediate representation
        let mut string_iter = s.split(',');
        let mut key_result = string_iter.next();

        while key_result.is_some() {
            let val = match string_iter.next() {
                Some(x) => x,
                None => return std::result::Result::Err("Missing value while parsing GenerateExampleSentenceRequest".to_string())
            };

            if let Some(key) = key_result {
                #[allow(clippy::match_single_binding)]
                match key {
                    #[allow(clippy::redundant_clone)]
                    "targetText" => intermediate_rep.target_text.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "userContextSummary" => intermediate_rep.user_context_summary.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    _ => return std::result::Result::Err("Unexpected key while parsing GenerateExampleSentenceRequest".to_string())
                }
            }

            // Get the next key
            key_result = string_iter.next();
        }

        // Use the intermediate representation to return the struct
        std::result::Result::Ok(GenerateExampleSentenceRequest {
            target_text: intermediate_rep.target_text.into_iter().next().ok_or_else(|| "targetText missing in GenerateExampleSentenceRequest".to_string())?,
            user_context_summary: intermediate_rep.user_context_summary.into_iter().next().ok_or_else(|| "userContextSummary missing in GenerateExampleSentenceRequest".to_string())?,
        })
    }
}

// Methods for converting between header::IntoHeaderValue<GenerateExampleSentenceRequest> and HeaderValue

#[cfg(feature = "server")]
impl std::convert::TryFrom<header::IntoHeaderValue<GenerateExampleSentenceRequest>> for HeaderValue {
    type Error = String;

    fn try_from(hdr_value: header::IntoHeaderValue<GenerateExampleSentenceRequest>) -> std::result::Result<Self, Self::Error> {
        let hdr_value = hdr_value.to_string();
        match HeaderValue::from_str(&hdr_value) {
             std::result::Result::Ok(value) => std::result::Result::Ok(value),
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Invalid header value for GenerateExampleSentenceRequest - value: {hdr_value} is invalid {e}"#))
        }
    }
}

#[cfg(feature = "server")]
impl std::convert::TryFrom<HeaderValue> for header::IntoHeaderValue<GenerateExampleSentenceRequest> {
    type Error = String;

    fn try_from(hdr_value: HeaderValue) -> std::result::Result<Self, Self::Error> {
        match hdr_value.to_str() {
             std::result::Result::Ok(value) => {
                    match <GenerateExampleSentenceRequest as std::str::FromStr>::from_str(value) {
                        std::result::Result::Ok(value) => std::result::Result::Ok(header::IntoHeaderValue(value)),
                        std::result::Result::Err(err) => std::result::Result::Err(format!(r#"Unable to convert header value '{value}' into GenerateExampleSentenceRequest - {err}"#))
                    }
             },
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Unable to convert header: {hdr_value:?} to string: {e}"#))
        }
    }
}



#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, validator::Validate)]
#[cfg_attr(feature = "conversion", derive(frunk::LabelledGeneric))]
pub struct GetAuthSession200Response {
    #[serde(rename = "authenticated")]
    pub authenticated: bool,

    #[serde(rename = "cognitoSub")]
          #[validate(custom(function = "check_xss_string"))]
    pub cognito_sub: String,

    #[serde(rename = "appUserId")]
    pub app_user_id: uuid::Uuid,

    #[serde(rename = "email")]
          #[validate(custom(function = "check_xss_string"))]
    pub email: String,

}



impl GetAuthSession200Response {
    #[allow(clippy::new_without_default, clippy::too_many_arguments)]
    pub fn new(authenticated: bool, cognito_sub: String, app_user_id: uuid::Uuid, email: String, ) -> GetAuthSession200Response {
        GetAuthSession200Response {
 authenticated,
 cognito_sub,
 app_user_id,
 email,
        }
    }
}

/// Converts the GetAuthSession200Response value to the Query Parameters representation (style=form, explode=false)
/// specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde serializer
impl std::fmt::Display for GetAuthSession200Response {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let params: Vec<Option<String>> = vec![

            Some("authenticated".to_string()),
            Some(self.authenticated.to_string()),


            Some("cognitoSub".to_string()),
            Some(self.cognito_sub.to_string()),

            // Skipping appUserId in query parameter serialization


            Some("email".to_string()),
            Some(self.email.to_string()),

        ];

        write!(f, "{}", params.into_iter().flatten().collect::<Vec<_>>().join(","))
    }
}

/// Converts Query Parameters representation (style=form, explode=false) to a GetAuthSession200Response value
/// as specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde deserializer
impl std::str::FromStr for GetAuthSession200Response {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        /// An intermediate representation of the struct to use for parsing.
        #[derive(Default)]
        #[allow(dead_code)]
        struct IntermediateRep {
            pub authenticated: Vec<bool>,
            pub cognito_sub: Vec<String>,
            pub app_user_id: Vec<uuid::Uuid>,
            pub email: Vec<String>,
        }

        let mut intermediate_rep = IntermediateRep::default();

        // Parse into intermediate representation
        let mut string_iter = s.split(',');
        let mut key_result = string_iter.next();

        while key_result.is_some() {
            let val = match string_iter.next() {
                Some(x) => x,
                None => return std::result::Result::Err("Missing value while parsing GetAuthSession200Response".to_string())
            };

            if let Some(key) = key_result {
                #[allow(clippy::match_single_binding)]
                match key {
                    #[allow(clippy::redundant_clone)]
                    "authenticated" => intermediate_rep.authenticated.push(<bool as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "cognitoSub" => intermediate_rep.cognito_sub.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "appUserId" => intermediate_rep.app_user_id.push(<uuid::Uuid as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "email" => intermediate_rep.email.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    _ => return std::result::Result::Err("Unexpected key while parsing GetAuthSession200Response".to_string())
                }
            }

            // Get the next key
            key_result = string_iter.next();
        }

        // Use the intermediate representation to return the struct
        std::result::Result::Ok(GetAuthSession200Response {
            authenticated: intermediate_rep.authenticated.into_iter().next().ok_or_else(|| "authenticated missing in GetAuthSession200Response".to_string())?,
            cognito_sub: intermediate_rep.cognito_sub.into_iter().next().ok_or_else(|| "cognitoSub missing in GetAuthSession200Response".to_string())?,
            app_user_id: intermediate_rep.app_user_id.into_iter().next().ok_or_else(|| "appUserId missing in GetAuthSession200Response".to_string())?,
            email: intermediate_rep.email.into_iter().next().ok_or_else(|| "email missing in GetAuthSession200Response".to_string())?,
        })
    }
}

// Methods for converting between header::IntoHeaderValue<GetAuthSession200Response> and HeaderValue

#[cfg(feature = "server")]
impl std::convert::TryFrom<header::IntoHeaderValue<GetAuthSession200Response>> for HeaderValue {
    type Error = String;

    fn try_from(hdr_value: header::IntoHeaderValue<GetAuthSession200Response>) -> std::result::Result<Self, Self::Error> {
        let hdr_value = hdr_value.to_string();
        match HeaderValue::from_str(&hdr_value) {
             std::result::Result::Ok(value) => std::result::Result::Ok(value),
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Invalid header value for GetAuthSession200Response - value: {hdr_value} is invalid {e}"#))
        }
    }
}

#[cfg(feature = "server")]
impl std::convert::TryFrom<HeaderValue> for header::IntoHeaderValue<GetAuthSession200Response> {
    type Error = String;

    fn try_from(hdr_value: HeaderValue) -> std::result::Result<Self, Self::Error> {
        match hdr_value.to_str() {
             std::result::Result::Ok(value) => {
                    match <GetAuthSession200Response as std::str::FromStr>::from_str(value) {
                        std::result::Result::Ok(value) => std::result::Result::Ok(header::IntoHeaderValue(value)),
                        std::result::Result::Err(err) => std::result::Result::Err(format!(r#"Unable to convert header value '{value}' into GetAuthSession200Response - {err}"#))
                    }
             },
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Unable to convert header: {hdr_value:?} to string: {e}"#))
        }
    }
}



#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, validator::Validate)]
#[cfg_attr(feature = "conversion", derive(frunk::LabelledGeneric))]
pub struct GetAuthSession401Response {
    #[serde(rename = "message")]
          #[validate(custom(function = "check_xss_string"))]
    pub message: String,

}



impl GetAuthSession401Response {
    #[allow(clippy::new_without_default, clippy::too_many_arguments)]
    pub fn new(message: String, ) -> GetAuthSession401Response {
        GetAuthSession401Response {
 message,
        }
    }
}

/// Converts the GetAuthSession401Response value to the Query Parameters representation (style=form, explode=false)
/// specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde serializer
impl std::fmt::Display for GetAuthSession401Response {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let params: Vec<Option<String>> = vec![

            Some("message".to_string()),
            Some(self.message.to_string()),

        ];

        write!(f, "{}", params.into_iter().flatten().collect::<Vec<_>>().join(","))
    }
}

/// Converts Query Parameters representation (style=form, explode=false) to a GetAuthSession401Response value
/// as specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde deserializer
impl std::str::FromStr for GetAuthSession401Response {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        /// An intermediate representation of the struct to use for parsing.
        #[derive(Default)]
        #[allow(dead_code)]
        struct IntermediateRep {
            pub message: Vec<String>,
        }

        let mut intermediate_rep = IntermediateRep::default();

        // Parse into intermediate representation
        let mut string_iter = s.split(',');
        let mut key_result = string_iter.next();

        while key_result.is_some() {
            let val = match string_iter.next() {
                Some(x) => x,
                None => return std::result::Result::Err("Missing value while parsing GetAuthSession401Response".to_string())
            };

            if let Some(key) = key_result {
                #[allow(clippy::match_single_binding)]
                match key {
                    #[allow(clippy::redundant_clone)]
                    "message" => intermediate_rep.message.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    _ => return std::result::Result::Err("Unexpected key while parsing GetAuthSession401Response".to_string())
                }
            }

            // Get the next key
            key_result = string_iter.next();
        }

        // Use the intermediate representation to return the struct
        std::result::Result::Ok(GetAuthSession401Response {
            message: intermediate_rep.message.into_iter().next().ok_or_else(|| "message missing in GetAuthSession401Response".to_string())?,
        })
    }
}

// Methods for converting between header::IntoHeaderValue<GetAuthSession401Response> and HeaderValue

#[cfg(feature = "server")]
impl std::convert::TryFrom<header::IntoHeaderValue<GetAuthSession401Response>> for HeaderValue {
    type Error = String;

    fn try_from(hdr_value: header::IntoHeaderValue<GetAuthSession401Response>) -> std::result::Result<Self, Self::Error> {
        let hdr_value = hdr_value.to_string();
        match HeaderValue::from_str(&hdr_value) {
             std::result::Result::Ok(value) => std::result::Result::Ok(value),
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Invalid header value for GetAuthSession401Response - value: {hdr_value} is invalid {e}"#))
        }
    }
}

#[cfg(feature = "server")]
impl std::convert::TryFrom<HeaderValue> for header::IntoHeaderValue<GetAuthSession401Response> {
    type Error = String;

    fn try_from(hdr_value: HeaderValue) -> std::result::Result<Self, Self::Error> {
        match hdr_value.to_str() {
             std::result::Result::Ok(value) => {
                    match <GetAuthSession401Response as std::str::FromStr>::from_str(value) {
                        std::result::Result::Ok(value) => std::result::Result::Ok(header::IntoHeaderValue(value)),
                        std::result::Result::Err(err) => std::result::Result::Err(format!(r#"Unable to convert header value '{value}' into GetAuthSession401Response - {err}"#))
                    }
             },
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Unable to convert header: {hdr_value:?} to string: {e}"#))
        }
    }
}



#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, validator::Validate)]
#[cfg_attr(feature = "conversion", derive(frunk::LabelledGeneric))]
pub struct GetLearnerProfile200Response {
    #[serde(rename = "learningPurpose")]
          #[validate(custom(function = "check_xss_string"))]
    pub learning_purpose: String,

    #[serde(rename = "targetLevel")]
          #[validate(custom(function = "check_xss_string"))]
    pub target_level: String,

    #[serde(rename = "deadline")]
          #[validate(custom(function = "check_xss_string"))]
    pub deadline: String,

    #[serde(rename = "interests")]
          #[validate(custom(function = "check_xss_string"))]
    pub interests: String,

    #[serde(rename = "favoriteContent")]
          #[validate(custom(function = "check_xss_string"))]
    pub favorite_content: String,

    #[serde(rename = "dailyScenes")]
          #[validate(custom(function = "check_xss_string"))]
    pub daily_scenes: String,

    #[serde(rename = "englishUseCases")]
          #[validate(custom(function = "check_xss_string"))]
    pub english_use_cases: String,

    #[serde(rename = "weakPoints")]
          #[validate(custom(function = "check_xss_string"))]
    pub weak_points: String,

    #[serde(rename = "vocabularyFocus")]
          #[validate(custom(function = "check_xss_string"))]
    pub vocabulary_focus: String,

    #[serde(rename = "updatedAt")]
    #[serde(skip_serializing_if="Option::is_none")]
    pub updated_at: Option<chrono::DateTime::<chrono::Utc>>,

}



impl GetLearnerProfile200Response {
    #[allow(clippy::new_without_default, clippy::too_many_arguments)]
    pub fn new(learning_purpose: String, target_level: String, deadline: String, interests: String, favorite_content: String, daily_scenes: String, english_use_cases: String, weak_points: String, vocabulary_focus: String, ) -> GetLearnerProfile200Response {
        GetLearnerProfile200Response {
 learning_purpose,
 target_level,
 deadline,
 interests,
 favorite_content,
 daily_scenes,
 english_use_cases,
 weak_points,
 vocabulary_focus,
 updated_at: None,
        }
    }
}

/// Converts the GetLearnerProfile200Response value to the Query Parameters representation (style=form, explode=false)
/// specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde serializer
impl std::fmt::Display for GetLearnerProfile200Response {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let params: Vec<Option<String>> = vec![

            Some("learningPurpose".to_string()),
            Some(self.learning_purpose.to_string()),


            Some("targetLevel".to_string()),
            Some(self.target_level.to_string()),


            Some("deadline".to_string()),
            Some(self.deadline.to_string()),


            Some("interests".to_string()),
            Some(self.interests.to_string()),


            Some("favoriteContent".to_string()),
            Some(self.favorite_content.to_string()),


            Some("dailyScenes".to_string()),
            Some(self.daily_scenes.to_string()),


            Some("englishUseCases".to_string()),
            Some(self.english_use_cases.to_string()),


            Some("weakPoints".to_string()),
            Some(self.weak_points.to_string()),


            Some("vocabularyFocus".to_string()),
            Some(self.vocabulary_focus.to_string()),

            // Skipping updatedAt in query parameter serialization

        ];

        write!(f, "{}", params.into_iter().flatten().collect::<Vec<_>>().join(","))
    }
}

/// Converts Query Parameters representation (style=form, explode=false) to a GetLearnerProfile200Response value
/// as specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde deserializer
impl std::str::FromStr for GetLearnerProfile200Response {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        /// An intermediate representation of the struct to use for parsing.
        #[derive(Default)]
        #[allow(dead_code)]
        struct IntermediateRep {
            pub learning_purpose: Vec<String>,
            pub target_level: Vec<String>,
            pub deadline: Vec<String>,
            pub interests: Vec<String>,
            pub favorite_content: Vec<String>,
            pub daily_scenes: Vec<String>,
            pub english_use_cases: Vec<String>,
            pub weak_points: Vec<String>,
            pub vocabulary_focus: Vec<String>,
            pub updated_at: Vec<chrono::DateTime::<chrono::Utc>>,
        }

        let mut intermediate_rep = IntermediateRep::default();

        // Parse into intermediate representation
        let mut string_iter = s.split(',');
        let mut key_result = string_iter.next();

        while key_result.is_some() {
            let val = match string_iter.next() {
                Some(x) => x,
                None => return std::result::Result::Err("Missing value while parsing GetLearnerProfile200Response".to_string())
            };

            if let Some(key) = key_result {
                #[allow(clippy::match_single_binding)]
                match key {
                    #[allow(clippy::redundant_clone)]
                    "learningPurpose" => intermediate_rep.learning_purpose.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "targetLevel" => intermediate_rep.target_level.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "deadline" => intermediate_rep.deadline.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "interests" => intermediate_rep.interests.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "favoriteContent" => intermediate_rep.favorite_content.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "dailyScenes" => intermediate_rep.daily_scenes.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "englishUseCases" => intermediate_rep.english_use_cases.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "weakPoints" => intermediate_rep.weak_points.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "vocabularyFocus" => intermediate_rep.vocabulary_focus.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "updatedAt" => intermediate_rep.updated_at.push(<chrono::DateTime::<chrono::Utc> as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    _ => return std::result::Result::Err("Unexpected key while parsing GetLearnerProfile200Response".to_string())
                }
            }

            // Get the next key
            key_result = string_iter.next();
        }

        // Use the intermediate representation to return the struct
        std::result::Result::Ok(GetLearnerProfile200Response {
            learning_purpose: intermediate_rep.learning_purpose.into_iter().next().ok_or_else(|| "learningPurpose missing in GetLearnerProfile200Response".to_string())?,
            target_level: intermediate_rep.target_level.into_iter().next().ok_or_else(|| "targetLevel missing in GetLearnerProfile200Response".to_string())?,
            deadline: intermediate_rep.deadline.into_iter().next().ok_or_else(|| "deadline missing in GetLearnerProfile200Response".to_string())?,
            interests: intermediate_rep.interests.into_iter().next().ok_or_else(|| "interests missing in GetLearnerProfile200Response".to_string())?,
            favorite_content: intermediate_rep.favorite_content.into_iter().next().ok_or_else(|| "favoriteContent missing in GetLearnerProfile200Response".to_string())?,
            daily_scenes: intermediate_rep.daily_scenes.into_iter().next().ok_or_else(|| "dailyScenes missing in GetLearnerProfile200Response".to_string())?,
            english_use_cases: intermediate_rep.english_use_cases.into_iter().next().ok_or_else(|| "englishUseCases missing in GetLearnerProfile200Response".to_string())?,
            weak_points: intermediate_rep.weak_points.into_iter().next().ok_or_else(|| "weakPoints missing in GetLearnerProfile200Response".to_string())?,
            vocabulary_focus: intermediate_rep.vocabulary_focus.into_iter().next().ok_or_else(|| "vocabularyFocus missing in GetLearnerProfile200Response".to_string())?,
            updated_at: intermediate_rep.updated_at.into_iter().next(),
        })
    }
}

// Methods for converting between header::IntoHeaderValue<GetLearnerProfile200Response> and HeaderValue

#[cfg(feature = "server")]
impl std::convert::TryFrom<header::IntoHeaderValue<GetLearnerProfile200Response>> for HeaderValue {
    type Error = String;

    fn try_from(hdr_value: header::IntoHeaderValue<GetLearnerProfile200Response>) -> std::result::Result<Self, Self::Error> {
        let hdr_value = hdr_value.to_string();
        match HeaderValue::from_str(&hdr_value) {
             std::result::Result::Ok(value) => std::result::Result::Ok(value),
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Invalid header value for GetLearnerProfile200Response - value: {hdr_value} is invalid {e}"#))
        }
    }
}

#[cfg(feature = "server")]
impl std::convert::TryFrom<HeaderValue> for header::IntoHeaderValue<GetLearnerProfile200Response> {
    type Error = String;

    fn try_from(hdr_value: HeaderValue) -> std::result::Result<Self, Self::Error> {
        match hdr_value.to_str() {
             std::result::Result::Ok(value) => {
                    match <GetLearnerProfile200Response as std::str::FromStr>::from_str(value) {
                        std::result::Result::Ok(value) => std::result::Result::Ok(header::IntoHeaderValue(value)),
                        std::result::Result::Err(err) => std::result::Result::Err(format!(r#"Unable to convert header value '{value}' into GetLearnerProfile200Response - {err}"#))
                    }
             },
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Unable to convert header: {hdr_value:?} to string: {e}"#))
        }
    }
}



#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, validator::Validate)]
#[cfg_attr(feature = "conversion", derive(frunk::LabelledGeneric))]
pub struct GetLearningPath200Response {
    #[serde(rename = "id")]
          #[validate(custom(function = "check_xss_string"))]
    pub id: String,

    #[serde(rename = "title")]
          #[validate(custom(function = "check_xss_string"))]
    pub title: String,

    #[serde(rename = "tagline")]
          #[validate(custom(function = "check_xss_string"))]
    pub tagline: String,

    #[serde(rename = "description")]
          #[validate(custom(function = "check_xss_string"))]
    pub description: String,

    #[serde(rename = "audience")]
          #[validate(custom(function = "check_xss_string"))]
    pub audience: String,

    #[serde(rename = "courses")]
          #[validate(nested)]
    pub courses: Vec<models::GetLearningPaths200ResponseInnerCoursesInner>,

}



impl GetLearningPath200Response {
    #[allow(clippy::new_without_default, clippy::too_many_arguments)]
    pub fn new(id: String, title: String, tagline: String, description: String, audience: String, courses: Vec<models::GetLearningPaths200ResponseInnerCoursesInner>, ) -> GetLearningPath200Response {
        GetLearningPath200Response {
 id,
 title,
 tagline,
 description,
 audience,
 courses,
        }
    }
}

/// Converts the GetLearningPath200Response value to the Query Parameters representation (style=form, explode=false)
/// specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde serializer
impl std::fmt::Display for GetLearningPath200Response {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let params: Vec<Option<String>> = vec![

            Some("id".to_string()),
            Some(self.id.to_string()),


            Some("title".to_string()),
            Some(self.title.to_string()),


            Some("tagline".to_string()),
            Some(self.tagline.to_string()),


            Some("description".to_string()),
            Some(self.description.to_string()),


            Some("audience".to_string()),
            Some(self.audience.to_string()),

            // Skipping courses in query parameter serialization

        ];

        write!(f, "{}", params.into_iter().flatten().collect::<Vec<_>>().join(","))
    }
}

/// Converts Query Parameters representation (style=form, explode=false) to a GetLearningPath200Response value
/// as specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde deserializer
impl std::str::FromStr for GetLearningPath200Response {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        /// An intermediate representation of the struct to use for parsing.
        #[derive(Default)]
        #[allow(dead_code)]
        struct IntermediateRep {
            pub id: Vec<String>,
            pub title: Vec<String>,
            pub tagline: Vec<String>,
            pub description: Vec<String>,
            pub audience: Vec<String>,
            pub courses: Vec<Vec<models::GetLearningPaths200ResponseInnerCoursesInner>>,
        }

        let mut intermediate_rep = IntermediateRep::default();

        // Parse into intermediate representation
        let mut string_iter = s.split(',');
        let mut key_result = string_iter.next();

        while key_result.is_some() {
            let val = match string_iter.next() {
                Some(x) => x,
                None => return std::result::Result::Err("Missing value while parsing GetLearningPath200Response".to_string())
            };

            if let Some(key) = key_result {
                #[allow(clippy::match_single_binding)]
                match key {
                    #[allow(clippy::redundant_clone)]
                    "id" => intermediate_rep.id.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "title" => intermediate_rep.title.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "tagline" => intermediate_rep.tagline.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "description" => intermediate_rep.description.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "audience" => intermediate_rep.audience.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    "courses" => return std::result::Result::Err("Parsing a container in this style is not supported in GetLearningPath200Response".to_string()),
                    _ => return std::result::Result::Err("Unexpected key while parsing GetLearningPath200Response".to_string())
                }
            }

            // Get the next key
            key_result = string_iter.next();
        }

        // Use the intermediate representation to return the struct
        std::result::Result::Ok(GetLearningPath200Response {
            id: intermediate_rep.id.into_iter().next().ok_or_else(|| "id missing in GetLearningPath200Response".to_string())?,
            title: intermediate_rep.title.into_iter().next().ok_or_else(|| "title missing in GetLearningPath200Response".to_string())?,
            tagline: intermediate_rep.tagline.into_iter().next().ok_or_else(|| "tagline missing in GetLearningPath200Response".to_string())?,
            description: intermediate_rep.description.into_iter().next().ok_or_else(|| "description missing in GetLearningPath200Response".to_string())?,
            audience: intermediate_rep.audience.into_iter().next().ok_or_else(|| "audience missing in GetLearningPath200Response".to_string())?,
            courses: intermediate_rep.courses.into_iter().next().ok_or_else(|| "courses missing in GetLearningPath200Response".to_string())?,
        })
    }
}

// Methods for converting between header::IntoHeaderValue<GetLearningPath200Response> and HeaderValue

#[cfg(feature = "server")]
impl std::convert::TryFrom<header::IntoHeaderValue<GetLearningPath200Response>> for HeaderValue {
    type Error = String;

    fn try_from(hdr_value: header::IntoHeaderValue<GetLearningPath200Response>) -> std::result::Result<Self, Self::Error> {
        let hdr_value = hdr_value.to_string();
        match HeaderValue::from_str(&hdr_value) {
             std::result::Result::Ok(value) => std::result::Result::Ok(value),
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Invalid header value for GetLearningPath200Response - value: {hdr_value} is invalid {e}"#))
        }
    }
}

#[cfg(feature = "server")]
impl std::convert::TryFrom<HeaderValue> for header::IntoHeaderValue<GetLearningPath200Response> {
    type Error = String;

    fn try_from(hdr_value: HeaderValue) -> std::result::Result<Self, Self::Error> {
        match hdr_value.to_str() {
             std::result::Result::Ok(value) => {
                    match <GetLearningPath200Response as std::str::FromStr>::from_str(value) {
                        std::result::Result::Ok(value) => std::result::Result::Ok(header::IntoHeaderValue(value)),
                        std::result::Result::Err(err) => std::result::Result::Err(format!(r#"Unable to convert header value '{value}' into GetLearningPath200Response - {err}"#))
                    }
             },
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Unable to convert header: {hdr_value:?} to string: {e}"#))
        }
    }
}



#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, validator::Validate)]
#[cfg_attr(feature = "conversion", derive(frunk::LabelledGeneric))]
pub struct GetLearningPathCourse200Response {
    #[serde(rename = "id")]
          #[validate(custom(function = "check_xss_string"))]
    pub id: String,

    #[serde(rename = "title")]
          #[validate(custom(function = "check_xss_string"))]
    pub title: String,

    #[serde(rename = "levelLabel")]
          #[validate(custom(function = "check_xss_string"))]
    pub level_label: String,

    #[serde(rename = "description")]
          #[validate(custom(function = "check_xss_string"))]
    pub description: String,

    #[serde(rename = "outcome")]
          #[validate(custom(function = "check_xss_string"))]
    pub outcome: String,

    #[serde(rename = "estimatedHours")]
    #[validate(
            range(min = 0u32),
    )]
    pub estimated_hours: u32,

    #[serde(rename = "units")]
          #[validate(nested)]
    pub units: Vec<models::GetLearningPaths200ResponseInnerCoursesInnerUnitsInner>,

}



impl GetLearningPathCourse200Response {
    #[allow(clippy::new_without_default, clippy::too_many_arguments)]
    pub fn new(id: String, title: String, level_label: String, description: String, outcome: String, estimated_hours: u32, units: Vec<models::GetLearningPaths200ResponseInnerCoursesInnerUnitsInner>, ) -> GetLearningPathCourse200Response {
        GetLearningPathCourse200Response {
 id,
 title,
 level_label,
 description,
 outcome,
 estimated_hours,
 units,
        }
    }
}

/// Converts the GetLearningPathCourse200Response value to the Query Parameters representation (style=form, explode=false)
/// specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde serializer
impl std::fmt::Display for GetLearningPathCourse200Response {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let params: Vec<Option<String>> = vec![

            Some("id".to_string()),
            Some(self.id.to_string()),


            Some("title".to_string()),
            Some(self.title.to_string()),


            Some("levelLabel".to_string()),
            Some(self.level_label.to_string()),


            Some("description".to_string()),
            Some(self.description.to_string()),


            Some("outcome".to_string()),
            Some(self.outcome.to_string()),


            Some("estimatedHours".to_string()),
            Some(self.estimated_hours.to_string()),

            // Skipping units in query parameter serialization

        ];

        write!(f, "{}", params.into_iter().flatten().collect::<Vec<_>>().join(","))
    }
}

/// Converts Query Parameters representation (style=form, explode=false) to a GetLearningPathCourse200Response value
/// as specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde deserializer
impl std::str::FromStr for GetLearningPathCourse200Response {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        /// An intermediate representation of the struct to use for parsing.
        #[derive(Default)]
        #[allow(dead_code)]
        struct IntermediateRep {
            pub id: Vec<String>,
            pub title: Vec<String>,
            pub level_label: Vec<String>,
            pub description: Vec<String>,
            pub outcome: Vec<String>,
            pub estimated_hours: Vec<u32>,
            pub units: Vec<Vec<models::GetLearningPaths200ResponseInnerCoursesInnerUnitsInner>>,
        }

        let mut intermediate_rep = IntermediateRep::default();

        // Parse into intermediate representation
        let mut string_iter = s.split(',');
        let mut key_result = string_iter.next();

        while key_result.is_some() {
            let val = match string_iter.next() {
                Some(x) => x,
                None => return std::result::Result::Err("Missing value while parsing GetLearningPathCourse200Response".to_string())
            };

            if let Some(key) = key_result {
                #[allow(clippy::match_single_binding)]
                match key {
                    #[allow(clippy::redundant_clone)]
                    "id" => intermediate_rep.id.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "title" => intermediate_rep.title.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "levelLabel" => intermediate_rep.level_label.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "description" => intermediate_rep.description.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "outcome" => intermediate_rep.outcome.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "estimatedHours" => intermediate_rep.estimated_hours.push(<u32 as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    "units" => return std::result::Result::Err("Parsing a container in this style is not supported in GetLearningPathCourse200Response".to_string()),
                    _ => return std::result::Result::Err("Unexpected key while parsing GetLearningPathCourse200Response".to_string())
                }
            }

            // Get the next key
            key_result = string_iter.next();
        }

        // Use the intermediate representation to return the struct
        std::result::Result::Ok(GetLearningPathCourse200Response {
            id: intermediate_rep.id.into_iter().next().ok_or_else(|| "id missing in GetLearningPathCourse200Response".to_string())?,
            title: intermediate_rep.title.into_iter().next().ok_or_else(|| "title missing in GetLearningPathCourse200Response".to_string())?,
            level_label: intermediate_rep.level_label.into_iter().next().ok_or_else(|| "levelLabel missing in GetLearningPathCourse200Response".to_string())?,
            description: intermediate_rep.description.into_iter().next().ok_or_else(|| "description missing in GetLearningPathCourse200Response".to_string())?,
            outcome: intermediate_rep.outcome.into_iter().next().ok_or_else(|| "outcome missing in GetLearningPathCourse200Response".to_string())?,
            estimated_hours: intermediate_rep.estimated_hours.into_iter().next().ok_or_else(|| "estimatedHours missing in GetLearningPathCourse200Response".to_string())?,
            units: intermediate_rep.units.into_iter().next().ok_or_else(|| "units missing in GetLearningPathCourse200Response".to_string())?,
        })
    }
}

// Methods for converting between header::IntoHeaderValue<GetLearningPathCourse200Response> and HeaderValue

#[cfg(feature = "server")]
impl std::convert::TryFrom<header::IntoHeaderValue<GetLearningPathCourse200Response>> for HeaderValue {
    type Error = String;

    fn try_from(hdr_value: header::IntoHeaderValue<GetLearningPathCourse200Response>) -> std::result::Result<Self, Self::Error> {
        let hdr_value = hdr_value.to_string();
        match HeaderValue::from_str(&hdr_value) {
             std::result::Result::Ok(value) => std::result::Result::Ok(value),
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Invalid header value for GetLearningPathCourse200Response - value: {hdr_value} is invalid {e}"#))
        }
    }
}

#[cfg(feature = "server")]
impl std::convert::TryFrom<HeaderValue> for header::IntoHeaderValue<GetLearningPathCourse200Response> {
    type Error = String;

    fn try_from(hdr_value: HeaderValue) -> std::result::Result<Self, Self::Error> {
        match hdr_value.to_str() {
             std::result::Result::Ok(value) => {
                    match <GetLearningPathCourse200Response as std::str::FromStr>::from_str(value) {
                        std::result::Result::Ok(value) => std::result::Result::Ok(header::IntoHeaderValue(value)),
                        std::result::Result::Err(err) => std::result::Result::Err(format!(r#"Unable to convert header value '{value}' into GetLearningPathCourse200Response - {err}"#))
                    }
             },
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Unable to convert header: {hdr_value:?} to string: {e}"#))
        }
    }
}



#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, validator::Validate)]
#[cfg_attr(feature = "conversion", derive(frunk::LabelledGeneric))]
pub struct GetLearningPaths200ResponseInner {
    #[serde(rename = "id")]
          #[validate(custom(function = "check_xss_string"))]
    pub id: String,

    #[serde(rename = "title")]
          #[validate(custom(function = "check_xss_string"))]
    pub title: String,

    #[serde(rename = "tagline")]
          #[validate(custom(function = "check_xss_string"))]
    pub tagline: String,

    #[serde(rename = "description")]
          #[validate(custom(function = "check_xss_string"))]
    pub description: String,

    #[serde(rename = "audience")]
          #[validate(custom(function = "check_xss_string"))]
    pub audience: String,

    #[serde(rename = "courses")]
          #[validate(nested)]
    pub courses: Vec<models::GetLearningPaths200ResponseInnerCoursesInner>,

}



impl GetLearningPaths200ResponseInner {
    #[allow(clippy::new_without_default, clippy::too_many_arguments)]
    pub fn new(id: String, title: String, tagline: String, description: String, audience: String, courses: Vec<models::GetLearningPaths200ResponseInnerCoursesInner>, ) -> GetLearningPaths200ResponseInner {
        GetLearningPaths200ResponseInner {
 id,
 title,
 tagline,
 description,
 audience,
 courses,
        }
    }
}

/// Converts the GetLearningPaths200ResponseInner value to the Query Parameters representation (style=form, explode=false)
/// specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde serializer
impl std::fmt::Display for GetLearningPaths200ResponseInner {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let params: Vec<Option<String>> = vec![

            Some("id".to_string()),
            Some(self.id.to_string()),


            Some("title".to_string()),
            Some(self.title.to_string()),


            Some("tagline".to_string()),
            Some(self.tagline.to_string()),


            Some("description".to_string()),
            Some(self.description.to_string()),


            Some("audience".to_string()),
            Some(self.audience.to_string()),

            // Skipping courses in query parameter serialization

        ];

        write!(f, "{}", params.into_iter().flatten().collect::<Vec<_>>().join(","))
    }
}

/// Converts Query Parameters representation (style=form, explode=false) to a GetLearningPaths200ResponseInner value
/// as specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde deserializer
impl std::str::FromStr for GetLearningPaths200ResponseInner {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        /// An intermediate representation of the struct to use for parsing.
        #[derive(Default)]
        #[allow(dead_code)]
        struct IntermediateRep {
            pub id: Vec<String>,
            pub title: Vec<String>,
            pub tagline: Vec<String>,
            pub description: Vec<String>,
            pub audience: Vec<String>,
            pub courses: Vec<Vec<models::GetLearningPaths200ResponseInnerCoursesInner>>,
        }

        let mut intermediate_rep = IntermediateRep::default();

        // Parse into intermediate representation
        let mut string_iter = s.split(',');
        let mut key_result = string_iter.next();

        while key_result.is_some() {
            let val = match string_iter.next() {
                Some(x) => x,
                None => return std::result::Result::Err("Missing value while parsing GetLearningPaths200ResponseInner".to_string())
            };

            if let Some(key) = key_result {
                #[allow(clippy::match_single_binding)]
                match key {
                    #[allow(clippy::redundant_clone)]
                    "id" => intermediate_rep.id.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "title" => intermediate_rep.title.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "tagline" => intermediate_rep.tagline.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "description" => intermediate_rep.description.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "audience" => intermediate_rep.audience.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    "courses" => return std::result::Result::Err("Parsing a container in this style is not supported in GetLearningPaths200ResponseInner".to_string()),
                    _ => return std::result::Result::Err("Unexpected key while parsing GetLearningPaths200ResponseInner".to_string())
                }
            }

            // Get the next key
            key_result = string_iter.next();
        }

        // Use the intermediate representation to return the struct
        std::result::Result::Ok(GetLearningPaths200ResponseInner {
            id: intermediate_rep.id.into_iter().next().ok_or_else(|| "id missing in GetLearningPaths200ResponseInner".to_string())?,
            title: intermediate_rep.title.into_iter().next().ok_or_else(|| "title missing in GetLearningPaths200ResponseInner".to_string())?,
            tagline: intermediate_rep.tagline.into_iter().next().ok_or_else(|| "tagline missing in GetLearningPaths200ResponseInner".to_string())?,
            description: intermediate_rep.description.into_iter().next().ok_or_else(|| "description missing in GetLearningPaths200ResponseInner".to_string())?,
            audience: intermediate_rep.audience.into_iter().next().ok_or_else(|| "audience missing in GetLearningPaths200ResponseInner".to_string())?,
            courses: intermediate_rep.courses.into_iter().next().ok_or_else(|| "courses missing in GetLearningPaths200ResponseInner".to_string())?,
        })
    }
}

// Methods for converting between header::IntoHeaderValue<GetLearningPaths200ResponseInner> and HeaderValue

#[cfg(feature = "server")]
impl std::convert::TryFrom<header::IntoHeaderValue<GetLearningPaths200ResponseInner>> for HeaderValue {
    type Error = String;

    fn try_from(hdr_value: header::IntoHeaderValue<GetLearningPaths200ResponseInner>) -> std::result::Result<Self, Self::Error> {
        let hdr_value = hdr_value.to_string();
        match HeaderValue::from_str(&hdr_value) {
             std::result::Result::Ok(value) => std::result::Result::Ok(value),
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Invalid header value for GetLearningPaths200ResponseInner - value: {hdr_value} is invalid {e}"#))
        }
    }
}

#[cfg(feature = "server")]
impl std::convert::TryFrom<HeaderValue> for header::IntoHeaderValue<GetLearningPaths200ResponseInner> {
    type Error = String;

    fn try_from(hdr_value: HeaderValue) -> std::result::Result<Self, Self::Error> {
        match hdr_value.to_str() {
             std::result::Result::Ok(value) => {
                    match <GetLearningPaths200ResponseInner as std::str::FromStr>::from_str(value) {
                        std::result::Result::Ok(value) => std::result::Result::Ok(header::IntoHeaderValue(value)),
                        std::result::Result::Err(err) => std::result::Result::Err(format!(r#"Unable to convert header value '{value}' into GetLearningPaths200ResponseInner - {err}"#))
                    }
             },
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Unable to convert header: {hdr_value:?} to string: {e}"#))
        }
    }
}



#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, validator::Validate)]
#[cfg_attr(feature = "conversion", derive(frunk::LabelledGeneric))]
pub struct GetLearningPaths200ResponseInnerCoursesInner {
    #[serde(rename = "id")]
          #[validate(custom(function = "check_xss_string"))]
    pub id: String,

    #[serde(rename = "title")]
          #[validate(custom(function = "check_xss_string"))]
    pub title: String,

    #[serde(rename = "levelLabel")]
          #[validate(custom(function = "check_xss_string"))]
    pub level_label: String,

    #[serde(rename = "description")]
          #[validate(custom(function = "check_xss_string"))]
    pub description: String,

    #[serde(rename = "outcome")]
          #[validate(custom(function = "check_xss_string"))]
    pub outcome: String,

    #[serde(rename = "estimatedHours")]
    #[validate(
            range(min = 0u32),
    )]
    pub estimated_hours: u32,

    #[serde(rename = "units")]
          #[validate(nested)]
    pub units: Vec<models::GetLearningPaths200ResponseInnerCoursesInnerUnitsInner>,

}



impl GetLearningPaths200ResponseInnerCoursesInner {
    #[allow(clippy::new_without_default, clippy::too_many_arguments)]
    pub fn new(id: String, title: String, level_label: String, description: String, outcome: String, estimated_hours: u32, units: Vec<models::GetLearningPaths200ResponseInnerCoursesInnerUnitsInner>, ) -> GetLearningPaths200ResponseInnerCoursesInner {
        GetLearningPaths200ResponseInnerCoursesInner {
 id,
 title,
 level_label,
 description,
 outcome,
 estimated_hours,
 units,
        }
    }
}

/// Converts the GetLearningPaths200ResponseInnerCoursesInner value to the Query Parameters representation (style=form, explode=false)
/// specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde serializer
impl std::fmt::Display for GetLearningPaths200ResponseInnerCoursesInner {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let params: Vec<Option<String>> = vec![

            Some("id".to_string()),
            Some(self.id.to_string()),


            Some("title".to_string()),
            Some(self.title.to_string()),


            Some("levelLabel".to_string()),
            Some(self.level_label.to_string()),


            Some("description".to_string()),
            Some(self.description.to_string()),


            Some("outcome".to_string()),
            Some(self.outcome.to_string()),


            Some("estimatedHours".to_string()),
            Some(self.estimated_hours.to_string()),

            // Skipping units in query parameter serialization

        ];

        write!(f, "{}", params.into_iter().flatten().collect::<Vec<_>>().join(","))
    }
}

/// Converts Query Parameters representation (style=form, explode=false) to a GetLearningPaths200ResponseInnerCoursesInner value
/// as specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde deserializer
impl std::str::FromStr for GetLearningPaths200ResponseInnerCoursesInner {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        /// An intermediate representation of the struct to use for parsing.
        #[derive(Default)]
        #[allow(dead_code)]
        struct IntermediateRep {
            pub id: Vec<String>,
            pub title: Vec<String>,
            pub level_label: Vec<String>,
            pub description: Vec<String>,
            pub outcome: Vec<String>,
            pub estimated_hours: Vec<u32>,
            pub units: Vec<Vec<models::GetLearningPaths200ResponseInnerCoursesInnerUnitsInner>>,
        }

        let mut intermediate_rep = IntermediateRep::default();

        // Parse into intermediate representation
        let mut string_iter = s.split(',');
        let mut key_result = string_iter.next();

        while key_result.is_some() {
            let val = match string_iter.next() {
                Some(x) => x,
                None => return std::result::Result::Err("Missing value while parsing GetLearningPaths200ResponseInnerCoursesInner".to_string())
            };

            if let Some(key) = key_result {
                #[allow(clippy::match_single_binding)]
                match key {
                    #[allow(clippy::redundant_clone)]
                    "id" => intermediate_rep.id.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "title" => intermediate_rep.title.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "levelLabel" => intermediate_rep.level_label.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "description" => intermediate_rep.description.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "outcome" => intermediate_rep.outcome.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "estimatedHours" => intermediate_rep.estimated_hours.push(<u32 as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    "units" => return std::result::Result::Err("Parsing a container in this style is not supported in GetLearningPaths200ResponseInnerCoursesInner".to_string()),
                    _ => return std::result::Result::Err("Unexpected key while parsing GetLearningPaths200ResponseInnerCoursesInner".to_string())
                }
            }

            // Get the next key
            key_result = string_iter.next();
        }

        // Use the intermediate representation to return the struct
        std::result::Result::Ok(GetLearningPaths200ResponseInnerCoursesInner {
            id: intermediate_rep.id.into_iter().next().ok_or_else(|| "id missing in GetLearningPaths200ResponseInnerCoursesInner".to_string())?,
            title: intermediate_rep.title.into_iter().next().ok_or_else(|| "title missing in GetLearningPaths200ResponseInnerCoursesInner".to_string())?,
            level_label: intermediate_rep.level_label.into_iter().next().ok_or_else(|| "levelLabel missing in GetLearningPaths200ResponseInnerCoursesInner".to_string())?,
            description: intermediate_rep.description.into_iter().next().ok_or_else(|| "description missing in GetLearningPaths200ResponseInnerCoursesInner".to_string())?,
            outcome: intermediate_rep.outcome.into_iter().next().ok_or_else(|| "outcome missing in GetLearningPaths200ResponseInnerCoursesInner".to_string())?,
            estimated_hours: intermediate_rep.estimated_hours.into_iter().next().ok_or_else(|| "estimatedHours missing in GetLearningPaths200ResponseInnerCoursesInner".to_string())?,
            units: intermediate_rep.units.into_iter().next().ok_or_else(|| "units missing in GetLearningPaths200ResponseInnerCoursesInner".to_string())?,
        })
    }
}

// Methods for converting between header::IntoHeaderValue<GetLearningPaths200ResponseInnerCoursesInner> and HeaderValue

#[cfg(feature = "server")]
impl std::convert::TryFrom<header::IntoHeaderValue<GetLearningPaths200ResponseInnerCoursesInner>> for HeaderValue {
    type Error = String;

    fn try_from(hdr_value: header::IntoHeaderValue<GetLearningPaths200ResponseInnerCoursesInner>) -> std::result::Result<Self, Self::Error> {
        let hdr_value = hdr_value.to_string();
        match HeaderValue::from_str(&hdr_value) {
             std::result::Result::Ok(value) => std::result::Result::Ok(value),
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Invalid header value for GetLearningPaths200ResponseInnerCoursesInner - value: {hdr_value} is invalid {e}"#))
        }
    }
}

#[cfg(feature = "server")]
impl std::convert::TryFrom<HeaderValue> for header::IntoHeaderValue<GetLearningPaths200ResponseInnerCoursesInner> {
    type Error = String;

    fn try_from(hdr_value: HeaderValue) -> std::result::Result<Self, Self::Error> {
        match hdr_value.to_str() {
             std::result::Result::Ok(value) => {
                    match <GetLearningPaths200ResponseInnerCoursesInner as std::str::FromStr>::from_str(value) {
                        std::result::Result::Ok(value) => std::result::Result::Ok(header::IntoHeaderValue(value)),
                        std::result::Result::Err(err) => std::result::Result::Err(format!(r#"Unable to convert header value '{value}' into GetLearningPaths200ResponseInnerCoursesInner - {err}"#))
                    }
             },
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Unable to convert header: {hdr_value:?} to string: {e}"#))
        }
    }
}



#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, validator::Validate)]
#[cfg_attr(feature = "conversion", derive(frunk::LabelledGeneric))]
pub struct GetLearningPaths200ResponseInnerCoursesInnerUnitsInner {
    #[serde(rename = "id")]
          #[validate(custom(function = "check_xss_string"))]
    pub id: String,

    #[serde(rename = "title")]
          #[validate(custom(function = "check_xss_string"))]
    pub title: String,

    #[serde(rename = "description")]
          #[validate(custom(function = "check_xss_string"))]
    pub description: String,

    #[serde(rename = "targetSkill")]
          #[validate(custom(function = "check_xss_string"))]
    pub target_skill: String,

    #[serde(rename = "durationMinutes")]
    #[validate(
            range(min = 0u32),
    )]
    pub duration_minutes: u32,

    #[serde(rename = "vocabularyEntries")]
          #[validate(nested)]
    pub vocabulary_entries: Vec<models::GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner>,

}



impl GetLearningPaths200ResponseInnerCoursesInnerUnitsInner {
    #[allow(clippy::new_without_default, clippy::too_many_arguments)]
    pub fn new(id: String, title: String, description: String, target_skill: String, duration_minutes: u32, vocabulary_entries: Vec<models::GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner>, ) -> GetLearningPaths200ResponseInnerCoursesInnerUnitsInner {
        GetLearningPaths200ResponseInnerCoursesInnerUnitsInner {
 id,
 title,
 description,
 target_skill,
 duration_minutes,
 vocabulary_entries,
        }
    }
}

/// Converts the GetLearningPaths200ResponseInnerCoursesInnerUnitsInner value to the Query Parameters representation (style=form, explode=false)
/// specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde serializer
impl std::fmt::Display for GetLearningPaths200ResponseInnerCoursesInnerUnitsInner {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let params: Vec<Option<String>> = vec![

            Some("id".to_string()),
            Some(self.id.to_string()),


            Some("title".to_string()),
            Some(self.title.to_string()),


            Some("description".to_string()),
            Some(self.description.to_string()),


            Some("targetSkill".to_string()),
            Some(self.target_skill.to_string()),


            Some("durationMinutes".to_string()),
            Some(self.duration_minutes.to_string()),

            // Skipping vocabularyEntries in query parameter serialization

        ];

        write!(f, "{}", params.into_iter().flatten().collect::<Vec<_>>().join(","))
    }
}

/// Converts Query Parameters representation (style=form, explode=false) to a GetLearningPaths200ResponseInnerCoursesInnerUnitsInner value
/// as specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde deserializer
impl std::str::FromStr for GetLearningPaths200ResponseInnerCoursesInnerUnitsInner {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        /// An intermediate representation of the struct to use for parsing.
        #[derive(Default)]
        #[allow(dead_code)]
        struct IntermediateRep {
            pub id: Vec<String>,
            pub title: Vec<String>,
            pub description: Vec<String>,
            pub target_skill: Vec<String>,
            pub duration_minutes: Vec<u32>,
            pub vocabulary_entries: Vec<Vec<models::GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner>>,
        }

        let mut intermediate_rep = IntermediateRep::default();

        // Parse into intermediate representation
        let mut string_iter = s.split(',');
        let mut key_result = string_iter.next();

        while key_result.is_some() {
            let val = match string_iter.next() {
                Some(x) => x,
                None => return std::result::Result::Err("Missing value while parsing GetLearningPaths200ResponseInnerCoursesInnerUnitsInner".to_string())
            };

            if let Some(key) = key_result {
                #[allow(clippy::match_single_binding)]
                match key {
                    #[allow(clippy::redundant_clone)]
                    "id" => intermediate_rep.id.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "title" => intermediate_rep.title.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "description" => intermediate_rep.description.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "targetSkill" => intermediate_rep.target_skill.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "durationMinutes" => intermediate_rep.duration_minutes.push(<u32 as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    "vocabularyEntries" => return std::result::Result::Err("Parsing a container in this style is not supported in GetLearningPaths200ResponseInnerCoursesInnerUnitsInner".to_string()),
                    _ => return std::result::Result::Err("Unexpected key while parsing GetLearningPaths200ResponseInnerCoursesInnerUnitsInner".to_string())
                }
            }

            // Get the next key
            key_result = string_iter.next();
        }

        // Use the intermediate representation to return the struct
        std::result::Result::Ok(GetLearningPaths200ResponseInnerCoursesInnerUnitsInner {
            id: intermediate_rep.id.into_iter().next().ok_or_else(|| "id missing in GetLearningPaths200ResponseInnerCoursesInnerUnitsInner".to_string())?,
            title: intermediate_rep.title.into_iter().next().ok_or_else(|| "title missing in GetLearningPaths200ResponseInnerCoursesInnerUnitsInner".to_string())?,
            description: intermediate_rep.description.into_iter().next().ok_or_else(|| "description missing in GetLearningPaths200ResponseInnerCoursesInnerUnitsInner".to_string())?,
            target_skill: intermediate_rep.target_skill.into_iter().next().ok_or_else(|| "targetSkill missing in GetLearningPaths200ResponseInnerCoursesInnerUnitsInner".to_string())?,
            duration_minutes: intermediate_rep.duration_minutes.into_iter().next().ok_or_else(|| "durationMinutes missing in GetLearningPaths200ResponseInnerCoursesInnerUnitsInner".to_string())?,
            vocabulary_entries: intermediate_rep.vocabulary_entries.into_iter().next().ok_or_else(|| "vocabularyEntries missing in GetLearningPaths200ResponseInnerCoursesInnerUnitsInner".to_string())?,
        })
    }
}

// Methods for converting between header::IntoHeaderValue<GetLearningPaths200ResponseInnerCoursesInnerUnitsInner> and HeaderValue

#[cfg(feature = "server")]
impl std::convert::TryFrom<header::IntoHeaderValue<GetLearningPaths200ResponseInnerCoursesInnerUnitsInner>> for HeaderValue {
    type Error = String;

    fn try_from(hdr_value: header::IntoHeaderValue<GetLearningPaths200ResponseInnerCoursesInnerUnitsInner>) -> std::result::Result<Self, Self::Error> {
        let hdr_value = hdr_value.to_string();
        match HeaderValue::from_str(&hdr_value) {
             std::result::Result::Ok(value) => std::result::Result::Ok(value),
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Invalid header value for GetLearningPaths200ResponseInnerCoursesInnerUnitsInner - value: {hdr_value} is invalid {e}"#))
        }
    }
}

#[cfg(feature = "server")]
impl std::convert::TryFrom<HeaderValue> for header::IntoHeaderValue<GetLearningPaths200ResponseInnerCoursesInnerUnitsInner> {
    type Error = String;

    fn try_from(hdr_value: HeaderValue) -> std::result::Result<Self, Self::Error> {
        match hdr_value.to_str() {
             std::result::Result::Ok(value) => {
                    match <GetLearningPaths200ResponseInnerCoursesInnerUnitsInner as std::str::FromStr>::from_str(value) {
                        std::result::Result::Ok(value) => std::result::Result::Ok(header::IntoHeaderValue(value)),
                        std::result::Result::Err(err) => std::result::Result::Err(format!(r#"Unable to convert header value '{value}' into GetLearningPaths200ResponseInnerCoursesInnerUnitsInner - {err}"#))
                    }
             },
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Unable to convert header: {hdr_value:?} to string: {e}"#))
        }
    }
}



#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, validator::Validate)]
#[cfg_attr(feature = "conversion", derive(frunk::LabelledGeneric))]
pub struct GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner {
    #[serde(rename = "id")]
          #[validate(custom(function = "check_xss_string"))]
    pub id: String,

    #[serde(rename = "targetText")]
          #[validate(custom(function = "check_xss_string"))]
    pub target_text: String,

    /// Note: inline enums are not fully supported by openapi-generator
    #[serde(rename = "kind")]
          #[validate(custom(function = "check_xss_string"))]
    pub kind: String,

    #[serde(rename = "sourceMeaning")]
          #[validate(custom(function = "check_xss_string"))]
    pub source_meaning: String,

    #[serde(rename = "targetExampleSentence")]
          #[validate(custom(function = "check_xss_string"))]
    pub target_example_sentence: String,

    #[serde(rename = "sourceExampleTranslation")]
          #[validate(custom(function = "check_xss_string"))]
    pub source_example_translation: String,

    /// Note: inline enums are not fully supported by openapi-generator
    #[serde(rename = "progressStatus")]
          #[validate(custom(function = "check_xss_string"))]
    #[serde(skip_serializing_if="Option::is_none")]
    pub progress_status: Option<String>,

    #[serde(rename = "exampleSentences")]
          #[validate(nested)]
    #[serde(skip_serializing_if="Option::is_none")]
    pub example_sentences: Option<Vec<models::GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner>>,

}



impl GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner {
    #[allow(clippy::new_without_default, clippy::too_many_arguments)]
    pub fn new(id: String, target_text: String, kind: String, source_meaning: String, target_example_sentence: String, source_example_translation: String, ) -> GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner {
        GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner {
 id,
 target_text,
 kind,
 source_meaning,
 target_example_sentence,
 source_example_translation,
 progress_status: None,
 example_sentences: None,
        }
    }
}

/// Converts the GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner value to the Query Parameters representation (style=form, explode=false)
/// specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde serializer
impl std::fmt::Display for GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let params: Vec<Option<String>> = vec![

            Some("id".to_string()),
            Some(self.id.to_string()),


            Some("targetText".to_string()),
            Some(self.target_text.to_string()),


            Some("kind".to_string()),
            Some(self.kind.to_string()),


            Some("sourceMeaning".to_string()),
            Some(self.source_meaning.to_string()),


            Some("targetExampleSentence".to_string()),
            Some(self.target_example_sentence.to_string()),


            Some("sourceExampleTranslation".to_string()),
            Some(self.source_example_translation.to_string()),


            self.progress_status.as_ref().map(|progress_status| {
                [
                    "progressStatus".to_string(),
                    progress_status.to_string(),
                ].join(",")
            }),

            // Skipping exampleSentences in query parameter serialization

        ];

        write!(f, "{}", params.into_iter().flatten().collect::<Vec<_>>().join(","))
    }
}

/// Converts Query Parameters representation (style=form, explode=false) to a GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner value
/// as specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde deserializer
impl std::str::FromStr for GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        /// An intermediate representation of the struct to use for parsing.
        #[derive(Default)]
        #[allow(dead_code)]
        struct IntermediateRep {
            pub id: Vec<String>,
            pub target_text: Vec<String>,
            pub kind: Vec<String>,
            pub source_meaning: Vec<String>,
            pub target_example_sentence: Vec<String>,
            pub source_example_translation: Vec<String>,
            pub progress_status: Vec<String>,
            pub example_sentences: Vec<Vec<models::GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner>>,
        }

        let mut intermediate_rep = IntermediateRep::default();

        // Parse into intermediate representation
        let mut string_iter = s.split(',');
        let mut key_result = string_iter.next();

        while key_result.is_some() {
            let val = match string_iter.next() {
                Some(x) => x,
                None => return std::result::Result::Err("Missing value while parsing GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner".to_string())
            };

            if let Some(key) = key_result {
                #[allow(clippy::match_single_binding)]
                match key {
                    #[allow(clippy::redundant_clone)]
                    "id" => intermediate_rep.id.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "targetText" => intermediate_rep.target_text.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "kind" => intermediate_rep.kind.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "sourceMeaning" => intermediate_rep.source_meaning.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "targetExampleSentence" => intermediate_rep.target_example_sentence.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "sourceExampleTranslation" => intermediate_rep.source_example_translation.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "progressStatus" => intermediate_rep.progress_status.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    "exampleSentences" => return std::result::Result::Err("Parsing a container in this style is not supported in GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner".to_string()),
                    _ => return std::result::Result::Err("Unexpected key while parsing GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner".to_string())
                }
            }

            // Get the next key
            key_result = string_iter.next();
        }

        // Use the intermediate representation to return the struct
        std::result::Result::Ok(GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner {
            id: intermediate_rep.id.into_iter().next().ok_or_else(|| "id missing in GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner".to_string())?,
            target_text: intermediate_rep.target_text.into_iter().next().ok_or_else(|| "targetText missing in GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner".to_string())?,
            kind: intermediate_rep.kind.into_iter().next().ok_or_else(|| "kind missing in GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner".to_string())?,
            source_meaning: intermediate_rep.source_meaning.into_iter().next().ok_or_else(|| "sourceMeaning missing in GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner".to_string())?,
            target_example_sentence: intermediate_rep.target_example_sentence.into_iter().next().ok_or_else(|| "targetExampleSentence missing in GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner".to_string())?,
            source_example_translation: intermediate_rep.source_example_translation.into_iter().next().ok_or_else(|| "sourceExampleTranslation missing in GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner".to_string())?,
            progress_status: intermediate_rep.progress_status.into_iter().next(),
            example_sentences: intermediate_rep.example_sentences.into_iter().next(),
        })
    }
}

// Methods for converting between header::IntoHeaderValue<GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner> and HeaderValue

#[cfg(feature = "server")]
impl std::convert::TryFrom<header::IntoHeaderValue<GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner>> for HeaderValue {
    type Error = String;

    fn try_from(hdr_value: header::IntoHeaderValue<GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner>) -> std::result::Result<Self, Self::Error> {
        let hdr_value = hdr_value.to_string();
        match HeaderValue::from_str(&hdr_value) {
             std::result::Result::Ok(value) => std::result::Result::Ok(value),
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Invalid header value for GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner - value: {hdr_value} is invalid {e}"#))
        }
    }
}

#[cfg(feature = "server")]
impl std::convert::TryFrom<HeaderValue> for header::IntoHeaderValue<GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner> {
    type Error = String;

    fn try_from(hdr_value: HeaderValue) -> std::result::Result<Self, Self::Error> {
        match hdr_value.to_str() {
             std::result::Result::Ok(value) => {
                    match <GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner as std::str::FromStr>::from_str(value) {
                        std::result::Result::Ok(value) => std::result::Result::Ok(header::IntoHeaderValue(value)),
                        std::result::Result::Err(err) => std::result::Result::Err(format!(r#"Unable to convert header value '{value}' into GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner - {err}"#))
                    }
             },
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Unable to convert header: {hdr_value:?} to string: {e}"#))
        }
    }
}



#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, validator::Validate)]
#[cfg_attr(feature = "conversion", derive(frunk::LabelledGeneric))]
pub struct GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner {
    #[serde(rename = "id")]
          #[validate(custom(function = "check_xss_string"))]
    pub id: String,

    #[serde(rename = "targetText")]
          #[validate(custom(function = "check_xss_string"))]
    pub target_text: String,

    #[serde(rename = "targetSentence")]
          #[validate(custom(function = "check_xss_string"))]
    pub target_sentence: String,

    #[serde(rename = "sourceTranslation")]
          #[validate(custom(function = "check_xss_string"))]
    pub source_translation: String,

    /// Note: inline enums are not fully supported by openapi-generator
    #[serde(rename = "variant")]
          #[validate(custom(function = "check_xss_string"))]
    pub variant: String,

    #[serde(rename = "personalization")]
          #[validate(nested)]
    #[serde(skip_serializing_if="Option::is_none")]
    pub personalization: Option<models::GenerateExampleSentence200ResponsePersonalization>,

    #[serde(rename = "usageNote")]
          #[validate(custom(function = "check_xss_string"))]
    #[serde(skip_serializing_if="Option::is_none")]
    pub usage_note: Option<String>,

}



impl GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner {
    #[allow(clippy::new_without_default, clippy::too_many_arguments)]
    pub fn new(id: String, target_text: String, target_sentence: String, source_translation: String, variant: String, ) -> GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner {
        GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner {
 id,
 target_text,
 target_sentence,
 source_translation,
 variant,
 personalization: None,
 usage_note: None,
        }
    }
}

/// Converts the GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner value to the Query Parameters representation (style=form, explode=false)
/// specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde serializer
impl std::fmt::Display for GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let params: Vec<Option<String>> = vec![

            Some("id".to_string()),
            Some(self.id.to_string()),


            Some("targetText".to_string()),
            Some(self.target_text.to_string()),


            Some("targetSentence".to_string()),
            Some(self.target_sentence.to_string()),


            Some("sourceTranslation".to_string()),
            Some(self.source_translation.to_string()),


            Some("variant".to_string()),
            Some(self.variant.to_string()),

            // Skipping personalization in query parameter serialization


            self.usage_note.as_ref().map(|usage_note| {
                [
                    "usageNote".to_string(),
                    usage_note.to_string(),
                ].join(",")
            }),

        ];

        write!(f, "{}", params.into_iter().flatten().collect::<Vec<_>>().join(","))
    }
}

/// Converts Query Parameters representation (style=form, explode=false) to a GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner value
/// as specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde deserializer
impl std::str::FromStr for GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        /// An intermediate representation of the struct to use for parsing.
        #[derive(Default)]
        #[allow(dead_code)]
        struct IntermediateRep {
            pub id: Vec<String>,
            pub target_text: Vec<String>,
            pub target_sentence: Vec<String>,
            pub source_translation: Vec<String>,
            pub variant: Vec<String>,
            pub personalization: Vec<models::GenerateExampleSentence200ResponsePersonalization>,
            pub usage_note: Vec<String>,
        }

        let mut intermediate_rep = IntermediateRep::default();

        // Parse into intermediate representation
        let mut string_iter = s.split(',');
        let mut key_result = string_iter.next();

        while key_result.is_some() {
            let val = match string_iter.next() {
                Some(x) => x,
                None => return std::result::Result::Err("Missing value while parsing GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner".to_string())
            };

            if let Some(key) = key_result {
                #[allow(clippy::match_single_binding)]
                match key {
                    #[allow(clippy::redundant_clone)]
                    "id" => intermediate_rep.id.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "targetText" => intermediate_rep.target_text.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "targetSentence" => intermediate_rep.target_sentence.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "sourceTranslation" => intermediate_rep.source_translation.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "variant" => intermediate_rep.variant.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "personalization" => intermediate_rep.personalization.push(<models::GenerateExampleSentence200ResponsePersonalization as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "usageNote" => intermediate_rep.usage_note.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    _ => return std::result::Result::Err("Unexpected key while parsing GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner".to_string())
                }
            }

            // Get the next key
            key_result = string_iter.next();
        }

        // Use the intermediate representation to return the struct
        std::result::Result::Ok(GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner {
            id: intermediate_rep.id.into_iter().next().ok_or_else(|| "id missing in GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner".to_string())?,
            target_text: intermediate_rep.target_text.into_iter().next().ok_or_else(|| "targetText missing in GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner".to_string())?,
            target_sentence: intermediate_rep.target_sentence.into_iter().next().ok_or_else(|| "targetSentence missing in GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner".to_string())?,
            source_translation: intermediate_rep.source_translation.into_iter().next().ok_or_else(|| "sourceTranslation missing in GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner".to_string())?,
            variant: intermediate_rep.variant.into_iter().next().ok_or_else(|| "variant missing in GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner".to_string())?,
            personalization: intermediate_rep.personalization.into_iter().next(),
            usage_note: intermediate_rep.usage_note.into_iter().next(),
        })
    }
}

// Methods for converting between header::IntoHeaderValue<GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner> and HeaderValue

#[cfg(feature = "server")]
impl std::convert::TryFrom<header::IntoHeaderValue<GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner>> for HeaderValue {
    type Error = String;

    fn try_from(hdr_value: header::IntoHeaderValue<GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner>) -> std::result::Result<Self, Self::Error> {
        let hdr_value = hdr_value.to_string();
        match HeaderValue::from_str(&hdr_value) {
             std::result::Result::Ok(value) => std::result::Result::Ok(value),
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Invalid header value for GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner - value: {hdr_value} is invalid {e}"#))
        }
    }
}

#[cfg(feature = "server")]
impl std::convert::TryFrom<HeaderValue> for header::IntoHeaderValue<GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner> {
    type Error = String;

    fn try_from(hdr_value: HeaderValue) -> std::result::Result<Self, Self::Error> {
        match hdr_value.to_str() {
             std::result::Result::Ok(value) => {
                    match <GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner as std::str::FromStr>::from_str(value) {
                        std::result::Result::Ok(value) => std::result::Result::Ok(header::IntoHeaderValue(value)),
                        std::result::Result::Err(err) => std::result::Result::Err(format!(r#"Unable to convert header value '{value}' into GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner - {err}"#))
                    }
             },
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Unable to convert header: {hdr_value:?} to string: {e}"#))
        }
    }
}



#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, validator::Validate)]
#[cfg_attr(feature = "conversion", derive(frunk::LabelledGeneric))]
pub struct LearnerProfile {
    #[serde(rename = "learningPurpose")]
          #[validate(custom(function = "check_xss_string"))]
    pub learning_purpose: String,

    #[serde(rename = "targetLevel")]
          #[validate(custom(function = "check_xss_string"))]
    pub target_level: String,

    #[serde(rename = "deadline")]
          #[validate(custom(function = "check_xss_string"))]
    pub deadline: String,

    #[serde(rename = "interests")]
          #[validate(custom(function = "check_xss_string"))]
    pub interests: String,

    #[serde(rename = "favoriteContent")]
          #[validate(custom(function = "check_xss_string"))]
    pub favorite_content: String,

    #[serde(rename = "dailyScenes")]
          #[validate(custom(function = "check_xss_string"))]
    pub daily_scenes: String,

    #[serde(rename = "englishUseCases")]
          #[validate(custom(function = "check_xss_string"))]
    pub english_use_cases: String,

    #[serde(rename = "weakPoints")]
          #[validate(custom(function = "check_xss_string"))]
    pub weak_points: String,

    #[serde(rename = "vocabularyFocus")]
          #[validate(custom(function = "check_xss_string"))]
    pub vocabulary_focus: String,

    #[serde(rename = "updatedAt")]
    #[serde(skip_serializing_if="Option::is_none")]
    pub updated_at: Option<chrono::DateTime::<chrono::Utc>>,

}



impl LearnerProfile {
    #[allow(clippy::new_without_default, clippy::too_many_arguments)]
    pub fn new(learning_purpose: String, target_level: String, deadline: String, interests: String, favorite_content: String, daily_scenes: String, english_use_cases: String, weak_points: String, vocabulary_focus: String, ) -> LearnerProfile {
        LearnerProfile {
 learning_purpose,
 target_level,
 deadline,
 interests,
 favorite_content,
 daily_scenes,
 english_use_cases,
 weak_points,
 vocabulary_focus,
 updated_at: None,
        }
    }
}

/// Converts the LearnerProfile value to the Query Parameters representation (style=form, explode=false)
/// specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde serializer
impl std::fmt::Display for LearnerProfile {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let params: Vec<Option<String>> = vec![

            Some("learningPurpose".to_string()),
            Some(self.learning_purpose.to_string()),


            Some("targetLevel".to_string()),
            Some(self.target_level.to_string()),


            Some("deadline".to_string()),
            Some(self.deadline.to_string()),


            Some("interests".to_string()),
            Some(self.interests.to_string()),


            Some("favoriteContent".to_string()),
            Some(self.favorite_content.to_string()),


            Some("dailyScenes".to_string()),
            Some(self.daily_scenes.to_string()),


            Some("englishUseCases".to_string()),
            Some(self.english_use_cases.to_string()),


            Some("weakPoints".to_string()),
            Some(self.weak_points.to_string()),


            Some("vocabularyFocus".to_string()),
            Some(self.vocabulary_focus.to_string()),

            // Skipping updatedAt in query parameter serialization

        ];

        write!(f, "{}", params.into_iter().flatten().collect::<Vec<_>>().join(","))
    }
}

/// Converts Query Parameters representation (style=form, explode=false) to a LearnerProfile value
/// as specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde deserializer
impl std::str::FromStr for LearnerProfile {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        /// An intermediate representation of the struct to use for parsing.
        #[derive(Default)]
        #[allow(dead_code)]
        struct IntermediateRep {
            pub learning_purpose: Vec<String>,
            pub target_level: Vec<String>,
            pub deadline: Vec<String>,
            pub interests: Vec<String>,
            pub favorite_content: Vec<String>,
            pub daily_scenes: Vec<String>,
            pub english_use_cases: Vec<String>,
            pub weak_points: Vec<String>,
            pub vocabulary_focus: Vec<String>,
            pub updated_at: Vec<chrono::DateTime::<chrono::Utc>>,
        }

        let mut intermediate_rep = IntermediateRep::default();

        // Parse into intermediate representation
        let mut string_iter = s.split(',');
        let mut key_result = string_iter.next();

        while key_result.is_some() {
            let val = match string_iter.next() {
                Some(x) => x,
                None => return std::result::Result::Err("Missing value while parsing LearnerProfile".to_string())
            };

            if let Some(key) = key_result {
                #[allow(clippy::match_single_binding)]
                match key {
                    #[allow(clippy::redundant_clone)]
                    "learningPurpose" => intermediate_rep.learning_purpose.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "targetLevel" => intermediate_rep.target_level.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "deadline" => intermediate_rep.deadline.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "interests" => intermediate_rep.interests.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "favoriteContent" => intermediate_rep.favorite_content.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "dailyScenes" => intermediate_rep.daily_scenes.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "englishUseCases" => intermediate_rep.english_use_cases.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "weakPoints" => intermediate_rep.weak_points.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "vocabularyFocus" => intermediate_rep.vocabulary_focus.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "updatedAt" => intermediate_rep.updated_at.push(<chrono::DateTime::<chrono::Utc> as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    _ => return std::result::Result::Err("Unexpected key while parsing LearnerProfile".to_string())
                }
            }

            // Get the next key
            key_result = string_iter.next();
        }

        // Use the intermediate representation to return the struct
        std::result::Result::Ok(LearnerProfile {
            learning_purpose: intermediate_rep.learning_purpose.into_iter().next().ok_or_else(|| "learningPurpose missing in LearnerProfile".to_string())?,
            target_level: intermediate_rep.target_level.into_iter().next().ok_or_else(|| "targetLevel missing in LearnerProfile".to_string())?,
            deadline: intermediate_rep.deadline.into_iter().next().ok_or_else(|| "deadline missing in LearnerProfile".to_string())?,
            interests: intermediate_rep.interests.into_iter().next().ok_or_else(|| "interests missing in LearnerProfile".to_string())?,
            favorite_content: intermediate_rep.favorite_content.into_iter().next().ok_or_else(|| "favoriteContent missing in LearnerProfile".to_string())?,
            daily_scenes: intermediate_rep.daily_scenes.into_iter().next().ok_or_else(|| "dailyScenes missing in LearnerProfile".to_string())?,
            english_use_cases: intermediate_rep.english_use_cases.into_iter().next().ok_or_else(|| "englishUseCases missing in LearnerProfile".to_string())?,
            weak_points: intermediate_rep.weak_points.into_iter().next().ok_or_else(|| "weakPoints missing in LearnerProfile".to_string())?,
            vocabulary_focus: intermediate_rep.vocabulary_focus.into_iter().next().ok_or_else(|| "vocabularyFocus missing in LearnerProfile".to_string())?,
            updated_at: intermediate_rep.updated_at.into_iter().next(),
        })
    }
}

// Methods for converting between header::IntoHeaderValue<LearnerProfile> and HeaderValue

#[cfg(feature = "server")]
impl std::convert::TryFrom<header::IntoHeaderValue<LearnerProfile>> for HeaderValue {
    type Error = String;

    fn try_from(hdr_value: header::IntoHeaderValue<LearnerProfile>) -> std::result::Result<Self, Self::Error> {
        let hdr_value = hdr_value.to_string();
        match HeaderValue::from_str(&hdr_value) {
             std::result::Result::Ok(value) => std::result::Result::Ok(value),
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Invalid header value for LearnerProfile - value: {hdr_value} is invalid {e}"#))
        }
    }
}

#[cfg(feature = "server")]
impl std::convert::TryFrom<HeaderValue> for header::IntoHeaderValue<LearnerProfile> {
    type Error = String;

    fn try_from(hdr_value: HeaderValue) -> std::result::Result<Self, Self::Error> {
        match hdr_value.to_str() {
             std::result::Result::Ok(value) => {
                    match <LearnerProfile as std::str::FromStr>::from_str(value) {
                        std::result::Result::Ok(value) => std::result::Result::Ok(header::IntoHeaderValue(value)),
                        std::result::Result::Err(err) => std::result::Result::Err(format!(r#"Unable to convert header value '{value}' into LearnerProfile - {err}"#))
                    }
             },
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Unable to convert header: {hdr_value:?} to string: {e}"#))
        }
    }
}



#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, validator::Validate)]
#[cfg_attr(feature = "conversion", derive(frunk::LabelledGeneric))]
pub struct LearningPath {
    #[serde(rename = "id")]
          #[validate(custom(function = "check_xss_string"))]
    pub id: String,

    #[serde(rename = "title")]
          #[validate(custom(function = "check_xss_string"))]
    pub title: String,

    #[serde(rename = "tagline")]
          #[validate(custom(function = "check_xss_string"))]
    pub tagline: String,

    #[serde(rename = "description")]
          #[validate(custom(function = "check_xss_string"))]
    pub description: String,

    #[serde(rename = "audience")]
          #[validate(custom(function = "check_xss_string"))]
    pub audience: String,

    #[serde(rename = "courses")]
          #[validate(nested)]
    pub courses: Vec<models::GetLearningPaths200ResponseInnerCoursesInner>,

}



impl LearningPath {
    #[allow(clippy::new_without_default, clippy::too_many_arguments)]
    pub fn new(id: String, title: String, tagline: String, description: String, audience: String, courses: Vec<models::GetLearningPaths200ResponseInnerCoursesInner>, ) -> LearningPath {
        LearningPath {
 id,
 title,
 tagline,
 description,
 audience,
 courses,
        }
    }
}

/// Converts the LearningPath value to the Query Parameters representation (style=form, explode=false)
/// specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde serializer
impl std::fmt::Display for LearningPath {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let params: Vec<Option<String>> = vec![

            Some("id".to_string()),
            Some(self.id.to_string()),


            Some("title".to_string()),
            Some(self.title.to_string()),


            Some("tagline".to_string()),
            Some(self.tagline.to_string()),


            Some("description".to_string()),
            Some(self.description.to_string()),


            Some("audience".to_string()),
            Some(self.audience.to_string()),

            // Skipping courses in query parameter serialization

        ];

        write!(f, "{}", params.into_iter().flatten().collect::<Vec<_>>().join(","))
    }
}

/// Converts Query Parameters representation (style=form, explode=false) to a LearningPath value
/// as specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde deserializer
impl std::str::FromStr for LearningPath {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        /// An intermediate representation of the struct to use for parsing.
        #[derive(Default)]
        #[allow(dead_code)]
        struct IntermediateRep {
            pub id: Vec<String>,
            pub title: Vec<String>,
            pub tagline: Vec<String>,
            pub description: Vec<String>,
            pub audience: Vec<String>,
            pub courses: Vec<Vec<models::GetLearningPaths200ResponseInnerCoursesInner>>,
        }

        let mut intermediate_rep = IntermediateRep::default();

        // Parse into intermediate representation
        let mut string_iter = s.split(',');
        let mut key_result = string_iter.next();

        while key_result.is_some() {
            let val = match string_iter.next() {
                Some(x) => x,
                None => return std::result::Result::Err("Missing value while parsing LearningPath".to_string())
            };

            if let Some(key) = key_result {
                #[allow(clippy::match_single_binding)]
                match key {
                    #[allow(clippy::redundant_clone)]
                    "id" => intermediate_rep.id.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "title" => intermediate_rep.title.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "tagline" => intermediate_rep.tagline.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "description" => intermediate_rep.description.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "audience" => intermediate_rep.audience.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    "courses" => return std::result::Result::Err("Parsing a container in this style is not supported in LearningPath".to_string()),
                    _ => return std::result::Result::Err("Unexpected key while parsing LearningPath".to_string())
                }
            }

            // Get the next key
            key_result = string_iter.next();
        }

        // Use the intermediate representation to return the struct
        std::result::Result::Ok(LearningPath {
            id: intermediate_rep.id.into_iter().next().ok_or_else(|| "id missing in LearningPath".to_string())?,
            title: intermediate_rep.title.into_iter().next().ok_or_else(|| "title missing in LearningPath".to_string())?,
            tagline: intermediate_rep.tagline.into_iter().next().ok_or_else(|| "tagline missing in LearningPath".to_string())?,
            description: intermediate_rep.description.into_iter().next().ok_or_else(|| "description missing in LearningPath".to_string())?,
            audience: intermediate_rep.audience.into_iter().next().ok_or_else(|| "audience missing in LearningPath".to_string())?,
            courses: intermediate_rep.courses.into_iter().next().ok_or_else(|| "courses missing in LearningPath".to_string())?,
        })
    }
}

// Methods for converting between header::IntoHeaderValue<LearningPath> and HeaderValue

#[cfg(feature = "server")]
impl std::convert::TryFrom<header::IntoHeaderValue<LearningPath>> for HeaderValue {
    type Error = String;

    fn try_from(hdr_value: header::IntoHeaderValue<LearningPath>) -> std::result::Result<Self, Self::Error> {
        let hdr_value = hdr_value.to_string();
        match HeaderValue::from_str(&hdr_value) {
             std::result::Result::Ok(value) => std::result::Result::Ok(value),
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Invalid header value for LearningPath - value: {hdr_value} is invalid {e}"#))
        }
    }
}

#[cfg(feature = "server")]
impl std::convert::TryFrom<HeaderValue> for header::IntoHeaderValue<LearningPath> {
    type Error = String;

    fn try_from(hdr_value: HeaderValue) -> std::result::Result<Self, Self::Error> {
        match hdr_value.to_str() {
             std::result::Result::Ok(value) => {
                    match <LearningPath as std::str::FromStr>::from_str(value) {
                        std::result::Result::Ok(value) => std::result::Result::Ok(header::IntoHeaderValue(value)),
                        std::result::Result::Err(err) => std::result::Result::Err(format!(r#"Unable to convert header value '{value}' into LearningPath - {err}"#))
                    }
             },
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Unable to convert header: {hdr_value:?} to string: {e}"#))
        }
    }
}



#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, validator::Validate)]
#[cfg_attr(feature = "conversion", derive(frunk::LabelledGeneric))]
pub struct PutLearnerProfileRequest {
    #[serde(rename = "learningPurpose")]
          #[validate(custom(function = "check_xss_string"))]
    pub learning_purpose: String,

    #[serde(rename = "targetLevel")]
          #[validate(custom(function = "check_xss_string"))]
    pub target_level: String,

    #[serde(rename = "deadline")]
          #[validate(custom(function = "check_xss_string"))]
    pub deadline: String,

    #[serde(rename = "interests")]
          #[validate(custom(function = "check_xss_string"))]
    pub interests: String,

    #[serde(rename = "favoriteContent")]
          #[validate(custom(function = "check_xss_string"))]
    pub favorite_content: String,

    #[serde(rename = "dailyScenes")]
          #[validate(custom(function = "check_xss_string"))]
    pub daily_scenes: String,

    #[serde(rename = "englishUseCases")]
          #[validate(custom(function = "check_xss_string"))]
    pub english_use_cases: String,

    #[serde(rename = "weakPoints")]
          #[validate(custom(function = "check_xss_string"))]
    pub weak_points: String,

    #[serde(rename = "vocabularyFocus")]
          #[validate(custom(function = "check_xss_string"))]
    pub vocabulary_focus: String,

    #[serde(rename = "updatedAt")]
    #[serde(skip_serializing_if="Option::is_none")]
    pub updated_at: Option<chrono::DateTime::<chrono::Utc>>,

}



impl PutLearnerProfileRequest {
    #[allow(clippy::new_without_default, clippy::too_many_arguments)]
    pub fn new(learning_purpose: String, target_level: String, deadline: String, interests: String, favorite_content: String, daily_scenes: String, english_use_cases: String, weak_points: String, vocabulary_focus: String, ) -> PutLearnerProfileRequest {
        PutLearnerProfileRequest {
 learning_purpose,
 target_level,
 deadline,
 interests,
 favorite_content,
 daily_scenes,
 english_use_cases,
 weak_points,
 vocabulary_focus,
 updated_at: None,
        }
    }
}

/// Converts the PutLearnerProfileRequest value to the Query Parameters representation (style=form, explode=false)
/// specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde serializer
impl std::fmt::Display for PutLearnerProfileRequest {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let params: Vec<Option<String>> = vec![

            Some("learningPurpose".to_string()),
            Some(self.learning_purpose.to_string()),


            Some("targetLevel".to_string()),
            Some(self.target_level.to_string()),


            Some("deadline".to_string()),
            Some(self.deadline.to_string()),


            Some("interests".to_string()),
            Some(self.interests.to_string()),


            Some("favoriteContent".to_string()),
            Some(self.favorite_content.to_string()),


            Some("dailyScenes".to_string()),
            Some(self.daily_scenes.to_string()),


            Some("englishUseCases".to_string()),
            Some(self.english_use_cases.to_string()),


            Some("weakPoints".to_string()),
            Some(self.weak_points.to_string()),


            Some("vocabularyFocus".to_string()),
            Some(self.vocabulary_focus.to_string()),

            // Skipping updatedAt in query parameter serialization

        ];

        write!(f, "{}", params.into_iter().flatten().collect::<Vec<_>>().join(","))
    }
}

/// Converts Query Parameters representation (style=form, explode=false) to a PutLearnerProfileRequest value
/// as specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde deserializer
impl std::str::FromStr for PutLearnerProfileRequest {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        /// An intermediate representation of the struct to use for parsing.
        #[derive(Default)]
        #[allow(dead_code)]
        struct IntermediateRep {
            pub learning_purpose: Vec<String>,
            pub target_level: Vec<String>,
            pub deadline: Vec<String>,
            pub interests: Vec<String>,
            pub favorite_content: Vec<String>,
            pub daily_scenes: Vec<String>,
            pub english_use_cases: Vec<String>,
            pub weak_points: Vec<String>,
            pub vocabulary_focus: Vec<String>,
            pub updated_at: Vec<chrono::DateTime::<chrono::Utc>>,
        }

        let mut intermediate_rep = IntermediateRep::default();

        // Parse into intermediate representation
        let mut string_iter = s.split(',');
        let mut key_result = string_iter.next();

        while key_result.is_some() {
            let val = match string_iter.next() {
                Some(x) => x,
                None => return std::result::Result::Err("Missing value while parsing PutLearnerProfileRequest".to_string())
            };

            if let Some(key) = key_result {
                #[allow(clippy::match_single_binding)]
                match key {
                    #[allow(clippy::redundant_clone)]
                    "learningPurpose" => intermediate_rep.learning_purpose.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "targetLevel" => intermediate_rep.target_level.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "deadline" => intermediate_rep.deadline.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "interests" => intermediate_rep.interests.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "favoriteContent" => intermediate_rep.favorite_content.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "dailyScenes" => intermediate_rep.daily_scenes.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "englishUseCases" => intermediate_rep.english_use_cases.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "weakPoints" => intermediate_rep.weak_points.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "vocabularyFocus" => intermediate_rep.vocabulary_focus.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "updatedAt" => intermediate_rep.updated_at.push(<chrono::DateTime::<chrono::Utc> as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    _ => return std::result::Result::Err("Unexpected key while parsing PutLearnerProfileRequest".to_string())
                }
            }

            // Get the next key
            key_result = string_iter.next();
        }

        // Use the intermediate representation to return the struct
        std::result::Result::Ok(PutLearnerProfileRequest {
            learning_purpose: intermediate_rep.learning_purpose.into_iter().next().ok_or_else(|| "learningPurpose missing in PutLearnerProfileRequest".to_string())?,
            target_level: intermediate_rep.target_level.into_iter().next().ok_or_else(|| "targetLevel missing in PutLearnerProfileRequest".to_string())?,
            deadline: intermediate_rep.deadline.into_iter().next().ok_or_else(|| "deadline missing in PutLearnerProfileRequest".to_string())?,
            interests: intermediate_rep.interests.into_iter().next().ok_or_else(|| "interests missing in PutLearnerProfileRequest".to_string())?,
            favorite_content: intermediate_rep.favorite_content.into_iter().next().ok_or_else(|| "favoriteContent missing in PutLearnerProfileRequest".to_string())?,
            daily_scenes: intermediate_rep.daily_scenes.into_iter().next().ok_or_else(|| "dailyScenes missing in PutLearnerProfileRequest".to_string())?,
            english_use_cases: intermediate_rep.english_use_cases.into_iter().next().ok_or_else(|| "englishUseCases missing in PutLearnerProfileRequest".to_string())?,
            weak_points: intermediate_rep.weak_points.into_iter().next().ok_or_else(|| "weakPoints missing in PutLearnerProfileRequest".to_string())?,
            vocabulary_focus: intermediate_rep.vocabulary_focus.into_iter().next().ok_or_else(|| "vocabularyFocus missing in PutLearnerProfileRequest".to_string())?,
            updated_at: intermediate_rep.updated_at.into_iter().next(),
        })
    }
}

// Methods for converting between header::IntoHeaderValue<PutLearnerProfileRequest> and HeaderValue

#[cfg(feature = "server")]
impl std::convert::TryFrom<header::IntoHeaderValue<PutLearnerProfileRequest>> for HeaderValue {
    type Error = String;

    fn try_from(hdr_value: header::IntoHeaderValue<PutLearnerProfileRequest>) -> std::result::Result<Self, Self::Error> {
        let hdr_value = hdr_value.to_string();
        match HeaderValue::from_str(&hdr_value) {
             std::result::Result::Ok(value) => std::result::Result::Ok(value),
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Invalid header value for PutLearnerProfileRequest - value: {hdr_value} is invalid {e}"#))
        }
    }
}

#[cfg(feature = "server")]
impl std::convert::TryFrom<HeaderValue> for header::IntoHeaderValue<PutLearnerProfileRequest> {
    type Error = String;

    fn try_from(hdr_value: HeaderValue) -> std::result::Result<Self, Self::Error> {
        match hdr_value.to_str() {
             std::result::Result::Ok(value) => {
                    match <PutLearnerProfileRequest as std::str::FromStr>::from_str(value) {
                        std::result::Result::Ok(value) => std::result::Result::Ok(header::IntoHeaderValue(value)),
                        std::result::Result::Err(err) => std::result::Result::Err(format!(r#"Unable to convert header value '{value}' into PutLearnerProfileRequest - {err}"#))
                    }
             },
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Unable to convert header: {hdr_value:?} to string: {e}"#))
        }
    }
}



#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, validator::Validate)]
#[cfg_attr(feature = "conversion", derive(frunk::LabelledGeneric))]
pub struct Unit {
    #[serde(rename = "id")]
          #[validate(custom(function = "check_xss_string"))]
    pub id: String,

    #[serde(rename = "title")]
          #[validate(custom(function = "check_xss_string"))]
    pub title: String,

    #[serde(rename = "description")]
          #[validate(custom(function = "check_xss_string"))]
    pub description: String,

    #[serde(rename = "targetSkill")]
          #[validate(custom(function = "check_xss_string"))]
    pub target_skill: String,

    #[serde(rename = "durationMinutes")]
    #[validate(
            range(min = 0u32),
    )]
    pub duration_minutes: u32,

    #[serde(rename = "vocabularyEntries")]
          #[validate(nested)]
    pub vocabulary_entries: Vec<models::GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner>,

}



impl Unit {
    #[allow(clippy::new_without_default, clippy::too_many_arguments)]
    pub fn new(id: String, title: String, description: String, target_skill: String, duration_minutes: u32, vocabulary_entries: Vec<models::GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner>, ) -> Unit {
        Unit {
 id,
 title,
 description,
 target_skill,
 duration_minutes,
 vocabulary_entries,
        }
    }
}

/// Converts the Unit value to the Query Parameters representation (style=form, explode=false)
/// specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde serializer
impl std::fmt::Display for Unit {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let params: Vec<Option<String>> = vec![

            Some("id".to_string()),
            Some(self.id.to_string()),


            Some("title".to_string()),
            Some(self.title.to_string()),


            Some("description".to_string()),
            Some(self.description.to_string()),


            Some("targetSkill".to_string()),
            Some(self.target_skill.to_string()),


            Some("durationMinutes".to_string()),
            Some(self.duration_minutes.to_string()),

            // Skipping vocabularyEntries in query parameter serialization

        ];

        write!(f, "{}", params.into_iter().flatten().collect::<Vec<_>>().join(","))
    }
}

/// Converts Query Parameters representation (style=form, explode=false) to a Unit value
/// as specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde deserializer
impl std::str::FromStr for Unit {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        /// An intermediate representation of the struct to use for parsing.
        #[derive(Default)]
        #[allow(dead_code)]
        struct IntermediateRep {
            pub id: Vec<String>,
            pub title: Vec<String>,
            pub description: Vec<String>,
            pub target_skill: Vec<String>,
            pub duration_minutes: Vec<u32>,
            pub vocabulary_entries: Vec<Vec<models::GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInner>>,
        }

        let mut intermediate_rep = IntermediateRep::default();

        // Parse into intermediate representation
        let mut string_iter = s.split(',');
        let mut key_result = string_iter.next();

        while key_result.is_some() {
            let val = match string_iter.next() {
                Some(x) => x,
                None => return std::result::Result::Err("Missing value while parsing Unit".to_string())
            };

            if let Some(key) = key_result {
                #[allow(clippy::match_single_binding)]
                match key {
                    #[allow(clippy::redundant_clone)]
                    "id" => intermediate_rep.id.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "title" => intermediate_rep.title.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "description" => intermediate_rep.description.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "targetSkill" => intermediate_rep.target_skill.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "durationMinutes" => intermediate_rep.duration_minutes.push(<u32 as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    "vocabularyEntries" => return std::result::Result::Err("Parsing a container in this style is not supported in Unit".to_string()),
                    _ => return std::result::Result::Err("Unexpected key while parsing Unit".to_string())
                }
            }

            // Get the next key
            key_result = string_iter.next();
        }

        // Use the intermediate representation to return the struct
        std::result::Result::Ok(Unit {
            id: intermediate_rep.id.into_iter().next().ok_or_else(|| "id missing in Unit".to_string())?,
            title: intermediate_rep.title.into_iter().next().ok_or_else(|| "title missing in Unit".to_string())?,
            description: intermediate_rep.description.into_iter().next().ok_or_else(|| "description missing in Unit".to_string())?,
            target_skill: intermediate_rep.target_skill.into_iter().next().ok_or_else(|| "targetSkill missing in Unit".to_string())?,
            duration_minutes: intermediate_rep.duration_minutes.into_iter().next().ok_or_else(|| "durationMinutes missing in Unit".to_string())?,
            vocabulary_entries: intermediate_rep.vocabulary_entries.into_iter().next().ok_or_else(|| "vocabularyEntries missing in Unit".to_string())?,
        })
    }
}

// Methods for converting between header::IntoHeaderValue<Unit> and HeaderValue

#[cfg(feature = "server")]
impl std::convert::TryFrom<header::IntoHeaderValue<Unit>> for HeaderValue {
    type Error = String;

    fn try_from(hdr_value: header::IntoHeaderValue<Unit>) -> std::result::Result<Self, Self::Error> {
        let hdr_value = hdr_value.to_string();
        match HeaderValue::from_str(&hdr_value) {
             std::result::Result::Ok(value) => std::result::Result::Ok(value),
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Invalid header value for Unit - value: {hdr_value} is invalid {e}"#))
        }
    }
}

#[cfg(feature = "server")]
impl std::convert::TryFrom<HeaderValue> for header::IntoHeaderValue<Unit> {
    type Error = String;

    fn try_from(hdr_value: HeaderValue) -> std::result::Result<Self, Self::Error> {
        match hdr_value.to_str() {
             std::result::Result::Ok(value) => {
                    match <Unit as std::str::FromStr>::from_str(value) {
                        std::result::Result::Ok(value) => std::result::Result::Ok(header::IntoHeaderValue(value)),
                        std::result::Result::Err(err) => std::result::Result::Err(format!(r#"Unable to convert header value '{value}' into Unit - {err}"#))
                    }
             },
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Unable to convert header: {hdr_value:?} to string: {e}"#))
        }
    }
}



#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, validator::Validate)]
#[cfg_attr(feature = "conversion", derive(frunk::LabelledGeneric))]
pub struct VocabularyEntry {
    #[serde(rename = "id")]
          #[validate(custom(function = "check_xss_string"))]
    pub id: String,

    #[serde(rename = "targetText")]
          #[validate(custom(function = "check_xss_string"))]
    pub target_text: String,

    /// Note: inline enums are not fully supported by openapi-generator
    #[serde(rename = "kind")]
          #[validate(custom(function = "check_xss_string"))]
    pub kind: String,

    #[serde(rename = "sourceMeaning")]
          #[validate(custom(function = "check_xss_string"))]
    pub source_meaning: String,

    #[serde(rename = "targetExampleSentence")]
          #[validate(custom(function = "check_xss_string"))]
    pub target_example_sentence: String,

    #[serde(rename = "sourceExampleTranslation")]
          #[validate(custom(function = "check_xss_string"))]
    pub source_example_translation: String,

    /// Note: inline enums are not fully supported by openapi-generator
    #[serde(rename = "progressStatus")]
          #[validate(custom(function = "check_xss_string"))]
    #[serde(skip_serializing_if="Option::is_none")]
    pub progress_status: Option<String>,

    #[serde(rename = "exampleSentences")]
          #[validate(nested)]
    #[serde(skip_serializing_if="Option::is_none")]
    pub example_sentences: Option<Vec<models::GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner>>,

}



impl VocabularyEntry {
    #[allow(clippy::new_without_default, clippy::too_many_arguments)]
    pub fn new(id: String, target_text: String, kind: String, source_meaning: String, target_example_sentence: String, source_example_translation: String, ) -> VocabularyEntry {
        VocabularyEntry {
 id,
 target_text,
 kind,
 source_meaning,
 target_example_sentence,
 source_example_translation,
 progress_status: None,
 example_sentences: None,
        }
    }
}

/// Converts the VocabularyEntry value to the Query Parameters representation (style=form, explode=false)
/// specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde serializer
impl std::fmt::Display for VocabularyEntry {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let params: Vec<Option<String>> = vec![

            Some("id".to_string()),
            Some(self.id.to_string()),


            Some("targetText".to_string()),
            Some(self.target_text.to_string()),


            Some("kind".to_string()),
            Some(self.kind.to_string()),


            Some("sourceMeaning".to_string()),
            Some(self.source_meaning.to_string()),


            Some("targetExampleSentence".to_string()),
            Some(self.target_example_sentence.to_string()),


            Some("sourceExampleTranslation".to_string()),
            Some(self.source_example_translation.to_string()),


            self.progress_status.as_ref().map(|progress_status| {
                [
                    "progressStatus".to_string(),
                    progress_status.to_string(),
                ].join(",")
            }),

            // Skipping exampleSentences in query parameter serialization

        ];

        write!(f, "{}", params.into_iter().flatten().collect::<Vec<_>>().join(","))
    }
}

/// Converts Query Parameters representation (style=form, explode=false) to a VocabularyEntry value
/// as specified in https://swagger.io/docs/specification/serialization/
/// Should be implemented in a serde deserializer
impl std::str::FromStr for VocabularyEntry {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        /// An intermediate representation of the struct to use for parsing.
        #[derive(Default)]
        #[allow(dead_code)]
        struct IntermediateRep {
            pub id: Vec<String>,
            pub target_text: Vec<String>,
            pub kind: Vec<String>,
            pub source_meaning: Vec<String>,
            pub target_example_sentence: Vec<String>,
            pub source_example_translation: Vec<String>,
            pub progress_status: Vec<String>,
            pub example_sentences: Vec<Vec<models::GetLearningPaths200ResponseInnerCoursesInnerUnitsInnerVocabularyEntriesInnerExampleSentencesInner>>,
        }

        let mut intermediate_rep = IntermediateRep::default();

        // Parse into intermediate representation
        let mut string_iter = s.split(',');
        let mut key_result = string_iter.next();

        while key_result.is_some() {
            let val = match string_iter.next() {
                Some(x) => x,
                None => return std::result::Result::Err("Missing value while parsing VocabularyEntry".to_string())
            };

            if let Some(key) = key_result {
                #[allow(clippy::match_single_binding)]
                match key {
                    #[allow(clippy::redundant_clone)]
                    "id" => intermediate_rep.id.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "targetText" => intermediate_rep.target_text.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "kind" => intermediate_rep.kind.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "sourceMeaning" => intermediate_rep.source_meaning.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "targetExampleSentence" => intermediate_rep.target_example_sentence.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "sourceExampleTranslation" => intermediate_rep.source_example_translation.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    #[allow(clippy::redundant_clone)]
                    "progressStatus" => intermediate_rep.progress_status.push(<String as std::str::FromStr>::from_str(val).map_err(|x| x.to_string())?),
                    "exampleSentences" => return std::result::Result::Err("Parsing a container in this style is not supported in VocabularyEntry".to_string()),
                    _ => return std::result::Result::Err("Unexpected key while parsing VocabularyEntry".to_string())
                }
            }

            // Get the next key
            key_result = string_iter.next();
        }

        // Use the intermediate representation to return the struct
        std::result::Result::Ok(VocabularyEntry {
            id: intermediate_rep.id.into_iter().next().ok_or_else(|| "id missing in VocabularyEntry".to_string())?,
            target_text: intermediate_rep.target_text.into_iter().next().ok_or_else(|| "targetText missing in VocabularyEntry".to_string())?,
            kind: intermediate_rep.kind.into_iter().next().ok_or_else(|| "kind missing in VocabularyEntry".to_string())?,
            source_meaning: intermediate_rep.source_meaning.into_iter().next().ok_or_else(|| "sourceMeaning missing in VocabularyEntry".to_string())?,
            target_example_sentence: intermediate_rep.target_example_sentence.into_iter().next().ok_or_else(|| "targetExampleSentence missing in VocabularyEntry".to_string())?,
            source_example_translation: intermediate_rep.source_example_translation.into_iter().next().ok_or_else(|| "sourceExampleTranslation missing in VocabularyEntry".to_string())?,
            progress_status: intermediate_rep.progress_status.into_iter().next(),
            example_sentences: intermediate_rep.example_sentences.into_iter().next(),
        })
    }
}

// Methods for converting between header::IntoHeaderValue<VocabularyEntry> and HeaderValue

#[cfg(feature = "server")]
impl std::convert::TryFrom<header::IntoHeaderValue<VocabularyEntry>> for HeaderValue {
    type Error = String;

    fn try_from(hdr_value: header::IntoHeaderValue<VocabularyEntry>) -> std::result::Result<Self, Self::Error> {
        let hdr_value = hdr_value.to_string();
        match HeaderValue::from_str(&hdr_value) {
             std::result::Result::Ok(value) => std::result::Result::Ok(value),
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Invalid header value for VocabularyEntry - value: {hdr_value} is invalid {e}"#))
        }
    }
}

#[cfg(feature = "server")]
impl std::convert::TryFrom<HeaderValue> for header::IntoHeaderValue<VocabularyEntry> {
    type Error = String;

    fn try_from(hdr_value: HeaderValue) -> std::result::Result<Self, Self::Error> {
        match hdr_value.to_str() {
             std::result::Result::Ok(value) => {
                    match <VocabularyEntry as std::str::FromStr>::from_str(value) {
                        std::result::Result::Ok(value) => std::result::Result::Ok(header::IntoHeaderValue(value)),
                        std::result::Result::Err(err) => std::result::Result::Err(format!(r#"Unable to convert header value '{value}' into VocabularyEntry - {err}"#))
                    }
             },
             std::result::Result::Err(e) => std::result::Result::Err(format!(r#"Unable to convert header: {hdr_value:?} to string: {e}"#))
        }
    }
}


