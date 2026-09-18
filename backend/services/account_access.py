from __future__ import annotations

from repositories.admin_account_control import AdminAccountControlRepository


class AccountSuspended(Exception):
    code = "account_suspended"

    def __init__(self) -> None:
        super().__init__("This account is suspended.")


def require_active_learner(
    user_id: str,
    account_repository: AdminAccountControlRepository,
) -> None:
    if account_repository.get_control(user_id).status == "suspended":
        raise AccountSuspended
