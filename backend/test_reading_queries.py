import unittest

from services.reading_queries import (
    build_vocabulary_book,
    get_preload_status,
    resolve_page_preload,
    to_preload_response,
)


class InMemoryPreloadRepository:
    def __init__(self, records):
        self.records = records

    def get_by_id(self, user_id, preload_id):
        return next(
            (
                record
                for record in self.records
                if record.get("user_id") == user_id and record.get("id") == preload_id
            ),
            None,
        )

    def get_by_page_url(self, user_id, page_url):
        return next(
            (
                record
                for record in self.records
                if record.get("user_id") == user_id and record.get("page_url") == page_url
            ),
            None,
        )

    def list_for_user(self, user_id):
        return [record for record in self.records if record.get("user_id") == user_id]


def _uuid7(index):
    return f"00000000-0000-7000-8000-{index:012x}"


def _record(preload_id, *, status=None, study_items=None, page_title=None):
    record = {
        "id": preload_id,
        "user_id": "user-1",
        "page_url": f"https://example.com/{preload_id}",
        "page_title": page_title or preload_id,
        "study_items": study_items or [],
        "sentences": [],
        "created_at": "2026-09-08T00:00:00+00:00",
    }
    if status is not None:
        record["status"] = status
    return record


class ReadingQueriesTests(unittest.TestCase):
    def test_resolve_by_id_falls_back_to_page_url(self):
        record = _record(_uuid7(1), page_title="Fixture Article")
        repository = InMemoryPreloadRepository([record])

        resolved = resolve_page_preload(
            repository,
            user_id="user-1",
            preload_id="missing",
            page_url=record["page_url"],
        )
        self.assertIs(resolved, record)
        self.assertIsNone(
            resolve_page_preload(repository, user_id="other", preload_id=record["id"])
        )

    def test_status_projection_preserves_legacy_ready_and_failed_error(self):
        legacy_record = _record(_uuid7(2), page_title="Legacy Article")
        legacy_record.update(
            {
                "learner_level": "intermediate",
                "target_language": "en",
                "native_language": "ja",
                "sentences_detected": 12,
                "sentence_limit": 10,
                "source_tokens_detected": 220,
                "source_tokens_analyzed": 180,
                "source_token_limit": 200,
            }
        )
        legacy = to_preload_response(legacy_record)
        self.assertIsNone(legacy.status)
        legacy_status = get_preload_status(
            InMemoryPreloadRepository([legacy_record]), "user-1", legacy_record["page_url"]
        )
        self.assertTrue(legacy_status.ready)
        self.assertEqual(legacy_status.preload.learner_level, "intermediate")
        self.assertEqual(legacy_status.preload.target_language, "en")
        self.assertEqual(legacy_status.preload.native_language, "ja")
        self.assertEqual(legacy_status.preload.sentences_detected, 12)
        self.assertEqual(legacy_status.preload.sentence_limit, 10)
        self.assertEqual(legacy_status.preload.source_tokens_detected, 220)
        self.assertEqual(legacy_status.preload.source_tokens_analyzed, 180)
        self.assertEqual(legacy_status.preload.source_token_limit, 200)

        missing_status = get_preload_status(InMemoryPreloadRepository([]), "user-1", "missing")
        self.assertFalse(missing_status.ready)
        self.assertIsNone(missing_status.preload)

        failed_record = _record(_uuid7(3), status="failed", page_title="Failed Article")
        failed_record["error"] = "analysis failed"
        status = get_preload_status(
            InMemoryPreloadRepository([failed_record]), "user-1", failed_record["page_url"]
        )
        self.assertFalse(status.ready)
        self.assertEqual(status.status, "failed")
        self.assertEqual(status.error, "analysis failed")
        self.assertEqual(status.preload.error, "analysis failed")

    def test_vocabulary_book_keeps_order_duplicates_and_bounds(self):
        records = []
        for record_number in range(31):
            records.append(
                _record(
                    _uuid7(10 + record_number),
                    page_title=f"Preload {record_number}",
                    study_items=[
                        {
                            "id": _uuid7(100 + record_number),
                            "text": "repeat",
                            "meaning": f"meaning-{record_number}",
                        }
                    ],
                )
            )
        repository = InMemoryPreloadRepository(records)

        book = build_vocabulary_book(repository, "user-1")

        self.assertEqual(book.preload_count, 30)
        self.assertEqual(len(book.items), 30)
        self.assertEqual(book.items[0].preload_id, _uuid7(10))
        self.assertEqual(book.items[-1].preload_id, _uuid7(39))
        self.assertEqual([item.text for item in book.items[:2]], ["repeat", "repeat"])

        many_items = _record(
            _uuid7(50),
            study_items=[
                {"id": _uuid7(1000 + index), "text": f"word-{index}"} for index in range(601)
            ],
        )
        bounded = build_vocabulary_book(InMemoryPreloadRepository([many_items]), "user-1")
        self.assertEqual(len(bounded.items), 600)
        self.assertEqual(bounded.items[-1].text, "word-599")


if __name__ == "__main__":
    unittest.main()
