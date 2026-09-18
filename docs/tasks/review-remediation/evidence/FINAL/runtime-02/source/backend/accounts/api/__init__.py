"""The FastAPI adapter — the only part of `accounts` that imports a web framework.

Everything else is transport-agnostic, so an application that speaks
WebSocket or runs as a Lambda handler can use the package without ever
importing this sub-package.
"""

from accounts.api.dependencies import (
    AccountsProvider,
    build_current_user_dependency,
    build_optional_user_dependency,
)
from accounts.api.router import build_accounts_router, install_accounts_exception_handlers

__all__ = [
    "AccountsProvider",
    "build_accounts_router",
    "build_current_user_dependency",
    "build_optional_user_dependency",
    "install_accounts_exception_handlers",
]
