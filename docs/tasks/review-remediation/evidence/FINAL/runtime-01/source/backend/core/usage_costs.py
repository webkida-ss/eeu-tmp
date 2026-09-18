"""Integer-only model cost calculation and configured rate loading."""

from __future__ import annotations

import os
from dataclasses import dataclass

MICRO_USD_RATE_DENOMINATOR = 1_000_000
DYNAMODB_MAX_INTEGER = 10**38 - 1


class UnknownModelRateError(ValueError):
    """Raised when pricing is unavailable for the requested model."""


@dataclass(frozen=True)
class ModelRate:
    model: str
    input_micro_usd_per_million: int
    output_micro_usd_per_million: int
    version: str


def ensure_dynamodb_safe_integer(value: int, name: str) -> int:
    if not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    if value > DYNAMODB_MAX_INTEGER:
        raise OverflowError(f"{name} exceeds DynamoDB numeric precision")
    return value


def _ceil_component(tokens: int, rate_micro_usd_per_million: int) -> int:
    ensure_dynamodb_safe_integer(tokens, "token count")
    ensure_dynamodb_safe_integer(rate_micro_usd_per_million, "model rate")
    numerator = tokens * rate_micro_usd_per_million
    return ensure_dynamodb_safe_integer(
        (numerator + MICRO_USD_RATE_DENOMINATOR - 1) // MICRO_USD_RATE_DENOMINATOR,
        "cost component",
    )


def calculate_cost_micro_usd(input_tokens: int, output_tokens: int, rate: ModelRate) -> int:
    """Calculate actual cost, rounding input and output independently."""

    return ensure_dynamodb_safe_integer(
        _ceil_component(input_tokens, rate.input_micro_usd_per_million)
        + _ceil_component(output_tokens, rate.output_micro_usd_per_million),
        "cost",
    )


def estimate_cost_micro_usd(input_tokens: int, max_output_tokens: int, rate: ModelRate) -> int:
    """Calculate a conservative cost using the maximum output token count."""

    return calculate_cost_micro_usd(input_tokens, max_output_tokens, rate)


def _configured_positive_rate(name: str) -> int:
    raw_value = os.getenv(name, "").strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise UnknownModelRateError(f"Missing or invalid model rate: {name}") from exc
    if value <= 0:
        raise UnknownModelRateError(f"Missing or invalid model rate: {name}")
    if value > DYNAMODB_MAX_INTEGER:
        raise UnknownModelRateError(f"Missing or invalid model rate: {name}")
    return value


def load_model_rate(model: str | None = None) -> ModelRate:
    """Load the configured OpenAI model's rate, failing closed if unknown."""

    configured_model = os.getenv("OPENAI_MODEL", "").strip()
    requested_model = (model or configured_model).strip()
    version = os.getenv("OPENAI_RATE_CARD_VERSION", "").strip()
    if not configured_model or requested_model != configured_model or not version:
        raise UnknownModelRateError(f"No configured rate for model: {requested_model or '<empty>'}")

    return ModelRate(
        model=configured_model,
        input_micro_usd_per_million=_configured_positive_rate(
            "OPENAI_MODEL_INPUT_MICRO_USD_PER_MILLION"
        ),
        output_micro_usd_per_million=_configured_positive_rate(
            "OPENAI_MODEL_OUTPUT_MICRO_USD_PER_MILLION"
        ),
        version=version,
    )
