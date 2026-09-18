"""Adversarial public-workflow regressions for preload content handoffs."""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import core.pipeline as pipeline
from accounts.storage import JsonSubscriptionRepository
from repositories.page_preload_repository import JsonPagePreloadRepository
from repositories.usage_repository import JsonUsageRepository
from schemas import PagePreloadRequest
from services import preloading
from services.entitlements import EntitlementError
from services.usage_meter import UsageMeter
from storage.preload_content_store import FilesystemPreloadContentStore

_PAGE_HTML = (
    "<html><body>"
    "<p>Readers use this complete article paragraph to exercise a durable handoff between "
    "submission and deferred analysis without relying on a provider response.</p>"
    "<p>A second paragraph gives extraction enough realistic text while describing leases, "
    "content ownership, and retryable retirement after terminal publication.</p>"
    "</body></html>"
)
_CONFLICTING_PAGE_HTML = (
    "<html><body>"
    "<p>This different article body has its own immutable meaning and must not replace the "
    "already accepted payload for a matching operation identifier.</p>"
    "<p>The extra paragraph keeps this fixture above the article extraction threshold and makes "
    "the canonical payload hash intentionally different.</p>"
    "</body></html>"
)
_PAGE_URL = "https://example.com/handoff"
_USER_ID = "handoff-user"
_OPERATION_ID = "019b63f8-f600-7000-8000-000000000101"


def _rate_environment():
    return mock.patch.dict(
        os.environ,
        {
            "OPENAI_MODEL": pipeline.OPENAI_MODEL,
            "OPENAI_RATE_CARD_VERSION": "test",
            "OPENAI_MODEL_INPUT_MICRO_USD_PER_MILLION": "1",
            "OPENAI_MODEL_OUTPUT_MICRO_USD_PER_MILLION": "1",
        },
    )


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def enqueue(
        self,
        user_id,
        page_url,
        preload_id,
        learner_profile_fingerprint,
        usage_context=None,
    ) -> None:
        self.calls.append(
            (user_id, page_url, preload_id, learner_profile_fingerprint, usage_context)
        )


class PausingCreateJsonRepository(JsonPagePreloadRepository):
    def __init__(
        self,
        path: Path,
        create_seen: threading.Event,
        continue_create: threading.Event,
    ) -> None:
        super().__init__(path)
        self._create_seen = create_seen
        self._continue_create = continue_create
        self._pause_once = True

    def create_if_absent(self, user_id: str, record: dict, *, now=None):
        if self._pause_once:
            self._pause_once = False
            self._create_seen.set()
            if not self._continue_create.wait(timeout=2):
                raise TimeoutError("Test did not release the delayed submitter")
        return super().create_if_absent(user_id, record, now=now)


class PausingLatestJsonRepository(JsonPagePreloadRepository):
    def __init__(
        self,
        path: Path,
        latest_lookup_seen: threading.Event,
        continue_latest_lookup: threading.Event,
    ) -> None:
        super().__init__(path)
        self._latest_lookup_seen = latest_lookup_seen
        self._continue_latest_lookup = continue_latest_lookup
        self._pause_once = True

    def get_by_page_url(self, user_id: str, page_url: str):
        if self._pause_once:
            self._pause_once = False
            self._latest_lookup_seen.set()
            if not self._continue_latest_lookup.wait(timeout=2):
                raise TimeoutError("Test did not release the stale worker")
        return super().get_by_page_url(user_id, page_url)


class CrashBeforePublicationContentStore(FilesystemPreloadContentStore):
    def __init__(self, base_dir: Path) -> None:
        super().__init__(base_dir)
        self._crash_once = True

    def put_if_absent(self, user_id: str, preload_id: str, content: str) -> bool:
        if self._crash_once:
            self._crash_once = False
            raise KeyboardInterrupt("simulated handoff crash")
        return super().put_if_absent(user_id, preload_id, content)


class PausingPublicationContentStore(FilesystemPreloadContentStore):
    def __init__(self, base_dir: Path) -> None:
        super().__init__(base_dir)
        self.publication_started = threading.Event()
        self.continue_publication = threading.Event()
        self._pause_once = True

    def put_if_absent(self, user_id: str, preload_id: str, content: str) -> bool:
        if self._pause_once and (user_id, preload_id) == (_USER_ID, _OPERATION_ID):
            self._pause_once = False
            self.publication_started.set()
            if not self.continue_publication.wait(timeout=2):
                raise TimeoutError("Test did not release the stale publisher")
        return super().put_if_absent(user_id, preload_id, content)


class FailOnceRetirementContentStore(FilesystemPreloadContentStore):
    def __init__(self, base_dir: Path) -> None:
        super().__init__(base_dir)
        self.retirement_calls = 0

    def retire(self, user_id: str, preload_id: str) -> bool:
        self.retirement_calls += 1
        if self.retirement_calls == 1:
            raise OSError("simulated retirement failure")
        return super().retire(user_id, preload_id)


class FailPublicationAndRetirementContentStore(FilesystemPreloadContentStore):
    def __init__(self, base_dir: Path) -> None:
        super().__init__(base_dir)
        self._publication_failed = False
        self.retirement_calls = 0

    def put_if_absent(self, user_id: str, preload_id: str, content: str) -> bool:
        if not self._publication_failed:
            self._publication_failed = True
            raise OSError("simulated content publication failure")
        return super().put_if_absent(user_id, preload_id, content)

    def retire(self, user_id: str, preload_id: str) -> bool:
        self.retirement_calls += 1
        if self.retirement_calls == 1:
            raise OSError("simulated retirement failure")
        return super().retire(user_id, preload_id)


class AdvancedWinnerOnEnqueueJsonRepository(JsonPagePreloadRepository):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self._advance_once = True

    def mark_enqueue_submitting(self, user_id: str, preload_id: str) -> bool:
        if self._advance_once:
            self._advance_once = False
            record = self.get_by_id(user_id, preload_id)
            if record is None:
                raise AssertionError("The competing worker requires a preload record")
            claimed = self.claim_processing(
                user_id,
                preload_id,
                str(record["learner_profile_fingerprint"]),
                lease_id="advanced-winner-lease",
                now=datetime.now(UTC),
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=1),
            )
            if claimed is None:
                raise AssertionError("The competing worker could not claim the preload")
            return False
        return super().mark_enqueue_submitting(user_id, preload_id)


class PreloadHandoffWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self._rate_environment = _rate_environment()
        self._rate_environment.start()
        self.addCleanup(self._rate_environment.stop)
        self._tempdir = tempfile.TemporaryDirectory()
        directory = Path(self._tempdir.name)
        self.preload_path = directory / "preloads.json"
        self.usage = JsonUsageRepository(directory / "usage.json")
        self.subscriptions = JsonSubscriptionRepository(directory / "subscriptions.json")
        self.content_dir = directory / "content"

    def tearDown(self) -> None:
        self._tempdir.cleanup()

    def _request(self) -> PagePreloadRequest:
        return PagePreloadRequest(
            page_url=_PAGE_URL,
            page_title="Handoff article",
            html=_PAGE_HTML,
            operation_id=_OPERATION_ID,
        )

    def _meter(self) -> UsageMeter:
        return UsageMeter(
            self.subscriptions,
            self.usage,
            _USER_ID,
            reservation_enabled=True,
        )

    def _shadow_meter(self) -> UsageMeter:
        return UsageMeter(
            self.subscriptions,
            self.usage,
            _USER_ID,
            reservation_enabled=False,
        )

    def _submit(self, repository, runner, content_store, *, request=None, meter=None):
        return preloading.submit_preload(
            repository,
            runner,
            content_store,
            _USER_ID,
            request or self._request(),
            usage_meter=meter or self._meter(),
        )

    def _run_job(self, repository, runner, content_store) -> None:
        with (
            mock.patch.object(preloading, "_split_sentences", return_value=["Handoff sentence."]),
            mock.patch.object(preloading, "_analyze_sentences", return_value=("summary", [], [])),
            mock.patch.object(preloading, "_extract_study_items", return_value=([], {})),
        ):
            preloading.run_preload_job(
                repository,
                self.subscriptions,
                self.usage,
                content_store,
                *runner.calls[0],
            )

    def _run_job_without_provider(self, repository, runner, content_store) -> None:
        with mock.patch.object(
            preloading,
            "_split_sentences",
            side_effect=AssertionError("provider work must not replay"),
        ):
            preloading.run_preload_job(
                repository,
                self.subscriptions,
                self.usage,
                content_store,
                *runner.calls[0],
            )

    def _expire_handoff(self, repository) -> None:
        record = repository.get_by_id(_USER_ID, _OPERATION_ID)
        self.assertIsNotNone(record)
        expired = dict(record)
        expired["content_handoff_expires_at"] = (
            datetime.now(UTC) - timedelta(minutes=1)
        ).isoformat()
        repository.save(_USER_ID, expired, make_latest=False)

    def test_delayed_same_operation_loser_cannot_reset_a_running_winner(self) -> None:
        winner_repository = JsonPagePreloadRepository(self.preload_path)
        create_seen = threading.Event()
        continue_create = threading.Event()
        loser_repository = PausingCreateJsonRepository(
            self.preload_path,
            create_seen,
            continue_create,
        )
        content = FilesystemPreloadContentStore(self.content_dir)
        winner_runner = RecordingRunner()
        loser_runner = RecordingRunner()
        loser_errors: list[BaseException] = []

        def delayed_submit() -> None:
            try:
                self._submit(loser_repository, loser_runner, content)
            except BaseException as exc:
                loser_errors.append(exc)

        loser_thread = threading.Thread(target=delayed_submit)
        loser_thread.start()
        try:
            self.assertTrue(create_seen.wait(timeout=2))
            self._submit(winner_repository, winner_runner, content)
            winner = winner_repository.get_by_id(_USER_ID, _OPERATION_ID)
            claimed = winner_repository.claim_processing(
                _USER_ID,
                _OPERATION_ID,
                winner["learner_profile_fingerprint"],
                lease_id="winner-lease",
                now=datetime.now(UTC),
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=1),
            )
            self.assertIsNotNone(claimed)
            winning_content = content.get(_USER_ID, _OPERATION_ID)
        finally:
            continue_create.set()
            loser_thread.join(timeout=2)

        self.assertFalse(loser_thread.is_alive())
        self.assertEqual(loser_errors, [])
        current = winner_repository.get_by_id(_USER_ID, _OPERATION_ID)
        self.assertEqual(current["status"], "running")
        self.assertEqual(current["lease_id"], "winner-lease")
        self.assertEqual(content.get(_USER_ID, _OPERATION_ID), winning_content)
        self.assertEqual(len(winner_runner.calls), 1)
        self.assertEqual(loser_runner.calls, [])
        self.assertEqual(self._meter().get_operation(_OPERATION_ID).state, "reserved")

    def test_delayed_same_operation_loser_cannot_replace_a_finished_winner(self) -> None:
        winner_repository = JsonPagePreloadRepository(self.preload_path)
        create_seen = threading.Event()
        continue_create = threading.Event()
        loser_repository = PausingCreateJsonRepository(
            self.preload_path,
            create_seen,
            continue_create,
        )
        content = FilesystemPreloadContentStore(self.content_dir)
        winner_runner = RecordingRunner()
        loser_runner = RecordingRunner()
        loser_errors: list[BaseException] = []

        def delayed_submit() -> None:
            try:
                self._submit(loser_repository, loser_runner, content)
            except BaseException as exc:
                loser_errors.append(exc)

        loser_thread = threading.Thread(target=delayed_submit)
        loser_thread.start()
        try:
            self.assertTrue(create_seen.wait(timeout=2))
            self._submit(winner_repository, winner_runner, content)
            self._run_job(winner_repository, winner_runner, content)
            finished = winner_repository.get_by_id(_USER_ID, _OPERATION_ID)
        finally:
            continue_create.set()
            loser_thread.join(timeout=2)

        self.assertFalse(loser_thread.is_alive())
        self.assertEqual(loser_errors, [])
        current = winner_repository.get_by_id(_USER_ID, _OPERATION_ID)
        self.assertEqual(current["status"], "ready")
        self.assertEqual(current["summary"], finished["summary"])
        self.assertIsNone(content.get(_USER_ID, _OPERATION_ID))
        self.assertEqual(len(winner_runner.calls), 1)
        self.assertEqual(loser_runner.calls, [])
        self.assertEqual(self._meter().get_operation(_OPERATION_ID).state, "finalized")

    def test_expired_pending_handoff_is_recovered_by_the_same_operation(self) -> None:
        repository = JsonPagePreloadRepository(self.preload_path)
        content = CrashBeforePublicationContentStore(self.content_dir)
        runner = RecordingRunner()

        with self.assertRaisesRegex(KeyboardInterrupt, "handoff crash"):
            self._submit(repository, runner, content)

        pending = repository.get_by_id(_USER_ID, _OPERATION_ID)
        self.assertEqual(pending["status"], "content_pending")
        self._expire_handoff(repository)
        replay = self._submit(repository, runner, content)

        self.assertEqual(replay.status, "processing")
        self.assertEqual(len(runner.calls), 1)
        self.assertIsNotNone(content.get(_USER_ID, _OPERATION_ID))
        self.assertEqual(self._meter().get_operation(_OPERATION_ID).state, "reserved")

    def test_conflicting_same_operation_does_not_mutate_or_enqueue_the_winner(self) -> None:
        repository = JsonPagePreloadRepository(self.preload_path)
        content = FilesystemPreloadContentStore(self.content_dir)
        runner = RecordingRunner()
        self._submit(repository, runner, content)
        winner = repository.get_by_id(_USER_ID, _OPERATION_ID)
        conflicting_request = self._request().model_copy(
            update={
                "html": _CONFLICTING_PAGE_HTML,
            }
        )

        with self.assertRaises(EntitlementError) as raised:
            preloading.submit_preload(
                repository,
                runner,
                content,
                _USER_ID,
                conflicting_request,
                usage_meter=self._meter(),
            )

        self.assertEqual(raised.exception.status_code, 409)
        current = repository.get_by_id(_USER_ID, _OPERATION_ID)
        self.assertEqual(current["payload_hash"], winner["payload_hash"])
        self.assertEqual(len(runner.calls), 1)
        self.assertIsNotNone(content.get(_USER_ID, _OPERATION_ID))

    def test_shadow_replay_keeps_operation_identity_and_rejects_changed_payload(self) -> None:
        repository = JsonPagePreloadRepository(self.preload_path)
        content = FilesystemPreloadContentStore(self.content_dir)
        runner = RecordingRunner()
        shadow_meter = self._shadow_meter()

        self._submit(repository, runner, content, meter=shadow_meter)
        self._submit(repository, runner, content, meter=shadow_meter)
        winner = repository.get_by_id(_USER_ID, _OPERATION_ID)
        conflicting_request = self._request().model_copy(update={"html": _CONFLICTING_PAGE_HTML})

        with self.assertRaises(EntitlementError) as raised:
            self._submit(
                repository,
                runner,
                content,
                request=conflicting_request,
                meter=shadow_meter,
            )

        self.assertEqual(raised.exception.status_code, 409)
        current = repository.get_by_id(_USER_ID, _OPERATION_ID)
        self.assertEqual(current["id"], _OPERATION_ID)
        self.assertEqual(current["operation_id"], _OPERATION_ID)
        self.assertEqual(current["shadow_usage"]["operation_id"], _OPERATION_ID)
        self.assertEqual(current["payload_hash"], winner["payload_hash"])
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(shadow_meter.get_operation(_OPERATION_ID).state, "reserved")
        self.assertIsNone(self.usage.get_operation(_USER_ID, _OPERATION_ID))

    def test_shadow_failed_handoff_retries_retirement_without_usage_release(self) -> None:
        repository = JsonPagePreloadRepository(self.preload_path)
        content = FailPublicationAndRetirementContentStore(self.content_dir)
        runner = RecordingRunner()
        shadow_meter = self._shadow_meter()

        try:
            self._submit(repository, runner, content, meter=shadow_meter)
        except OSError as exc:
            self.assertIn("simulated", str(exc))

        pending = repository.get_by_id(_USER_ID, _OPERATION_ID)
        self.assertEqual(pending["status"], "failed_pending_release")
        self.assertTrue(pending["content_retirement_pending"])
        self.assertEqual(content.retirement_calls, 1)
        with mock.patch.object(
            shadow_meter,
            "release",
            side_effect=AssertionError("shadow mode must not release a reservation"),
        ):
            replay = self._submit(repository, runner, content, meter=shadow_meter)

        recovered = repository.get_by_id(_USER_ID, _OPERATION_ID)
        self.assertEqual(replay.status, "failed")
        self.assertEqual(recovered["status"], "failed")
        self.assertFalse(recovered["content_retirement_pending"])
        self.assertEqual(content.retirement_calls, 2)
        self.assertIsNone(content.get(_USER_ID, _OPERATION_ID))
        self.assertEqual(shadow_meter.get_operation(_OPERATION_ID).state, "reserved")
        self.assertIsNone(self.usage.get_operation(_USER_ID, _OPERATION_ID))

    def test_advanced_winner_rejects_stale_submitter_release_and_retirement(self) -> None:
        repository = AdvancedWinnerOnEnqueueJsonRepository(self.preload_path)
        content = FilesystemPreloadContentStore(self.content_dir)
        runner = RecordingRunner()
        meter = self._meter()

        with mock.patch.object(
            meter,
            "release",
            side_effect=AssertionError("a stale submitter must not release the winner"),
        ):
            self._submit(repository, runner, content, meter=meter)

        current = repository.get_by_id(_USER_ID, _OPERATION_ID)
        self.assertEqual(current["status"], "running")
        self.assertEqual(current["lease_id"], "advanced-winner-lease")
        self.assertIsNotNone(content.get(_USER_ID, _OPERATION_ID))
        self.assertEqual(runner.calls, [])
        self.assertEqual(meter.get_operation(_OPERATION_ID).state, "reserved")

    def test_stale_publication_cannot_recreate_content_after_winner_retires(self) -> None:
        first_repository = JsonPagePreloadRepository(self.preload_path)
        winner_repository = JsonPagePreloadRepository(self.preload_path)
        content = PausingPublicationContentStore(self.content_dir)
        self.assertTrue(content.put_if_absent("unrelated-user", "other-op", "other private body"))
        stale_runner = RecordingRunner()
        winner_runner = RecordingRunner()
        stale_errors: list[BaseException] = []

        def stale_submit() -> None:
            try:
                self._submit(first_repository, stale_runner, content)
            except BaseException as exc:
                stale_errors.append(exc)

        stale_thread = threading.Thread(target=stale_submit)
        stale_thread.start()
        try:
            self.assertTrue(content.publication_started.wait(timeout=2))
            self._expire_handoff(winner_repository)
            self._submit(winner_repository, winner_runner, content)
            self._run_job(winner_repository, winner_runner, content)
        finally:
            content.continue_publication.set()
            stale_thread.join(timeout=2)

        self.assertFalse(stale_thread.is_alive())
        self.assertEqual(stale_errors, [])
        self.assertEqual(len(stale_runner.calls), 0)
        self.assertEqual(len(winner_runner.calls), 1)
        self.assertEqual(
            winner_repository.get_by_id(_USER_ID, _OPERATION_ID)["status"],
            "ready",
        )
        self.assertIsNone(content.get(_USER_ID, _OPERATION_ID))
        self.assertFalse(content.put_if_absent(_USER_ID, _OPERATION_ID, "stale private body"))
        self.assertEqual(content.get("unrelated-user", "other-op"), "other private body")
        self.assertEqual(self._meter().get_operation(_OPERATION_ID).state, "finalized")

    def test_stale_superseded_worker_cannot_release_or_clean_up_a_newer_lease(self) -> None:
        source_repository = JsonPagePreloadRepository(self.preload_path)
        latest_lookup_seen = threading.Event()
        continue_latest_lookup = threading.Event()
        stale_repository = PausingLatestJsonRepository(
            self.preload_path,
            latest_lookup_seen,
            continue_latest_lookup,
        )
        content = FilesystemPreloadContentStore(self.content_dir)
        old_runner = RecordingRunner()
        newest_runner = RecordingRunner()
        stale_errors: list[BaseException] = []
        self._submit(source_repository, old_runner, content)
        old = source_repository.get_by_id(_USER_ID, _OPERATION_ID)

        def stale_worker() -> None:
            try:
                preloading.run_preload_job(
                    stale_repository,
                    self.subscriptions,
                    self.usage,
                    content,
                    *old_runner.calls[0],
                )
            except BaseException as exc:
                stale_errors.append(exc)

        stale_thread = threading.Thread(target=stale_worker)
        stale_thread.start()
        try:
            self.assertTrue(latest_lookup_seen.wait(timeout=2))
            newest_request = self._request().model_copy(
                update={
                    "operation_id": "019b63f8-f600-7000-8000-000000000102",
                    "learner_level": "Changed learner profile",
                }
            )
            preloading.submit_preload(
                source_repository,
                newest_runner,
                content,
                _USER_ID,
                newest_request,
                usage_meter=self._meter(),
            )
            claimed = source_repository.claim_processing(
                _USER_ID,
                _OPERATION_ID,
                old["learner_profile_fingerprint"],
                lease_id="concurrent-worker-lease",
                now=datetime.now(UTC),
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=1),
            )
            self.assertIsNotNone(claimed)
        finally:
            continue_latest_lookup.set()
            stale_thread.join(timeout=2)

        self.assertFalse(stale_thread.is_alive())
        self.assertEqual(stale_errors, [])
        current_old = source_repository.get_by_id(_USER_ID, _OPERATION_ID)
        self.assertEqual(current_old["status"], "running")
        self.assertEqual(current_old["lease_id"], "concurrent-worker-lease")
        self.assertIsNotNone(content.get(_USER_ID, _OPERATION_ID))
        self.assertEqual(self._meter().get_operation(_OPERATION_ID).state, "reserved")
        self.assertEqual(
            source_repository.get_by_page_url(_USER_ID, _PAGE_URL)["id"],
            newest_request.operation_id,
        )

    def test_retirement_failure_remains_retryable_without_provider_replay(self) -> None:
        repository = JsonPagePreloadRepository(self.preload_path)
        content = FailOnceRetirementContentStore(self.content_dir)
        runner = RecordingRunner()
        self._submit(repository, runner, content)
        self._run_job(repository, runner, content)

        first = repository.get_by_id(_USER_ID, _OPERATION_ID)
        self.assertEqual(first["status"], "ready")
        self.assertTrue(first["content_retirement_pending"])
        self.assertIsNotNone(content.get(_USER_ID, _OPERATION_ID))

        with mock.patch.object(
            preloading,
            "_split_sentences",
            side_effect=AssertionError("provider work must not replay"),
        ):
            preloading.run_preload_job(
                repository,
                self.subscriptions,
                self.usage,
                content,
                *runner.calls[0],
            )

        recovered = repository.get_by_id(_USER_ID, _OPERATION_ID)
        self.assertEqual(recovered["status"], "ready")
        self.assertFalse(recovered.get("content_retirement_pending"))
        self.assertIsNone(content.get(_USER_ID, _OPERATION_ID))
        self.assertEqual(content.retirement_calls, 2)

    def test_terminal_recovery_retries_retirement_without_provider_work(self) -> None:
        for outcome in ("released", "interrupted"):
            with self.subTest(outcome=outcome):
                operation_id = (
                    "019b63f8-f600-7000-8000-000000000103"
                    if outcome == "released"
                    else "019b63f8-f600-7000-8000-000000000104"
                )
                request = self._request().model_copy(
                    update={
                        "operation_id": operation_id,
                        "page_url": f"{_PAGE_URL}/{outcome}",
                    }
                )
                repository = JsonPagePreloadRepository(self.preload_path)
                content = FailOnceRetirementContentStore(self.content_dir / outcome)
                runner = RecordingRunner()
                meter = self._meter()
                self._submit(repository, runner, content, request=request, meter=meter)

                if outcome == "released":
                    meter.release(operation_id, "simulated expiration")
                else:
                    operation = meter.get_operation(operation_id)
                    meter.save_result(
                        operation_id,
                        {
                            "kind": "preload",
                            "state": "dispatching",
                            "usage": {
                                "actual_cost_micro_usd": operation.reserved_cost_micro_usd,
                            },
                        },
                    )
                    meter.finalize(
                        operation_id,
                        {
                            "actual_cost_micro_usd": operation.reserved_cost_micro_usd,
                        },
                        result_ref=operation_id,
                    )

                self._run_job_without_provider(repository, runner, content)
                first = repository.get_by_id(_USER_ID, operation_id)
                self.assertEqual(first["status"], "failed")
                self.assertTrue(first["content_retirement_pending"])
                self.assertIsNotNone(content.get(_USER_ID, operation_id))

                self._run_job_without_provider(repository, runner, content)
                recovered = repository.get_by_id(_USER_ID, operation_id)
                self.assertEqual(recovered["status"], "failed")
                self.assertFalse(recovered["content_retirement_pending"])
                self.assertIsNone(content.get(_USER_ID, operation_id))
                self.assertEqual(content.retirement_calls, 2)


if __name__ == "__main__":
    unittest.main()
