from __future__ import annotations

from collections.abc import Iterable

from accounts import User


class AdminForbidden(Exception):
    code = "admin_forbidden"

    def __init__(self) -> None:
        super().__init__("Administrator access is required.")


def require_admin(user: User, allowlist: Iterable[str]) -> User:
    email = user.email.strip().lower() if isinstance(user.email, str) else ""
    allowed_emails = frozenset(
        candidate.strip().lower()
        for candidate in allowlist
        if isinstance(candidate, str) and candidate.strip()
    )
    if not email or email not in allowed_emails:
        raise AdminForbidden
    return user
