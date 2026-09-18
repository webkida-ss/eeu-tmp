from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import schemas
from core.pipeline import UsageTally
from repositories.admin_activity import (
    ActivityEvent,
    ActivityOperation,
    ActivityStatus,
    AdminActivityRepository,
    require_aware_datetime,
)

_UNSAFE_METADATA = re.compile(r"[^A-Za-z0-9._:/-]+")
_ERROR_CODE_LIMIT = 64
_MODEL_LIMIT = 128
logger = logging.getLogger("untangle.backend")


def _safe_metadata(value: str | None, *, limit: int) -> str | None:
    if value is None:
        return None
    sanitized = _UNSAFE_METADATA.sub("_", value.strip()).strip("_")
    return sanitized[:limit] or None


@dataclass(frozen=True)
class TerminalActivityOutcome:
    """The terminal result needed to persist one learner activity event."""

    operation: ActivityOperation
    operation_id: str
    user_id: str
    status: ActivityStatus
    error: Exception | None = None
    tally: UsageTally | None = None
    usage: dict[str, Any] | None = None
    model: str | None = None

    @property
    def source_id(self) -> str:
        return f"{self.operation}:{self.operation_id}:{self.status}"

    @classmethod
    def for_preload(
        cls,
        user_id: str,
        preload_id: str,
        status: ActivityStatus,
        *,
        error: Exception | None = None,
        record: dict[str, Any] | None = None,
        tally: UsageTally | None = None,
    ) -> TerminalActivityOutcome:
        details = record or {}
        return cls(
            operation="article",
            operation_id=preload_id,
            user_id=user_id,
            status=status,
            error=error,
            tally=tally,
            usage=details.get("usage_tally") or details.get("failure_usage"),
            model=details.get("model"),
        )


def _shadow_usage(tally: UsageTally) -> dict[str, Any]:
    try:
        return asdict(tally.snapshot())
    except Exception:
        return {
            "input_tokens": tally.input_tokens,
            "output_tokens": tally.output_tokens,
            "total_tokens": tally.total_tokens,
        }


def _activity_values(
    tally: UsageTally | None,
    usage: dict[str, Any] | None,
    *,
    model: str | None,
) -> dict[str, Any]:
    values = dict(usage or {})
    if tally is not None:
        try:
            values = {**asdict(tally.snapshot()), **values}
        except Exception:
            values = {
                **_shadow_usage(tally),
                "provider_model": tally.provider_model or None,
                **values,
            }
    return {
        "input_tokens": values.get("input_tokens"),
        "output_tokens": values.get("output_tokens"),
        "tokens": (
            values.get("total_tokens")
            if values.get("total_tokens") is not None
            else values.get("tokens")
        ),
        "actual_cost_micro_usd": (
            values.get("actual_cost_micro_usd")
            if values.get("actual_cost_micro_usd") is not None
            else values.get("cost_micro_usd")
        ),
        "model": model or values.get("provider_model") or values.get("model"),
    }


def _error_code(error: Exception | None) -> str | None:
    if error is None:
        return None
    from services.entitlements import EntitlementError

    return error.code if isinstance(error, EntitlementError) else type(error).__name__


def record_terminal_activity(
    repository: AdminActivityRepository | None,
    outcome: TerminalActivityOutcome,
    *,
    preserve_failure: bool = False,
) -> None:
    """Translate and persist a terminal outcome at the activity seam.

    Telemetry failures normally retain the historical propagation behavior.
    Callers handling an original request failure may explicitly request the
    legacy logging-and-suppression behavior with ``preserve_failure``.
    """
    if repository is None:
        return

    try:
        AdminActivityService(repository).record_activity(
            source_id=outcome.source_id,
            user_id=outcome.user_id,
            operation=outcome.operation,
            status=outcome.status,
            error_code=_error_code(outcome.error),
            **_activity_values(
                outcome.tally,
                outcome.usage,
                model=outcome.model,
            ),
        )
    except Exception:
        if not preserve_failure:
            raise
        logger.exception(
            "admin activity recording failed operation=%s status=%s source_id=%s",
            outcome.operation,
            outcome.status,
            outcome.source_id,
        )


class AdminActivityService:
    def __init__(self, repository: AdminActivityRepository) -> None:
        self._repository = repository

    def record_activity(
        self,
        *,
        source_id: str,
        user_id: str,
        operation: ActivityOperation,
        status: ActivityStatus,
        recorded_at: datetime | None = None,
        error_code: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        tokens: int | None = None,
        actual_cost_micro_usd: int | None = None,
        model: str | None = None,
    ) -> ActivityEvent:
        timestamp = recorded_at or datetime.now(UTC)
        require_aware_datetime("recorded_at", timestamp)
        timestamp = timestamp.astimezone(UTC)

        for name, value in (
            ("input_tokens", input_tokens),
            ("output_tokens", output_tokens),
            ("tokens", tokens),
            ("actual_cost_micro_usd", actual_cost_micro_usd),
        ):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a non-negative integer or None")

        event = ActivityEvent(
            id=schemas.generate_uuid7(),
            source_id=source_id,
            user_id=user_id,
            operation=operation,
            status=status,
            recorded_at=timestamp,
            error_code=_safe_metadata(error_code, limit=_ERROR_CODE_LIMIT),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tokens=tokens,
            actual_cost_micro_usd=actual_cost_micro_usd,
            model=_safe_metadata(model, limit=_MODEL_LIMIT),
        )
        return self._repository.append(event)
