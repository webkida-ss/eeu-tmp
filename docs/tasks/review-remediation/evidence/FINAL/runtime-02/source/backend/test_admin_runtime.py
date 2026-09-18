from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import config

BACKEND_DIR = Path(__file__).resolve().parent


def _run_backend_code(code: str, **environment: str) -> subprocess.CompletedProcess[str]:
    child_environment = os.environ.copy()
    child_environment.update(
        AUTH_PROVIDER="mock",
        BILLING_PROVIDER="mock",
        STORAGE_BACKEND="json",
        JOB_RUNNER="inline",
        PYTHON_DOTENV_DISABLED="1",
    )
    child_environment.update(environment)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR,
        env=child_environment,
        capture_output=True,
        text=True,
    )


class AdminRuntimeGuardTests(unittest.TestCase):
    def test_enabled_admin_rejects_dynamodb_storage(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "STORAGE_BACKEND=json"):
            config.validate_admin_runtime(admin_enabled=True, storage_backend="dynamodb")

    def test_disabled_admin_accepts_dynamodb_storage(self) -> None:
        config.validate_admin_runtime(admin_enabled=False, storage_backend="dynamodb")

    def test_main_import_applies_admin_runtime_guard(self) -> None:
        result = _run_backend_code(
            "import main",
            ADMIN_ENABLED="true",
            STORAGE_BACKEND="dynamodb",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("STORAGE_BACKEND=json", result.stderr)


class AdminConfigTests(unittest.TestCase):
    def test_admin_defaults_are_local_and_disabled(self) -> None:
        result = _run_backend_code(
            "import json, config; print(json.dumps({"
            "'enabled': config.ADMIN_ENABLED,"
            "'emails': config.ADMIN_EMAILS,"
            "'origin': config.ADMIN_ALLOWED_ORIGIN,"
            "'activity': str(config.ADMIN_ACTIVITY_PATH),"
            "'control': str(config.ADMIN_CONTROL_PATH)"
            "}))",
            ADMIN_ENABLED="",
            ADMIN_EMAILS="",
            ADMIN_ALLOWED_ORIGIN="",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout)
        self.assertFalse(values["enabled"])
        self.assertEqual(values["emails"], [])
        self.assertEqual(values["origin"], "http://localhost:3000")
        self.assertTrue(values["activity"].endswith("/data/admin_activity.json"))
        self.assertTrue(values["control"].endswith("/data/admin_control.json"))

    def test_admin_values_are_normalized(self) -> None:
        result = _run_backend_code(
            "import json, config; print(json.dumps({"
            "'enabled': config.ADMIN_ENABLED,"
            "'emails': config.ADMIN_EMAILS,"
            "'immutable': isinstance(config.ADMIN_EMAILS, tuple)"
            "}))",
            ADMIN_ENABLED="ON",
            ADMIN_EMAILS=" Admin@Example.COM, ,SECOND@example.com ",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout)
        self.assertTrue(values["enabled"])
        self.assertEqual(values["emails"], ["admin@example.com", "second@example.com"])
        self.assertTrue(values["immutable"])

    def test_enabled_admin_origin_does_not_expand_learner_origins(self) -> None:
        result = _run_backend_code(
            "import json, main; print(json.dumps(main.ALLOWED_ORIGINS))",
            ADMIN_ENABLED="yes",
            STORAGE_BACKEND="json",
            ADMIN_ALLOWED_ORIGIN="http://localhost:4000",
            ALLOWED_ORIGINS="http://extension.test",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            ["http://extension.test"],
        )


if __name__ == "__main__":
    unittest.main()
