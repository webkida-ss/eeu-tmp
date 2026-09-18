"""Guards the clean-architecture seam: the schemas/core/services layers must
work without FastAPI, so the handler layer (FastAPI today, e.g. an AWS
Lambda handler tomorrow) can be swapped without touching them."""

import importlib
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

from accounts.storage import JsonEmailAuthService
from accounts.testing import build_test_accounts
from core.plans import PLAN_CATALOG
from deps import get_accounts, get_page_preload_repository
from fastapi.testclient import TestClient
from main import app
from repositories.page_preload_repository import JsonPagePreloadRepository
from storage import dynamodb_store

_dynamodb_resource_factory = dynamodb_store.create_dynamodb_resource
_dynamodb_client_factory = dynamodb_store.create_dynamodb_client


class FakeMangum:
    """Test adapter that records the application composed by the entrypoint."""

    def __init__(self, application: object) -> None:
        self.application = application


_MISSING_MODULE = object()


@contextmanager
def import_lambda_handler_with_fake_mangum() -> Iterator[ModuleType]:
    """Import the real entrypoint with a scoped adapter dependency.

    The service-free unit suite intentionally does not install the Lambda
    runtime dependencies. `test_lambda_package.py` separately validates the
    real package and its Mangum dependency.
    """

    previous_mangum = sys.modules.get("mangum", _MISSING_MODULE)
    previous_lambda_handler = sys.modules.get("lambda_handler", _MISSING_MODULE)
    fake_mangum = ModuleType("mangum")
    fake_mangum.Mangum = FakeMangum
    sys.modules["mangum"] = fake_mangum
    sys.modules.pop("lambda_handler", None)

    try:
        yield importlib.import_module("lambda_handler")
    finally:
        sys.modules.pop("mangum", None)
        sys.modules.pop("lambda_handler", None)
        if previous_mangum is not _MISSING_MODULE:
            sys.modules["mangum"] = previous_mangum
        if previous_lambda_handler is not _MISSING_MODULE:
            sys.modules["lambda_handler"] = previous_lambda_handler


class FrameworkIndependenceTests(unittest.TestCase):
    def test_api_lambda_entrypoint_keeps_both_dynamodb_factories(self):
        with import_lambda_handler_with_fake_mangum() as lambda_handler:
            self.assertIs(dynamodb_store.create_dynamodb_resource, _dynamodb_resource_factory)
            self.assertIs(dynamodb_store.create_dynamodb_client, _dynamodb_client_factory)
            self.assertIsInstance(lambda_handler.handler, FakeMangum)
            self.assertIs(lambda_handler.handler.application, app)

    def test_core_and_services_import_without_fastapi(self):
        # A fresh interpreter proves the import graph is clean; in-process
        # checks would be polluted by other tests importing main.
        code = (
            "import sys\n"
            "import core.pipeline, core.plans, schemas\n"
            "import services.reading, services.entitlements\n"
            # accounts is a shared package: everything except its
            # accounts.api adapter must stay framework-free too.
            "import accounts, accounts.services.auth_flow, accounts.services.billing_flow\n"
            "import accounts.billing, accounts.identity, accounts.storage\n"
            "import services.admin_activity, services.admin_accounts\n"
            "import services.admin_auth, services.account_access\n"
            "import repositories.admin_account_control, repositories.session_repository\n"
            "leaked = [m for m in sys.modules if m == 'fastapi' or m.startswith('fastapi.')]\n"
            "assert not leaked, f'fastapi leaked into core/services: {leaked}'\n"
            "print('clean')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("clean", result.stdout)


class PipelineErrorMappingTests(unittest.TestCase):
    """PipelineError raised inside the framework-free layers must surface as
    the same HTTP responses the old in-route HTTPExceptions produced."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmpdir.name)
        auth_service = JsonEmailAuthService(tmp / "users.json", tmp / "sessions.json")
        repository = JsonPagePreloadRepository(tmp / "preloads.json")
        accounts = build_test_accounts(plans=PLAN_CATALOG, auth_service=auth_service)
        app.dependency_overrides[get_accounts] = lambda: accounts
        app.dependency_overrides[get_page_preload_repository] = lambda: repository
        # raise_server_exceptions=False lets the app's exception handler
        # produce the response instead of re-raising into the test.
        self.client = TestClient(app, raise_server_exceptions=False)

        login = self.client.post("/auth/login", json={"credential": "mock:reader@example.com"})
        self.headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    def tearDown(self):
        app.dependency_overrides.clear()
        self._tmpdir.cleanup()

    def test_unextractable_html_maps_to_400(self):
        response = self.client.post(
            "/pages/preload",
            json={"page_url": "https://example.com/a", "html": "<html><body></body></html>"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("article text", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
