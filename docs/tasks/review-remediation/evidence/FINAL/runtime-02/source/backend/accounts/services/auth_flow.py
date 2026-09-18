"""Sign-in use case: verify an identity credential and issue a session.

Framework-free: raises IdentityVerificationError (bad credential) and
ValueError (rejected login) for the handler layer to map onto its own
error responses.
"""

from __future__ import annotations

from accounts.models import AuthSessionResponse
from accounts.ports import AuthService, IdentityProvider


def login_with_identity(
    auth_service: AuthService,
    identity_provider: IdentityProvider,
    credential: str,
) -> AuthSessionResponse:
    claims = identity_provider.verify(credential)
    access_token, user = auth_service.login(
        email=claims.email,
        display_name=claims.display_name,
    )
    return AuthSessionResponse(access_token=access_token, user=user)
