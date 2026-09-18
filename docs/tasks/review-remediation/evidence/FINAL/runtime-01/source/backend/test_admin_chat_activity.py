from __future__ import annotations

import tempfile
import types
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

import jobs.inline_runner as inline_runner_module
from accounts.storage import JsonSubscriptionRepository
from core.pipeline import PipelineError
from jobs.inline_runner import InlinePreloadJobRunner
from repositories.memory_admin_activity import MemoryAdminActivityRepository
from repositories.page_preload_repository import JsonPagePreloadRepository
from repositories.usage_repository import JsonUsageRepository
from schemas import ChatRequest, PagePreloadRequest
from services import preloading, reading
from services.entitlements import EntitlementError, build_guard
from storage.preload_content_store import FilesystemPreloadContentStore

_PAGE_URL = "https://example.com/activity"
_PAGE_HTML = (
    "<html><body>"
    "<p>The quick brown fox jumps over the lazy dog every single morning.</p>"
    "<p>She sells fresh seashells by the seashore during the warm summer months.</p>"
    "<p>Programming languages evolve steadily as developers demand more power.</p>"
    "</body></html>"
)
_START = datetime(2026, 7, 1, tzinfo=UTC)
_QUERY_START = datetime.min.replace(tzinfo=UTC)
_QUERY_END = datetime.max.replace(tzinfo=UTC)


class _Runner:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def enqueue(self, *args: object) -> None:
        self.calls.append(args)


class _FailingActivityRepository(MemoryAdminActivityRepository):
    def append(self, event):
        raise RuntimeError("activity storage unavailable")


class AdminTerminalActivityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.preloads = JsonPagePreloadRepository(root / "preloads.json")
        self.subscriptions = JsonSubscriptionRepository(root / "subscriptions.json")
        self.usage = JsonUsageRepository(root / "usage.json")
        self.content = FilesystemPreloadContentStore(root / "content")
        self.activity = MemoryAdminActivityRepository()
        self.guard = build_guard(self.subscriptions, self.usage, "u1", now=_START)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _events(self, operation: str | None = None):
        return self.activity.query(
            user_id="u1",
            start=_QUERY_START,
            end=_QUERY_END,
            operation=operation,
        )

    def _chat_request(self) -> ChatRequest:
        return ChatRequest(
            operation_id="019b63f8-f600-7000-8000-000000000101",
            message="PRIVATE learner question",
            context_text="PRIVATE learner context",
        )

    @staticmethod
    def _chat_success(messages, *, max_completion_tokens, tally):
        tally.add_response(
            types.SimpleNamespace(
                model="test-model",
                usage=types.SimpleNamespace(
                    input_tokens=7,
                    output_tokens=3,
                    total_tokens=10,
                ),
            )
        )
        return "PRIVATE provider reply"

    def _submit(
        self,
        *,
        activity_repository=None,
        operation_id="019b63f8-f600-7000-8000-000000000102",
    ):
        runner = _Runner()
        request = PagePreloadRequest(
            operation_id=operation_id,
            page_url=_PAGE_URL,
            page_title="PRIVATE title",
            html=_PAGE_HTML,
        )
        response = reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            request,
            guard=self.guard,
            admin_activity_repository=activity_repository,
        )
        return request, runner, response

    def _run(self, runner: _Runner, *, activity_repository=None) -> None:
        reading.run_preload_job(
            self.preloads,
            self.subscriptions,
            self.usage,
            self.content,
            *runner.calls[0],
            admin_activity_repository=activity_repository,
        )

    def test_chat_records_success_after_usage_with_safe_metrics(self) -> None:
        with mock.patch.object(reading, "_call_openai_chat", side_effect=self._chat_success):
            response = reading.chat_reply(
                self.preloads,
                "u1",
                self._chat_request(),
                guard=self.guard,
                admin_activity_repository=self.activity,
            )

        self.assertEqual(response.reply, "PRIVATE provider reply")
        event = self._events("chat")[0]
        self.assertEqual(event.source_id, f"chat:{self._chat_request().operation_id}:success")
        self.assertEqual((event.input_tokens, event.output_tokens, event.tokens), (7, 3, 10))
        self.assertEqual(event.model, "test-model")
        self.assertEqual(self.usage.get_month("u1", "2026-07")["chats"], 1)
        self.assertNotIn("PRIVATE", repr(event))

    def test_chat_records_failure_and_preserves_original_error_if_recording_fails(self) -> None:
        request = self._chat_request()
        with mock.patch.object(
            reading,
            "_call_openai_chat",
            side_effect=PipelineError("PRIVATE provider response", status_code=502),
        ):
            with self.assertRaisesRegex(PipelineError, "PRIVATE provider response"):
                reading.chat_reply(
                    self.preloads,
                    "u1",
                    request,
                    guard=self.guard,
                    admin_activity_repository=self.activity,
                )

        event = self._events("chat")[0]
        self.assertEqual(event.source_id, f"chat:{request.operation_id}:failed")
        self.assertEqual(event.error_code, "PipelineError")
        self.assertNotIn("PRIVATE", repr(event))

        with (
            mock.patch.object(
                reading,
                "_call_openai_chat",
                side_effect=PipelineError("ORIGINAL PRIVATE ERROR", status_code=502),
            ),
            self.assertLogs("untangle.backend", level="ERROR") as logs,
            self.assertRaisesRegex(PipelineError, "ORIGINAL PRIVATE ERROR"),
        ):
            reading.chat_reply(
                self.preloads,
                "u1",
                request.model_copy(update={"operation_id": "019b63f8-f600-7000-8000-000000000103"}),
                guard=self.guard,
                admin_activity_repository=_FailingActivityRepository(),
            )
        self.assertNotIn("ORIGINAL PRIVATE ERROR", "\n".join(logs.output))

    def test_chat_records_quota_block_and_success_recording_failure_fails_request(self) -> None:
        blocked_guard = mock.Mock()
        blocked_guard.check_chat.side_effect = EntitlementError(
            "PRIVATE quota detail",
            code="chat quota / exceeded",
            status_code=402,
        )
        request = self._chat_request()
        with self.assertRaises(EntitlementError):
            reading.chat_reply(
                self.preloads,
                "u1",
                request,
                guard=blocked_guard,
                admin_activity_repository=self.activity,
            )
        event = self._events("chat")[0]
        self.assertEqual(event.status, "quota_blocked")
        self.assertEqual(event.error_code, "chat_quota_/_exceeded")
        self.assertNotIn("PRIVATE", repr(event))

        with (
            mock.patch.object(reading, "_call_openai_chat", side_effect=self._chat_success),
            self.assertRaisesRegex(RuntimeError, "activity storage unavailable"),
        ):
            reading.chat_reply(
                self.preloads,
                "u1",
                request.model_copy(update={"operation_id": "019b63f8-f600-7000-8000-000000000104"}),
                guard=self.guard,
                admin_activity_repository=_FailingActivityRepository(),
            )

    def test_chat_duplicate_outcome_deduplicates_and_later_success_remains_visible(self) -> None:
        request = self._chat_request()
        with mock.patch.object(
            reading,
            "_call_openai_chat",
            side_effect=PipelineError("temporary", status_code=502),
        ):
            for _ in range(2):
                with self.assertRaises(PipelineError):
                    reading.chat_reply(
                        self.preloads,
                        "u1",
                        request,
                        guard=self.guard,
                        admin_activity_repository=self.activity,
                    )
        with mock.patch.object(reading, "_call_openai_chat", side_effect=self._chat_success):
            reading.chat_reply(
                self.preloads,
                "u1",
                request,
                guard=self.guard,
                admin_activity_repository=self.activity,
            )

        events = self._events("chat")
        self.assertEqual([event.status for event in events], ["failed", "success"])
        self.assertEqual(len({event.source_id for event in events}), 2)

    def test_article_records_quota_blocked_without_recording_fresh_short_circuit(self) -> None:
        blocked_guard = mock.Mock()
        blocked_guard.check_article.side_effect = EntitlementError(
            "PRIVATE quota detail",
            code="article_quota_exceeded",
            status_code=402,
        )
        request = PagePreloadRequest(page_url=_PAGE_URL, html=_PAGE_HTML)
        with self.assertRaises(EntitlementError):
            reading.submit_preload(
                self.preloads,
                _Runner(),
                self.content,
                "u1",
                request,
                guard=blocked_guard,
                admin_activity_repository=self.activity,
            )
        self.assertEqual(self._events("article")[0].status, "quota_blocked")

        self.activity = MemoryAdminActivityRepository()
        _, runner, _ = self._submit(activity_repository=self.activity)
        reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            PagePreloadRequest(page_url=_PAGE_URL, html=_PAGE_HTML),
            guard=self.guard,
            admin_activity_repository=self.activity,
        )
        self.assertEqual(self._events("article"), [])

    def test_article_records_success_once_after_ready_and_no_terminal_short_circuit_event(
        self,
    ) -> None:
        _, runner, _ = self._submit(activity_repository=self.activity)
        with (
            mock.patch.object(preloading, "_split_sentences", return_value=["Sentence."]),
            mock.patch.object(
                preloading,
                "_analyze_sentences",
                return_value=("summary", [], []),
            ),
            mock.patch.object(preloading, "_extract_study_items", return_value=([], {})),
        ):
            self._run(runner, activity_repository=self.activity)
            self._run(runner, activity_repository=self.activity)

        event = self._events("article")[0]
        record = self.preloads.get_by_page_url("u1", _PAGE_URL)
        self.assertEqual(record["status"], "ready")
        self.assertEqual(event.source_id, f"article:{record['id']}:success")
        self.assertEqual(len(self._events("article")), 1)
        self.assertNotIn("PRIVATE", repr(event))

    def test_article_records_failed_then_success_and_activity_failure_propagates(self) -> None:
        _, runner, _ = self._submit(activity_repository=self.activity)
        with mock.patch.object(
            preloading, "_split_sentences", side_effect=RuntimeError("PRIVATE provider error")
        ):
            self._run(runner, activity_repository=self.activity)

        failed = self.preloads.get_by_page_url("u1", _PAGE_URL)
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(self._events("article")[0].error_code, "RuntimeError")

        failed["status"] = "processing"
        failed["error"] = None
        self.preloads.save("u1", failed)
        self.content.put("u1", failed["id"], "Sentence.")
        with (
            mock.patch.object(preloading, "_split_sentences", return_value=["Sentence."]),
            mock.patch.object(
                preloading,
                "_analyze_sentences",
                return_value=("summary", [], []),
            ),
            mock.patch.object(preloading, "_extract_study_items", return_value=([], {})),
        ):
            self._run(runner, activity_repository=self.activity)
        self.assertEqual(
            [event.status for event in self._events("article")],
            ["failed", "success"],
        )

        _, second_runner, _ = self._submit(operation_id="019b63f8-f600-7000-8000-000000000106")
        with (
            mock.patch.object(preloading, "_split_sentences", return_value=["Sentence."]),
            mock.patch.object(
                preloading,
                "_analyze_sentences",
                return_value=("summary", [], []),
            ),
            mock.patch.object(preloading, "_extract_study_items", return_value=([], {})),
            self.assertRaisesRegex(RuntimeError, "activity storage unavailable"),
        ):
            self._run(
                second_runner,
                activity_repository=_FailingActivityRepository(),
            )

        third_request = PagePreloadRequest(
            operation_id="019b63f8-f600-7000-8000-000000000105",
            page_url="https://example.com/failed-activity",
            html=_PAGE_HTML,
        )
        third_runner = _Runner()
        reading.submit_preload(
            self.preloads,
            third_runner,
            self.content,
            "u1",
            third_request,
            guard=self.guard,
        )
        with (
            mock.patch.object(
                preloading,
                "_split_sentences",
                side_effect=RuntimeError("PRIVATE provider error"),
            ),
            self.assertRaisesRegex(RuntimeError, "activity storage unavailable"),
        ):
            self._run(
                third_runner,
                activity_repository=_FailingActivityRepository(),
            )

    def test_inline_runner_propagates_activity_repository(self) -> None:
        completed = mock.Mock()
        runner = InlinePreloadJobRunner(
            self.preloads,
            self.subscriptions,
            self.usage,
            self.content,
            self.activity,
            max_workers=1,
            queue_capacity=0,
        )
        with mock.patch.object(inline_runner_module, "run_preload_job", completed):
            runner.enqueue("u1", _PAGE_URL, "preload-1", "profile")
            runner.shutdown(wait=True)

        self.assertIs(
            completed.call_args.kwargs["admin_activity_repository"],
            self.activity,
        )


if __name__ == "__main__":
    unittest.main()
