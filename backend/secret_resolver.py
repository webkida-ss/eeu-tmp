"""Resolve provider secrets from env or SSM without putting values in Terraform.

Local development keeps setting OPENAI_API_KEY and STRIPE_* in `.env`.
Deployed Lambdas receive only `*_SSM_PARAMETER` names and load values at
startup. The placeholder created by Terraform (`REPLACE_ME`) is treated as
unset so a forgotten `put-parameter` fails closed.
"""

from __future__ import annotations

import os
from functools import lru_cache

_SSM_SUFFIX = "_SSM_PARAMETER"
_UNSET_PLACEHOLDERS = frozenset({"", "REPLACE_ME"})


def resolve_runtime_secrets() -> None:
    """Fill empty secret env vars from matching `*_SSM_PARAMETER` names."""
    assignments = [
        (name[: -len(_SSM_SUFFIX)], value.strip())
        for name, value in os.environ.items()
        if name.endswith(_SSM_SUFFIX) and value.strip()
    ]
    for target, parameter_name in assignments:
        current = os.getenv(target, "").strip()
        if current and current not in _UNSET_PLACEHOLDERS:
            continue
        resolved = _get_ssm_parameter(parameter_name)
        if resolved in _UNSET_PLACEHOLDERS:
            os.environ.pop(target, None)
            continue
        os.environ[target] = resolved


@lru_cache(maxsize=16)
def _get_ssm_parameter(name: str) -> str:
    import boto3

    client = boto3.client("ssm", region_name=os.getenv("AWS_REGION", "ap-northeast-1"))
    response = client.get_parameter(Name=name, WithDecryption=True)
    value = response.get("Parameter", {}).get("Value")
    if not isinstance(value, str):
        return ""
    return value.strip()
