"""Read-only projections for preloads and the vocabulary book."""

from __future__ import annotations

from typing import Any

from repositories.page_preload_repository import PagePreloadRepository
from schemas import (
    IndexedSentence,
    PagePreloadResponse,
    PagePreloadStatusResponse,
    StudyItem,
    VocabularyBookItem,
    VocabularyBookResponse,
    VocabularyCoverageStats,
)

# Vocabulary from the newest preloaded articles is intentionally bounded.
VOCABULARY_BOOK_MAX_PRELOADS = 30
VOCABULARY_BOOK_MAX_ITEMS = 600


def resolve_page_preload(
    repository: PagePreloadRepository,
    *,
    user_id: str,
    preload_id: str | None = None,
    page_url: str | None = None,
) -> dict[str, Any] | None:
    if preload_id:
        record = repository.get_by_id(user_id, preload_id)
        if record:
            return record

    if page_url:
        return repository.get_by_page_url(user_id, page_url)

    return None


def to_preload_response(record: dict[str, Any]) -> PagePreloadResponse:
    # Tolerant of "processing" and "failed" records, which have no summary,
    # sentences, or study items yet. A missing status stays None, which
    # clients read as "ready" (records saved before the async pipeline).
    vocabulary_coverage = record.get("vocabulary_coverage")
    return PagePreloadResponse(
        id=record["id"],
        page_url=record["page_url"],
        page_title=record.get("page_title"),
        summary=record.get("summary") or "",
        topics=record.get("topics") or [],
        sentences=[IndexedSentence(**sentence) for sentence in record.get("sentences") or []],
        study_items=[StudyItem(**item) for item in record.get("study_items") or []],
        learner_level=record.get("learner_level"),
        target_language=record.get("target_language"),
        native_language=record.get("native_language"),
        vocabulary_coverage_percent=record.get("vocabulary_coverage_percent"),
        vocabulary_coverage=(
            VocabularyCoverageStats(**vocabulary_coverage) if vocabulary_coverage else None
        ),
        created_at=record.get("created_at") or "",
        sentences_detected=record.get("sentences_detected"),
        sentence_limit=record.get("sentence_limit"),
        source_tokens_detected=record.get("source_tokens_detected"),
        source_tokens_analyzed=record.get("source_tokens_analyzed"),
        source_token_limit=record.get("source_token_limit"),
        status=record.get("status"),
        error=record.get("error"),
    )


def record_status(record: dict[str, Any]) -> str | None:
    return record.get("status")


def is_ready(record: dict[str, Any]) -> bool:
    # A missing status means the record predates the async pipeline and is
    # already fully populated, so it counts as ready.
    return record_status(record) in (None, "ready")


def to_status_response(record: dict[str, Any]) -> PagePreloadStatusResponse:
    return PagePreloadStatusResponse(
        ready=is_ready(record),
        preload=to_preload_response(record),
        status=record_status(record),
        error=record.get("error"),
    )


def get_preload_status(
    repository: PagePreloadRepository, user_id: str, page_url: str
) -> PagePreloadStatusResponse:
    record = repository.get_by_page_url(user_id, page_url)
    if not record:
        return PagePreloadStatusResponse(ready=False)

    return to_status_response(record)


def build_vocabulary_book(
    repository: PagePreloadRepository, user_id: str
) -> VocabularyBookResponse:
    # Vocabulary from every preloaded article, newest article first. Meanings
    # are context-specific per article, so the same word appearing in two
    # articles is deliberately kept as two entries.
    records = repository.list_for_user(user_id)[:VOCABULARY_BOOK_MAX_PRELOADS]

    items: list[VocabularyBookItem] = []
    for record in records:
        for study_item in record.get("study_items") or []:
            if len(items) >= VOCABULARY_BOOK_MAX_ITEMS:
                break
            text = str(study_item.get("text") or "").strip()
            if not text:
                continue
            items.append(
                VocabularyBookItem(
                    id=str(study_item.get("id") or ""),
                    text=text,
                    meaning=str(study_item.get("meaning") or ""),
                    part_of_speech=str(study_item.get("part_of_speech") or ""),
                    example=str(study_item.get("example") or ""),
                    preload_id=str(record.get("id") or ""),
                    page_url=str(record.get("page_url") or ""),
                    page_title=record.get("page_title"),
                    created_at=str(record.get("created_at") or ""),
                    target_language=record.get("target_language"),
                    native_language=record.get("native_language"),
                )
            )

    return VocabularyBookResponse(items=items, preload_count=len(records))
