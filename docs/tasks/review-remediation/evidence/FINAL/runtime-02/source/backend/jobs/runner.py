"""Preload job runner port.

Framework-free. The reading service submits a preload synchronously (fast:
extraction only), persists a "processing" record, then hands the slow
analysis off to a runner. The runner is chosen by DI, mirroring the
auth/billing provider pattern: an inline thread runner for local
development, an SQS runner in AWS so the analysis outlives API Gateway's
30-second integration cap.
"""

from __future__ import annotations

from typing import Any, Protocol


class PreloadJobRunner(Protocol):
    def enqueue(
        self,
        user_id: str,
        page_url: str,
        preload_id: str,
        learner_profile_fingerprint: str,
        usage_context: dict[str, Any] | None = None,
    ) -> None: ...
