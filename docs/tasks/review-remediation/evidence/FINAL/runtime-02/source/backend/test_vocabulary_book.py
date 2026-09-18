import tempfile
import unittest
from pathlib import Path

from accounts.storage import JsonEmailAuthService
from accounts.testing import build_test_accounts
from core.plans import PLAN_CATALOG
from deps import get_accounts, get_page_preload_repository
from fastapi.testclient import TestClient
from main import app
from repositories.page_preload_repository import JsonPagePreloadRepository


def _preload_record(preload_id, page_url, title, created_at, study_items):
    return {
        "id": preload_id,
        "page_url": page_url,
        "page_title": title,
        "summary": "s",
        "topics": [],
        "sentences": [],
        "study_items": study_items,
        "target_language": "en",
        "native_language": "ja",
        "created_at": created_at,
    }


class VocabularyBookTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmpdir.name)
        auth_service = JsonEmailAuthService(tmp / "users.json", tmp / "sessions.json")
        self.repository = JsonPagePreloadRepository(tmp / "preloads.json")
        accounts = build_test_accounts(plans=PLAN_CATALOG, auth_service=auth_service)
        app.dependency_overrides[get_accounts] = lambda: accounts
        app.dependency_overrides[get_page_preload_repository] = lambda: self.repository
        self.client = TestClient(app)

        login = self.client.post("/auth/login", json={"credential": "mock:reader@example.com"})
        self.headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        self.user_id = login.json()["user"]["id"]

    def tearDown(self):
        app.dependency_overrides.clear()
        self._tmpdir.cleanup()

    def test_aggregates_study_items_newest_article_first(self):
        self.repository.save(
            self.user_id,
            _preload_record(
                "p-old",
                "https://example.com/old",
                "Old Article",
                "2026-07-01T00:00:00+00:00",
                [
                    {
                        "id": "v1",
                        "type": "word",
                        "text": "obsolete",
                        "meaning": "時代遅れの",
                        "part_of_speech": "adjective",
                        "example": "",
                        "sentence_ids": [],
                    },
                ],
            ),
        )
        self.repository.save(
            self.user_id,
            _preload_record(
                "p-new",
                "https://example.com/new",
                "New Article",
                "2026-07-10T00:00:00+00:00",
                [
                    {
                        "id": "v2",
                        "type": "word",
                        "text": "resilient",
                        "meaning": "回復力のある",
                        "part_of_speech": "adjective",
                        "example": "A resilient system.",
                        "sentence_ids": [],
                    },
                    {
                        "id": "v3",
                        "type": "phrase",
                        "text": "phase out",
                        "meaning": "段階的に廃止する",
                        "part_of_speech": "phrasal verb",
                        "example": "",
                        "sentence_ids": [],
                    },
                ],
            ),
        )

        response = self.client.get("/vocabulary", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        body = response.json()

        self.assertEqual(body["preload_count"], 2)
        self.assertEqual(
            [item["text"] for item in body["items"]], ["resilient", "phase out", "obsolete"]
        )
        first = body["items"][0]
        self.assertEqual(first["page_title"], "New Article")
        self.assertEqual(first["page_url"], "https://example.com/new")
        self.assertEqual(first["target_language"], "en")
        self.assertEqual(first["example"], "A resilient system.")

    def test_empty_book_when_no_preloads(self):
        response = self.client.get("/vocabulary", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"items": [], "preload_count": 0})

    def test_requires_authentication(self):
        response = self.client.get("/vocabulary")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
