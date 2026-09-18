from __future__ import annotations

import re

from accounts.models import IdentityClaims
from accounts.ports import IdentityVerificationError

_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class MockIdentityProvider:
    """Development-only identity provider.

    Accepts credentials of the form ``mock:<email>`` or
    ``mock:<email>:<display name>`` and trusts them without verification.
    The explicit ``mock:`` prefix ensures a real token can never be
    mistaken for a mock credential (and vice versa).
    """

    provider_name = "mock"

    def verify(self, credential: str) -> IdentityClaims:
        raw = str(credential or "").strip()
        if not raw.startswith("mock:"):
            raise IdentityVerificationError(
                "Mock credentials must look like 'mock:<email>' or 'mock:<email>:<display name>'."
            )

        email, _, display_name = raw.removeprefix("mock:").partition(":")
        email = email.strip().lower()
        if not _EMAIL_PATTERN.match(email):
            raise IdentityVerificationError(f"Invalid email in mock credential: {email!r}")

        display_name = display_name.strip() or email.split("@")[0]
        return IdentityClaims(email=email, display_name=display_name, subject=f"mock|{email}")
