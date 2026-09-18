from __future__ import annotations

import json
import uuid
from importlib import import_module, util

from accounts.storage import JsonEmailAuthService
from auth.dynamodb_email_auth import DynamoEmailAuthService
from boto3.dynamodb.types import TypeDeserializer
from botocore.exceptions import ClientError
from core import pipeline
from repositories.phrase_repository import JsonPhraseRepository
from schemas import AnalyzeResponse, OperationRequest, PhraseCreateRequest
from services import reading

_DESERIALIZER = TypeDeserializer()


def assert_uuid7(value: str) -> None:
    parsed = uuid.UUID(value)
    assert parsed.version == 7
    assert parsed.variant == uuid.RFC_4122


def test_framework_neutral_generator_produces_rfc9562_uuid7_values():
    assert util.find_spec("core.ids") is not None
    generate_uuid7 = import_module("core.ids").generate_uuid7
    values = {generate_uuid7() for _ in range(256)}
    assert len(values) == 256
    for value in values:
        assert_uuid7(value)


def test_operation_request_keeps_one_retry_identifier():
    request = OperationRequest()
    first = request.operation_id
    assert_uuid7(first)
    assert OperationRequest.model_validate(request.model_dump()).operation_id == first


def test_json_auth_creates_uuid7_user(tmp_path):
    service = JsonEmailAuthService(tmp_path / "users.json", tmp_path / "sessions.json")
    _, user = service.login(email="learner@example.test")
    assert_uuid7(user.id)


class MemoryDynamoStore:
    table_name = "uuid7-test"

    def __init__(self):
        self.documents = {}

    def put_document(self, partition_key, sort_key, value):
        self.documents[(partition_key, sort_key)] = dict(value)

    def get_document(self, partition_key, sort_key, *, consistent_read=False):
        value = self.documents.get((partition_key, sort_key))
        return dict(value) if value is not None else None

    def delete(self, partition_key, sort_key):
        self.documents.pop((partition_key, sort_key), None)

    def transact_write(self, transactions):
        decoded = []
        for transaction in transactions:
            put = transaction["Put"]
            item = {name: _DESERIALIZER.deserialize(value) for name, value in put["Item"].items()}
            decoded.append((item, put["ConditionExpression"]))
        for item, condition in decoded:
            if condition != "attribute_not_exists(pk) AND attribute_not_exists(sk)":
                raise AssertionError(f"Unexpected condition: {condition}")
            if (item["pk"], item["sk"]) in self.documents:
                raise ClientError(
                    {
                        "Error": {
                            "Code": "TransactionCanceledException",
                            "Message": "conditional",
                        },
                        "CancellationReasons": [
                            {"Code": "ConditionalCheckFailed"},
                            {"Code": "None"},
                        ],
                    },
                    "TransactWriteItems",
                )
        for item, _condition in decoded:
            self.documents[(item["pk"], item["sk"])] = json.loads(item["document"])


def test_dynamodb_auth_creates_uuid7_user():
    service = DynamoEmailAuthService(MemoryDynamoStore())
    _, user = service.login(email="learner@example.test")
    assert_uuid7(user.id)


def test_phrase_creation_uses_uuid7(tmp_path):
    repository = JsonPhraseRepository(tmp_path / "phrases.json")
    phrase = reading.create_phrase(
        repository,
        "user-1",
        PhraseCreateRequest(
            original_text="Learning takes practice.",
            analysis=AnalyzeResponse(original_text="Learning takes practice."),
        ),
    )
    assert_uuid7(phrase.id)


def test_pipeline_indexed_sentences_and_study_items_use_uuid7(monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "_call_openai_json",
        lambda *args, **kwargs: {
            "summary": "Summary",
            "topics": ["learning"],
            "sentences": [
                {
                    "index": 0,
                    "translation": "Translation",
                    "vocabulary": ["practice [noun]: repeated exercise"],
                }
            ],
        },
    )
    _, _, sentences = pipeline._analyze_sentences(
        ["Learning takes practice."],
        page_title=None,
        vocabulary_coverage_percent=10,
    )
    items = pipeline._collect_study_items_from_sentences(sentences)
    assert_uuid7(sentences[0]["id"])
    assert_uuid7(items[0]["id"])
