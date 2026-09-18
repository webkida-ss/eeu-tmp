use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LearningPath {
    pub id: String,
    pub title: String,
    pub tagline: String,
    pub description: String,
    pub audience: String,
    pub courses: Vec<Course>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Course {
    pub id: String,
    pub title: String,
    pub level_label: String,
    pub description: String,
    pub outcome: String,
    pub estimated_hours: u32,
    pub units: Vec<Unit>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Unit {
    pub id: String,
    pub title: String,
    pub description: String,
    pub target_skill: String,
    pub duration_minutes: u32,
    pub vocabulary_entries: Vec<VocabularyEntry>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct VocabularyEntry {
    pub id: String,
    pub target_text: String,
    pub kind: VocabularyKind,
    pub source_meaning: String,
    pub target_example_sentence: String,
    pub source_example_translation: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub progress_status: Option<ProgressStatus>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub example_sentences: Vec<ExampleSentence>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum VocabularyKind {
    Word,
    Phrase,
    Idiom,
    PhrasalVerb,
    Expression,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum ProgressStatus {
    NotStarted,
    Learning,
    Remembered,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExampleSentence {
    pub id: String,
    pub target_text: String,
    pub target_sentence: String,
    pub source_translation: String,
    pub variant: ExampleSentenceVariant,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub personalization: Option<ExampleSentencePersonalization>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub usage_note: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum ExampleSentenceVariant {
    Curated,
    Personalized,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExampleSentencePersonalization {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub context_summary: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub personalized_from_user_context_at: Option<String>,
}
