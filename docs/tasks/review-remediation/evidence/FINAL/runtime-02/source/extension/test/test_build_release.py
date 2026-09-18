from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

EXTENSION_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = EXTENSION_DIR.parent
BUILD_SCRIPT = EXTENSION_DIR / "scripts" / "build_release.py"

MODULE_SPEC = importlib.util.spec_from_file_location("build_release", BUILD_SCRIPT)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
release_builder = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(release_builder)


class ReleaseBuildTests(unittest.TestCase):
    def run_build(self, api_base_url: str, output: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(BUILD_SCRIPT),
                "--api-base-url",
                api_base_url,
                "--output",
                str(output),
            ],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_build_is_deterministic_and_does_not_modify_sources(self) -> None:
        source_settings = (EXTENSION_DIR / "settings.js").read_bytes()
        source_manifest = (EXTENSION_DIR / "manifest.json").read_bytes()

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            first_output = temporary_path / "first.zip"
            second_output = temporary_path / "second.zip"

            first = self.run_build("https://api.example.com/", first_output)
            second = self.run_build("https://api.example.com", second_output)

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            first_digest = hashlib.sha256(first_output.read_bytes()).hexdigest()
            second_digest = hashlib.sha256(second_output.read_bytes()).hexdigest()
            self.assertEqual(first_digest, second_digest)
            self.assertIn("version=0.1.0", first.stdout)
            self.assertIn(f"sha256={first_digest}", first.stdout)

            with zipfile.ZipFile(first_output) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                settings = archive.read("settings.js").decode("utf-8")
                entries = set(archive.namelist())
                worker = archive.read(manifest["background"]["service_worker"]).decode()
                imports = re.search(r"importScripts\((.*?)\)", worker, re.DOTALL)
                self.assertIsNotNone(imports)
                assert imports is not None
                worker_imports = re.findall(r"['\"]([^'\"]+)['\"]", imports.group(1))
                self.assertIn("shared.js", worker_imports)
                self.assertIn("async function updatePreloadJob", archive.read("shared.js").decode())
                for reference in worker_imports:
                    self.assertIn(reference, entries)
                html = archive.read("sidepanel.html").decode()
                for reference in re.findall(r'<script\s+src="([^"]+)"', html):
                    self.assertIn(reference, entries)
                for content_script in manifest["content_scripts"]:
                    for reference in content_script["js"] + content_script["css"]:
                        self.assertIn(reference, entries)
                for resource_group in manifest["web_accessible_resources"]:
                    for reference in resource_group["resources"]:
                        self.assertIn(reference, entries)
                self.assertIn("generated/api-contract.js", entries)
                self.assertFalse(
                    any(
                        {"dev", "test", "node_modules", ".env"}.intersection(
                            Path(name).parts,
                        )
                        or name.endswith((".svg", ".map", ".pem", ".key"))
                        for name in entries
                    ),
                )

            self.assertEqual(manifest["manifest_version"], 3)
            self.assertEqual(
                manifest["host_permissions"],
                ["https://api.example.com/*"],
            )
            self.assertIn(
                "var DEFAULT_API_BASE_URL = 'https://api.example.com';",
                settings,
            )
            self.assertNotIn(
                "var DEFAULT_API_BASE_URL = 'http://localhost:18765';",
                settings,
            )

        self.assertEqual((EXTENSION_DIR / "settings.js").read_bytes(), source_settings)
        self.assertEqual((EXTENSION_DIR / "manifest.json").read_bytes(), source_manifest)

    def test_build_preserves_api_path_but_permissions_use_origin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "release.zip"
            result = self.run_build("https://api.example.com/prod/", output)

            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(output) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                settings = archive.read("settings.js").decode("utf-8")

            self.assertEqual(
                manifest["host_permissions"],
                ["https://api.example.com/*"],
            )
            self.assertIn(
                "var DEFAULT_API_BASE_URL = 'https://api.example.com/prod';",
                settings,
            )

    def test_build_rejects_insecure_or_ambiguous_api_urls(self) -> None:
        invalid_urls = (
            "http://api.example.com",
            "https://user:secret@api.example.com",
            "https://api.example.com?environment=prod",
            "https://api.example.com#prod",
            "https:///missing-host",
            "https://api.example.com:not-a-port",
            "https://api.example.com:65536",
            "https://api.example.com:-1",
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            for index, api_base_url in enumerate(invalid_urls):
                with self.subTest(api_base_url=api_base_url):
                    output = temporary_path / f"invalid-{index}.zip"
                    result = self.run_build(api_base_url, output)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("error:", result.stderr)
                    self.assertFalse(output.exists())

    def test_build_rejects_referenced_files_omitted_from_allowlist(self) -> None:
        for missing in ("generated/api-contract.js", "select-ui.js", "content.css"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "release.zip"
                allowlist = tuple(name for name in release_builder.RUNTIME_FILES if name != missing)
                with (
                    patch.object(release_builder, "RUNTIME_FILES", allowlist),
                    self.assertRaisesRegex(release_builder.BuildError, re.escape(missing)),
                ):
                    release_builder.build_release("https://api.example.com", str(output))
                self.assertFalse(output.exists())

    def test_build_rejects_missing_nested_worker_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "source"
            release_builder.copy_runtime_files(fixture)
            dependency = fixture / "generated" / "api-contract.js"
            dependency.parent.mkdir(parents=True, exist_ok=True)
            dependency.write_text("importScripts('./missing.js');\n", encoding="utf-8")
            output = Path(temporary) / "release.zip"
            with (
                patch.object(release_builder, "EXTENSION_DIR", fixture),
                self.assertRaisesRegex(release_builder.BuildError, "missing.js"),
            ):
                release_builder.build_release("https://api.example.com", str(output))
            self.assertFalse(output.exists())

    def test_build_excludes_unlisted_secret_and_development_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "source"
            release_builder.copy_runtime_files(fixture)
            for name in (".env", "private.key", "dev/debug.js", "generated/private.json"):
                unlisted = fixture / name
                unlisted.parent.mkdir(parents=True, exist_ok=True)
                unlisted.write_text("synthetic excluded fixture", encoding="utf-8")
            output = Path(temporary) / "release.zip"
            with patch.object(release_builder, "EXTENSION_DIR", fixture):
                release_builder.build_release("https://api.example.com", str(output))
            with zipfile.ZipFile(output) as archive:
                self.assertFalse(
                    any(
                        b"synthetic excluded fixture" in archive.read(name)
                        for name in archive.namelist()
                    )
                )

    def test_nested_classic_imports_resolve_against_worker_url(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "source"
            release_builder.copy_runtime_files(fixture)
            (fixture / "generated" / "api-contract.js").write_text(
                "importScripts('./api-contract-runtime.js', 'background.js');\n",
                encoding="utf-8",
            )
            output = Path(temporary) / "release.zip"
            with patch.object(release_builder, "EXTENSION_DIR", fixture):
                release_builder.build_release("https://api.example.com", str(output))
            self.assertTrue(output.is_file())

    def test_build_rejects_unsafe_worker_references(self) -> None:
        for reference in ("../settings.js", "https://example.com/code.js", "variable"):
            with self.subTest(reference=reference), tempfile.TemporaryDirectory() as temporary:
                fixture = Path(temporary) / "source"
                release_builder.copy_runtime_files(fixture)
                argument = "variable" if reference == "variable" else json.dumps(reference)
                (fixture / "background.js").write_text(
                    f"importScripts({argument});\n", encoding="utf-8"
                )
                output = Path(temporary) / "release.zip"
                with (
                    patch.object(release_builder, "EXTENSION_DIR", fixture),
                    self.assertRaises(release_builder.BuildError),
                ):
                    release_builder.build_release("https://api.example.com", str(output))
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
