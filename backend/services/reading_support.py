"""Shared usage evidence and request identity for reading execution."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict
from typing import Any

from core.pipeline import UsageTally

logger = logging.getLogger("untangle.backend")


def _log_recovery_event(event: str, **fields: Any) -> None:
    logger.info(
        json.dumps(
            {"event": event, "metric_name": event, "metric_value": 1, **fields},
            sort_keys=True,
        )
    )


def canonical_payload_hash(payload: Any, *, exclude: set[str] | None = None) -> str:
    """Hash a stable, normalized representation of cost-affecting input."""
    raw = payload.model_dump() if hasattr(payload, "model_dump") else payload
    excluded = exclude or set()
    if isinstance(raw, dict):
        raw = {key: value for key, value in raw.items() if key not in excluded}

    def normalize(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in sorted(value.items())}
        if isinstance(value, list):
            return [normalize(item) for item in value]
        return value

    encoded = json.dumps(normalize(raw), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _dispatch_was_attempted(tally: UsageTally | None, error: Exception) -> bool:
    return bool(
        (tally and tally.any_dispatch_attempted) or getattr(error, "dispatch_attempted", False)
    )


def _settlement_usage(tally: UsageTally, operation: Any) -> dict[str, Any]:
    """Build one durable usage snapshot without replacing known partial usage.

    Complete provider usage settles at its measured cost. Any missing or
    incurred-call uncertainty retains every known counter and applies only the
    reservation floor, rather than adding that floor on top of known cost.
    """
    snapshot = asdict(tally.snapshot())
    complete = not snapshot["missing_usage"] and snapshot["total_tokens"] > 0
    snapshot["usage_complete"] = complete
    if complete:
        snapshot["actual_cost_micro_usd"] = int(snapshot["cost_micro_usd"])
    else:
        snapshot["actual_cost_micro_usd"] = max(
            int(snapshot["cost_micro_usd"]),
            int(operation.reserved_cost_micro_usd),
        )
    return snapshot


def _shadow_estimate(factory: Any) -> int | None:
    try:
        return max(0, int(factory()))
    except Exception:
        # Shadow calibration must never block a provider call.
        return None


def _shadow_usage(tally: UsageTally | None) -> dict[str, Any]:
    if tally is None:
        return {}
    try:
        return asdict(tally.snapshot())
    except Exception:
        return {
            "input_tokens": tally.input_tokens,
            "output_tokens": tally.output_tokens,
            "total_tokens": tally.total_tokens,
        }
