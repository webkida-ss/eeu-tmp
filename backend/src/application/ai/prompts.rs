pub fn personalized_example_sentence_system_prompt() -> String {
    "You create one natural English example sentence for a learner. Return only the sentence."
        .to_string()
}

pub fn personalized_example_sentence_user_prompt(
    target_text: &str,
    user_context_summary: &str,
) -> String {
    format!(
        "Target text: {target_text}\nLearner context: {user_context_summary}\nCreate one useful sentence."
    )
}
