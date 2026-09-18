from pathlib import Path

import yaml
from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
OPENAPI_PATH = REPOSITORY_ROOT / "contracts" / "openapi" / "openapi.yaml"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as source:
        return yaml.safe_load(source)


def _resolve_path_item(path_item: dict) -> dict:
    reference = path_item.get("$ref")
    if reference is None:
        return path_item
    referenced_path = (OPENAPI_PATH.parent / reference).resolve()
    return _load_yaml(referenced_path)


def test_admin_openapi_document_is_valid() -> None:
    specification, base_uri = read_from_filename(str(OPENAPI_PATH))

    validate(specification, base_uri=base_uri)


def test_admin_openapi_operation_ids_are_stable() -> None:
    specification = _load_yaml(OPENAPI_PATH)
    operation_ids = {
        operation["operationId"]
        for path, path_item in specification["paths"].items()
        if path.startswith("/admin/")
        for method, operation in _resolve_path_item(path_item).items()
        if method in HTTP_METHODS
    }

    assert operation_ids == {"getAdminSession"}


def test_only_one_canonical_openapi_root_exists() -> None:
    roots = [path for path in OPENAPI_PATH.parent.rglob("*.yaml") if "openapi" in _load_yaml(path)]
    assert roots == [OPENAPI_PATH]


def test_generated_admin_models_validate_email_fields() -> None:
    from generated.admin_models import AdminSession

    session = AdminSession.model_validate(
        {
            "user_id": "user-admin-1",
            "email": "admin@example.com",
            "display_name": "Local Admin",
        }
    )

    assert session.email == "admin@example.com"
