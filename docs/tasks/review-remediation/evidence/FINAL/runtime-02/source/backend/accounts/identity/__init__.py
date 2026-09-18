"""Identity provider adapters (see `accounts.ports.IdentityProvider`).

Module names carry the `_identity` suffix so importing `stripe`-style
third-party packages from inside them can never resolve to a sibling.
"""

from accounts.identity.google_identity import GoogleIdentityProvider
from accounts.identity.mock_identity import MockIdentityProvider

__all__ = ["GoogleIdentityProvider", "MockIdentityProvider"]
