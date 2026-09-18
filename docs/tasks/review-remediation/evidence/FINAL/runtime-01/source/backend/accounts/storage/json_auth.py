"""JSON-file account and session store (local development default)."""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from core.ids import generate_uuid7

from accounts.models import User
from accounts.settings import DEFAULT_SESSION_TTL_DAYS
from accounts.storage.json_store import json_list_lock, read_json_list, write_json_list


def _normalize_email(email: str) -> str:
    return email.strip().lower()


class JsonEmailAuthService:
    def __init__(
        self,
        users_path: Path,
        sessions_path: Path,
        session_ttl_days: int = DEFAULT_SESSION_TTL_DAYS,
    ) -> None:
        self._users_path = users_path
        self._sessions_path = sessions_path.resolve()
        self._session_ttl = timedelta(days=session_ttl_days)

    def login(self, *, email: str, display_name: str | None = None) -> tuple[str, User]:
        normalized_email = _normalize_email(email)
        if not normalized_email:
            raise ValueError("Email is required.")

        users = read_json_list(self._users_path)
        user_record = next((item for item in users if item.get("email") == normalized_email), None)

        if user_record is None:
            user_record = {
                "id": generate_uuid7(),
                "email": normalized_email,
                "display_name": (display_name or normalized_email.split("@")[0]).strip()
                or normalized_email,
                "created_at": datetime.now(UTC).isoformat(),
            }
            users.append(user_record)
            write_json_list(self._users_path, users)
        elif display_name and display_name.strip():
            user_record["display_name"] = display_name.strip()
            write_json_list(self._users_path, users)

        user = User(
            id=user_record["id"],
            email=user_record["email"],
            display_name=user_record.get("display_name") or normalized_email,
        )
        access_token = self._create_session(user.id)
        return access_token, user

    def resolve_user(self, access_token: str) -> User | None:
        token = access_token.strip()
        if not token:
            return None

        sessions = self._read_active_sessions()
        session = next((item for item in sessions if item.get("token") == token), None)
        if not session:
            return None

        user_id = session.get("user_id")
        if not isinstance(user_id, str) or not user_id:
            return None

        users = read_json_list(self._users_path)
        user_record = next((item for item in users if item.get("id") == user_id), None)
        if not user_record:
            return None

        return User(
            id=user_record["id"],
            email=user_record["email"],
            display_name=user_record.get("display_name") or user_record["email"],
        )

    def logout(self, access_token: str) -> None:
        token = access_token.strip()
        if not token:
            return

        with json_list_lock(self._sessions_path):
            sessions = self._read_sessions_unlocked()
            retained = [item for item in sessions if item.get("token") != token]
            if len(retained) != len(sessions):
                write_json_list(self._sessions_path, retained)

    def _create_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        with json_list_lock(self._sessions_path):
            sessions = self._read_active_sessions_unlocked(now)
            sessions.append(
                {
                    "token": token,
                    "user_id": user_id,
                    "created_at": now.isoformat(),
                    "expires_at": (now + self._session_ttl).isoformat(),
                }
            )
            write_json_list(self._sessions_path, sessions)
        return token

    def _read_active_sessions(self) -> list[dict[str, Any]]:
        with json_list_lock(self._sessions_path):
            return self._read_active_sessions_unlocked(datetime.now(UTC))

    def _read_active_sessions_unlocked(self, now: datetime) -> list[dict[str, Any]]:
        sessions = self._read_sessions_unlocked()
        active_sessions: list[dict[str, Any]] = []

        for session in sessions:
            expires_at = _session_expiry(session)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at >= now:
                active_sessions.append(session)

        if len(active_sessions) != len(sessions):
            write_json_list(self._sessions_path, active_sessions)

        return active_sessions

    def _read_sessions_unlocked(self) -> list[dict[str, Any]]:
        if not self._sessions_path.exists():
            return []
        try:
            with self._sessions_path.open(encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Session document is corrupt") from exc
        if not isinstance(raw, list) or not all(isinstance(session, dict) for session in raw):
            raise ValueError("Session document must be a list of objects")
        for session in raw:
            _session_expiry(session)
        return raw


def _session_expiry(session: dict[str, Any]) -> datetime:
    token = session.get("token")
    user_id = session.get("user_id")
    expires_at_raw = session.get("expires_at")
    if not isinstance(token, str) or not token:
        raise ValueError("Session document has an invalid token")
    if not isinstance(user_id, str) or not user_id:
        raise ValueError("Session document has an invalid user ID")
    if not isinstance(expires_at_raw, str):
        raise ValueError("Session document has an invalid expiry")
    try:
        return datetime.fromisoformat(expires_at_raw)
    except ValueError as exc:
        raise ValueError("Session document has an invalid expiry") from exc
