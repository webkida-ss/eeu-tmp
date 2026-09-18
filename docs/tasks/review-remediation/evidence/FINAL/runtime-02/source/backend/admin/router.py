from __future__ import annotations

from accounts import User
from fastapi import APIRouter, Depends
from generated.admin_models import AdminSession, CorrelationError

from admin.deps import get_admin_user

router = APIRouter(prefix="/admin/v1", tags=["admin"])


@router.get(
    "/session",
    operation_id="getAdminSession",
    response_model=AdminSession,
    responses={status: {"model": CorrelationError} for status in (401, 403, 422)},
)
def get_admin_session(
    current_user: User = Depends(get_admin_user),
) -> AdminSession:
    return AdminSession(
        user_id=current_user.id,
        email=current_user.email.strip().lower(),
        display_name=current_user.display_name,
    )
