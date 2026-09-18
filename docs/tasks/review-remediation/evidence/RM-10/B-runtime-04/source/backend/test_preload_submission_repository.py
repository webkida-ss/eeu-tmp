from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

from botocore.exceptions import ClientError
from repositories.dynamodb_page_preload_repository import DynamoPagePreloadRepository
from repositories.page_preload_repository import (
    JsonPagePreloadRepository,
    PreloadOperationConflict,
)
from storage.dynamodb_keys import preload_id_sk, preload_sk, user_pk
from storage.preload_content_store import FilesystemPreloadContentStore, S3PreloadContentStore


def _record(preload_id: str = "op-1") -> dict[str, object]:
    return {
        "id": preload_id,
        "operation_id": preload_id,
        "payload_hash": "payload-a",
        "page_url": "https://example.com/article#fragment",
        "learner_profile_fingerprint": "profile-a",
        "enqueue_state": "pending",
    }


class PreloadCreationRepositoryTests(TestCase):
    def setUp(self) -> None:
        self.tmpdir = TemporaryDirectory()
        self.path = Path(self.tmpdir.name) / "preloads.json"
        self.repository = JsonPagePreloadRepository(self.path)
        self.now = datetime.now(UTC)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_json_create_if_absent_returns_winner_without_rewriting_latest(self) -> None:
        winner = self.repository.create_if_absent("u1", _record(), now=self.now)
        replay = self.repository.create_if_absent("u1", _record(), now=self.now)

        self.assertTrue(winner.created)
        self.assertFalse(replay.created)
        self.assertEqual(
            winner.record["content_handoff_token"], replay.record["content_handoff_token"]
        )
        self.assertEqual(replay.record["status"], "content_pending")
        self.assertFalse(self.repository.mark_enqueue_submitting("u1", "op-1"))
        self.assertIsNone(self.repository.claim_processing("u1", "op-1", "profile-a"))
        other_user = self.repository.create_if_absent("u2", _record(), now=self.now)
        self.assertTrue(other_user.created)

    def test_json_adapters_race_for_one_winner_without_resetting_the_winner(self) -> None:
        other_adapter = JsonPagePreloadRepository(self.path)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(adapter.create_if_absent, "u1", _record(), now=self.now)
                for adapter in (self.repository, other_adapter)
            ]
            outcomes = [future.result(timeout=2) for future in futures]

        self.assertEqual(sum(outcome.created for outcome in outcomes), 1)
        winner = self.repository.get_by_id("u1", "op-1")
        self.assertIsNotNone(winner)
        self.assertEqual(winner["status"], "content_pending")
        self.assertTrue(winner["is_latest"])

    def test_json_conflicting_identity_and_stale_handoff_owner_fail_closed(self) -> None:
        winner = self.repository.create_if_absent("u1", _record(), now=self.now)
        with self.assertRaises(PreloadOperationConflict):
            self.repository.create_if_absent(
                "u1", {**_record(), "payload_hash": "other"}, now=self.now
            )

        expired = self.now + timedelta(minutes=6)
        takeover = self.repository.claim_content_handoff("u1", _record(), now=expired)
        self.assertTrue(takeover.created)
        self.assertFalse(
            self.repository.mark_content_available(
                "u1", "op-1", winner.record["content_handoff_token"]
            )
        )
        self.assertTrue(
            self.repository.mark_content_available(
                "u1", "op-1", takeover.record["content_handoff_token"]
            )
        )

    def test_json_failed_content_handoff_cannot_be_enqueued(self) -> None:
        winner = self.repository.create_if_absent("u1", _record(), now=self.now)

        self.assertTrue(
            self.repository.fail_content_handoff(
                "u1", "op-1", winner.record["content_handoff_token"], "content write failed"
            )
        )
        self.assertFalse(self.repository.mark_enqueue_submitting("u1", "op-1"))

    def test_json_handoff_failure_requires_the_current_unclaimed_processing_owner(self) -> None:
        winner = self.repository.create_if_absent("u1", _record(), now=self.now)
        token = winner.record["content_handoff_token"]
        self.assertTrue(self.repository.mark_content_available("u1", "op-1", token))
        self.assertTrue(self.repository.fail_content_handoff("u1", "op-1", token, "queue failed"))

        stale = self.repository.create_if_absent("u1", _record("op-stale"), now=self.now)
        takeover = self.repository.claim_content_handoff(
            "u1", _record("op-stale"), now=self.now + timedelta(minutes=6)
        )
        self.assertTrue(
            self.repository.mark_content_available(
                "u1", "op-stale", takeover.record["content_handoff_token"]
            )
        )
        self.assertFalse(
            self.repository.fail_content_handoff(
                "u1", "op-stale", stale.record["content_handoff_token"], "queue failed"
            )
        )

        expired = self.repository.create_if_absent("u1", _record("op-expired"), now=self.now)
        expired_record = dict(expired.record)
        expired_record["content_handoff_expires_at"] = (self.now - timedelta(minutes=1)).isoformat()
        self.repository.save("u1", expired_record, make_latest=False)
        self.assertFalse(
            self.repository.fail_content_handoff(
                "u1", "op-expired", expired.record["content_handoff_token"], "queue failed"
            )
        )

        active = self.repository.create_if_absent("u1", _record("op-active"), now=self.now)
        active_token = active.record["content_handoff_token"]
        self.assertTrue(self.repository.mark_content_available("u1", "op-active", active_token))
        claimed = self.repository.claim_processing(
            "u1", "op-active", "profile-a", lease_id="worker-lease", now=self.now
        )
        self.assertIsNotNone(claimed)
        self.assertFalse(
            self.repository.fail_content_handoff("u1", "op-active", active_token, "queue failed")
        )
        terminal = {**claimed, "status": "ready"}
        self.assertTrue(
            self.repository.finish_processing(
                "u1", "op-active", "profile-a", terminal, lease_id="worker-lease"
            )
        )
        self.assertFalse(
            self.repository.fail_content_handoff("u1", "op-active", active_token, "queue failed")
        )


class _FakeDynamoStore:
    table_name = "preloads"

    def __init__(self) -> None:
        self.documents: dict[tuple[str, str], dict[str, object]] = {}
        self.attributes: dict[tuple[str, str], dict[str, object]] = {}
        self.transact_items = []
        self.consistent_reads: list[tuple[str, str]] = []
        self.transaction_error: ClientError | None = None
        self.before_transaction = None
        self.miss_next_page_query = False

    def get_document(self, pk, sk, *, consistent_read=False):
        if consistent_read:
            self.consistent_reads.append((pk, sk))
        return self.documents.get((pk, sk))

    def query_by_pk(self, pk, *, sk_prefix=None):
        if self.miss_next_page_query:
            self.miss_next_page_query = False
            return []
        return [
            value
            for (item_pk, item_sk), value in self.documents.items()
            if item_pk == pk and (sk_prefix is None or item_sk.startswith(sk_prefix))
        ]

    def transact_write(self, items):
        self.transact_items.append(items)
        if self.before_transaction is not None:
            self.before_transaction()
        if self.transaction_error is not None:
            raise self.transaction_error
        keys = []
        for position, item in enumerate(items):
            put = item["Put"]
            values = put["Item"]
            key = (values["pk"]["S"], values["sk"]["S"])
            if key in keys:
                raise ClientError({"Error": {"Code": "ValidationException"}}, "TransactWriteItems")
            keys.append(key)
            condition = put["ConditionExpression"]
            if condition == "attribute_not_exists(pk)":
                matches = key not in self.documents
            elif condition == "#document = :expected_document":
                if put["ExpressionAttributeNames"] != {"#document": "document"}:
                    raise AssertionError("Expected document condition name")
                expected = put["ExpressionAttributeValues"][":expected_document"]["S"]
                matches = self.documents.get(key) == json.loads(expected)
            else:
                raise AssertionError(f"Unexpected transaction condition: {condition}")
            if not matches:
                reasons = [{"Code": "None"} for _ in items]
                reasons[position] = {"Code": "ConditionalCheckFailed"}
                raise ClientError(
                    {
                        "Error": {"Code": "TransactionCanceledException"},
                        "CancellationReasons": reasons,
                    },
                    "TransactWriteItems",
                )
        for item in items:
            values = item["Put"]["Item"]
            key = (values["pk"]["S"], values["sk"]["S"])
            self.documents[key] = json.loads(values["document"]["S"])
            self.attributes[key] = {
                name: _deserialize_attribute(value)
                for name, value in values.items()
                if name not in {"pk", "sk", "document"}
            }

    def conditional_put_document(self, pk, sk, document, *, extra_attributes, expected_attributes):
        current = self.documents.get((pk, sk))
        current_attributes = self.attributes.get((pk, sk), {})
        if current is None or any(
            current_attributes.get(name) != value for name, value in expected_attributes.items()
        ):
            return False
        self.documents[(pk, sk)] = document
        self.attributes[(pk, sk)] = dict(extra_attributes)
        return True

    def put_document_if_absent(self, pk, sk, document, *, extra_attributes=None):
        if (pk, sk) in self.documents:
            return False
        self.documents[(pk, sk)] = document
        self.attributes[(pk, sk)] = dict(extra_attributes or {})
        return True

    def put_document(self, pk, sk, document, *, extra_attributes=None):
        self.documents[(pk, sk)] = dict(document)
        self.attributes[(pk, sk)] = dict(extra_attributes or {})


def _deserialize_attribute(value: dict[str, object]) -> object:
    if "S" in value:
        return value["S"]
    if "BOOL" in value:
        return value["BOOL"]
    raise AssertionError(f"Unsupported fake Dynamo attribute: {value}")


class DynamoPreloadCreationTests(TestCase):
    def test_dynamo_transaction_returns_the_consistent_winner(self) -> None:
        store = _FakeDynamoStore()
        repository = DynamoPagePreloadRepository(store)
        winner = repository.create_if_absent("u1", _record(), now=datetime(2026, 9, 14, tzinfo=UTC))
        replay = repository.create_if_absent("u1", _record(), now=datetime(2026, 9, 14, tzinfo=UTC))

        self.assertTrue(winner.created)
        self.assertFalse(replay.created)
        self.assertEqual(
            store.documents[(user_pk("u1"), preload_sk("https://example.com/article"))][
                "preload_id"
            ],
            "op-1",
        )
        self.assertIn((user_pk("u1"), preload_id_sk("op-1")), store.documents)
        transaction = store.transact_items[0]
        self.assertEqual(len(transaction), 2)
        self.assertTrue(
            all(
                item["Put"]["ConditionExpression"] == "attribute_not_exists(pk)"
                for item in transaction
            )
        )
        self.assertIn((user_pk("u1"), preload_id_sk("op-1")), store.consistent_reads)

    def test_dynamo_legacy_direct_id_materialization_preserves_page_index(self) -> None:
        store = _FakeDynamoStore()
        user = "u1"
        legacy = {
            **_record(),
            "user_id": user,
            "page_url": "https://example.com/article",
            "status": "processing",
        }
        page_key = (user_pk(user), preload_sk("https://example.com/article"))
        store.documents[page_key] = legacy
        repository = DynamoPagePreloadRepository(store)

        claimed = repository.claim_processing(user, "op-1", "profile-a")

        self.assertIsNotNone(claimed)
        self.assertEqual(store.documents[page_key], legacy)
        self.assertEqual(store.documents[(user_pk(user), preload_id_sk("op-1"))]["id"], "op-1")

    def test_dynamo_conditional_create_propagates_nonconditional_errors(self) -> None:
        store = _FakeDynamoStore()
        store.transaction_error = ClientError(
            {"Error": {"Code": "ProvisionedThroughputExceededException"}}, "TransactWriteItems"
        )

        with self.assertRaises(ClientError):
            DynamoPagePreloadRepository(store).create_if_absent("u1", _record())

    def test_dynamo_create_does_not_mask_mixed_transaction_cancellation(self) -> None:
        store = _FakeDynamoStore()
        store.transaction_error = ClientError(
            {
                "Error": {"Code": "TransactionCanceledException"},
                "CancellationReasons": [
                    {"Code": "ConditionalCheckFailed"},
                    {"Code": "ProvisionedThroughputExceeded"},
                ],
            },
            "TransactWriteItems",
        )

        with self.assertRaises(ClientError):
            DynamoPagePreloadRepository(store).create_if_absent("u1", _record())

    def test_dynamo_create_does_not_mask_nonconditional_cancellation(self) -> None:
        store = _FakeDynamoStore()
        store.transaction_error = ClientError(
            {
                "Error": {"Code": "TransactionCanceledException"},
                "CancellationReasons": [{"Code": "ValidationError"}, {"Code": "None"}],
            },
            "TransactWriteItems",
        )

        with self.assertRaises(ClientError):
            DynamoPagePreloadRepository(store).create_if_absent("u1", _record())

    def test_dynamo_create_does_not_mask_malformed_transaction_cancellation(self) -> None:
        store = _FakeDynamoStore()
        store.transaction_error = ClientError(
            {
                "Error": {"Code": "TransactionCanceledException"},
                "CancellationReasons": [{"Code": "ConditionalCheckFailed"}, {}],
            },
            "TransactWriteItems",
        )

        with self.assertRaises(ClientError):
            DynamoPagePreloadRepository(store).create_if_absent("u1", _record())

    def test_dynamo_new_operation_replaces_only_the_observed_predecessor_index(self) -> None:
        store = _FakeDynamoStore()
        repository = DynamoPagePreloadRepository(store)
        old = repository.create_if_absent("u1", _record("op-old"))

        created = repository.create_if_absent("u1", _record("op-new"))

        self.assertTrue(created.created)
        self.assertEqual(
            store.documents[(user_pk("u1"), preload_sk("https://example.com/article"))][
                "preload_id"
            ],
            "op-new",
        )
        self.assertEqual(
            store.documents[(user_pk("u1"), preload_id_sk("op-old"))]["content_handoff_token"],
            old.record["content_handoff_token"],
        )
        self.assertEqual(
            store.transact_items[-1][1]["Put"]["ConditionExpression"],
            "#document = :expected_document",
        )

    def test_dynamo_predecessor_change_during_create_fails_without_overwrite(self) -> None:
        store = _FakeDynamoStore()
        repository = DynamoPagePreloadRepository(store)
        repository.create_if_absent("u1", _record("op-old"))
        index_key = (user_pk("u1"), preload_sk("https://example.com/article"))

        def replace_index() -> None:
            store.documents[index_key] = {
                "user_id": "u1",
                "page_url": "https://example.com/article",
                "preload_id": "op-concurrent",
            }

        store.before_transaction = replace_index
        with self.assertRaises(PreloadOperationConflict):
            repository.create_if_absent("u1", _record("op-new"))
        self.assertEqual(store.documents[index_key]["preload_id"], "op-concurrent")
        self.assertNotIn((user_pk("u1"), preload_id_sk("op-new")), store.documents)

    def test_dynamo_handoff_rejects_expired_token_and_recovers_the_same_operation(self) -> None:
        store = _FakeDynamoStore()
        repository = DynamoPagePreloadRepository(store)
        now = datetime.now(UTC)
        winner = repository.create_if_absent("u1", _record(), now=now)
        takeover = repository.claim_content_handoff("u1", _record(), now=now + timedelta(minutes=6))

        self.assertTrue(takeover.created)
        self.assertFalse(
            repository.mark_content_available("u1", "op-1", winner.record["content_handoff_token"])
        )
        self.assertTrue(
            repository.mark_content_available(
                "u1", "op-1", takeover.record["content_handoff_token"]
            )
        )

    def test_dynamo_handoff_failure_requires_the_current_unclaimed_processing_owner(self) -> None:
        store = _FakeDynamoStore()
        repository = DynamoPagePreloadRepository(store)
        now = datetime.now(UTC)
        winner = repository.create_if_absent("u1", _record(), now=now)
        token = winner.record["content_handoff_token"]
        self.assertTrue(repository.mark_content_available("u1", "op-1", token))
        self.assertTrue(repository.fail_content_handoff("u1", "op-1", token, "queue failed"))
        self.assertFalse(repository.mark_enqueue_submitting("u1", "op-1"))

        stale = repository.create_if_absent("u1", _record("op-stale"), now=now)
        takeover = repository.claim_content_handoff(
            "u1", _record("op-stale"), now=now + timedelta(minutes=6)
        )
        self.assertTrue(
            repository.mark_content_available(
                "u1", "op-stale", takeover.record["content_handoff_token"]
            )
        )
        self.assertFalse(
            repository.fail_content_handoff(
                "u1", "op-stale", stale.record["content_handoff_token"], "queue failed"
            )
        )

        expired = repository.create_if_absent("u1", _record("op-expired"), now=now)
        expired_record = dict(expired.record)
        expired_record["content_handoff_expires_at"] = (now - timedelta(minutes=1)).isoformat()
        repository.save("u1", expired_record, make_latest=False)
        self.assertFalse(
            repository.fail_content_handoff(
                "u1", "op-expired", expired.record["content_handoff_token"], "queue failed"
            )
        )

        active = repository.create_if_absent("u1", _record("op-active"), now=now)
        active_token = active.record["content_handoff_token"]
        self.assertTrue(repository.mark_content_available("u1", "op-active", active_token))
        claimed = repository.claim_processing(
            "u1", "op-active", "profile-a", lease_id="worker-lease", now=now
        )
        self.assertIsNotNone(claimed)
        self.assertFalse(
            repository.fail_content_handoff("u1", "op-active", active_token, "queue failed")
        )
        terminal = {**claimed, "status": "ready"}
        self.assertTrue(
            repository.finish_processing(
                "u1", "op-active", "profile-a", terminal, lease_id="worker-lease"
            )
        )
        self.assertFalse(
            repository.fail_content_handoff("u1", "op-active", active_token, "queue failed")
        )

    def test_dynamo_legacy_page_record_is_materialized_before_index_replacement(self) -> None:
        store = _FakeDynamoStore()
        page_key = (user_pk("u1"), preload_sk("https://example.com/article"))
        legacy = {
            **_record("op-old"),
            "user_id": "u1",
            "page_url": "https://example.com/article",
        }
        store.documents[page_key] = legacy
        repository = DynamoPagePreloadRepository(store)

        created = repository.create_if_absent("u1", _record("op-new"))

        self.assertTrue(created.created)
        self.assertEqual(store.documents[(user_pk("u1"), preload_id_sk("op-old"))], legacy)
        self.assertEqual(store.documents[page_key]["preload_id"], "op-new")
        self.assertEqual(len(store.transact_items[-1]), 3)

    def test_dynamo_consistent_legacy_winner_prevents_duplicate_direct_put(self) -> None:
        store = _FakeDynamoStore()
        page_key = (user_pk("u1"), preload_sk("https://example.com/article"))
        legacy = {
            **_record(),
            "user_id": "u1",
            "page_url": "https://example.com/article",
        }
        store.documents[page_key] = legacy
        store.miss_next_page_query = True

        winner = DynamoPagePreloadRepository(store).create_if_absent("u1", _record())

        self.assertFalse(winner.created)
        self.assertEqual(winner.record, legacy)
        self.assertEqual(store.transact_items, [])

    def test_dynamo_legacy_page_index_without_a_winner_fails_closed(self) -> None:
        store = _FakeDynamoStore()
        page_key = (user_pk("u1"), preload_sk("https://example.com/article"))
        store.documents[page_key] = {
            "user_id": "u1",
            "page_url": "https://example.com/article",
            "preload_id": "missing-direct-record",
        }

        with self.assertRaises(PreloadOperationConflict):
            DynamoPagePreloadRepository(store).create_if_absent("u1", _record())
        self.assertNotIn((user_pk("u1"), preload_id_sk("op-1")), store.documents)


class ConditionalContentStoreTests(TestCase):
    def test_filesystem_conditional_create_never_replaces_complete_content(self) -> None:
        with TemporaryDirectory() as directory:
            store = FilesystemPreloadContentStore(Path(directory))
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = [
                    executor.submit(store.put_if_absent, "u1", "op-1", content)
                    for content in ("first", "second")
                ]
                outcomes = [result.result(timeout=2) for result in results]

            self.assertEqual(sum(outcomes), 1)
            self.assertIn(store.get("u1", "op-1"), {"first", "second"})
            self.assertTrue(store.retire("u1", "op-1"))
            self.assertIsNone(store.get("u1", "op-1"))
            self.assertFalse(store.put_if_absent("u1", "op-1", "late private content"))

    def test_s3_conditional_create_maps_only_412_to_existing_content(self) -> None:
        client = mock.Mock()
        client.put_object.side_effect = ClientError(
            {"Error": {"Code": "PreconditionFailed"}, "ResponseMetadata": {"HTTPStatusCode": 412}},
            "PutObject",
        )
        store = S3PreloadContentStore("bucket")
        store._client = client
        self.assertFalse(store.put_if_absent("u1", "op-1", "content"))
        self.assertEqual(client.put_object.call_args.kwargs["IfNoneMatch"], "*")

    def test_s3_conditional_create_propagates_conflict_responses(self) -> None:
        client = mock.Mock()
        client.put_object.side_effect = ClientError(
            {
                "Error": {"Code": "ConditionalRequestConflict"},
                "ResponseMetadata": {"HTTPStatusCode": 409},
            },
            "PutObject",
        )
        store = S3PreloadContentStore("bucket")
        store._client = client

        with self.assertRaises(ClientError):
            store.put_if_absent("u1", "op-1", "content")

    def test_s3_retirement_uses_a_tombstone_until_lifecycle_expiry(self) -> None:
        client = mock.Mock()
        store = S3PreloadContentStore("bucket")
        store._client = client

        self.assertTrue(store.retire("u1", "op-1"))
        self.assertEqual(client.put_object.call_args.kwargs["Body"], b"")

        client.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
            "GetObject",
        )
        self.assertIsNone(store.get("u1", "op-1"))
        client.put_object.reset_mock()
        self.assertTrue(store.put_if_absent("u1", "op-1", "late after lifecycle expiry"))

    def test_s3_retirement_failure_propagates_and_a_later_retry_succeeds(self) -> None:
        client = mock.Mock()
        client.put_object.side_effect = [
            ClientError(
                {"Error": {"Code": "SlowDown"}, "ResponseMetadata": {"HTTPStatusCode": 503}},
                "PutObject",
            ),
            {},
        ]
        store = S3PreloadContentStore("bucket")
        store._client = client

        with self.assertRaises(ClientError):
            store.retire("u1", "op-1")
        self.assertTrue(store.retire("u1", "op-1"))
        self.assertEqual(client.put_object.call_args.kwargs["Body"], b"")
