"""Framework-neutral opaque identifier generation."""

from __future__ import annotations

import secrets
import time
import uuid


def generate_uuid7() -> str:
    """Generate an RFC 9562 UUID v7 using a secure random source."""
    timestamp_ms = int(time.time_ns() // 1_000_000) & ((1 << 48) - 1)
    random_bits = secrets.randbits(74)
    value = timestamp_ms << 80
    value |= 0x7 << 76
    value |= ((random_bits >> 62) & 0xFFF) << 64
    value |= 0b10 << 62
    value |= random_bits & ((1 << 62) - 1)
    return str(uuid.UUID(int=value))
