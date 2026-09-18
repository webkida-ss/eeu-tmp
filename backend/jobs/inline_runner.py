"""Bounded local-development preload job runner.

Runs preload analysis in a fixed-size executor so `POST /pages/preload`
returns immediately while worker and queue capacity remain deterministic.
Shutdown waits for accepted work by default; unaccepted work receives a
stable saturation error and follows normal reservation-release recovery.
"""

from __future__ import annotations

import atexit
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from accounts import SubscriptionRepository
from repositories.admin_activity import AdminActivityRepository
from repositories.page_preload_repository import PagePreloadRepository
from repositories.usage_repository import UsageRepository
from services.reading import run_preload_job
from storage.preload_content_store import PreloadContentStore

logger = logging.getLogger("untangle.backend")


class InlineJobQueueSaturated(RuntimeError):
    pass


class InlinePreloadJobRunner:
    def __init__(
        self,
        repository: PagePreloadRepository,
        subscription_repository: SubscriptionRepository,
        usage_repository: UsageRepository,
        content_store: PreloadContentStore,
        admin_activity_repository: AdminActivityRepository | None = None,
        *,
        max_workers: int | None = None,
        queue_capacity: int | None = None,
        billing_provider_mode: str = "stripe",
    ) -> None:
        self._repository = repository
        self._subscription_repository = subscription_repository
        self._usage_repository = usage_repository
        self._content_store = content_store
        self._admin_activity_repository = admin_activity_repository
        self._billing_provider_mode = billing_provider_mode
        workers = max(
            1,
            max_workers
            if max_workers is not None
            else int(os.getenv("INLINE_JOB_MAX_WORKERS", "2")),
        )
        queued = max(
            0,
            queue_capacity
            if queue_capacity is not None
            else int(os.getenv("INLINE_JOB_QUEUE_CAPACITY", "16")),
        )
        self._capacity = threading.BoundedSemaphore(workers + queued)
        self._executor = ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="preload-job",
        )
        self._state_lock = threading.Lock()
        self._shutdown = False
        atexit.register(self.shutdown, wait=False)

    def enqueue(
        self,
        user_id: str,
        page_url: str,
        preload_id: str,
        learner_profile_fingerprint: str,
        usage_context: dict[str, Any] | None = None,
    ) -> None:
        with self._state_lock:
            if self._shutdown:
                raise RuntimeError("Inline preload runner is shut down")
            if not self._capacity.acquire(blocking=False):
                raise InlineJobQueueSaturated("Inline preload job queue is saturated")
            try:
                future = self._executor.submit(
                    self._run,
                    user_id,
                    page_url,
                    preload_id,
                    learner_profile_fingerprint,
                    usage_context,
                )
            except Exception:
                self._capacity.release()
                raise
            future.add_done_callback(lambda _future: self._capacity.release())

    def shutdown(self, *, wait: bool = True) -> None:
        with self._state_lock:
            if self._shutdown:
                return
            self._shutdown = True
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def _run(
        self,
        user_id: str,
        page_url: str,
        preload_id: str,
        learner_profile_fingerprint: str,
        usage_context: dict[str, Any] | None = None,
    ) -> None:
        try:
            run_preload_job(
                self._repository,
                self._subscription_repository,
                self._usage_repository,
                self._content_store,
                user_id,
                page_url,
                preload_id,
                learner_profile_fingerprint,
                usage_context,
                admin_activity_repository=self._admin_activity_repository,
                billing_provider_mode=self._billing_provider_mode,
            )
        except Exception:  # pragma: no cover - defensive; run_preload_job self-guards
            logger.exception("inline preload job crashed user=%s url=%s", user_id, page_url)
