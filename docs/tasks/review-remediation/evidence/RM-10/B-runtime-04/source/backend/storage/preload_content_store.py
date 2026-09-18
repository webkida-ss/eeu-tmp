"""Transient store for a preloaded article's raw extracted text.

``submit_preload`` extracts the cleaned article text ("content", capped at
~50 KB) and hands it to the deferred analysis job exactly once. It is a
submit -> worker handoff payload, not durable data: nothing reads it after
the analysis completes, and keeping it inside the DynamoDB preload record
would be dead weight that (with sentences + analysis) risks the 400 KB item
limit. So it lives here instead, outside the record, and is retired to a
nonprivate tombstone once the worker consumes it.

The store is chosen by DI, mirroring the auth/billing/job-runner pattern: a
filesystem implementation for local development and an S3 implementation in
AWS. The content key is derived from the immutable preload ID, carried by
the queue message, so an old worker cannot read or delete newer content for
the same page URL.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Protocol

logger = logging.getLogger("untangle.backend")


class PreloadContentStore(Protocol):
    def put(self, user_id: str, preload_id: str, content: str) -> None: ...

    def put_if_absent(self, user_id: str, preload_id: str, content: str) -> bool: ...

    def retire(self, user_id: str, preload_id: str) -> bool: ...

    def get(self, user_id: str, preload_id: str) -> str | None: ...

    def delete(self, user_id: str, preload_id: str) -> None: ...


class FilesystemPreloadContentStore:
    """Local/default implementation: one UTF-8 text file per (user, preload)
    under a base directory. Deletes are best-effort (a missing file is not an
    error), matching the transient, at-most-once contract."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = Path(base_dir)

    def _path(self, user_id: str, preload_id: str) -> Path:
        return self._base_dir / user_id / f"{preload_id}.txt"

    def put(self, user_id: str, preload_id: str, content: str) -> None:
        path = self._path(user_id, preload_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def put_if_absent(self, user_id: str, preload_id: str, content: str) -> bool:
        path = self._path(user_id, preload_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
                temporary_path = Path(handle.name)
                handle.write(content.encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary_path, path)
            except FileExistsError:
                return False
            directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return True
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def retire(self, user_id: str, preload_id: str) -> bool:
        """Replace private content with an empty tombstone that blocks late writers."""
        path = self._path(user_id, preload_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
                temporary_path = Path(handle.name)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
            temporary_path = None
            directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return True
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def get(self, user_id: str, preload_id: str) -> str | None:
        path = self._path(user_id, preload_id)
        if not path.exists():
            return None
        content = path.read_text(encoding="utf-8")
        return content or None

    def delete(self, user_id: str, preload_id: str) -> None:
        self._path(user_id, preload_id).unlink(missing_ok=True)


class S3PreloadContentStore:
    """AWS implementation: one object per (user, preload) under a fixed prefix.

    boto3 is imported lazily so the local-development import graph stays free
    of the AWS SDK unless the S3 store is actually used (mirrors the SQS job
    runner and the DynamoDB store). Orphaned objects self-clean via a bucket
    lifecycle rule (see infra/modules/reading-assistant-data), so this store
    never needs to sweep; it only puts, gets, and best-effort deletes.
    """

    _PREFIX = "preload-content"

    def __init__(self, bucket: str, *, region_name: str | None = None) -> None:
        self._bucket = bucket
        self._region_name = region_name
        self._client = None

    def _get_client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("s3", region_name=self._region_name)
        return self._client

    def _key(self, user_id: str, preload_id: str) -> str:
        return f"{self._PREFIX}/{user_id}/{preload_id}.txt"

    def put(self, user_id: str, preload_id: str, content: str) -> None:
        self._get_client().put_object(
            Bucket=self._bucket,
            Key=self._key(user_id, preload_id),
            Body=content.encode("utf-8"),
            ContentType="text/plain; charset=utf-8",
        )

    def put_if_absent(self, user_id: str, preload_id: str, content: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._get_client().put_object(
                Bucket=self._bucket,
                Key=self._key(user_id, preload_id),
                Body=content.encode("utf-8"),
                ContentType="text/plain; charset=utf-8",
                IfNoneMatch="*",
            )
        except ClientError as exc:
            error = exc.response.get("Error", {})
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 412 or error.get("Code") in {"PreconditionFailed", "412"}:
                return False
            raise
        return True

    def retire(self, user_id: str, preload_id: str) -> bool:
        self._get_client().put_object(
            Bucket=self._bucket,
            Key=self._key(user_id, preload_id),
            Body=b"",
            ContentType="text/plain; charset=utf-8",
        )
        return True

    def get(self, user_id: str, preload_id: str) -> str | None:
        from botocore.exceptions import ClientError

        try:
            response = self._get_client().get_object(
                Bucket=self._bucket, Key=self._key(user_id, preload_id)
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return None
            raise
        content = response["Body"].read().decode("utf-8")
        return content or None

    def delete(self, user_id: str, preload_id: str) -> None:
        # delete_object is idempotent: deleting a missing key is not an error.
        self._get_client().delete_object(Bucket=self._bucket, Key=self._key(user_id, preload_id))
