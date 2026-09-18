import unittest

from core.pipeline import (
    _collect_study_items_from_sentences,
    _limit_study_items_by_coverage,
    _parse_vocabulary_entry,
    _resolve_vocabulary_coverage_percent,
    _target_study_item_count,
)


class VocabularyCoverageTests(unittest.TestCase):
    def test_parse_vocabulary_entry_with_part_of_speech(self) -> None:
        parsed = _parse_vocabulary_entry(
            "divorce [noun]: ここでは離婚という意味で、法的な手続きを指す"
        )
        self.assertEqual(
            parsed,
            (
                "divorce",
                "noun",
                "ここでは離婚という意味で、法的な手続きを指す",
            ),
        )

    def test_parse_vocabulary_entry_without_part_of_speech(self) -> None:
        parsed = _parse_vocabulary_entry("obtain: ここでは取得する")
        self.assertEqual(parsed, ("obtain", "", "ここでは取得する"))

    def test_collect_study_items_merges_duplicates_and_preserves_order(self) -> None:
        indexed_sentences = [
            {
                "id": "s1",
                "index": 0,
                "text": "They decided to divorce.",
                "analysis": {
                    "vocabulary": [
                        "divorce [noun]: 離婚",
                        "decide [verb]: 決める",
                    ],
                },
            },
            {
                "id": "s2",
                "index": 1,
                "text": "The divorce was final.",
                "analysis": {
                    "vocabulary": [
                        "divorce [noun]: 離婚手続き",
                        "final [adjective]: 最終的な",
                    ],
                },
            },
        ]

        items = _collect_study_items_from_sentences(indexed_sentences)
        texts = [item["text"] for item in items]

        self.assertEqual(texts, ["decide", "divorce", "final"])
        divorce = next(item for item in items if item["text"] == "divorce")
        self.assertEqual(divorce["sentence_ids"], ["s1", "s2"])
        self.assertEqual(divorce["meaning"], "離婚")

    def test_target_study_item_count_uses_percentage_of_pool(self) -> None:
        self.assertEqual(_target_study_item_count(200, 8.0), 16)
        self.assertEqual(_target_study_item_count(0, 8.0), 1)

    def test_resolve_vocabulary_coverage_percent_prefers_request_value(self) -> None:
        self.assertEqual(_resolve_vocabulary_coverage_percent(12.0), 12.0)
        self.assertEqual(_resolve_vocabulary_coverage_percent(99.0), 50.0)
        self.assertEqual(_resolve_vocabulary_coverage_percent(0.5), 1.0)
        self.assertEqual(_resolve_vocabulary_coverage_percent(None), 8.0)

    def test_limit_study_items_by_coverage_trims_to_target_count(self) -> None:
        indexed_sentences = [
            {
                "id": f"s{index}",
                "index": index,
                "text": (
                    "Alpha beta gamma delta epsilon zeta eta theta iota kappa "
                    "lambda mu nu xi omicron."
                ),
                "analysis": {
                    "vocabulary": [
                        f"word{index}a [noun]: meaning {index}a",
                        f"word{index}b [verb]: meaning {index}b",
                    ],
                },
            }
            for index in range(5)
        ]

        candidates = _collect_study_items_from_sentences(indexed_sentences)
        limited, stats = _limit_study_items_by_coverage(candidates, indexed_sentences, 8.0)

        self.assertEqual(stats["coverage_percent"], 8.0)
        self.assertEqual(stats["candidate_count"], len(candidates))
        self.assertEqual(stats["item_count"], stats["target_count"])
        self.assertEqual(len(limited), stats["target_count"])

    def test_coverage_cap_changes_study_item_quantity_by_learner_band(self) -> None:
        indexed_sentences = [
            {
                "id": "s1",
                "index": 0,
                "text": (
                    "Alpha beta gamma delta epsilon zeta eta theta iota kappa "
                    "lambda mu nu xi omicron."
                ),
                "analysis": {
                    "vocabulary": [
                        "alpha [noun]: meaning",
                        "beta [noun]: meaning",
                        "gamma [noun]: meaning",
                        "delta [noun]: meaning",
                    ],
                },
            }
        ]
        candidates = _collect_study_items_from_sentences(indexed_sentences)

        beginner_items, beginner_stats = _limit_study_items_by_coverage(
            candidates, indexed_sentences, 18.0
        )
        advanced_items, advanced_stats = _limit_study_items_by_coverage(
            candidates, indexed_sentences, 7.0
        )

        self.assertGreater(beginner_stats["target_count"], advanced_stats["target_count"])
        self.assertGreater(len(beginner_items), len(advanced_items))


if __name__ == "__main__":
    unittest.main()
