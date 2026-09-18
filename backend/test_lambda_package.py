from __future__ import annotations

import ast
import platform
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
BUILD_DIR = BACKEND_DIR / "build" / "lambda"
ZIP_PATH = BACKEND_DIR / "dist" / "reading-assistant-lambda.zip"
EXPECTED_COLD_START_MODULES = {
    "boto3",
    "botocore",
    "dotenv",
    "fastapi",
    "mangum",
    "openai",
    "pydantic",
    "starlette",
    "tiktoken",
}


def _local_module_paths(module: str, imported_names: tuple[str, ...]) -> set[Path]:
    module_path = BACKEND_DIR.joinpath(*module.split("."))
    candidates = {module_path.with_suffix(".py"), module_path / "__init__.py"}
    candidates.update(
        module_path.joinpath(*name.split(".")).with_suffix(".py")
        for name in imported_names
        if name != "*"
    )
    return {path for path in candidates if path.is_file()}


def _cold_start_external_modules(entrypoint: Path) -> set[str]:
    pending = [entrypoint]
    visited: set[Path] = set()
    external: set[str] = set()

    while pending:
        source_path = pending.pop()
        if source_path in visited:
            continue
        visited.add(source_path)

        tree = ast.parse(source_path.read_text(), filename=str(source_path))
        for node in tree.body:
            if isinstance(node, ast.Import):
                imports = tuple(alias.name for alias in node.names)
                for imported in imports:
                    local_paths = _local_module_paths(imported, ())
                    if local_paths:
                        pending.extend(local_paths)
                    elif imported.split(".", 1)[0] not in sys.stdlib_module_names:
                        external.add(imported.split(".", 1)[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_names = tuple(alias.name for alias in node.names)
                local_paths = _local_module_paths(node.module, imported_names)
                if local_paths:
                    pending.extend(local_paths)
                elif node.module.split(".", 1)[0] not in sys.stdlib_module_names:
                    external.add(node.module.split(".", 1)[0])

    return external


class LambdaPackageTests(unittest.TestCase):
    def test_artifact_contains_every_cold_start_external_module(self):
        self.assertTrue(ZIP_PATH.is_file(), "Build the Lambda package before running this test.")
        external_modules = _cold_start_external_modules(BACKEND_DIR / "lambda_handler.py")
        self.assertEqual(external_modules, EXPECTED_COLD_START_MODULES)

        with zipfile.ZipFile(ZIP_PATH) as artifact:
            members = set(artifact.namelist())
        missing = {
            module
            for module in external_modules
            if f"{module}.py" not in members
            and not any(member.startswith(f"{module}/") for member in members)
        }
        self.assertEqual(missing, set(), f"Missing cold-start modules: {sorted(missing)}")

    def test_imports_lambda_handler_when_host_matches_target(self):
        host_matches_target = (
            sys.version_info[:2] == (3, 12)
            and sys.platform == "linux"
            and platform.machine().lower() in {"aarch64", "arm64"}
        )
        if not host_matches_target:
            self.skipTest(
                "The package targets Linux arm64; package-content and import-graph "
                "validation covers hosts with a different OS or architecture."
            )

        subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                (f"import sys; sys.path.insert(0, {str(BUILD_DIR)!r}); import lambda_handler"),
            ],
            check=True,
            cwd=BUILD_DIR,
        )


if __name__ == "__main__":
    unittest.main()
