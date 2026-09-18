from __future__ import annotations

from accounts import User
from config import ADMIN_EMAILS
from deps import get_current_user
from fastapi import Depends, HTTPException
from services.admin_auth import AdminForbidden, require_admin


def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    try:
        return require_admin(current_user, ADMIN_EMAILS)
    except AdminForbidden as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
