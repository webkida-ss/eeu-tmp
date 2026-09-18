"""AWS Lambda entrypoint for the async preload worker (SQS-triggered).

The API Lambda (lambda_handler.py) enqueues immutable {user_id, page_url,
preload_id, learner_profile_fingerprint} messages onto the preload jobs queue.
This worker conditionally claims the matching record before running the slow
analysis, so stale or duplicate messages cannot publish results.

The DynamoDB store factory applies the SDK default credential chain outside
DynamoDB Local, so this entrypoint imports its dependencies without rewriting
storage factories.

Returns a partial batch response (batchItemFailures): only messages that
raised an infrastructure error are reported for redelivery. A failed
*analysis* is recorded on the preload record as status "failed" inside
run_preload_job and does not retry.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from deps import (
    get_accounts,
    get_page_preload_repository,
    get_preload_content_store,
    get_subscription_repository,
    get_usage_repository,
)
from services.reading import run_preload_job

logger = logging.getLogger("untangle.worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    repository = get_page_preload_repository()
    subscription_repository = get_subscription_repository()
    usage_repository = get_usage_repository()
    content_store = get_preload_content_store()
    billing_provider_mode = get_accounts().settings.billing_provider

    batch_item_failures: list[dict[str, str]] = []
    for message in event.get("Records", []):
        message_id = message.get("messageId")
        try:
            body = json.loads(message["body"])
            required_fields = {
                "user_id",
                "page_url",
                "preload_id",
                "learner_profile_fingerprint",
            }
            if not required_fields.issubset(body):
                logger.warning(
                    "acknowledging legacy preload message without immutable identity: %s",
                    message_id or "-",
                )
                continue
            run_preload_job(
                repository,
                subscription_repository,
                usage_repository,
                content_store,
                body["user_id"],
                body["page_url"],
                body["preload_id"],
                body["learner_profile_fingerprint"],
                body.get("usage_context") or None,
                billing_provider_mode=billing_provider_mode,
            )
        except Exception:  # noqa: BLE001 - report the message for SQS redelivery
            logger.exception("preload worker failed for message %s", message_id)
            if message_id:
                batch_item_failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": batch_item_failures}
