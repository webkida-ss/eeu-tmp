"""Shared openapi-core adapters for canonical contract tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit

from openapi_core import OpenAPI
from openapi_core.protocols import RequestParameters


@dataclass
class ContractRequest:
    method: str
    url: str
    body: bytes | None = None
    content_type: str = ""
    headers: Mapping[str, Any] | None = None
    path_parameters: Mapping[str, Any] | None = None

    @property
    def host_url(self) -> str:
        parsed = urlsplit(self.url)
        return f"{parsed.scheme}://{parsed.netloc}"

    @property
    def path(self) -> str:
        return urlsplit(self.url).path

    @property
    def parameters(self) -> RequestParameters:
        parsed = urlsplit(self.url)
        query = {
            key: values[-1] if len(values) == 1 else values
            for key, values in parse_qs(parsed.query, keep_blank_values=True).items()
        }
        return RequestParameters(
            query=query,
            header=dict(self.headers or {}),
            path=dict(self.path_parameters or {}),
            cookie={},
        )


@dataclass
class ContractResponse:
    status_code: int
    data: bytes | None
    headers: Mapping[str, Any]

    @property
    def content_type(self) -> str:
        return str(self.headers.get("content-type", ""))


def openapi_from_bundle(bundle: dict[str, Any]) -> OpenAPI:
    return OpenAPI.from_dict(bundle)


def encode_body(value: Any, media_type: str | None) -> bytes | None:
    if value is None:
        return None
    if media_type == "application/json":
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
    return str(value).encode()


def assert_status_and_media(actual: Any, expected_status: int, expected_media_type: str) -> None:
    assert actual.status_code == expected_status
    content_type = actual.headers.get("content-type")
    assert content_type, "Response Content-Type is required."
    assert content_type.split(";", 1)[0].strip().lower() == expected_media_type.lower()
