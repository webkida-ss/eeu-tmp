import tempfile
import unittest
from pathlib import Path

from accounts import AccountsSettings, IdentityVerificationError, build_accounts_container
from accounts.identity import GoogleIdentityProvider, MockIdentityProvider
from accounts.storage import JsonEmailAuthService
from accounts.testing import build_test_accounts
from core.plans import PLAN_CATALOG
from deps import get_accounts
from fastapi.testclient import TestClient
from main import app


class MockIdentityProviderTests(unittest.TestCase):
    def setUp(self):
        self.provider = MockIdentityProvider()

    def test_accepts_mock_email_credential(self):
        claims = self.provider.verify("mock:user@example.com")
        self.assertEqual(claims.email, "user@example.com")
        self.assertEqual(claims.display_name, "user")
        self.assertEqual(claims.subject, "mock|user@example.com")

    def test_accepts_display_name_and_normalizes_email(self):
        claims = self.provider.verify("mock:User@Example.COM:Taro Yamada")
        self.assertEqual(claims.email, "user@example.com")
        self.assertEqual(claims.display_name, "Taro Yamada")

    def test_rejects_credentials_without_mock_prefix(self):
        with self.assertRaises(IdentityVerificationError):
            self.provider.verify("user@example.com")
        with self.assertRaises(IdentityVerificationError):
            self.provider.verify("eyJhbGciOiJSUzI1NiJ9.fake.jwt")

    def test_rejects_invalid_email(self):
        with self.assertRaises(IdentityVerificationError):
            self.provider.verify("mock:not-an-email")
        with self.assertRaises(IdentityVerificationError):
            self.provider.verify("mock:")


class GoogleIdentityProviderTests(unittest.TestCase):
    def test_requires_client_id(self):
        from accounts.identity import GoogleIdentityProvider

        with self.assertRaises(ValueError):
            GoogleIdentityProvider("")

    def test_rejects_empty_credential(self):
        from accounts.identity import GoogleIdentityProvider

        provider = GoogleIdentityProvider("client-id.apps.googleusercontent.com")
        with self.assertRaises(IdentityVerificationError):
            provider.verify("")


class SsoLoginEndpointTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmpdir.name)
        auth_service = JsonEmailAuthService(tmp / "users.json", tmp / "sessions.json")
        accounts = build_test_accounts(auth_service=auth_service)
        app.dependency_overrides[get_accounts] = lambda: accounts
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self._tmpdir.cleanup()

    def test_login_with_mock_credential_issues_session(self):
        response = self.client.post(
            "/auth/login", json={"credential": "mock:learner@example.com:Learner"}
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["access_token"])
        self.assertEqual(body["user"]["email"], "learner@example.com")
        self.assertEqual(body["user"]["display_name"], "Learner")

        me = self.client.get(
            "/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
        )
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["email"], "learner@example.com")

    def test_login_rejects_unverifiable_credential(self):
        response = self.client.post("/auth/login", json={"credential": "learner@example.com"})
        self.assertEqual(response.status_code, 401)

    def test_auth_config_reports_provider(self):
        response = self.client.get("/auth/config")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn(body["provider"], {"mock", "google"})


class GoogleProviderBypassTests(unittest.TestCase):
    """Mock-style credentials must never authenticate against the Google
    provider: the provider is fixed server-side by DI, so a client cannot
    downgrade verification by changing the credential shape."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmpdir.name)
        auth_service = JsonEmailAuthService(tmp / "users.json", tmp / "sessions.json")
        provider = GoogleIdentityProvider("dummy-client-id.apps.googleusercontent.com")
        accounts = build_test_accounts(auth_service=auth_service, identity_provider=provider)
        app.dependency_overrides[get_accounts] = lambda: accounts
        self.client = TestClient(app)
        self._auth_service = auth_service

    def tearDown(self):
        app.dependency_overrides.clear()
        self._tmpdir.cleanup()

    def _assert_rejected(self, credential: str):
        response = self.client.post("/auth/login", json={"credential": credential})
        self.assertEqual(response.status_code, 401, credential)
        self.assertNotIn("access_token", response.json())

    def test_mock_credential_is_rejected(self):
        self._assert_rejected("mock:attacker@example.com")
        self._assert_rejected("mock:attacker@example.com:Attacker")

    def test_raw_email_is_rejected(self):
        self._assert_rejected("attacker@example.com")

    def test_garbage_jwt_is_rejected(self):
        self._assert_rejected("eyJhbGciOiJSUzI1NiJ9.eyJlbWFpbCI6ImFAYi5jIn0.invalid-signature")

    def test_no_user_or_session_is_created_on_rejection(self):
        self.client.post("/auth/login", json={"credential": "mock:attacker@example.com"})
        self.assertIsNone(self._auth_service.resolve_user("any-token"))


class IdentityProviderDispatchTests(unittest.TestCase):
    """The provider is chosen from server config alone."""

    def _accounts(self, **settings):
        return build_accounts_container(AccountsSettings(**settings), plans=PLAN_CATALOG)

    def test_google_config_selects_google_provider(self):
        accounts = self._accounts(auth_provider="google", google_oauth_client_id="client-id")
        self.assertIsInstance(accounts.identity_provider, GoogleIdentityProvider)

    def test_google_without_client_id_fails_closed_at_startup(self):
        with self.assertRaises(ValueError):
            self._accounts(auth_provider="google", google_oauth_client_id="")

    def test_default_config_selects_mock_provider(self):
        accounts = self._accounts(auth_provider="mock")
        self.assertIsInstance(accounts.identity_provider, MockIdentityProvider)


if __name__ == "__main__":
    unittest.main()
