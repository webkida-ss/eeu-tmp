"""Reference implementations of the accounts storage ports.

JSON files for local development and in-memory for tests. Production
adapters that live in the host application's own datastore (DynamoDB,
Postgres, …) are written there and injected at the composition root — the
package must not learn the host's schema.
"""

from accounts.storage.json_auth import JsonEmailAuthService
from accounts.storage.json_subscriptions import JsonSubscriptionRepository
from accounts.storage.memory import InMemoryAuthService, InMemorySubscriptionRepository

__all__ = [
    "InMemoryAuthService",
    "InMemorySubscriptionRepository",
    "JsonEmailAuthService",
    "JsonSubscriptionRepository",
]
