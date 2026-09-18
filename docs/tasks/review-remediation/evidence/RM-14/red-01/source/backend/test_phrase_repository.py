"""Regression coverage for atomic JSON phrase persistence."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from core.ids import generate_uuid7
from repositories import phrase_repository
from repositories.phrase_repository import JsonPhraseRepository
from schemas import AnalyzeResponse, PhraseCreateRequest, PhraseRecord
from services import reading


def _request(label: str) -> PhraseCreateRequest:
    original_text = f"{label} sentence for phrase persistence."
    return PhraseCreateRequest(
        original_text=original_text,
        analysis=AnalyzeResponse(
            original_text=original_text,
            translation=f"{label} translation",
        ),
        page_url=f"https://example.test/{label}",
        page_title=f"{label} article",
    )


def _assert_uuid7(test_case: unittest.TestCase, value: str) -> None:
    parsed = uuid.UUID(value)
    test_case.assertEqual(parsed.version, 7)
    test_case.assertEqual(parsed.variant, uuid.RFC_4122)


class JsonPhraseRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self._directory = Path(self._temporary_directory.name)

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def test_create_uses_trusted_owner_and_preserves_prepend_order(self) -> None:
        repository = JsonPhraseRepository(self._directory / "phrases.json")
        trusted_owner = "trusted-owner"
        caller_owner = "caller-supplied-owner"
        preexisting = PhraseRecord(
            id=generate_uuid7(),
            created_at="2026-09-15T00:00:00+00:00",
            **_request("preexisting").model_dump(),
        )
        latest = PhraseRecord(
            id=generate_uuid7(),
            created_at="2026-09-15T00:00:01+00:00",
            **_request("latest").model_dump(),
        )

        first = repository.create(
            trusted_owner,
            {**preexisting.model_dump(), "user_id": caller_owner},
        )
        second = repository.create(
            trusted_owner,
            {**latest.model_dump(), "user_id": caller_owner},
        )

        self.assertEqual(first["user_id"], trusted_owner)
        self.assertEqual(second["user_id"], trusted_owner)
        self.assertEqual(
            [record["id"] for record in repository.list_for_user(trusted_owner)],
            [latest.id, preexisting.id],
        )
        self.assertEqual(repository.list_for_user(caller_owner), [])

    def test_reading_create_phrase_persists_a_uuid7_record_for_the_service_owner(self) -> None:
        repository = JsonPhraseRepository(self._directory / "phrases.json")

        phrase = reading.create_phrase(repository, "learner-1", _request("service"))

        _assert_uuid7(self, phrase.id)
        self.assertEqual(
            repository.list_for_user("learner-1"),
            [{**phrase.model_dump(), "user_id": "learner-1"}],
        )
        self.assertEqual(repository.list_for_user("learner-2"), [])

    def test_two_instance_creates_hold_the_lock_across_read_prepend_and_write(self) -> None:
        cases = (
            ("same owner", "learner-1", "learner-1", False),
            ("cross owner", "learner-1", "learner-2", False),
            ("symlink aliases", "learner-1", "learner-1", True),
        )
        for label, first_owner, second_owner, use_symlink in cases:
            with self.subTest(label=label):
                self._assert_serialized_creates(
                    label.replace(" ", "-"),
                    first_owner,
                    second_owner,
                    use_symlink=use_symlink,
                )

    def _assert_serialized_creates(
        self,
        label: str,
        first_owner: str,
        second_owner: str,
        *,
        use_symlink: bool,
    ) -> None:
        case_directory = self._directory / label
        case_directory.mkdir()
        path = case_directory / "phrases.json"
        alias = case_directory / "phrases-alias.json"
        if use_symlink:
            alias.symlink_to(path)

        first_repository = JsonPhraseRepository(path)
        second_repository = JsonPhraseRepository(alias if use_symlink else path)
        self.assertEqual(first_repository._path, path.resolve())
        self.assertEqual(second_repository._path, path.resolve())

        preexisting = reading.create_phrase(first_repository, first_owner, _request("preexisting"))
        acknowledgements: dict[str, PhraseRecord] = {}
        errors: list[BaseException] = []
        first_read = threading.Event()
        release_first = threading.Event()
        second_lock_attempted = threading.Event()
        second_acknowledged = threading.Event()
        read_guard = threading.Lock()
        paused = False
        lock_entries = 0
        original_read = phrase_repository.read_json_list
        original_lock = phrase_repository.json_list_lock

        def pause_first_protected_read(read_path: Path) -> list[dict]:
            nonlocal paused
            phrases = original_read(read_path)
            with read_guard:
                should_pause = not paused
                if should_pause:
                    paused = True
            if should_pause:
                first_read.set()
                if not release_first.wait(timeout=2):
                    raise TimeoutError("test did not release the first phrase save")
            return phrases

        @contextmanager
        def observe_lock_attempt(lock_path: Path):
            nonlocal lock_entries
            with read_guard:
                lock_entries += 1
                is_second_attempt = lock_entries == 2
            if is_second_attempt:
                second_lock_attempted.set()
            with original_lock(lock_path):
                yield

        def save_first() -> None:
            try:
                acknowledgements["first"] = reading.create_phrase(
                    first_repository,
                    first_owner,
                    _request("first"),
                )
            except BaseException as error:
                errors.append(error)

        def save_second() -> None:
            try:
                acknowledgements["second"] = reading.create_phrase(
                    second_repository,
                    second_owner,
                    _request("second"),
                )
            except BaseException as error:
                errors.append(error)
            finally:
                second_acknowledged.set()

        first_thread = threading.Thread(target=save_first, daemon=True)
        second_thread = threading.Thread(target=save_second, daemon=True)
        first_started = False
        second_started = False
        with (
            mock.patch.object(
                phrase_repository,
                "read_json_list",
                side_effect=pause_first_protected_read,
            ),
            mock.patch.object(
                phrase_repository,
                "json_list_lock",
                side_effect=observe_lock_attempt,
            ),
        ):
            first_thread.start()
            first_started = True
            try:
                self.assertTrue(first_read.wait(timeout=2))
                second_thread.start()
                second_started = True
                self.assertTrue(second_lock_attempted.wait(timeout=2))
                self.assertFalse(second_acknowledged.wait(timeout=0.1))
            finally:
                release_first.set()
                if first_started:
                    first_thread.join(timeout=2)
                if second_started:
                    second_thread.join(timeout=2)

        self.assertFalse(first_thread.is_alive())
        self.assertFalse(second_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(set(acknowledgements), {"first", "second"})
        first_phrase = acknowledgements["first"]
        second_phrase = acknowledgements["second"]
        _assert_uuid7(self, first_phrase.id)
        _assert_uuid7(self, second_phrase.id)

        raw = json.loads(path.read_text(encoding="utf-8"))
        raw_ids = [record["id"] for record in raw]
        self.assertEqual(raw_ids.count(preexisting.id), 1)
        self.assertEqual(raw_ids.count(first_phrase.id), 1)
        self.assertEqual(raw_ids.count(second_phrase.id), 1)
        self.assertEqual(raw_ids, [second_phrase.id, first_phrase.id, preexisting.id])
        self.assertEqual(
            {record["id"] for record in first_repository.list_for_user(first_owner)},
            {
                preexisting.id,
                first_phrase.id,
                *({second_phrase.id} if first_owner == second_owner else set()),
            },
        )
        self.assertEqual(
            {record["id"] for record in second_repository.list_for_user(second_owner)},
            {
                second_phrase.id,
                *({preexisting.id, first_phrase.id} if first_owner == second_owner else set()),
            },
        )
