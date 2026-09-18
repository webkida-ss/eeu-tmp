"""API contracts: request/response models shared by every handler layer.

Framework-free (pydantic only): the FastAPI app, tests, and any future
Lambda handler all validate against these same models.
"""

from __future__ import annotations

import uuid
from typing import Any

from core.ids import generate_uuid7
from pydantic import BaseModel, Field, field_validator

MAX_PAGE_HTML_LENGTH = 500_000
MIN_VOCABULARY_COVERAGE_PERCENT = 1
MAX_VOCABULARY_COVERAGE_PERCENT = 50


class ApiError(BaseModel):
    detail: Any
    code: str | None = None


class OperationRequest(BaseModel):
    # Omission is accepted for legacy transports, but cross-request
    # idempotency requires the caller to supply and reuse one operation ID.
    operation_id: str = Field(
        default_factory=generate_uuid7,
        description="Opaque RFC 9562 UUID v7 idempotency identifier.",
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        json_schema_extra={
            "format": "uuid",
            "example": "018f47a2-7b3c-7abc-8def-0123456789ab",
        },
    )

    @field_validator("operation_id")
    @classmethod
    def validate_operation_id(cls, value: str) -> str:
        try:
            parsed = uuid.UUID(str(value))
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("operation_id must be a UUID v7") from exc
        if parsed.version != 7 or parsed.variant != uuid.RFC_4122:
            raise ValueError("operation_id must be a UUID v7")
        return str(parsed)


class SentenceAnalysis(BaseModel):
    translation: str
    grammar: str
    nuance: str
    vocabulary: list[str]
    examples: list[str]
    study_tip: str


class IndexedSentence(BaseModel):
    id: str
    index: int
    text: str
    analysis: SentenceAnalysis


class StudyItem(BaseModel):
    id: str
    type: str
    text: str
    meaning: str
    part_of_speech: str = ""
    example: str = ""
    sentence_ids: list[str] = Field(default_factory=list)


class VocabularyCoverageStats(BaseModel):
    coverage_percent: float
    pool_size: int
    target_count: int
    item_count: int
    candidate_count: int


class AnalyzeRequest(OperationRequest):
    text: str = Field(min_length=1, max_length=3000)
    page_url: str | None = None
    page_title: str | None = None
    page_preload_id: str | None = None
    target_language: str | None = Field(default=None, max_length=16)
    native_language: str | None = Field(default=None, max_length=16)


class AnalyzeResponse(BaseModel):
    original_text: str
    translation: str = ""
    grammar: str = ""
    # The model is no longer asked to emit these three, but stored preloads
    # and API consumers still carry them, so they stay with empty defaults.
    nuance: str = ""
    vocabulary: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    study_tip: str = ""
    used_preload: bool = False


class PhraseCreateRequest(BaseModel):
    original_text: str = Field(min_length=1, max_length=3000)
    analysis: AnalyzeResponse
    page_url: str | None = None
    page_title: str | None = None


class PhraseRecord(PhraseCreateRequest):
    id: str
    created_at: str


class PagePreloadRequest(OperationRequest):
    page_url: str = Field(min_length=1, max_length=4096)
    page_title: str | None = None
    html: str = Field(min_length=1, max_length=MAX_PAGE_HTML_LENGTH)
    learner_level: str | None = Field(default=None, max_length=500)
    target_language: str | None = Field(default=None, max_length=16)
    native_language: str | None = Field(default=None, max_length=16)
    vocabulary_coverage_percent: float | None = Field(
        default=None,
        ge=MIN_VOCABULARY_COVERAGE_PERCENT,
        le=MAX_VOCABULARY_COVERAGE_PERCENT,
    )


class PagePreloadResponse(BaseModel):
    id: str
    page_url: str
    page_title: str | None
    summary: str
    topics: list[str]
    sentences: list[IndexedSentence]
    study_items: list[StudyItem] = Field(default_factory=list)
    learner_level: str | None = None
    target_language: str | None = None
    native_language: str | None = None
    vocabulary_coverage_percent: float | None = None
    vocabulary_coverage: VocabularyCoverageStats | None = None
    created_at: str
    # Plan-cap truncation info: how many sentences the mechanical pre-split
    # detected vs. the per-article limit that was applied (None on records
    # stored before metering existed).
    sentences_detected: int | None = None
    sentence_limit: int | None = None
    source_tokens_detected: int | None = None
    source_tokens_analyzed: int | None = None
    source_token_limit: int | None = None
    # Async preload lifecycle: "processing" while the analysis runs, "ready"
    # once it is done, "failed" (with `error` set) if it could not complete.
    # None on records stored before the async pipeline existed; clients treat
    # a missing status as "ready" for backward compatibility.
    status: str | None = None
    error: str | None = None


class PagePreloadStatusResponse(BaseModel):
    ready: bool
    preload: PagePreloadResponse | None = None
    # Passthrough of the record's lifecycle so a client can distinguish a
    # missing record (status None, preload None) from one still processing or
    # one that failed, without inspecting the nested preload.
    status: str | None = None
    error: str | None = None


class VocabularyBookItem(BaseModel):
    id: str
    text: str
    meaning: str
    part_of_speech: str = ""
    example: str = ""
    preload_id: str
    page_url: str
    page_title: str | None = None
    created_at: str = ""
    target_language: str | None = None
    native_language: str | None = None


class VocabularyBookResponse(BaseModel):
    items: list[VocabularyBookItem]
    preload_count: int


class ChatMessage(BaseModel):
    role: str = Field(pattern=r"^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(OperationRequest):
    message: str = Field(min_length=1, max_length=2000)
    page_preload_id: str | None = None
    page_url: str | None = None
    page_title: str | None = None
    sentence_id: str | None = None
    study_item_id: str | None = None
    context_label: str = Field(default="sentence", max_length=32)
    context_text: str = Field(min_length=1, max_length=3000)
    context_analysis: dict[str, Any] | None = None
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)
    target_language: str | None = Field(default=None, max_length=16)
    native_language: str | None = Field(default=None, max_length=16)


class ChatResponse(BaseModel):
    reply: str


class BillingMeResponse(BaseModel):
    plan: str
    quota_plan: str
    month: str
    articles_used: int
    articles_pending: int
    articles_limit: int
    articles_remaining: int
    chats_used: int
    chats_pending: int
    chats_limit: int
    chats_remaining: int
    reset_at: str
    sentences_per_article: int
    source_tokens_per_article: int
    warning_codes: list[str] = Field(default_factory=list)
    # Unix timestamp of a scheduled cancellation (the plan stays active
    # until then); None when no cancellation is pending.
    plan_ends_at: int | None = None


# CheckoutRequest / CheckoutResponse / PortalResponse now live in
# accounts.models: they are part of the shared subscription contract, not
# of Untangle's reading API.
