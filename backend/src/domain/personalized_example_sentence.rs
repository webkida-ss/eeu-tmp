use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PersonalizedExampleSentence {
    pub id: String,
    pub learner_id: Uuid,
    pub vocabulary_entry_id: String,
    pub target_text: String,
    pub target_sentence: String,
    pub source_translation: String,
    pub context_summary: String,
    pub profile_version: String,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}
