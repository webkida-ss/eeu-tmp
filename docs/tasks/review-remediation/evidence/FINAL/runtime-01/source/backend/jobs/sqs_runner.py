"""AWS SQS preload job runner.

Sends a {user_id, page_url, preload_id, learner_profile_fingerprint} message
to the preload jobs queue; a separate worker Lambda (worker_handler.py)
conditionally claims that exact record before running the analysis. This
decouples the slow analysis from the request/response cycle while preventing
an old message from publishing over a newer learner profile.

boto3 is imported lazily so the module (and the local-development import
graph) stays free of the AWS SDK unless the SQS runner is actually used.
"""

from __future__ import annotations

import json
from typing import Any

from core.pipeline import PipelineError


class SqsPreloadJobRunner:
    def __init__(self, queue_url: str, *, region_name: str | None = None) -> None:
        self._queue_url = queue_url
        self._region_name = region_name
        self._client = None

    def _get_client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("sqs", region_name=self._region_name)
        return self._client

    def enqueue(
        self,
        user_id: str,
        page_url: str,
        preload_id: str,
        learner_profile_fingerprint: str,
        usage_context: dict[str, Any] | None = None,
    ) -> None:
        if not self._queue_url:
            raise PipelineError(
                "PRELOAD_JOBS_QUEUE_URL is not set; cannot enqueue the preload job.",
                status_code=500,
            )

        self._get_client().send_message(
            QueueUrl=self._queue_url,
            MessageBody=json.dumps(
                {
                    "user_id": user_id,
                    "page_url": page_url,
                    "preload_id": preload_id,
                    "learner_profile_fingerprint": learner_profile_fingerprint,
                    "usage_context": usage_context or {},
                }
            ),
        )
