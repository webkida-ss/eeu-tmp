"""Async preload pipeline: submit (fast) + deferred job (split/analyze).

Covers the framework-free service (submit_preload / run_preload_job), the
inline job runner running end-to-end on its background thread, and the
HTTP surface (202 processing, GET reflecting the lifecycle) with a fake
OpenAI client patched onto core.pipeline._client (see
test_parallel_analysis.py for the pattern).
"""

import contextlib
import json
import re
import tempfile
import threading
import time
import types
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import core.pipeline as pipeline
import jobs.inline_runner as inline_runner_module
import repositories.page_preload_repository as preload_repository_module
from accounts.storage import JsonEmailAuthService, JsonSubscriptionRepository
from accounts.testing import build_test_accounts
from core.plans import PLAN_CATALOG
from deps import (
    get_accounts,
    get_entitlement_guard,
    get_page_preload_repository,
    get_preload_content_store,
    get_preload_job_runner,
    get_subscription_repository,
    get_usage_meter,
    get_usage_repository,
)
from fastapi.testclient import TestClient
from jobs.inline_runner import InlinePreloadJobRunner
from main import app
from pydantic import ValidationError
from repositories.dynamodb_page_preload_repository import DynamoPagePreloadRepository
from repositories.page_preload_repository import JsonPagePreloadRepository
from repositories.usage_repository import JsonUsageRepository
from schemas import AnalyzeRequest, ChatRequest, PagePreloadRequest
from services import preloading, reading
from services.entitlements import build_guard, current_month
from services.usage_meter import UsageMeter
from storage.json_list_store import write_json_list
from storage.preload_content_store import FilesystemPreloadContentStore

_PAGE_HTML = (
    "<html><body>"
    "<p>The quick brown fox jumps over the lazy dog every single morning.</p>"
    "<p>She sells fresh seashells by the seashore during the warm summer months.</p>"
    "<p>Programming languages evolve steadily as developers demand ever more power.</p>"
    "</body></html>"
)
_PAGE_URL = "https://example.com/article"

_ANALYZE_INDEX_RE = re.compile(r'^(\d+)\. "', re.MULTILINE)
_DRAFT_LINE_RE = re.compile(r"^\d+\.\s+(.*\S)\s*$", re.MULTILINE)


def _rate_env_patch():
    return mock.patch.dict(
        "os.environ",
        {
            "OPENAI_MODEL": pipeline.OPENAI_MODEL,
            "OPENAI_RATE_CARD_VERSION": "test",
            "OPENAI_MODEL_INPUT_MICRO_USD_PER_MILLION": "1",
            "OPENAI_MODEL_OUTPUT_MICRO_USD_PER_MILLION": "1",
        },
    )


def _fake_openai_client():
    """Answers both pipeline call shapes: the one-shot split (echoes the
    mechanical draft the prompt embeds, which is verbatim from the chunk) and
    the batch analysis (translations derived from the numbered sentences)."""

    def create(**kwargs):
        prompt = kwargs["messages"][-1]["content"]
        if "Mechanical draft split:" in prompt:
            draft = prompt.split("Mechanical draft split:", 1)[1]
            sentences = _DRAFT_LINE_RE.findall(draft)
            payload = {"sentences": sentences}
        else:
            indexes = [int(match) for match in _ANALYZE_INDEX_RE.findall(prompt)]
            payload = {
                "summary": "article summary" if 0 in indexes else "",
                "topics": ["topic"] if 0 in indexes else [],
                "sentences": [
                    {
                        "index": index,
                        "translation": f"translation-{index}",
                        "grammar": f"grammar-{index}",
                        "vocabulary": [],
                    }
                    for index in indexes
                ],
            }
        message = types.SimpleNamespace(content=json.dumps(payload))
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    completions = types.SimpleNamespace(create=create)
    return types.SimpleNamespace(chat=types.SimpleNamespace(completions=completions))


def _failing_openai_client():
    def create(**kwargs):
        raise RuntimeError("simulated OpenAI outage")

    completions = types.SimpleNamespace(create=create)
    return types.SimpleNamespace(chat=types.SimpleNamespace(completions=completions))


class OperationIdentityTests(unittest.TestCase):
    def test_requests_generate_uuid_v7_when_transport_omits_operation_id(self):
        requests = [
            PagePreloadRequest(page_url=_PAGE_URL, html=_PAGE_HTML),
            AnalyzeRequest(text="A selected sentence."),
            ChatRequest(message="Explain.", context_text="A selected sentence."),
        ]

        for request in requests:
            operation_id = uuid.UUID(request.operation_id)
            self.assertEqual(operation_id.version, 7)
            self.assertEqual(operation_id.variant, uuid.RFC_4122)
        # Legacy omission creates a new logical operation each time; callers
        # only receive retry idempotency by supplying and reusing the ID.
        self.assertNotEqual(
            AnalyzeRequest(text="Same request.").operation_id,
            AnalyzeRequest(text="Same request.").operation_id,
        )

    def test_requests_reject_non_uuid_v7_operation_id(self):
        for model, values in [
            (PagePreloadRequest, {"page_url": _PAGE_URL, "html": _PAGE_HTML}),
            (AnalyzeRequest, {"text": "A selected sentence."}),
            (ChatRequest, {"message": "Explain.", "context_text": "A selected sentence."}),
        ]:
            with self.subTest(model=model.__name__):
                with self.assertRaises(ValidationError):
                    model(operation_id=str(uuid.uuid4()), **values)

    def test_payload_hash_is_canonical_and_covers_cost_affecting_inputs(self):
        first = PagePreloadRequest(
            operation_id="019b63f8-f600-7000-8000-000000000001",
            page_url=_PAGE_URL,
            page_title="Title",
            html=_PAGE_HTML,
            learner_level="  News   reader ",
        )
        equivalent = PagePreloadRequest(
            operation_id="019b63f8-f600-7000-8000-000000000002",
            html=_PAGE_HTML,
            learner_level="News reader",
            page_title="Title",
            page_url=_PAGE_URL,
        )
        changed = equivalent.model_copy(update={"html": _PAGE_HTML + "<p>More.</p>"})

        self.assertNotEqual(
            reading.canonical_payload_hash(first, exclude={"operation_id"}),
            reading.canonical_payload_hash(equivalent, exclude={"operation_id"}),
        )
        self.assertNotEqual(
            reading.canonical_payload_hash(first, exclude={"operation_id"}),
            reading.canonical_payload_hash(changed, exclude={"operation_id"}),
        )

        nested_first = ChatRequest(
            operation_id="019b63f8-f600-7000-8000-000000000003",
            message="Explain.",
            context_text="Text.",
            context_analysis={"operation_id": "model-bound-a"},
        )
        nested_changed = nested_first.model_copy(
            update={"context_analysis": {"operation_id": "model-bound-b"}}
        )
        self.assertNotEqual(
            reading.canonical_payload_hash(nested_first, exclude={"operation_id"}),
            reading.canonical_payload_hash(nested_changed, exclude={"operation_id"}),
        )


class PreloadLeaseRepositoryTests(unittest.TestCase):
    def test_enqueue_confirmation_preserves_fast_worker_state(self):
        record = self.repository.get_by_id("u1", self.record["id"])
        record["enqueue_state"] = "pending"
        record["submitted"] = False
        self.repository.save("u1", record, make_latest=False)
        self.assertTrue(self.repository.mark_enqueue_submitting("u1", self.record["id"]))
        claimed = self.repository.claim_processing(
            "u1",
            self.record["id"],
            "profile",
            lease_id="fast-worker",
            now=self.now,
            lease_expires_at=self.now + timedelta(minutes=1),
        )
        self.assertIsNotNone(claimed)

        self.assertTrue(self.repository.confirm_enqueued("u1", self.record["id"]))
        current = self.repository.get_by_id("u1", self.record["id"])
        self.assertEqual(current["status"], "running")
        self.assertEqual(current["lease_id"], "fast-worker")
        self.assertEqual(current["enqueue_state"], "queued")
        self.assertTrue(current["submitted"])

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repository = JsonPagePreloadRepository(Path(self._tmpdir.name) / "preloads.json")
        self.now = datetime(2026, 7, 31, 23, 59, tzinfo=UTC)
        self.record = {
            "id": "019b63f8-f600-7000-8000-000000000020",
            "operation_id": "019b63f8-f600-7000-8000-000000000020",
            "page_url": _PAGE_URL,
            "status": "processing",
            "learner_profile_fingerprint": "profile",
        }
        self.repository.save("u1", self.record)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_fresh_lease_blocks_duplicate_and_expired_lease_is_reclaimable(self):
        first = self.repository.claim_processing(
            "u1",
            self.record["id"],
            "profile",
            lease_id="019b63f8-f600-7000-8000-000000000021",
            now=self.now,
            lease_expires_at=self.now + timedelta(minutes=5),
        )
        blocked = self.repository.claim_processing(
            "u1",
            self.record["id"],
            "profile",
            lease_id="019b63f8-f600-7000-8000-000000000022",
            now=self.now + timedelta(minutes=1),
            lease_expires_at=self.now + timedelta(minutes=6),
        )
        reclaimed = self.repository.claim_processing(
            "u1",
            self.record["id"],
            "profile",
            lease_id="019b63f8-f600-7000-8000-000000000023",
            now=self.now + timedelta(minutes=6),
            lease_expires_at=self.now + timedelta(minutes=11),
        )

        self.assertEqual(first["attempt_count"], 1)
        self.assertIsNone(blocked)
        self.assertEqual(reclaimed["attempt_count"], 2)
        self.assertEqual(reclaimed["lease_id"], "019b63f8-f600-7000-8000-000000000023")

    def test_only_matching_lease_can_publish_completion(self):
        lease_id = "019b63f8-f600-7000-8000-000000000024"
        claimed = self.repository.claim_processing(
            "u1",
            self.record["id"],
            "profile",
            lease_id=lease_id,
            now=self.now,
            lease_expires_at=self.now + timedelta(minutes=5),
        )
        ready = {**claimed, "status": "ready_pending_usage", "summary": "done"}

        self.assertFalse(
            self.repository.finish_processing(
                "u1", self.record["id"], "profile", ready, lease_id="wrong"
            )
        )
        self.assertTrue(
            self.repository.finish_processing(
                "u1", self.record["id"], "profile", ready, lease_id=lease_id
            )
        )
        completed = {**ready, "status": "ready", "usage_state": "finalized"}
        self.assertFalse(
            self.repository.finish_processing(
                "u1",
                self.record["id"],
                "profile",
                completed,
                lease_id="wrong",
                expected_status="ready_pending_usage",
            )
        )
        self.assertTrue(
            self.repository.finish_processing(
                "u1",
                self.record["id"],
                "profile",
                completed,
                lease_id=lease_id,
                expected_status="ready_pending_usage",
            )
        )

    def test_saves_immutable_records_and_tracks_latest_by_url(self):
        old = {**self.record, "id": "old", "status": "ready", "created_at": "1"}
        new = {**self.record, "id": "new", "status": "processing", "created_at": "2"}

        self.repository.save("u1", old)
        self.repository.save("u1", new)

        self.assertEqual(self.repository.get_by_id("u1", "old")["status"], "ready")
        self.assertEqual(self.repository.get_by_id("u1", "new")["status"], "processing")
        self.assertEqual(self.repository.get_by_page_url("u1", _PAGE_URL)["id"], "new")
        self.assertEqual(
            [record["id"] for record in self.repository.list_for_user("u1")],
            ["new"],
        )


class DynamoPreloadLeaseTests(unittest.TestCase):
    class Store:
        def __init__(self):
            self.items = {}
            self.atomic_writes = 0

        def put_document(self, pk, sk, document, *, extra_attributes=None):
            self.items[(pk, sk)] = (dict(document), dict(extra_attributes or {}))

        def get_document(self, pk, sk):
            item = self.items.get((pk, sk))
            return dict(item[0]) if item else None

        def put_documents_atomically(self, entries):
            self.atomic_writes += 1
            for pk, sk, document, extra_attributes in entries:
                self.put_document(
                    pk,
                    sk,
                    document,
                    extra_attributes=extra_attributes,
                )

        def query_by_pk(self, pk, *, sk_prefix=None):
            return [
                dict(document)
                for (item_pk, sk), (document, _attrs) in self.items.items()
                if item_pk == pk and (sk_prefix is None or sk.startswith(sk_prefix))
            ]

        def conditional_put_document(
            self,
            pk,
            sk,
            document,
            *,
            extra_attributes,
            expected_attributes,
        ):
            current = self.items.get((pk, sk))
            if not current:
                return False
            _document, attrs = current
            if any(attrs.get(key) != value for key, value in expected_attributes.items()):
                return False
            self.put_document(pk, sk, document, extra_attributes=extra_attributes)
            return True

    def test_reclaims_expired_lease_and_requires_matching_completion(self):
        store = self.Store()
        repository = DynamoPagePreloadRepository(store)
        now = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
        repository.save(
            "u1",
            {
                "id": "preload-1",
                "page_url": _PAGE_URL,
                "status": "processing",
                "learner_profile_fingerprint": "profile",
            },
        )
        self.assertEqual(store.atomic_writes, 1)
        first = repository.claim_processing(
            "u1",
            "preload-1",
            "profile",
            lease_id="lease-1",
            now=now,
            lease_expires_at=now + timedelta(minutes=1),
        )
        reclaimed = repository.claim_processing(
            "u1",
            "preload-1",
            "profile",
            lease_id="lease-2",
            now=now + timedelta(minutes=2),
            lease_expires_at=now + timedelta(minutes=3),
        )

        self.assertEqual(first["attempt_count"], 1)
        self.assertEqual(reclaimed["attempt_count"], 2)
        self.assertFalse(
            repository.finish_processing(
                "u1", "preload-1", "profile", reclaimed, lease_id="lease-1"
            )
        )
        self.assertTrue(
            repository.finish_processing(
                "u1", "preload-1", "profile", reclaimed, lease_id="lease-2"
            )
        )

    def test_enqueue_confirmation_preserves_dynamo_worker_lease(self):
        store = self.Store()
        repository = DynamoPagePreloadRepository(store)
        now = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
        repository.save(
            "u1",
            {
                "id": "preload-enqueue",
                "page_url": _PAGE_URL,
                "status": "processing",
                "enqueue_state": "pending",
                "submitted": False,
                "learner_profile_fingerprint": "profile",
            },
        )
        self.assertTrue(repository.mark_enqueue_submitting("u1", "preload-enqueue"))
        repository.claim_processing(
            "u1",
            "preload-enqueue",
            "profile",
            lease_id="fast-worker",
            now=now,
            lease_expires_at=now + timedelta(minutes=1),
        )

        self.assertTrue(repository.confirm_enqueued("u1", "preload-enqueue"))
        current = repository.get_by_id("u1", "preload-enqueue")
        self.assertEqual(current["status"], "running")
        self.assertEqual(current["lease_id"], "fast-worker")
        self.assertEqual(current["enqueue_state"], "queued")
        self.assertTrue(current["submitted"])

    def test_serialized_preload_size_ceiling_allows_near_and_rejects_over(self):
        repository = DynamoPagePreloadRepository(self.Store())
        with mock.patch.dict("os.environ", {"DYNAMODB_PRELOAD_MAX_BYTES": "500"}):
            repository.save(
                "u1",
                {
                    "id": "near",
                    "page_url": _PAGE_URL,
                    "status": "ready",
                    "summary": "x" * 100,
                },
            )
            with self.assertRaisesRegex(Exception, "size ceiling"):
                repository.save(
                    "u1",
                    {
                        "id": "over",
                        "page_url": _PAGE_URL + "/over",
                        "status": "ready",
                        "summary": "x" * 1000,
                    },
                )


class _RecordingRunner:
    """Captures enqueue calls without running the job, so the record stays
    in "processing" for the resubmission tests."""

    def __init__(self):
        self.calls = []

    def enqueue(self, user_id, page_url, preload_id, learner_profile_fingerprint):
        self.calls.append((user_id, page_url, preload_id, learner_profile_fingerprint))


class _UsageAwareRunner(_RecordingRunner):
    def __init__(self, usage, *, fail=False):
        super().__init__()
        self.usage = usage
        self.fail = fail

    def enqueue(
        self, user_id, page_url, preload_id, learner_profile_fingerprint, usage_context=None
    ):
        operation_id = usage_context["operation_id"]
        operation = self.usage.get_operation(user_id, operation_id)
        if not operation or operation.state != "reserved":
            raise AssertionError("preload was enqueued before usage reservation")
        if self.fail:
            raise RuntimeError("queue unavailable")
        self.calls.append(
            (user_id, page_url, preload_id, learner_profile_fingerprint, usage_context)
        )


class SubmitPreloadServiceTests(unittest.TestCase):
    def test_distinct_operation_same_fresh_page_reuses_one_reservation_and_enqueue(self):
        runner = _UsageAwareRunner(self.usage)
        first = self._request().model_copy(
            update={"operation_id": "019b63f8-f600-7000-8000-000000000069"}
        )
        second = first.model_copy(update={"operation_id": "019b63f8-f600-7000-8000-00000000006a"})

        first_response = reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            first,
            usage_meter=self._meter(),
        )
        second_response = reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            second,
            usage_meter=self._meter(),
        )

        self.assertEqual(second_response.status, first_response.status)
        self.assertEqual(
            self.preloads.get_by_page_url("u1", _PAGE_URL)["id"],
            first.operation_id,
        )
        self.assertEqual(len(runner.calls), 1)
        month = self.usage.get_month("u1", current_month())
        self.assertEqual(month["reserved_articles"], 1)

    def test_crash_after_save_before_enqueue_is_reenqueued_once_on_same_operation_replay(self):
        class CrashBeforeEnqueueRunner:
            def enqueue(self, *args, **kwargs):
                raise KeyboardInterrupt("simulated process crash")

        request = self._request().model_copy(
            update={"operation_id": "019b63f8-f600-7000-8000-00000000006b"}
        )
        with self.assertRaisesRegex(KeyboardInterrupt, "simulated process crash"):
            reading.submit_preload(
                self.preloads,
                CrashBeforeEnqueueRunner(),
                self.content,
                "u1",
                request,
                usage_meter=self._meter(),
            )

        pending = self.preloads.get_by_id("u1", request.operation_id)
        self.assertEqual(pending["enqueue_state"], "queued_unconfirmed")
        self.assertTrue(pending["submitted"])
        runner = _UsageAwareRunner(self.usage)
        replay = reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            request,
            usage_meter=self._meter(),
        )
        second_replay = reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            request,
            usage_meter=self._meter(),
        )

        self.assertEqual(replay.status, "processing")
        self.assertEqual(second_replay.status, "processing")
        self.assertEqual(len(runner.calls), 1)
        queued = self.preloads.get_by_id("u1", request.operation_id)
        self.assertEqual(queued["enqueue_state"], "queued")

    def test_fast_worker_completion_is_not_overwritten_after_enqueue_returns(self):
        repository = self.preloads

        class FastRunner(_UsageAwareRunner):
            def enqueue(
                inner_self,
                user_id,
                page_url,
                preload_id,
                learner_profile_fingerprint,
                usage_context=None,
            ):
                super().enqueue(
                    user_id,
                    page_url,
                    preload_id,
                    learner_profile_fingerprint,
                    usage_context,
                )
                now = datetime.now(UTC)
                claimed = repository.claim_processing(
                    user_id,
                    preload_id,
                    learner_profile_fingerprint,
                    lease_id="fast-worker",
                    now=now,
                    lease_expires_at=now + timedelta(minutes=1),
                )
                ready = {
                    **claimed,
                    "status": "ready",
                    "summary": "fast result",
                }
                self.assertTrue(
                    repository.finish_processing(
                        user_id,
                        preload_id,
                        learner_profile_fingerprint,
                        ready,
                        lease_id="fast-worker",
                    )
                )

        request = self._request().model_copy(
            update={"operation_id": "019b63f8-f600-7000-8000-00000000006e"}
        )
        reading.submit_preload(
            repository,
            FastRunner(self.usage),
            self.content,
            "u1",
            request,
            usage_meter=self._meter(),
        )

        current = repository.get_by_id("u1", request.operation_id)
        self.assertEqual(current["status"], "ready")
        self.assertEqual(current["summary"], "fast result")
        self.assertEqual(current["enqueue_state"], "queued")

    def test_replay_enqueue_fast_worker_is_confirmed_without_stale_overwrite(self):
        class CrashBeforeEnqueueRunner:
            def enqueue(self, *args, **kwargs):
                raise KeyboardInterrupt("simulated process crash")

        request = self._request().model_copy(
            update={"operation_id": "019b63f8-f600-7000-8000-000000000073"}
        )
        with self.assertRaises(KeyboardInterrupt):
            reading.submit_preload(
                self.preloads,
                CrashBeforeEnqueueRunner(),
                self.content,
                "u1",
                request,
                usage_meter=self._meter(),
            )
        repository = self.preloads
        pending = repository.get_by_id("u1", request.operation_id)
        pending["enqueue_state"] = "pending"
        pending["submitted"] = False
        repository.save("u1", pending, make_latest=False)

        class FastReplayRunner(_UsageAwareRunner):
            def enqueue(
                inner_self,
                user_id,
                page_url,
                preload_id,
                learner_profile_fingerprint,
                usage_context=None,
            ):
                super().enqueue(
                    user_id,
                    page_url,
                    preload_id,
                    learner_profile_fingerprint,
                    usage_context,
                )
                now = datetime.now(UTC)
                claimed = repository.claim_processing(
                    user_id,
                    preload_id,
                    learner_profile_fingerprint,
                    lease_id="fast-replay-worker",
                    now=now,
                    lease_expires_at=now + timedelta(minutes=1),
                )
                self.assertTrue(
                    repository.finish_processing(
                        user_id,
                        preload_id,
                        learner_profile_fingerprint,
                        {
                            **claimed,
                            "status": "ready",
                            "summary": "replay fast result",
                        },
                        lease_id="fast-replay-worker",
                    )
                )

        response = reading.submit_preload(
            repository,
            FastReplayRunner(self.usage),
            self.content,
            "u1",
            request,
            usage_meter=self._meter(),
        )

        self.assertTrue(response.ready)
        current = repository.get_by_id("u1", request.operation_id)
        self.assertEqual(current["status"], "ready")
        self.assertEqual(current["summary"], "replay fast result")
        self.assertEqual(current["enqueue_state"], "queued")

    def test_post_send_confirmation_failure_keeps_reservation_recoverable(self):
        class FailingConfirmationRepository(JsonPagePreloadRepository):
            confirm_called = False

            def confirm_enqueued(self, user_id, preload_id):
                self.confirm_called = True
                raise RuntimeError("confirmation storage unavailable")

        repository = FailingConfirmationRepository(Path(self._tmpdir.name) / "confirm-failure.json")
        runner = _UsageAwareRunner(self.usage)
        request = self._request().model_copy(
            update={"operation_id": "019b63f8-f600-7000-8000-00000000006f"}
        )

        response = reading.submit_preload(
            repository,
            runner,
            self.content,
            "u1",
            request,
            usage_meter=self._meter(),
        )

        self.assertTrue(repository.confirm_called)
        self.assertEqual(response.status, "processing")
        current = repository.get_by_id("u1", request.operation_id)
        self.assertEqual(current["enqueue_state"], "queued_unconfirmed")
        self.assertTrue(current["submitted"])
        self.assertEqual(
            self.usage.get_operation("u1", request.operation_id).state,
            "reserved",
        )

    def setUp(self):
        self.rate_env = _rate_env_patch()
        self.rate_env.start()
        self.addCleanup(self.rate_env.stop)
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmpdir.name)
        self.preloads = JsonPagePreloadRepository(tmp / "preloads.json")
        self.usage = JsonUsageRepository(tmp / "usage.json")
        self.subs = JsonSubscriptionRepository(tmp / "subs.json")
        self.content = FilesystemPreloadContentStore(tmp / "preload_content")

    def tearDown(self):
        self._tmpdir.cleanup()

    def _request(self):
        return PagePreloadRequest(page_url=_PAGE_URL, page_title="Title", html=_PAGE_HTML)

    def _guard(self):
        return build_guard(self.subs, self.usage, "u1")

    def _meter(self, *, now=None):
        return UsageMeter(
            self.subs,
            self.usage,
            "u1",
            now=now,
            reservation_enabled=True,
        )

    def _submit(self, runner):
        return reading.submit_preload(
            self.preloads, runner, self.content, "u1", self._request(), self._guard()
        )

    def _run_job(self):
        record = self.preloads.get_by_page_url("u1", _PAGE_URL)
        reading.run_preload_job(
            self.preloads,
            self.subs,
            self.usage,
            self.content,
            "u1",
            _PAGE_URL,
            record["id"],
            record["learner_profile_fingerprint"],
        )

    def test_submit_stores_content_outside_record_and_enqueues(self):
        runner = _RecordingRunner()
        response = self._submit(runner)

        self.assertFalse(response.ready)
        self.assertEqual(response.status, "processing")
        self.assertEqual(len(runner.calls), 1)

        stored = self.preloads.get_by_page_url("u1", _PAGE_URL)
        self.assertEqual(stored["status"], "processing")
        self.assertGreater(stored["source_tokens_detected"], 0)
        self.assertGreater(stored["source_tokens_analyzed"], 0)
        self.assertEqual(stored["source_token_limit"], self._guard().plan.source_tokens_per_article)
        self.assertEqual(
            response.preload.source_tokens_analyzed,
            stored["source_tokens_analyzed"],
        )
        # The record no longer carries the raw text; the content store does.
        self.assertNotIn("content", stored)
        self.assertTrue(self.content.get("u1", stored["id"]))
        # No usage recorded until the job completes.
        self.assertEqual(self.usage.get_month("u1", current_month())["articles"], 0)

    def test_enabled_submit_reserves_before_enqueue_and_persists_snapshot(self):
        runner = _UsageAwareRunner(self.usage)
        request = self._request()

        response = reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            request,
            usage_meter=self._meter(),
        )

        stored = self.preloads.get_by_id("u1", response.preload.id)
        operation = self.usage.get_operation("u1", request.operation_id)
        self.assertEqual(operation.state, "reserved")
        self.assertEqual(stored["operation_id"], request.operation_id)
        self.assertEqual(stored["payload_hash"], operation.payload_hash)
        self.assertEqual(stored["usage_month"], operation.month)
        self.assertEqual(stored["rate_card_version"], operation.rate_card_version)
        self.assertEqual(stored["usage_state"], "reserved")
        self.assertGreater(operation.reserved_cost_micro_usd, 0)
        self.assertEqual(runner.calls[0][4]["operation_id"], request.operation_id)

    def test_enqueue_failure_releases_reservation_and_marks_failed(self):
        runner = _UsageAwareRunner(self.usage, fail=True)
        request = self._request()

        with self.assertRaisesRegex(RuntimeError, "queue unavailable"):
            reading.submit_preload(
                self.preloads,
                runner,
                self.content,
                "u1",
                request,
                usage_meter=self._meter(),
            )

        operation = self.usage.get_operation("u1", request.operation_id)
        record = self.preloads.get_by_id("u1", request.operation_id)
        self.assertEqual(operation.state, "released")
        self.assertEqual(operation.release_reason, "enqueue_failed")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["usage_state"], "released")
        self.assertIsNone(self.content.get("u1", request.operation_id))

        retry_runner = _UsageAwareRunner(self.usage)
        replay = reading.submit_preload(
            self.preloads,
            retry_runner,
            self.content,
            "u1",
            request,
            usage_meter=self._meter(),
        )
        self.assertEqual(replay.status, "failed")
        self.assertEqual(retry_runner.calls, [])

    def test_content_store_failure_releases_reservation(self):
        runner = _UsageAwareRunner(self.usage)
        request = self._request().model_copy(
            update={"operation_id": "019b63f8-f600-7000-8000-000000000060"}
        )
        failing_content = mock.Mock()
        failing_content.put.side_effect = RuntimeError("content unavailable")

        with self.assertRaisesRegex(RuntimeError, "content unavailable"):
            reading.submit_preload(
                self.preloads,
                runner,
                failing_content,
                "u1",
                request,
                usage_meter=self._meter(),
            )

        operation = self.usage.get_operation("u1", request.operation_id)
        self.assertEqual(operation.state, "released")
        self.assertEqual(runner.calls, [])

    def test_preload_repository_failure_releases_reservation(self):
        runner = _UsageAwareRunner(self.usage)
        request = self._request().model_copy(
            update={"operation_id": "019b63f8-f600-7000-8000-000000000061"}
        )

        with (
            mock.patch.object(
                self.preloads,
                "save",
                side_effect=RuntimeError("preload unavailable"),
            ),
            self.assertRaisesRegex(RuntimeError, "preload unavailable"),
        ):
            reading.submit_preload(
                self.preloads,
                runner,
                self.content,
                "u1",
                request,
                usage_meter=self._meter(),
            )

        operation = self.usage.get_operation("u1", request.operation_id)
        self.assertEqual(operation.state, "released")
        self.assertIsNone(self.content.get("u1", request.operation_id))
        self.assertEqual(runner.calls, [])

    def test_enqueue_and_release_failure_recovers_without_overwriting_latest(self):
        failing_runner = _UsageAwareRunner(self.usage, fail=True)
        old_request = self._request().model_copy(
            update={"operation_id": "019b63f8-f600-7000-8000-000000000064"}
        )
        old_meter = self._meter()

        with (
            mock.patch.object(
                old_meter,
                "release",
                side_effect=RuntimeError("usage release unavailable"),
            ),
            self.assertRaises(RuntimeError),
        ):
            reading.submit_preload(
                self.preloads,
                failing_runner,
                self.content,
                "u1",
                old_request,
                usage_meter=old_meter,
            )

        pending = self.preloads.get_by_id("u1", old_request.operation_id)
        self.assertEqual(pending["status"], "failed_pending_release")
        self.assertEqual(pending["usage_state"], "pending_release")
        self.assertIsNotNone(self.content.get("u1", old_request.operation_id))

        new_request = self._request().model_copy(
            update={"operation_id": "019b63f8-f600-7000-8000-000000000065"}
        )
        new_runner = _UsageAwareRunner(self.usage)
        reading.submit_preload(
            self.preloads,
            new_runner,
            self.content,
            "u1",
            new_request,
            usage_meter=self._meter(),
        )

        replay = reading.submit_preload(
            self.preloads,
            new_runner,
            self.content,
            "u1",
            old_request,
            usage_meter=self._meter(),
        )

        self.assertEqual(replay.status, "failed")
        self.assertEqual(
            self.preloads.get_by_page_url("u1", _PAGE_URL)["id"],
            new_request.operation_id,
        )
        self.assertIsNone(self.content.get("u1", old_request.operation_id))
        self.assertEqual(len(new_runner.calls), 1)

    def test_enabled_preload_same_operation_different_payload_conflicts(self):
        runner = _UsageAwareRunner(self.usage)
        request = self._request()
        reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            request,
            usage_meter=self._meter(),
        )
        changed = request.model_copy(update={"html": request.html + "<p>Changed.</p>"})

        with self.assertRaisesRegex(Exception, "different payload"):
            reading.submit_preload(
                self.preloads,
                runner,
                self.content,
                "u1",
                changed,
                usage_meter=self._meter(),
            )

        self.assertEqual(len(runner.calls), 1)

    def test_enabled_preload_same_operation_replays_without_second_enqueue(self):
        runner = _UsageAwareRunner(self.usage)
        request = self._request()

        first = reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            request,
            usage_meter=self._meter(),
        )
        replay = reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            request,
            usage_meter=self._meter(),
        )

        self.assertEqual(replay.preload.id, first.preload.id)
        self.assertEqual(len(runner.calls), 1)

    def test_submit_rejects_when_source_cap_cannot_fit_one_sentence(self):
        runner = _RecordingRunner()
        guard = types.SimpleNamespace(
            plan=types.SimpleNamespace(
                sentences_per_article=10,
                source_tokens_per_article=1,
            ),
            check_article=mock.Mock(),
        )

        with self.assertRaises(pipeline.PipelineError) as raised:
            reading.submit_preload(
                self.preloads,
                runner,
                self.content,
                "u1",
                self._request(),
                guard,
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIsNone(self.preloads.get_by_page_url("u1", _PAGE_URL))
        self.assertEqual(runner.calls, [])

    def test_submit_defaults_and_retains_vocabulary_coverage(self):
        runner = _RecordingRunner()
        response = self._submit(runner)
        stored = self.preloads.get_by_page_url("u1", _PAGE_URL)

        self.assertEqual(stored["vocabulary_coverage_percent"], 8.0)
        self.assertEqual(response.preload.vocabulary_coverage_percent, 8.0)

    def test_worker_uses_requested_vocabulary_coverage(self):
        runner = _RecordingRunner()
        request = PagePreloadRequest(
            page_url=_PAGE_URL,
            page_title="Title",
            html=_PAGE_HTML,
            learner_level="TOEIC 500点程度",
            vocabulary_coverage_percent=18.0,
        )
        reading.submit_preload(self.preloads, runner, self.content, "u1", request, self._guard())
        indexed_sentences = [
            {
                "id": "sentence-1",
                "index": 0,
                "text": "A difficult sentence.",
                "analysis": {
                    "translation": "",
                    "grammar": "",
                    "nuance": "",
                    "vocabulary": [],
                    "examples": [],
                    "study_tip": "",
                },
            }
        ]
        coverage_calls = []

        def analyze_stub(*args, **kwargs):
            coverage_calls.append(("analyze", kwargs["vocabulary_coverage_percent"]))
            return "", [], indexed_sentences

        def extract_stub(*args, **kwargs):
            coverage_calls.append(("extract", kwargs["vocabulary_coverage_percent"]))
            return [], {
                "coverage_percent": kwargs["vocabulary_coverage_percent"],
                "pool_size": 0,
                "target_count": 0,
                "item_count": 0,
                "candidate_count": 0,
            }

        with (
            mock.patch.object(
                preloading, "_split_sentences", return_value=["A difficult sentence."]
            ),
            mock.patch.object(preloading, "_analyze_sentences", side_effect=analyze_stub),
            mock.patch.object(preloading, "_extract_study_items", side_effect=extract_stub),
        ):
            self._run_job()

        record = self.preloads.get_by_page_url("u1", _PAGE_URL)
        self.assertEqual(coverage_calls, [("analyze", 18.0), ("extract", 18.0)])
        self.assertEqual(record["vocabulary_coverage_percent"], 18.0)
        self.assertEqual(record["vocabulary_coverage"]["coverage_percent"], 18.0)

    def test_fresh_processing_short_circuits(self):
        runner = _RecordingRunner()
        first = self._submit(runner)
        second = self._submit(runner)

        # Second submit returns the same record without enqueueing again.
        self.assertEqual(first.preload.id, second.preload.id)
        self.assertEqual(len(runner.calls), 1)

    def test_fresh_processing_is_replaced_for_a_new_learner_profile(self):
        runner = _RecordingRunner()
        first = reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            PagePreloadRequest(
                page_url=_PAGE_URL,
                page_title="Title",
                html=_PAGE_HTML,
                learner_level="TOEIC 500点程度",
                vocabulary_coverage_percent=18.0,
            ),
            self._guard(),
        )
        second = reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            PagePreloadRequest(
                page_url=_PAGE_URL,
                page_title="Title",
                html=_PAGE_HTML,
                learner_level="TOEIC 900点程度",
                vocabulary_coverage_percent=7.0,
            ),
            self._guard(),
        )

        self.assertNotEqual(first.preload.id, second.preload.id)
        self.assertEqual(len(runner.calls), 2)
        stored = self.preloads.get_by_page_url("u1", _PAGE_URL)
        self.assertEqual(stored["learner_level"], "TOEIC 900点程度")
        self.assertEqual(stored["vocabulary_coverage_percent"], 7.0)
        self.assertTrue(stored["learner_profile_fingerprint"])

    def test_processing_dedupe_normalizes_learner_profile_whitespace(self):
        runner = _RecordingRunner()
        first = reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            PagePreloadRequest(
                page_url=_PAGE_URL,
                page_title="Title",
                html=_PAGE_HTML,
                learner_level="News  reader\nwith notes",
                vocabulary_coverage_percent=12.0,
            ),
            self._guard(),
        )
        second = reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            PagePreloadRequest(
                page_url=_PAGE_URL,
                page_title="Title",
                html=_PAGE_HTML,
                learner_level=" News reader   with\t notes ",
                vocabulary_coverage_percent=12.0,
            ),
            self._guard(),
        )

        self.assertEqual(first.preload.id, second.preload.id)
        self.assertEqual(len(runner.calls), 1)

    def test_old_job_cannot_overwrite_newer_profile_record(self):
        runner = _RecordingRunner()
        first = reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            PagePreloadRequest(
                page_url=_PAGE_URL,
                page_title="Title",
                html=_PAGE_HTML,
                learner_level="TOEIC 500点程度",
                vocabulary_coverage_percent=18.0,
            ),
            self._guard(),
        )
        old_job = runner.calls[-1]
        second = reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            PagePreloadRequest(
                page_url=_PAGE_URL,
                page_title="Title",
                html=_PAGE_HTML,
                learner_level="TOEIC 900点程度",
                vocabulary_coverage_percent=7.0,
            ),
            self._guard(),
        )
        new_job = runner.calls[-1]
        self.assertTrue(self.content.get("u1", first.preload.id))
        self.assertTrue(self.content.get("u1", second.preload.id))

        with mock.patch.object(pipeline, "_client", _fake_openai_client):
            reading.run_preload_job(self.preloads, self.subs, self.usage, self.content, *old_job)

        current = self.preloads.get_by_page_url("u1", _PAGE_URL)
        self.assertEqual(current["id"], second.preload.id)
        self.assertEqual(current["status"], "processing")
        self.assertEqual(self.usage.get_month("u1", current_month())["articles"], 0)
        self.assertTrue(self.content.get("u1", second.preload.id))

        with mock.patch.object(pipeline, "_client", _fake_openai_client):
            reading.run_preload_job(self.preloads, self.subs, self.usage, self.content, *new_job)
            reading.run_preload_job(self.preloads, self.subs, self.usage, self.content, *new_job)

        current = self.preloads.get_by_page_url("u1", _PAGE_URL)
        self.assertEqual(current["id"], second.preload.id)
        self.assertEqual(current["status"], "ready")
        self.assertEqual(self.usage.get_month("u1", current_month())["articles"], 1)
        self.assertIsNone(self.content.get("u1", second.preload.id))

    def test_stale_processing_is_replaced(self):
        runner = _RecordingRunner()
        first = self._submit(runner)

        stale = self.preloads.get_by_page_url("u1", _PAGE_URL)
        stale["requested_at"] = (datetime.now(UTC) - timedelta(minutes=16)).isoformat()
        self.preloads.save("u1", stale)

        second = self._submit(runner)
        self.assertNotEqual(first.preload.id, second.preload.id)
        self.assertEqual(len(runner.calls), 2)

    def test_failed_record_is_replaced(self):
        runner = _RecordingRunner()
        self._submit(runner)
        failed = self.preloads.get_by_page_url("u1", _PAGE_URL)
        failed["status"] = "failed"
        failed["error"] = "boom"
        self.preloads.save("u1", failed)

        response = self._submit(runner)
        self.assertEqual(response.status, "processing")
        self.assertEqual(len(runner.calls), 2)

    def test_run_job_completes_records_usage_and_clears_content(self):
        runner = _RecordingRunner()
        self._submit(runner)

        with mock.patch.object(pipeline, "_client", _fake_openai_client):
            self._run_job()

        record = self.preloads.get_by_page_url("u1", _PAGE_URL)
        self.assertEqual(record["status"], "ready")
        self.assertIsNone(record.get("error"))
        self.assertTrue(record["sentences"])
        self.assertEqual(record["summary"], "article summary")
        # The ready record never carries the raw text...
        self.assertNotIn("content", record)
        # ...and the handoff payload was deleted from the content store.
        self.assertIsNone(self.content.get("u1", record["id"]))
        self.assertEqual(self.usage.get_month("u1", current_month())["articles"], 1)

    def test_run_job_failure_marks_failed_without_usage(self):
        runner = _RecordingRunner()
        self._submit(runner)

        with mock.patch.object(pipeline, "_client", _failing_openai_client):
            self._run_job()

        record = self.preloads.get_by_page_url("u1", _PAGE_URL)
        self.assertEqual(record["status"], "failed")
        self.assertTrue(record["error"])
        self.assertEqual(self.usage.get_month("u1", current_month())["articles"], 0)

    def test_run_job_with_missing_content_marks_failed_without_usage(self):
        runner = _RecordingRunner()
        self._submit(runner)
        # Simulate a lost/expired handoff payload (e.g. the transient store
        # expired the object before the worker ran).
        record = self.preloads.get_by_page_url("u1", _PAGE_URL)
        self.content.delete("u1", record["id"])

        with mock.patch.object(pipeline, "_client", _fake_openai_client):
            self._run_job()

        record = self.preloads.get_by_page_url("u1", _PAGE_URL)
        self.assertEqual(record["status"], "failed")
        self.assertTrue(record["error"])
        self.assertEqual(self.usage.get_month("u1", current_month())["articles"], 0)

    def test_run_job_falls_back_to_legacy_inline_content(self):
        # A record written by the old code carries the text inline and has no
        # entry in the content store; the job must still complete from it.
        now = datetime.now(UTC).isoformat()
        legacy = {
            "id": "legacy-processing-1",
            "page_url": _PAGE_URL,
            "page_title": "Title",
            "content": "The quick brown fox jumps over the lazy dog every morning.",
            "status": "processing",
            "error": None,
            "requested_at": now,
            "created_at": now,
            "learner_profile_fingerprint": preloading._learner_profile_fingerprint(None, 8.0),
        }
        self.preloads.save("u1", legacy)
        self.assertIsNone(self.content.get("u1", legacy["id"]))

        with mock.patch.object(pipeline, "_client", _fake_openai_client):
            self._run_job()

        record = self.preloads.get_by_page_url("u1", _PAGE_URL)
        self.assertEqual(record["status"], "ready")
        self.assertNotIn("content", record)
        self.assertEqual(self.usage.get_month("u1", current_month())["articles"], 1)

    def test_run_job_is_idempotent_on_ready_record(self):
        runner = _RecordingRunner()
        self._submit(runner)
        with mock.patch.object(pipeline, "_client", _fake_openai_client):
            self._run_job()
            # A redelivered SQS message must not re-run or double-count usage.
            self._run_job()

        self.assertEqual(self.usage.get_month("u1", current_month())["articles"], 1)

    def test_enabled_worker_persists_pending_then_repairs_settlement_without_model_replay(self):
        runner = _UsageAwareRunner(self.usage)
        request = self._request()
        reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            request,
            usage_meter=self._meter(now=datetime(2026, 7, 31, 23, 59, tzinfo=UTC)),
        )
        job = runner.calls[0]
        analyzed = mock.Mock(
            return_value=(
                "summary",
                [],
                [
                    {
                        "id": "s1",
                        "index": 0,
                        "text": "Sentence.",
                        "analysis": {
                            "translation": "",
                            "grammar": "",
                            "nuance": "",
                            "vocabulary": [],
                            "examples": [],
                            "study_tip": "",
                        },
                    }
                ],
            )
        )

        with (
            mock.patch.object(preloading, "_split_sentences", return_value=["Sentence."]),
            mock.patch.object(preloading, "_analyze_sentences", analyzed),
            mock.patch.object(preloading, "_extract_study_items", return_value=([], {})),
            mock.patch.object(
                UsageMeter, "finalize", side_effect=RuntimeError("settlement unavailable")
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "settlement unavailable"):
                reading.run_preload_job(self.preloads, self.subs, self.usage, self.content, *job)

        pending = self.preloads.get_by_id("u1", request.operation_id)
        self.assertEqual(pending["status"], "ready_pending_usage")
        self.assertEqual(pending["usage_state"], "reserved")
        self.assertEqual(self.usage.get_operation("u1", request.operation_id).state, "reserved")

        with mock.patch.object(preloading, "_analyze_sentences", analyzed):
            reading.run_preload_job(self.preloads, self.subs, self.usage, self.content, *job)
            reading.run_preload_job(self.preloads, self.subs, self.usage, self.content, *job)

        ready = self.preloads.get_by_id("u1", request.operation_id)
        operation = self.usage.get_operation("u1", request.operation_id)
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["usage_state"], "finalized")
        self.assertEqual(operation.state, "finalized")
        self.assertEqual(operation.month, "2026-07")
        analyzed.assert_called_once()

    def test_enabled_worker_repairs_failed_pending_usage_without_provider_replay(self):
        runner = _UsageAwareRunner(self.usage)
        request = self._request()
        reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            request,
            usage_meter=self._meter(),
        )
        job = runner.calls[0]
        provider = mock.Mock(
            side_effect=pipeline.PipelineError(
                "provider lost",
                status_code=502,
                dispatch_attempted=True,
            )
        )

        with (
            mock.patch.object(preloading, "_split_sentences", provider),
            mock.patch.object(
                UsageMeter,
                "finalize",
                side_effect=RuntimeError("settlement unavailable"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "settlement unavailable"):
                reading.run_preload_job(self.preloads, self.subs, self.usage, self.content, *job)

        pending = self.preloads.get_by_id("u1", request.operation_id)
        self.assertEqual(pending["status"], "failed_pending_usage")

        reading.run_preload_job(self.preloads, self.subs, self.usage, self.content, *job)
        failed = self.preloads.get_by_id("u1", request.operation_id)
        operation = self.usage.get_operation("u1", request.operation_id)
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["usage_state"], "finalized_conservative")
        self.assertEqual(operation.state, "finalized")
        provider.assert_called_once()

    def test_released_expired_operation_blocks_worker_provider_dispatch(self):
        runner = _UsageAwareRunner(self.usage)
        request = self._request()
        reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            request,
            usage_meter=self._meter(),
        )
        self.usage.release("u1", request.operation_id, reason="reservation_expired")
        provider = mock.Mock()

        with mock.patch.object(preloading, "_split_sentences", provider):
            reading.run_preload_job(
                self.preloads, self.subs, self.usage, self.content, *runner.calls[0]
            )

        provider.assert_not_called()
        self.assertEqual(self.usage.get_operation("u1", request.operation_id).state, "released")

    def test_worker_renews_expired_timestamp_before_provider_dispatch(self):
        runner = _UsageAwareRunner(self.usage)
        request = self._request()
        reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            request,
            usage_meter=self._meter(now=datetime(2026, 7, 1, 0, 0, tzinfo=UTC)),
        )
        observed = []

        def split(*args, **kwargs):
            operation = self.usage.get_operation("u1", request.operation_id)
            observed.append(operation.expires_at)
            self.assertGreater(operation.expires_at, datetime.now(UTC))
            return ["Sentence."]

        with (
            mock.patch.object(preloading, "_split_sentences", side_effect=split),
            mock.patch.object(
                preloading,
                "_analyze_sentences",
                return_value=("summary", [], []),
            ),
            mock.patch.object(preloading, "_extract_study_items", return_value=([], {})),
        ):
            reading.run_preload_job(
                self.preloads, self.subs, self.usage, self.content, *runner.calls[0]
            )

        self.assertEqual(len(observed), 1)
        self.assertEqual(
            self.usage.get_operation("u1", request.operation_id).state,
            "finalized",
        )

    def test_worker_reclaimed_expired_lease_emits_safe_recovery_event(self):
        runner = _UsageAwareRunner(self.usage)
        request = self._request()
        reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            request,
            usage_meter=self._meter(),
        )
        job = runner.calls[0]
        moment = datetime.now(UTC)
        claimed = self.preloads.claim_processing(
            "u1",
            request.operation_id,
            job[3],
            lease_id="expired-private-worker",
            now=moment - timedelta(minutes=2),
            lease_expires_at=moment - timedelta(minutes=1),
        )
        self.assertIsNotNone(claimed)

        with (
            mock.patch.object(preloading, "_split_sentences", return_value=["Sentence."]),
            mock.patch.object(
                preloading,
                "_analyze_sentences",
                return_value=("summary", [], []),
            ),
            mock.patch.object(preloading, "_extract_study_items", return_value=([], {})),
            self.assertLogs("untangle.backend", level="INFO") as captured,
        ):
            reading.run_preload_job(self.preloads, self.subs, self.usage, self.content, *job)

        recovery_logs = [
            line for line in captured.output if '"event": "execution_lease_recovered"' in line
        ]
        self.assertEqual(len(recovery_logs), 1)
        self.assertIn('"kind": "preload"', recovery_logs[0])
        self.assertNotIn("expired-private-worker", recovery_logs[0])
        self.assertNotIn(_PAGE_HTML, recovery_logs[0])

    def test_disabled_article_runtime_observes_shadow_without_double_counting(self):
        runner = _RecordingRunner()
        request = self._request()
        meter = UsageMeter(
            self.subs,
            self.usage,
            "u1",
            reservation_enabled=False,
        )
        response = reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            request,
            guard=self._guard(),
            usage_meter=meter,
        )
        self.assertEqual(uuid.UUID(response.preload.id).version, 7)
        self.assertEqual(uuid.UUID(response.preload.id).variant, uuid.RFC_4122)

        def split(*args, **kwargs):
            tally = kwargs["tally"]
            tally.mark_dispatch_attempt()
            tally.add_response(
                types.SimpleNamespace(
                    model=pipeline.OPENAI_MODEL,
                    usage=types.SimpleNamespace(input_tokens=3, output_tokens=2, total_tokens=5),
                )
            )
            return ["Sentence."]

        with (
            mock.patch.object(preloading, "_split_sentences", side_effect=split),
            mock.patch.object(
                preloading,
                "_analyze_sentences",
                return_value=("summary", [], []),
            ),
            mock.patch.object(preloading, "_extract_study_items", return_value=([], {})),
            self.assertLogs("untangle.usage", level="INFO") as captured,
        ):
            reading.run_preload_job(
                self.preloads,
                self.subs,
                self.usage,
                self.content,
                *runner.calls[0],
            )

        shadow = [line for line in captured.output if '"event": "usage_shadow_observed"' in line]
        self.assertEqual(len(shadow), 1)
        event = json.loads(shadow[0].split(":", 2)[-1].strip())
        self.assertEqual(event["meter"], "article")
        self.assertEqual(event["outcome"], "succeeded")
        month = self.usage.get_month("u1", current_month())
        self.assertEqual(month["articles"], 1)
        self.assertEqual(month["reserved_articles"], 0)
        self.assertEqual(month["committed_articles"], 0)

    def test_worker_finalizes_pinned_july_period_after_august_rollover(self):
        runner = _UsageAwareRunner(self.usage)
        request = self._request().model_copy(
            update={"operation_id": "019b63f8-f600-7000-8000-000000000062"}
        )
        july = datetime(2026, 7, 31, 23, 59, tzinfo=UTC)
        reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            request,
            usage_meter=self._meter(now=july),
        )

        class AugustDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                value = datetime(2026, 8, 1, 0, 1, tzinfo=UTC)
                return value if tz else value.replace(tzinfo=None)

        with (
            mock.patch.object(preloading, "datetime", AugustDateTime),
            mock.patch.object(preloading, "_split_sentences", return_value=["Sentence."]),
            mock.patch.object(
                preloading,
                "_analyze_sentences",
                return_value=("summary", [], []),
            ),
            mock.patch.object(preloading, "_extract_study_items", return_value=([], {})),
        ):
            reading.run_preload_job(
                self.preloads, self.subs, self.usage, self.content, *runner.calls[0]
            )

        operation = self.usage.get_operation("u1", request.operation_id)
        self.assertEqual(operation.month, "2026-07")
        self.assertEqual(operation.state, "finalized")
        self.assertEqual(self.usage.get_month("u1", "2026-07")["committed_articles"], 1)
        self.assertEqual(self.usage.get_month("u1", "2026-08")["committed_articles"], 0)

    def test_worker_heartbeats_during_processing_beyond_lease_ttl(self):
        runner = _UsageAwareRunner(self.usage)
        request = self._request().model_copy(
            update={"operation_id": "019b63f8-f600-7000-8000-000000000063"}
        )
        reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            request,
            usage_meter=self._meter(),
        )
        entered = threading.Event()
        release = threading.Event()
        calls = []

        def slow_split(*args, **kwargs):
            calls.append(threading.get_ident())
            if len(calls) == 1:
                entered.set()
                self.assertTrue(release.wait(3))
            return ["Sentence."]

        def run_worker():
            reading.run_preload_job(
                self.preloads, self.subs, self.usage, self.content, *runner.calls[0]
            )

        with (
            mock.patch.dict("os.environ", {"PRELOAD_WORKER_LEASE_SECONDS": "1"}),
            mock.patch.object(preloading, "_split_sentences", side_effect=slow_split),
            mock.patch.object(
                preloading,
                "_analyze_sentences",
                return_value=("summary", [], []),
            ),
            mock.patch.object(preloading, "_extract_study_items", return_value=([], {})),
        ):
            first = threading.Thread(target=run_worker)
            first.start()
            self.assertTrue(entered.wait(1))
            time.sleep(1.2)
            active_operation = self.usage.get_operation("u1", request.operation_id)
            self.assertGreater(active_operation.expires_at, datetime.now(UTC))
            run_worker()
            self.assertEqual(len(calls), 1)
            release.set()
            first.join(3)

        self.assertFalse(first.is_alive())
        self.assertEqual(
            self.usage.get_operation("u1", request.operation_id).state,
            "finalized",
        )

    def test_oversized_preload_result_settles_without_provider_replay(self):
        runner = _UsageAwareRunner(self.usage)
        request = self._request().model_copy(
            update={"operation_id": "019b63f8-f600-7000-8000-000000000066"}
        )
        reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            request,
            usage_meter=self._meter(),
        )
        original_finish = self.preloads.finish_processing

        def limited_finish(*args, **kwargs):
            record = args[3]
            if record.get("status") == "ready_pending_usage":
                raise preload_repository_module.PreloadResultTooLarge(
                    "preload result exceeds size ceiling"
                )
            return original_finish(*args, **kwargs)

        provider = mock.Mock(return_value=["Sentence."])
        with (
            mock.patch.object(preloading, "_split_sentences", provider),
            mock.patch.object(
                preloading,
                "_analyze_sentences",
                return_value=("summary", [], []),
            ),
            mock.patch.object(preloading, "_extract_study_items", return_value=([], {})),
            mock.patch.object(
                self.preloads,
                "finish_processing",
                side_effect=limited_finish,
            ),
        ):
            reading.run_preload_job(
                self.preloads, self.subs, self.usage, self.content, *runner.calls[0]
            )
            reading.run_preload_job(
                self.preloads, self.subs, self.usage, self.content, *runner.calls[0]
            )

        operation = self.usage.get_operation("u1", request.operation_id)
        self.assertEqual(operation.state, "finalized")
        self.assertEqual(
            operation.actual_cost_micro_usd,
            operation.reserved_cost_micro_usd,
        )
        self.assertEqual(
            self.preloads.get_by_id("u1", request.operation_id)["status"],
            "failed",
        )
        provider.assert_called_once()

    def test_prior_article_dispatch_prevents_release_after_later_local_failure(self):
        runner = _UsageAwareRunner(self.usage)
        request = self._request().model_copy(
            update={"operation_id": "019b63f8-f600-7000-8000-000000000067"}
        )
        reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            request,
            usage_meter=self._meter(),
        )

        def dispatched_split(*args, **kwargs):
            kwargs["tally"].mark_dispatch_attempt()
            return ["Sentence."]

        with (
            mock.patch.object(
                preloading,
                "_split_sentences",
                side_effect=dispatched_split,
            ),
            mock.patch.object(
                preloading,
                "_analyze_sentences",
                side_effect=ValueError("local response processing failed"),
            ),
        ):
            reading.run_preload_job(
                self.preloads,
                self.subs,
                self.usage,
                self.content,
                *runner.calls[0],
            )

        operation = self.usage.get_operation("u1", request.operation_id)
        self.assertEqual(operation.state, "finalized")
        self.assertEqual(
            operation.actual_cost_micro_usd,
            operation.reserved_cost_micro_usd,
        )

    def test_fallback_split_agent_failure_is_settled_as_dispatched_cost(self):
        runner = _UsageAwareRunner(self.usage)
        request = self._request().model_copy(
            update={"operation_id": "019b63f8-f600-7000-8000-000000000068"}
        )
        reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            request,
            usage_meter=self._meter(),
        )
        client = mock.Mock()
        client.chat.completions.create.side_effect = RuntimeError("fallback agent connection lost")

        with (
            mock.patch.object(
                pipeline,
                "_split_article_chunk_one_shot",
                return_value=[],
            ),
            mock.patch.object(pipeline, "_client", return_value=client),
        ):
            reading.run_preload_job(
                self.preloads,
                self.subs,
                self.usage,
                self.content,
                *runner.calls[0],
            )

        operation = self.usage.get_operation("u1", request.operation_id)
        self.assertEqual(operation.state, "finalized")
        self.assertEqual(
            operation.actual_cost_micro_usd,
            operation.reserved_cost_micro_usd,
        )
        client.chat.completions.create.assert_called_once()

    def test_ready_pending_expiry_reclaims_usage_and_retry_publishes_ready(self):
        runner = _UsageAwareRunner(self.usage)
        request = self._request().model_copy(
            update={"operation_id": "019b63f8-f600-7000-8000-00000000006c"}
        )
        reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            request,
            usage_meter=self._meter(),
        )
        job = runner.calls[0]
        with (
            mock.patch.object(preloading, "_split_sentences", return_value=["Sentence."]),
            mock.patch.object(
                preloading,
                "_analyze_sentences",
                return_value=("summary", [], []),
            ),
            mock.patch.object(preloading, "_extract_study_items", return_value=([], {})),
            mock.patch.object(
                UsageMeter,
                "finalize",
                side_effect=RuntimeError("settlement unavailable"),
            ),
            self.assertRaisesRegex(RuntimeError, "settlement unavailable"),
        ):
            reading.run_preload_job(
                self.preloads,
                self.subs,
                self.usage,
                self.content,
                *job,
            )

        pending = self.preloads.get_by_id("u1", request.operation_id)
        self.assertEqual(pending["status"], "ready_pending_usage")
        self.assertIsNotNone(self.usage.get_result("u1", request.operation_id))
        usage_items = json.loads(self.usage._path.read_text())
        for item in usage_items:
            if (
                item.get("record_type") == "usage_operation"
                and item.get("operation_id") == request.operation_id
            ):
                item["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        write_json_list(self.usage._path, usage_items)
        self.assertEqual(
            self.usage.reclaim_expired("u1", datetime.now(UTC)),
            1,
        )

        with mock.patch.object(
            preloading,
            "_split_sentences",
            side_effect=AssertionError("provider must not replay"),
        ):
            reading.run_preload_job(
                self.preloads,
                self.subs,
                self.usage,
                self.content,
                *job,
            )

        ready = self.preloads.get_by_id("u1", request.operation_id)
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(
            self.usage.get_operation("u1", request.operation_id).state,
            "finalized",
        )

    def test_lease_loss_after_dispatch_persists_conservative_usage_result(self):
        runner = _UsageAwareRunner(self.usage)
        request = self._request().model_copy(
            update={"operation_id": "019b63f8-f600-7000-8000-00000000006d"}
        )
        reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            request,
            usage_meter=self._meter(),
        )

        def dispatched_split(*args, **kwargs):
            kwargs["tally"].mark_dispatch_attempt()
            return ["Sentence."]

        with (
            mock.patch.object(
                preloading,
                "_split_sentences",
                side_effect=dispatched_split,
            ),
            mock.patch.object(
                preloading,
                "_analyze_sentences",
                return_value=("summary", [], []),
            ),
            mock.patch.object(preloading, "_extract_study_items", return_value=([], {})),
            mock.patch.object(
                preloading._PreloadHeartbeat,
                "stop_and_verify",
                return_value=False,
            ),
        ):
            reading.run_preload_job(
                self.preloads,
                self.subs,
                self.usage,
                self.content,
                *runner.calls[0],
            )

        result = self.usage.get_result("u1", request.operation_id)
        self.assertIsNotNone(result)
        self.assertEqual(
            result["usage"]["actual_cost_micro_usd"],
            self.usage.get_operation("u1", request.operation_id).reserved_cost_micro_usd,
        )
        self.assertEqual(
            self.preloads.get_by_id("u1", request.operation_id)["status"],
            "ready",
        )
        self.assertEqual(
            self.usage.get_operation("u1", request.operation_id).state,
            "finalized",
        )

    def test_preload_dispatch_callback_persists_marker_before_provider_create(self):
        meter = self._meter()
        operation = meter.reserve(
            "019b63f8-f600-7000-8000-000000000070",
            "payload",
            "article",
            37,
        )
        tally = reading.UsageTally(rate=meter.rate)
        preloading._configure_preload_dispatch_marker(meter, operation, tally)

        client = mock.Mock()
        client.chat.completions.create.side_effect = SystemExit(
            "simulated hard death after dispatch marker"
        )
        with self.assertRaisesRegex(SystemExit, "simulated hard death"):
            pipeline._create_chat_completion_at_dispatch_boundary(
                client,
                tally=tally,
                model="test",
                messages=[],
            )

        marker = self.usage.get_result("u1", operation.operation_id)
        self.assertEqual(marker["state"], "dispatching")
        self.assertEqual(marker["usage"]["actual_cost_micro_usd"], 37)

    def test_finalized_crash_markers_repair_processing_and_running_without_replay(self):
        for index, (preload_status, result_state, actual_cost) in enumerate(
            (
                ("processing", "dispatching", None),
                ("running", "completed", 7),
            )
        ):
            with self.subTest(status=preload_status):
                operation_id = f"019b63f8-f600-7000-8000-{71 + index:012d}"
                runner = _UsageAwareRunner(self.usage)
                request = self._request().model_copy(
                    update={
                        "operation_id": operation_id,
                        "page_url": f"{_PAGE_URL}/{index}",
                    }
                )
                reading.submit_preload(
                    self.preloads,
                    runner,
                    self.content,
                    "u1",
                    request,
                    usage_meter=self._meter(),
                )
                if preload_status == "running":
                    now = datetime.now(UTC)
                    self.preloads.claim_processing(
                        "u1",
                        operation_id,
                        runner.calls[0][3],
                        lease_id="dead-worker",
                        now=now,
                        lease_expires_at=now + timedelta(minutes=1),
                    )
                operation = self.usage.get_operation("u1", operation_id)
                cost = operation.reserved_cost_micro_usd if actual_cost is None else actual_cost
                with self.assertRaisesRegex(SystemExit, "after durable result"):
                    self.usage.save_result(
                        "u1",
                        operation_id,
                        {
                            "kind": "preload",
                            "state": result_state,
                            "usage": {"actual_cost_micro_usd": cost},
                        },
                    )
                    raise SystemExit("simulated hard death after durable result")
                usage_items = json.loads(self.usage._path.read_text())
                for item in usage_items:
                    if (
                        item.get("record_type") == "usage_operation"
                        and item.get("operation_id") == operation_id
                    ):
                        item["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
                write_json_list(self.usage._path, usage_items)
                self.assertEqual(
                    self.usage.reclaim_expired("u1", datetime.now(UTC)),
                    1,
                )

                with mock.patch.object(
                    preloading,
                    "_split_sentences",
                    side_effect=AssertionError("provider must not replay"),
                ):
                    reading.run_preload_job(
                        self.preloads,
                        self.subs,
                        self.usage,
                        self.content,
                        *runner.calls[0],
                    )

                repaired = self.preloads.get_by_id("u1", operation_id)
                self.assertEqual(repaired["status"], "failed")
                self.assertIn("interrupted", repaired["error"].lower())

    def test_expired_sqs_retry_settles_crash_marker_before_renewal_or_provider(self):
        for index, (result_state, actual_cost) in enumerate(
            (("dispatching", None), ("completed", 9))
        ):
            with self.subTest(state=result_state):
                operation_id = f"019b63f8-f600-7000-8000-{81 + index:012d}"
                runner = _UsageAwareRunner(self.usage)
                request = self._request().model_copy(
                    update={
                        "operation_id": operation_id,
                        "page_url": f"{_PAGE_URL}/direct-retry-{index}",
                    }
                )
                reading.submit_preload(
                    self.preloads,
                    runner,
                    self.content,
                    "u1",
                    request,
                    usage_meter=self._meter(),
                )
                now = datetime.now(UTC)
                self.preloads.claim_processing(
                    "u1",
                    operation_id,
                    runner.calls[0][3],
                    lease_id="dead-worker",
                    now=now - timedelta(seconds=2),
                    lease_expires_at=now - timedelta(seconds=1),
                )
                meter = self._meter()
                meter.claim_execution(
                    operation_id,
                    "dead-execution",
                    now - timedelta(seconds=2),
                    now - timedelta(seconds=1),
                )
                operation = self.usage.get_operation("u1", operation_id)
                self.usage.save_result(
                    "u1",
                    operation_id,
                    {
                        "kind": "preload",
                        "state": result_state,
                        "usage": {
                            "actual_cost_micro_usd": (
                                operation.reserved_cost_micro_usd
                                if actual_cost is None
                                else actual_cost
                            )
                        },
                    },
                )

                with mock.patch.object(
                    preloading,
                    "_split_sentences",
                    side_effect=AssertionError("provider must not replay"),
                ):
                    reading.run_preload_job(
                        self.preloads,
                        self.subs,
                        self.usage,
                        self.content,
                        *runner.calls[0],
                    )

                finalized = self.usage.get_operation("u1", operation_id)
                self.assertEqual(finalized.state, "finalized")
                self.assertEqual(
                    finalized.actual_cost_micro_usd,
                    operation.reserved_cost_micro_usd if actual_cost is None else actual_cost,
                )
                repaired = self.preloads.get_by_id("u1", operation_id)
                self.assertEqual(repaired["status"], "failed")
                self.assertIn("interrupted", repaired["error"].lower())

    def test_finalized_old_preload_retries_after_newer_url_operation(self):
        runner = _UsageAwareRunner(self.usage)
        old_request = self._request()
        old = reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            old_request,
            usage_meter=self._meter(),
        )
        with (
            mock.patch.object(preloading, "_split_sentences", return_value=["Sentence."]),
            mock.patch.object(
                preloading,
                "_analyze_sentences",
                return_value=("old summary", [], []),
            ),
            mock.patch.object(preloading, "_extract_study_items", return_value=([], {})),
        ):
            reading.run_preload_job(
                self.preloads, self.subs, self.usage, self.content, *runner.calls[0]
            )

        new_request = self._request().model_copy(
            update={"operation_id": "019b63f8-f600-7000-8000-000000000050"}
        )
        reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            new_request,
            usage_meter=self._meter(),
        )
        replay = reading.submit_preload(
            self.preloads,
            runner,
            self.content,
            "u1",
            old_request,
            usage_meter=self._meter(),
        )

        self.assertEqual(replay.preload.id, old.preload.id)
        self.assertEqual(replay.status, "ready")
        self.assertEqual(replay.preload.summary, "old summary")
        self.assertEqual(len(runner.calls), 2)

    def test_legacy_record_without_status_reads_ready(self):
        legacy = {
            "id": "legacy-1",
            "page_url": _PAGE_URL,
            "summary": "s",
            "topics": [],
            "sentences": [],
            "created_at": "2020-01-01T00:00:00+00:00",
        }
        self.preloads.save("u1", legacy)
        status = reading.get_preload_status(self.preloads, "u1", _PAGE_URL)
        self.assertTrue(status.ready)
        self.assertIsNone(status.status)


class SynchronousUsageFlowTests(unittest.TestCase):
    def setUp(self):
        self.rate_env = _rate_env_patch()
        self.rate_env.start()
        self.addCleanup(self.rate_env.stop)
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmpdir.name)
        self.preloads = JsonPagePreloadRepository(tmp / "preloads.json")
        self.usage = JsonUsageRepository(tmp / "usage.json")
        self.subs = JsonSubscriptionRepository(tmp / "subs.json")
        self.meter = UsageMeter(self.subs, self.usage, "u1", reservation_enabled=True)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_disabled_chat_and_uncached_analyze_emit_shadow_and_legacy_once(self):
        guard = build_guard(self.subs, self.usage, "u1")
        meter = UsageMeter(self.subs, self.usage, "u1", reservation_enabled=False)

        def add_usage(tally):
            tally.mark_dispatch_attempt()
            tally.add_response(
                types.SimpleNamespace(
                    model=pipeline.OPENAI_MODEL,
                    usage=types.SimpleNamespace(input_tokens=3, output_tokens=2, total_tokens=5),
                )
            )

        def chat_provider(*args, **kwargs):
            add_usage(kwargs["tally"])
            return "Shadow reply"

        def analyze_provider(*args, **kwargs):
            add_usage(kwargs["tally"])
            return {"translation": "Shadow translation", "grammar": "g"}

        with (
            mock.patch.object(reading, "_call_openai_chat", side_effect=chat_provider),
            mock.patch.object(reading, "_call_openai_json", side_effect=analyze_provider),
            self.assertLogs("untangle.usage", level="INFO") as captured,
        ):
            reading.chat_reply(
                self.preloads,
                "u1",
                ChatRequest(
                    operation_id="019b63f8-f600-7000-8000-000000000070",
                    message="Explain.",
                    context_text="Shadow chat context.",
                ),
                guard=guard,
                usage_meter=meter,
            )
            reading.analyze_selection(
                self.preloads,
                "u1",
                AnalyzeRequest(
                    operation_id="019b63f8-f600-7000-8000-000000000071",
                    text="Uncached shadow selection.",
                ),
                guard=guard,
                usage_meter=meter,
            )

        events = [
            json.loads(line.split(":", 2)[-1].strip())
            for line in captured.output
            if '"event": "usage_shadow_observed"' in line
        ]
        self.assertEqual([event["meter"] for event in events], ["chat", "cost"])
        self.assertTrue(all(event["outcome"] == "succeeded" for event in events))
        self.assertTrue(all(event["model"] == pipeline.OPENAI_MODEL for event in events))
        self.assertTrue(all(event["rate_card_version"] == "test" for event in events))
        month = self.usage.get_month("u1", current_month())
        self.assertEqual(month["chats"], 1)
        self.assertEqual(month["tokens"], 10)
        self.assertEqual(month["reserved_chats"], 0)
        self.assertEqual(month["committed_chats"], 0)

    def test_disabled_dispatched_failure_emits_conservative_shadow(self):
        guard = build_guard(self.subs, self.usage, "u1")
        meter = UsageMeter(self.subs, self.usage, "u1", reservation_enabled=False)

        def provider(*args, **kwargs):
            kwargs["tally"].mark_dispatch_attempt()
            raise ValueError("private provider detail")

        with (
            mock.patch.object(reading, "_call_openai_json", side_effect=provider),
            self.assertLogs("untangle.usage", level="INFO") as captured,
            self.assertRaisesRegex(ValueError, "private provider detail"),
        ):
            reading.analyze_selection(
                self.preloads,
                "u1",
                AnalyzeRequest(
                    operation_id="019b63f8-f600-7000-8000-000000000072",
                    text="Never log this private selection.",
                ),
                guard=guard,
                usage_meter=meter,
            )

        shadow = next(
            line for line in captured.output if '"event": "usage_shadow_observed"' in line
        )
        event = json.loads(shadow.split(":", 2)[-1].strip())
        self.assertEqual(event["outcome"], "conservative_failure")
        self.assertEqual(event["actual_cost_micro_usd"], event["estimated_cost_micro_usd"])
        self.assertNotIn("Never log this private selection", shadow)
        self.assertNotIn("private provider detail", shadow)

    def _assert_long_concurrent_execution(self, kind, *, fail_usage_renewal=False):
        operation_id = {
            "chat": "019b63f8-f600-7000-8000-00000000001c",
            "analyze": "019b63f8-f600-7000-8000-00000000001d",
        }[kind]
        request = (
            ChatRequest(
                operation_id=operation_id,
                message="Explain.",
                context_text="Long provider work.",
            )
            if kind == "chat"
            else AnalyzeRequest(
                operation_id=operation_id,
                text="Long provider work.",
            )
        )
        provider_entered = threading.Event()
        provider_release = threading.Event()
        provider_calls = []
        results = []
        errors = []

        def provider(*args, **kwargs):
            provider_calls.append(threading.get_ident())
            provider_entered.set()
            self.assertTrue(provider_release.wait(3))
            return (
                "Long durable reply"
                if kind == "chat"
                else {"translation": "long durable", "grammar": "g"}
            )

        def invoke():
            meter = UsageMeter(
                self.subs,
                self.usage,
                "u1",
                reservation_enabled=True,
                reservation_ttl_seconds=1,
            )
            try:
                result = (
                    reading.chat_reply(self.preloads, "u1", request, usage_meter=meter)
                    if kind == "chat"
                    else reading.analyze_selection(self.preloads, "u1", request, usage_meter=meter)
                )
                results.append(result)
            except Exception as exc:
                errors.append(exc)

        provider_name = "_call_openai_chat" if kind == "chat" else "_call_openai_json"
        renewal_patch = (
            mock.patch.object(
                UsageMeter,
                "renew",
                side_effect=RuntimeError("usage renewal unavailable"),
            )
            if fail_usage_renewal
            else contextlib.nullcontext()
        )
        with (
            mock.patch.dict(
                "os.environ",
                {
                    "SYNC_EXECUTION_LEASE_SECONDS": "1",
                    "SYNC_EXECUTION_WAIT_SECONDS": "3",
                },
            ),
            mock.patch.object(reading, provider_name, side_effect=provider),
            renewal_patch,
        ):
            first = threading.Thread(target=invoke)
            second = threading.Thread(target=invoke)
            first.start()
            self.assertTrue(provider_entered.wait(1))
            time.sleep(1.2)
            second.start()
            time.sleep(0.1)
            self.assertEqual(len(provider_calls), 1)
            provider_release.set()
            first.join(3)
            second.join(3)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(len(provider_calls), 1)
        self.assertEqual(
            self.usage.get_operation("u1", operation_id).state,
            "finalized",
        )
        self.assertFalse(
            any(
                thread.name == f"sync-operation-heartbeat-{operation_id}"
                for thread in threading.enumerate()
            )
        )

    def test_chat_heartbeat_prevents_duplicate_after_execution_and_usage_expiry(self):
        self._assert_long_concurrent_execution("chat")

    def test_analyze_heartbeat_prevents_duplicate_after_execution_and_usage_expiry(self):
        self._assert_long_concurrent_execution("analyze")

    def test_execution_claim_remains_owned_when_usage_renewal_fails(self):
        self._assert_long_concurrent_execution("chat", fail_usage_renewal=True)

    def test_lost_execution_ownership_blocks_pending_result_and_settlement(self):
        request = ChatRequest(
            operation_id="019b63f8-f600-7000-8000-00000000001e",
            message="Explain.",
            context_text="Lost ownership.",
        )
        meter = UsageMeter(self.subs, self.usage, "u1", reservation_enabled=True)

        with (
            mock.patch.object(meter, "renew_execution", return_value=False),
            mock.patch.object(
                reading, "_call_openai_chat", return_value="must not persist"
            ) as provider,
            self.assertRaisesRegex(pipeline.PipelineError, "ownership was lost"),
        ):
            reading.chat_reply(self.preloads, "u1", request, usage_meter=meter)

        provider.assert_called_once()
        self.assertIsNone(self.usage.get_result("u1", request.operation_id))
        self.assertEqual(
            self.usage.get_operation("u1", request.operation_id).state,
            "reserved",
        )

    def test_chat_reserves_before_model_and_replays_stored_response(self):
        request = ChatRequest(
            operation_id="019b63f8-f600-7000-8000-000000000010",
            message="Explain this.",
            context_text="A sentence.",
        )
        calls = []

        def reply(messages, *, max_completion_tokens, tally):
            operation = self.usage.get_operation("u1", request.operation_id)
            self.assertEqual(operation.state, "reserved")
            calls.append(messages)
            return "Stored reply"

        with mock.patch.object(reading, "_call_openai_chat", side_effect=reply):
            first = reading.chat_reply(self.preloads, "u1", request, usage_meter=self.meter)
            replay = reading.chat_reply(self.preloads, "u1", request, usage_meter=self.meter)

        self.assertEqual(first, replay)
        self.assertEqual(replay.reply, "Stored reply")
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            self.usage.get_operation("u1", request.operation_id).state,
            "finalized",
        )
        operation = self.usage.get_operation("u1", request.operation_id)
        self.assertEqual(
            operation.actual_cost_micro_usd,
            operation.reserved_cost_micro_usd,
        )

    def test_same_chat_operation_with_different_payload_conflicts_before_model(self):
        operation_id = "019b63f8-f600-7000-8000-000000000011"
        first = ChatRequest(
            operation_id=operation_id,
            message="First",
            context_text="A sentence.",
        )
        changed = ChatRequest(
            operation_id=operation_id,
            message="Changed",
            context_text="A sentence.",
        )

        with mock.patch.object(reading, "_call_openai_chat", return_value="reply") as provider:
            reading.chat_reply(self.preloads, "u1", first, usage_meter=self.meter)
            with self.assertRaisesRegex(Exception, "different payload"):
                reading.chat_reply(self.preloads, "u1", changed, usage_meter=self.meter)

        provider.assert_called_once()

    def test_chat_whitespace_change_is_a_payload_conflict(self):
        operation_id = "019b63f8-f600-7000-8000-000000000016"
        first = ChatRequest(
            operation_id=operation_id,
            message="Explain this.",
            context_text="Exact  spacing.",
        )
        changed = ChatRequest(
            operation_id=operation_id,
            message="Explain this.",
            context_text="Exact spacing.",
        )

        with mock.patch.object(reading, "_call_openai_chat", return_value="reply") as provider:
            reading.chat_reply(self.preloads, "u1", first, usage_meter=self.meter)
            with self.assertRaisesRegex(Exception, "different payload"):
                reading.chat_reply(self.preloads, "u1", changed, usage_meter=self.meter)

        provider.assert_called_once()

    def test_chat_finalize_failure_recovers_pending_result_without_provider_replay(self):
        request = ChatRequest(
            operation_id="019b63f8-f600-7000-8000-000000000017",
            message="Explain.",
            context_text="Pending result.",
        )
        provider = mock.Mock(return_value="Durable reply")

        with (
            mock.patch.object(reading, "_call_openai_chat", provider),
            mock.patch.object(
                self.meter,
                "finalize",
                side_effect=RuntimeError("usage unavailable"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "usage unavailable"):
                reading.chat_reply(self.preloads, "u1", request, usage_meter=self.meter)

        pending = self.usage.get_result("u1", request.operation_id)
        self.assertEqual(pending["kind"], "chat")
        self.assertEqual(pending["response"]["reply"], "Durable reply")
        self.assertEqual(set(pending), {"kind", "state", "response", "usage"})
        self.assertNotIn(
            request.context_text,
            json.dumps(pending, ensure_ascii=False),
        )
        replay = reading.chat_reply(self.preloads, "u1", request, usage_meter=self.meter)

        self.assertEqual(replay.reply, "Durable reply")
        self.assertEqual(
            self.usage.get_operation("u1", request.operation_id).state,
            "finalized",
        )
        provider.assert_called_once()

    def test_concurrent_chat_callers_dispatch_provider_once_and_replay(self):
        request = ChatRequest(
            operation_id="019b63f8-f600-7000-8000-000000000019",
            message="Explain.",
            context_text="Concurrent result.",
        )
        provider_entered = threading.Event()
        provider_release = threading.Event()
        provider_calls = []
        results = []
        errors = []

        def provider(*args, **kwargs):
            provider_calls.append(threading.get_ident())
            provider_entered.set()
            self.assertTrue(provider_release.wait(2))
            return "One durable reply"

        def invoke():
            meter = UsageMeter(self.subs, self.usage, "u1", reservation_enabled=True)
            try:
                results.append(reading.chat_reply(self.preloads, "u1", request, usage_meter=meter))
            except Exception as exc:
                errors.append(exc)

        with mock.patch.object(reading, "_call_openai_chat", side_effect=provider):
            first = threading.Thread(target=invoke)
            second = threading.Thread(target=invoke)
            first.start()
            self.assertTrue(provider_entered.wait(1))
            second.start()
            time.sleep(0.1)
            self.assertEqual(len(provider_calls), 1)
            provider_release.set()
            first.join(2)
            second.join(2)

        self.assertEqual(errors, [])
        self.assertEqual(
            [result.reply for result in results],
            [
                "One durable reply",
                "One durable reply",
            ],
        )
        self.assertEqual(len(provider_calls), 1)

    def test_chat_returns_deterministic_in_progress_error_after_bounded_wait(self):
        request = ChatRequest(
            operation_id="019b63f8-f600-7000-8000-00000000001a",
            message="Explain.",
            context_text="Still running.",
        )
        payload_hash = reading.canonical_payload_hash(request, exclude={"operation_id"})
        operation = self.meter.reserve(request.operation_id, payload_hash, "chat", 1)
        now = datetime.now(UTC)
        self.assertTrue(
            self.usage.claim_execution(
                "u1",
                operation.operation_id,
                "other-claim",
                now,
                now + timedelta(seconds=30),
            )
        )

        with (
            mock.patch.dict("os.environ", {"SYNC_EXECUTION_WAIT_SECONDS": "0.05"}),
            mock.patch.object(reading, "_call_openai_chat") as provider,
            self.assertRaises(pipeline.PipelineError) as raised,
        ):
            reading.chat_reply(self.preloads, "u1", request, usage_meter=self.meter)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("already in progress", str(raised.exception))
        provider.assert_not_called()

    def test_analyze_respects_existing_execution_claim(self):
        request = AnalyzeRequest(
            operation_id="019b63f8-f600-7000-8000-00000000001b",
            text="Still analyzing.",
        )
        operation = self.meter.reserve(
            request.operation_id,
            reading.canonical_payload_hash(request, exclude={"operation_id"}),
            "cost",
            1,
        )
        now = datetime.now(UTC)
        self.assertTrue(
            self.usage.claim_execution(
                "u1",
                operation.operation_id,
                "other-analysis-claim",
                now,
                now + timedelta(seconds=30),
            )
        )

        with (
            mock.patch.dict("os.environ", {"SYNC_EXECUTION_WAIT_SECONDS": "0"}),
            mock.patch.object(reading, "_call_openai_json") as provider,
            self.assertRaises(pipeline.PipelineError) as raised,
        ):
            reading.analyze_selection(self.preloads, "u1", request, usage_meter=self.meter)

        self.assertEqual(raised.exception.status_code, 409)
        provider.assert_not_called()

    def test_analyze_finalize_failure_recovers_pending_result_without_provider_replay(self):
        request = AnalyzeRequest(
            operation_id="019b63f8-f600-7000-8000-000000000018",
            text="Pending selection.",
        )
        provider = mock.Mock(return_value={"translation": "durable", "grammar": "g"})

        with (
            mock.patch.object(reading, "_call_openai_json", provider),
            mock.patch.object(
                self.meter,
                "finalize",
                side_effect=RuntimeError("usage unavailable"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "usage unavailable"):
                reading.analyze_selection(self.preloads, "u1", request, usage_meter=self.meter)

        replay = reading.analyze_selection(self.preloads, "u1", request, usage_meter=self.meter)
        self.assertEqual(replay.translation, "durable")
        provider.assert_called_once()

    def test_cached_selection_bypasses_usage_and_uncached_replays(self):
        cached_request = AnalyzeRequest(
            operation_id="019b63f8-f600-7000-8000-000000000012",
            text="Cached sentence.",
            page_url=_PAGE_URL,
        )
        self.preloads.save(
            "u1",
            {
                "id": "preload",
                "page_url": _PAGE_URL,
                "sentences": [
                    {
                        "text": "Cached sentence.",
                        "analysis": {"translation": "cached", "grammar": "cached"},
                    }
                ],
            },
        )
        cached = reading.analyze_selection(
            self.preloads, "u1", cached_request, usage_meter=self.meter
        )
        self.assertEqual(cached.translation, "cached")
        self.assertIsNone(self.usage.get_operation("u1", cached_request.operation_id))

        request = AnalyzeRequest(
            operation_id="019b63f8-f600-7000-8000-000000000013",
            text="Not cached.",
        )
        parsed = {"translation": "fresh", "grammar": "g"}
        with mock.patch.object(reading, "_call_openai_json", return_value=parsed) as provider:
            first = reading.analyze_selection(self.preloads, "u1", request, usage_meter=self.meter)
            replay = reading.analyze_selection(self.preloads, "u1", request, usage_meter=self.meter)

        self.assertEqual(first, replay)
        provider.assert_called_once()

    def test_chat_known_pre_dispatch_failure_releases_reservation(self):
        request = ChatRequest(
            operation_id="019b63f8-f600-7000-8000-000000000014",
            message="Explain.",
            context_text="A sentence.",
        )
        provider = mock.Mock(
            side_effect=pipeline.PipelineError(
                "input too large",
                status_code=413,
                dispatch_attempted=False,
            )
        )
        with mock.patch.object(reading, "_call_openai_chat", provider):
            with self.assertRaises(pipeline.PipelineError):
                reading.chat_reply(self.preloads, "u1", request, usage_meter=self.meter)
            with self.assertRaisesRegex(pipeline.PipelineError, "no longer executable"):
                reading.chat_reply(self.preloads, "u1", request, usage_meter=self.meter)

        operation = self.usage.get_operation("u1", request.operation_id)
        self.assertEqual(operation.state, "released")
        self.assertEqual(operation.release_reason, "failed_before_dispatch")
        provider.assert_called_once()

    def test_ambiguous_provider_failure_commits_conservative_estimate(self):
        request = AnalyzeRequest(
            operation_id="019b63f8-f600-7000-8000-000000000015",
            text="Dispatch may have completed.",
        )
        with mock.patch.object(
            reading,
            "_call_openai_json",
            side_effect=pipeline.PipelineError(
                "provider connection lost",
                status_code=502,
                dispatch_attempted=True,
            ),
        ):
            with self.assertRaises(pipeline.PipelineError):
                reading.analyze_selection(self.preloads, "u1", request, usage_meter=self.meter)

        operation = self.usage.get_operation("u1", request.operation_id)
        self.assertEqual(operation.state, "finalized")
        self.assertEqual(
            operation.actual_cost_micro_usd,
            operation.reserved_cost_micro_usd,
        )

    def test_post_dispatch_response_validation_finalizes_without_provider_replay(self):
        request = AnalyzeRequest(
            operation_id="019b63f8-f600-7000-8000-00000000001f",
            text="Invalid provider response.",
        )
        provider = mock.Mock(return_value={"translation": ["not", "a", "string"]})

        with mock.patch.object(reading, "_call_openai_json", provider):
            with self.assertRaises(ValidationError):
                reading.analyze_selection(self.preloads, "u1", request, usage_meter=self.meter)
            with self.assertRaises(pipeline.PipelineError):
                reading.analyze_selection(self.preloads, "u1", request, usage_meter=self.meter)

        operation = self.usage.get_operation("u1", request.operation_id)
        self.assertEqual(operation.state, "finalized")
        self.assertEqual(
            operation.actual_cost_micro_usd,
            operation.reserved_cost_micro_usd,
        )
        provider.assert_called_once()

    def test_analyze_non_pipeline_error_after_dispatch_is_not_released_or_replayed(self):
        request = AnalyzeRequest(
            operation_id="019b63f8-f600-7000-8000-000000000024",
            text="Malformed dispatched analysis.",
        )

        def malformed_provider(*args, **kwargs):
            kwargs["tally"].mark_dispatch_attempt()
            raise ValueError("malformed provider response")

        provider = mock.Mock(side_effect=malformed_provider)
        with mock.patch.object(reading, "_call_openai_json", provider):
            with self.assertRaisesRegex(ValueError, "malformed provider response"):
                reading.analyze_selection(self.preloads, "u1", request, usage_meter=self.meter)
            with self.assertRaises(pipeline.PipelineError):
                reading.analyze_selection(self.preloads, "u1", request, usage_meter=self.meter)

        operation = self.usage.get_operation("u1", request.operation_id)
        self.assertEqual(operation.state, "finalized")
        self.assertEqual(
            operation.actual_cost_micro_usd,
            operation.reserved_cost_micro_usd,
        )
        provider.assert_called_once()

    def test_chat_non_pipeline_error_after_dispatch_is_not_released_or_replayed(self):
        request = ChatRequest(
            operation_id="019b63f8-f600-7000-8000-000000000025",
            message="Explain.",
            context_text="Malformed dispatched chat.",
        )

        def malformed_provider(*args, **kwargs):
            kwargs["tally"].mark_dispatch_attempt()
            raise ValueError("malformed provider response")

        provider = mock.Mock(side_effect=malformed_provider)
        with mock.patch.object(reading, "_call_openai_chat", provider):
            with self.assertRaisesRegex(ValueError, "malformed provider response"):
                reading.chat_reply(self.preloads, "u1", request, usage_meter=self.meter)
            with self.assertRaises(pipeline.PipelineError):
                reading.chat_reply(self.preloads, "u1", request, usage_meter=self.meter)

        operation = self.usage.get_operation("u1", request.operation_id)
        self.assertEqual(operation.state, "finalized")
        self.assertEqual(
            operation.actual_cost_micro_usd,
            operation.reserved_cost_micro_usd,
        )
        provider.assert_called_once()

    def test_post_dispatch_result_persistence_failure_prevents_provider_replay(self):
        request = ChatRequest(
            operation_id="019b63f8-f600-7000-8000-000000000020",
            message="Explain.",
            context_text="Persistence failure.",
        )
        provider = mock.Mock(return_value="Generated reply")

        with (
            mock.patch.object(reading, "_call_openai_chat", provider),
            mock.patch.object(
                self.meter,
                "save_result",
                side_effect=RuntimeError("result store unavailable"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "result store unavailable"):
                reading.chat_reply(self.preloads, "u1", request, usage_meter=self.meter)
            with self.assertRaises(pipeline.PipelineError):
                reading.chat_reply(self.preloads, "u1", request, usage_meter=self.meter)

        operation = self.usage.get_operation("u1", request.operation_id)
        self.assertEqual(operation.state, "finalized")
        provider.assert_called_once()

    def test_provider_boundary_persists_dispatch_marker_before_api_call(self):
        request = ChatRequest(
            operation_id="019b63f8-f600-7000-8000-000000000021",
            message="Explain.",
            context_text="Ambiguous network failure.",
        )
        client = mock.Mock()
        client.chat.completions.create.side_effect = RuntimeError("connection reset after dispatch")

        with mock.patch.object(pipeline, "_client", return_value=client):
            with self.assertRaises(pipeline.PipelineError):
                reading.chat_reply(self.preloads, "u1", request, usage_meter=self.meter)
            with self.assertRaises(pipeline.PipelineError):
                reading.chat_reply(self.preloads, "u1", request, usage_meter=self.meter)

        stored = self.usage.get_result("u1", request.operation_id)
        self.assertEqual(stored["state"], "dispatching")
        self.assertNotIn("response", stored)
        self.assertEqual(
            self.usage.get_operation("u1", request.operation_id).state,
            "finalized",
        )
        client.chat.completions.create.assert_called_once()

    def test_openai_client_prerequisites_fail_before_dispatch_without_charge(self):
        cases = [
            (
                "019b63f8-f600-7000-8000-000000000022",
                mock.patch.object(pipeline, "OPENAI_API_KEY", ""),
            ),
            (
                "019b63f8-f600-7000-8000-000000000023",
                contextlib.ExitStack(),
            ),
        ]
        for operation_id, prerequisite_patch in cases:
            request = ChatRequest(
                operation_id=operation_id,
                message="Explain.",
                context_text="Pre-dispatch prerequisite.",
            )
            with self.subTest(operation_id=operation_id):
                with contextlib.ExitStack() as stack:
                    if isinstance(prerequisite_patch, contextlib.ExitStack):
                        stack.enter_context(
                            mock.patch.object(pipeline, "OPENAI_API_KEY", "configured")
                        )
                        stack.enter_context(
                            mock.patch.object(
                                pipeline,
                                "OpenAI",
                                side_effect=RuntimeError("client construction failed"),
                            )
                        )
                    else:
                        stack.enter_context(prerequisite_patch)
                    with self.assertRaises((pipeline.PipelineError, RuntimeError)):
                        reading.chat_reply(
                            self.preloads,
                            "u1",
                            request,
                            usage_meter=self.meter,
                        )

                operation = self.usage.get_operation("u1", request.operation_id)
                self.assertEqual(operation.state, "released")
                self.assertIsNone(self.usage.get_result("u1", request.operation_id))


class InlinePreloadJobRunnerTests(unittest.TestCase):
    def test_inline_runner_passes_its_configured_billing_mode_to_the_job(self):
        runner = InlinePreloadJobRunner(
            mock.Mock(),
            mock.Mock(),
            mock.Mock(),
            mock.Mock(),
            max_workers=1,
            queue_capacity=0,
            billing_provider_mode="mock",
        )
        with mock.patch.object(inline_runner_module, "run_preload_job") as run_preload_job:
            runner.enqueue("u1", "https://example.com/article", "preload-1", "profile")
            runner.shutdown(wait=True)

        self.assertEqual(run_preload_job.call_args.kwargs["billing_provider_mode"], "mock")

    def test_bounded_queue_rejects_saturation_and_shuts_down_cleanly(self):
        started = threading.Event()
        release = threading.Event()
        completed = []

        def run_job(*args, **kwargs):
            completed.append(args[6])
            if len(completed) == 1:
                started.set()
                self.assertTrue(release.wait(2))

        runner = InlinePreloadJobRunner(
            mock.Mock(),
            mock.Mock(),
            mock.Mock(),
            mock.Mock(),
            max_workers=1,
            queue_capacity=1,
        )
        with mock.patch.object(inline_runner_module, "run_preload_job", side_effect=run_job):
            runner.enqueue("u", "url", "job-1", "profile")
            self.assertTrue(started.wait(1))
            runner.enqueue("u", "url", "job-2", "profile")
            with self.assertRaisesRegex(Exception, "queue is saturated"):
                runner.enqueue("u", "url", "job-3", "profile")
            release.set()
            runner.shutdown(wait=True)

        self.assertEqual(completed, ["job-1", "job-2"])
        self.assertFalse(
            any(thread.name.startswith("preload-job") for thread in threading.enumerate())
        )
        with self.assertRaisesRegex(Exception, "shut down"):
            runner.enqueue("u", "url", "job-4", "profile")


class PreloadApiTests(unittest.TestCase):
    def setUp(self):
        self.rate_env = _rate_env_patch()
        self.rate_env.start()
        self.addCleanup(self.rate_env.stop)
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmpdir.name)
        auth_service = JsonEmailAuthService(tmp / "users.json", tmp / "sessions.json")
        self.usage = JsonUsageRepository(tmp / "usage.json")
        self.subs = JsonSubscriptionRepository(tmp / "subs.json")
        self.preloads = JsonPagePreloadRepository(tmp / "preloads.json")
        self.content = FilesystemPreloadContentStore(tmp / "preload_content")
        self.runner = InlinePreloadJobRunner(self.preloads, self.subs, self.usage, self.content)

        accounts = build_test_accounts(
            plans=PLAN_CATALOG,
            auth_service=auth_service,
            subscription_repository=self.subs,
        )
        app.dependency_overrides[get_accounts] = lambda: accounts
        app.dependency_overrides[get_page_preload_repository] = lambda: self.preloads
        app.dependency_overrides[get_usage_repository] = lambda: self.usage
        app.dependency_overrides[get_subscription_repository] = lambda: self.subs
        app.dependency_overrides[get_preload_job_runner] = lambda: self.runner
        app.dependency_overrides[get_preload_content_store] = lambda: self.content
        app.dependency_overrides[get_entitlement_guard] = self._guard_override
        self.client = TestClient(app, raise_server_exceptions=False)

        login = self.client.post("/auth/login", json={"credential": "mock:reader@example.com"})
        self.user_id = login.json()["user"]["id"]
        self.headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    def tearDown(self):
        self.runner.shutdown(wait=True)
        app.dependency_overrides.clear()
        self._tmpdir.cleanup()

    def _guard_override(self):
        return build_guard(self.subs, self.usage, self.user_id)

    def _submit(self):
        return self.client.post(
            "/pages/preload",
            json={"page_url": _PAGE_URL, "page_title": "Title", "html": _PAGE_HTML},
            headers=self.headers,
        )

    def _poll_until_done(self, timeout_s=10.0):
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            body = self.client.get(
                "/pages/preload", params={"page_url": _PAGE_URL}, headers=self.headers
            ).json()
            if body.get("status") in ("ready", "failed") or body.get("ready"):
                return body
            time.sleep(0.05)
        return None

    def test_submit_returns_202_processing(self):
        recording_runner = _RecordingRunner()
        app.dependency_overrides[get_preload_job_runner] = lambda: recording_runner
        response = self._submit()
        self.assertEqual(response.status_code, 202)
        body = response.json()
        self.assertFalse(body["ready"])
        self.assertEqual(body["status"], "processing")
        self.assertEqual(body["preload"]["status"], "processing")
        self.assertEqual(len(recording_runner.calls), 1)

    def test_post_then_poll_reaches_ready(self):
        with mock.patch.object(pipeline, "_client", _fake_openai_client):
            self.assertEqual(self._submit().status_code, 202)
            body = self._poll_until_done()

        self.assertIsNotNone(body, "preload never reached a terminal state")
        self.assertTrue(body["ready"])
        self.assertEqual(body["status"], "ready")
        preload = body["preload"]
        self.assertTrue(preload["sentences"])
        self.assertEqual(preload["summary"], "article summary")
        self.assertEqual(self.usage.get_month(self.user_id, current_month())["articles"], 1)

    def test_post_then_poll_surfaces_failure(self):
        with mock.patch.object(pipeline, "_client", _failing_openai_client):
            self.assertEqual(self._submit().status_code, 202)
            body = self._poll_until_done()

        self.assertIsNotNone(body, "preload never reached a terminal state")
        self.assertFalse(body["ready"])
        self.assertEqual(body["status"], "failed")
        self.assertTrue(body["error"])
        self.assertEqual(self.usage.get_month(self.user_id, current_month())["articles"], 0)

    def test_unextractable_html_still_400_synchronously(self):
        response = self.client.post(
            "/pages/preload",
            json={"page_url": _PAGE_URL, "html": "<html><body></body></html>"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 400)

    def test_enabled_same_operation_different_payload_maps_to_stable_409(self):
        meter = UsageMeter(
            self.subs,
            self.usage,
            self.user_id,
            reservation_enabled=True,
        )
        runner = _UsageAwareRunner(self.usage)
        app.dependency_overrides[get_usage_meter] = lambda: meter
        app.dependency_overrides[get_preload_job_runner] = lambda: runner
        operation_id = "019b63f8-f600-7000-8000-000000000040"
        payload = {
            "operation_id": operation_id,
            "page_url": _PAGE_URL,
            "page_title": "Title",
            "html": _PAGE_HTML,
        }

        first = self.client.post("/pages/preload", json=payload, headers=self.headers)
        conflict = self.client.post(
            "/pages/preload",
            json={**payload, "html": _PAGE_HTML + "<p>Changed.</p>"},
            headers=self.headers,
        )

        self.assertEqual(first.status_code, 202)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["code"], "operation_payload_conflict")


if __name__ == "__main__":
    unittest.main()
