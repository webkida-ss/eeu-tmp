from __future__ import annotations

from accounts.models import IdentityClaims
from accounts.ports import IdentityVerificationError


class GoogleIdentityProvider:
    """Verifies Google Sign-In ID tokens.

    Requires the ``google-auth`` package and a configured OAuth client id.
    The dependency is imported lazily so local development with the mock
    provider does not need it installed.
    """

    provider_name = "google"

    def __init__(self, client_id: str) -> None:
        client_id = str(client_id or "").strip()
        if not client_id:
            raise ValueError("GOOGLE_OAUTH_CLIENT_ID must be set when AUTH_PROVIDER=google.")
        self._client_id = client_id

    def verify(self, credential: str) -> IdentityClaims:
        token = str(credential or "").strip()
        if not token:
            raise IdentityVerificationError("A Google ID token is required.")

        try:
            from google.auth.transport import requests as google_requests
            from google.oauth2 import id_token as google_id_token
        except ImportError as exc:  # pragma: no cover - environment-specific
            raise IdentityVerificationError(
                "Google sign-in requires the 'google-auth' package: pip install google-auth requests"
            ) from exc

        try:
            claims = google_id_token.verify_oauth2_token(
                token, google_requests.Request(), self._client_id
            )
        # Fail closed: any failure at all means "not verified".
        except Exception as exc:
            raise IdentityVerificationError(f"Google ID token verification failed: {exc}") from exc

        email = str(claims.get("email") or "").strip().lower()
        if not email:
            raise IdentityVerificationError("The Google account did not provide an email address.")
        if not claims.get("email_verified", False):
            raise IdentityVerificationError("The Google account email is not verified.")

        display_name = str(claims.get("name") or "").strip() or email.split("@")[0]
        subject = str(claims.get("sub") or "").strip() or f"google|{email}"
        return IdentityClaims(email=email, display_name=display_name, subject=subject)
