use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LearnerProfile {
    pub user_id: Uuid,
    pub learning_purpose: String,
    pub target_level: String,
    pub deadline: String,
    pub interests: String,
    pub favorite_content: String,
    pub daily_scenes: String,
    pub english_use_cases: String,
    pub weak_points: String,
    pub vocabulary_focus: String,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct LearnerProfileInput {
    pub learning_purpose: String,
    pub target_level: String,
    pub deadline: String,
    pub interests: String,
    pub favorite_content: String,
    pub daily_scenes: String,
    pub english_use_cases: String,
    pub weak_points: String,
    pub vocabulary_focus: String,
}

impl LearnerProfile {
    pub fn new(user_id: Uuid, input: LearnerProfileInput) -> Self {
        Self {
            user_id,
            learning_purpose: input.learning_purpose,
            target_level: input.target_level,
            deadline: input.deadline,
            interests: input.interests,
            favorite_content: input.favorite_content,
            daily_scenes: input.daily_scenes,
            english_use_cases: input.english_use_cases,
            weak_points: input.weak_points,
            vocabulary_focus: input.vocabulary_focus,
            updated_at: Utc::now(),
        }
    }

    pub fn context_summary(&self) -> String {
        [
            ("Learning purpose", self.learning_purpose.as_str()),
            ("Target level", self.target_level.as_str()),
            ("Target timing", self.deadline.as_str()),
            ("Interests", self.interests.as_str()),
            ("Favorite content", self.favorite_content.as_str()),
            ("Daily scenes", self.daily_scenes.as_str()),
            ("English use cases", self.english_use_cases.as_str()),
            ("Weak points", self.weak_points.as_str()),
            ("Vocabulary focus", self.vocabulary_focus.as_str()),
        ]
        .into_iter()
        .filter_map(|(label, value)| {
            let value = value.trim();

            if value.is_empty() {
                None
            } else {
                Some(format!("{label}: {value}"))
            }
        })
        .collect::<Vec<_>>()
        .join("\n")
    }
}
