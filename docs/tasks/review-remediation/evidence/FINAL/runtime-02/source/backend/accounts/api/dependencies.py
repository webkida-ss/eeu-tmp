"""FastAPI dependencies bound to an `AccountsContainer`.

The container arrives through a *provider* — a zero-argument callable used
as a `Depends` target — rather than being captured directly, so a test can
swap the whole accounts stack with one
`app.dependency_overrides[provider]` entry.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Header, HTTPException

from accounts.container import AccountsContainer
from accounts.models import User

AccountsProvider = Callable[[], AccountsContainer]


def build_current_user_dependency(provider: AccountsProvider) -> Callable[..., User]:
    """A `Depends(...)` target that rejects unauthenticated requests with 401."""

    def get_current_user(
        authorization: str | None = Header(default=None),
        accounts: AccountsContainer = Depends(provider),
    ) -> User:
        if not authorization:
            raise HTTPException(status_code=401, detail="Authentication required.")
        user = accounts.resolve_bearer(authorization)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid or expired session.")
        return user

    return get_current_user


def build_optional_user_dependency(provider: AccountsProvider) -> Callable[..., User | None]:
    """A `Depends(...)` target for endpoints that serve signed-out callers too."""

    def get_optional_user(
        authorization: str | None = Header(default=None),
        accounts: AccountsContainer = Depends(provider),
    ) -> User | None:
        return accounts.resolve_bearer(authorization)

    return get_optional_user
