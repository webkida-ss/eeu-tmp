#!/usr/bin/env python3
"""Build a deterministic Chrome Web Store ZIP for Untangle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import shutil
import sys
import tempfile
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import SplitResult, unquote, urlsplit, urlunsplit

EXTENSION_DIR = Path(__file__).resolve().parents[1]
DEVELOPMENT_API_ASSIGNMENT = "var DEFAULT_API_BASE_URL = 'http://localhost:18765';"
RUNTIME_FILES = (
    "api-contract-runtime.js",
    "background.js",
    "content.css",
    "content.js",
    "generated/api-contract.js",
    "i18n.js",
    "icons/icon16.png",
    "icons/icon32.png",
    "icons/icon48.png",
    "icons/icon128.png",
    "manifest.json",
    "panel-ui.css",
    "panel-ui.js",
    "reading-panel.css",
    "reading-panel.js",
    "select-ui.js",
    "settings.js",
    "shared.js",
    "sidepanel.html",
    "signin-methods.js",
)
FORBIDDEN_PATH_PARTS = {"dev", "test", ".web-ext-profile"}
FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class BuildError(RuntimeError):
    """Raised when a release artifact cannot be built safely."""


def normalize_api_base_url(value: str) -> tuple[str, SplitResult]:
    raw_value = value.strip()
    if not raw_value or any(character.isspace() for character in raw_value):
        raise BuildError("API base URL must be a non-empty HTTPS URL")

    try:
        parsed = urlsplit(raw_value)
        # Accessing port validates both its numeric format and its range.
        _ = parsed.port
    except ValueError as error:
        raise BuildError("API base URL is invalid") from error

    if parsed.scheme.lower() != "https":
        raise BuildError("API base URL must use HTTPS")
    if not parsed.hostname:
        raise BuildError("API base URL must include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise BuildError("API base URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise BuildError("API base URL must not contain a query or fragment")

    path = parsed.path.rstrip("/")
    normalized = urlunsplit(("https", parsed.netloc, path, "", ""))
    normalized_parts = urlsplit(normalized)
    return normalized, normalized_parts


def api_host_permission(parsed: SplitResult) -> str:
    return f"https://{parsed.netloc}/*"


def copy_runtime_files(staging_directory: Path) -> None:
    for relative_name in RUNTIME_FILES:
        source = EXTENSION_DIR / relative_name
        if not source.is_file():
            raise BuildError(f"required runtime file is missing: {relative_name}")
        destination = staging_directory / relative_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


def write_release_settings(staging_directory: Path, api_base_url: str) -> None:
    settings_path = staging_directory / "settings.js"
    source = settings_path.read_text(encoding="utf-8")
    if source.count(DEVELOPMENT_API_ASSIGNMENT) != 1:
        raise BuildError("development API assignment must appear exactly once")

    escaped_url = api_base_url.replace("\\", "\\\\").replace("'", "\\'")
    release_assignment = f"var DEFAULT_API_BASE_URL = '{escaped_url}';"
    settings_path.write_text(
        source.replace(DEVELOPMENT_API_ASSIGNMENT, release_assignment),
        encoding="utf-8",
    )


def write_release_manifest(
    staging_directory: Path,
    host_permission: str,
) -> dict[str, object]:
    manifest_path = staging_directory / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise BuildError("manifest.json is not valid JSON") from error

    manifest["host_permissions"] = [host_permission]
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def manifest_references(value: object) -> list[str]:
    references: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"icons", "default_icon"} and isinstance(child, dict):
                references.extend(child.values())
            elif key in {
                "service_worker",
                "default_icon",
                "default_popup",
                "default_path",
                "options_page",
                "page",
            } and isinstance(child, str):
                references.append(child)
            elif key in {"js", "css", "resources"} and isinstance(child, list):
                references.extend(child)
            else:
                references.extend(manifest_references(child))
    elif isinstance(value, list):
        for child in value:
            references.extend(manifest_references(child))
    return references


class HTMLReferences(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[tuple[str, bool]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        source = attributes.get("src")
        if source is not None:
            self.references.append((source, tag != "script"))
        if tag == "link" and "stylesheet" in (attributes.get("rel") or "").split():
            href = attributes.get("href")
            if href is not None:
                self.references.append((href, True))


def validate_references(staging_directory: Path, manifest: dict[str, object]) -> None:
    def require_reference(
        reference: str, directory: str = "", allow_remote: bool = False
    ) -> str | None:
        if not isinstance(reference, str):
            raise BuildError("runtime references must be strings")
        parsed = urlsplit(reference)
        if parsed.scheme or parsed.netloc:
            if allow_remote and parsed.scheme == "https":
                return None
            raise BuildError(f"runtime reference must be local: {reference}")
        path = unquote(parsed.path)
        resolved = posixpath.normpath(posixpath.join(directory, path))
        if (
            not path
            or "\\" in path
            or path.startswith("/")
            or resolved == ".."
            or resolved.startswith("../")
            or resolved not in RUNTIME_FILES
            or not (staging_directory / resolved).is_file()
        ):
            raise BuildError(f"runtime reference is missing or unsafe: {reference}")
        return resolved

    for reference in manifest_references(manifest):
        require_reference(reference)
    for name in RUNTIME_FILES:
        if name.endswith(".html"):
            parser = HTMLReferences()
            parser.feed((staging_directory / name).read_text(encoding="utf-8"))
            for reference, allow_remote in parser.references:
                require_reference(reference, posixpath.dirname(name), allow_remote)

    background = manifest.get("background", {})
    if not isinstance(background, dict) or not background.get("service_worker"):
        return
    if background.get("type", "classic") != "classic":
        raise BuildError("release dependency validation supports classic workers only")
    worker = require_reference(background["service_worker"])
    assert worker is not None
    pending = [worker]
    visited: set[str] = set()
    literal = r"""(?:'[^'\\]*'|"[^"\\]*")"""
    arguments_pattern = rf"\s*(?:{literal}\s*(?:,\s*{literal}\s*)*,?)?\s*"
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        source = (staging_directory / name).read_text(encoding="utf-8")
        for call in re.finditer(r"\bimportScripts\s*\((.*?)\)", source, re.DOTALL):
            arguments = call.group(1)
            if not re.fullmatch(arguments_pattern, arguments):
                raise BuildError(f"worker imports must use literal local paths: {name}")
            for argument in re.findall(literal, arguments):
                # Classic imports resolve against the worker URL, including nested imports.
                dependency = require_reference(argument[1:-1], posixpath.dirname(worker))
                if dependency is not None:
                    pending.append(dependency)


def validate_staging(
    staging_directory: Path,
    manifest: dict[str, object],
    api_base_url: str,
    host_permission: str,
) -> str:
    staged_files = {
        path.relative_to(staging_directory).as_posix()
        for path in staging_directory.rglob("*")
        if path.is_file()
    }
    if staged_files != set(RUNTIME_FILES):
        raise BuildError("staged files do not match the runtime allowlist")
    if any(FORBIDDEN_PATH_PARTS.intersection(Path(name).parts) for name in staged_files):
        raise BuildError("development or test files were staged")
    if any(name.endswith(".svg") for name in staged_files):
        raise BuildError("source SVG files must not be included in the release")

    if manifest.get("manifest_version") != 3:
        raise BuildError("release manifest must use Manifest V3")
    version = manifest.get("version")
    if not isinstance(version, str) or not version.strip():
        raise BuildError("release manifest must contain a version")
    if manifest.get("host_permissions") != [host_permission]:
        raise BuildError("release host permissions do not match the API origin")
    validate_references(staging_directory, manifest)

    icon_paths: set[str] = set()
    icons = manifest.get("icons")
    if isinstance(icons, dict):
        icon_paths.update(value for value in icons.values() if isinstance(value, str))
    action = manifest.get("action")
    if isinstance(action, dict):
        action_icons = action.get("default_icon")
        if isinstance(action_icons, dict):
            icon_paths.update(value for value in action_icons.values() if isinstance(value, str))
    if not icon_paths:
        raise BuildError("release manifest must reference PNG icons")
    for icon_path in icon_paths:
        if not icon_path.endswith(".png"):
            raise BuildError(f"release icon must be PNG: {icon_path}")
        if not (staging_directory / icon_path).is_file():
            raise BuildError(f"release icon is missing: {icon_path}")

    settings = (staging_directory / "settings.js").read_text(encoding="utf-8")
    expected_assignment = f"var DEFAULT_API_BASE_URL = '{api_base_url}';"
    if settings.count(expected_assignment) != 1:
        raise BuildError("release API base URL was not written exactly once")
    if DEVELOPMENT_API_ASSIGNMENT in settings:
        raise BuildError("development API base URL remains in release settings")

    return version


def validate_output_location(output: Path) -> Path:
    resolved_output = output.expanduser().resolve()
    resolved_extension = EXTENSION_DIR.resolve()
    if resolved_output.is_relative_to(resolved_extension):
        relative_output = resolved_output.relative_to(resolved_extension)
        if not relative_output.parts or relative_output.parts[0] != "dist":
            raise BuildError("output inside extension source must be placed under extension/dist")
    return resolved_output


def write_deterministic_zip(staging_directory: Path, output: Path) -> str:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = tempfile.NamedTemporaryFile(
        prefix=f".{output.name}.",
        suffix=".tmp",
        dir=output.parent,
        delete=False,
    )
    temporary_path = Path(temporary_file.name)
    temporary_file.close()

    try:
        with zipfile.ZipFile(temporary_path, "w") as archive:
            for relative_name in sorted(RUNTIME_FILES):
                data = (staging_directory / relative_name).read_bytes()
                entry = zipfile.ZipInfo(relative_name, FIXED_ZIP_TIMESTAMP)
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                entry.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(entry, data, compresslevel=9)
        os.replace(temporary_path, output)
    finally:
        temporary_path.unlink(missing_ok=True)

    return hashlib.sha256(output.read_bytes()).hexdigest()


def build_release(api_base_url_value: str, output_value: str) -> tuple[Path, str, str]:
    api_base_url, parsed_url = normalize_api_base_url(api_base_url_value)
    host_permission = api_host_permission(parsed_url)
    output = validate_output_location(Path(output_value))

    with tempfile.TemporaryDirectory(prefix="untangle-extension-release-") as temporary:
        staging_directory = Path(temporary)
        copy_runtime_files(staging_directory)
        write_release_settings(staging_directory, api_base_url)
        manifest = write_release_manifest(staging_directory, host_permission)
        version = validate_staging(
            staging_directory,
            manifest,
            api_base_url,
            host_permission,
        )
        digest = write_deterministic_zip(staging_directory, output)

    return output, version, digest


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a deterministic Chrome Web Store ZIP for Untangle."
    )
    parser.add_argument(
        "--api-base-url",
        required=True,
        help="Production HTTPS API base URL.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path for the generated ZIP artifact.",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        output, version, digest = build_release(
            arguments.api_base_url,
            arguments.output,
        )
    except BuildError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"artifact={output} version={version} sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
