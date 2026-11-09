from __future__ import annotations

from pathlib import Path

from src.common import ContractError, read_json, sha256_file, write_json
from src.contracts import InventoryPayload, ModelInventory

EXPECTATIONS_PATH = Path("config") / "inventory_expectations.json"
SCHEMA_PATH = "config/inventory_schema.json"


def load_expectations(repository: Path) -> dict:
    path = repository / EXPECTATIONS_PATH
    if not path.is_file():
        raise ContractError("config/inventory_expectations.json is missing")
    expectations = read_json(path)
    models = expectations.get("models")
    if not isinstance(models, dict) or not models:
        raise ContractError("inventory expectations declare no models")
    return expectations


def expected_model_ids(repository: Path) -> list[str]:
    return sorted(load_expectations(repository)["models"])


def model_expectation(repository: Path, model_id: str) -> dict:
    models = load_expectations(repository)["models"]
    if model_id not in models:
        raise ContractError(f"No inventory expectation is configured for {model_id}")
    return models[model_id]


def inventory_path(run_dir: Path, model_id: str) -> Path:
    """Keep the v1 path stable and give the new models their own artifacts."""

    if model_id == "MDL_CREDIT_V1":
        return run_dir / "model_inventory.json"
    return run_dir / "inventories" / f"{model_id}.json"


def allowed_inventory_sources(repository: Path, model_id: str) -> set[str]:
    return set(model_expectation(repository, model_id)["sources"])


def validate_sources(sources, repository: Path, allowed: set[str]) -> None:
    for source in sources:
        source.validate_range()
        if source.path not in allowed:
            raise ContractError(f"Inventory source is not allowlisted: {source.path}")
        path = repository / source.path
        if not path.is_file() or sha256_file(path) != source.sha256:
            raise ContractError(f"Inventory source hash mismatch: {source.path}")
        lines = path.read_text(encoding="utf-8").splitlines()
        if source.line_end > len(lines):
            raise ContractError(f"Inventory source line range is invalid: {source.path}")
        selected = "\n".join(lines[source.line_start - 1 : source.line_end])
        if source.excerpt not in selected:
            raise ContractError(f"Inventory source excerpt mismatch: {source.path}")


def build_inventory(run_id: str, payload: dict, repository: Path, output_path: Path) -> dict:
    parsed = InventoryPayload.model_validate(payload)
    expectation = model_expectation(repository, parsed.model_id)
    validate_sources(parsed.sources, repository, set(expectation["sources"]))
    if parsed.feature_order != expectation["feature_order"]:
        raise ContractError(
            f"Inventory feature order does not match the frozen {parsed.model_id} contract"
        )
    if (
        abs(parsed.code_threshold - float(expectation["code_threshold"])) > 1e-12
        or abs(parsed.documented_threshold - float(expectation["documented_threshold"])) > 1e-12
    ):
        raise ContractError(
            f"Inventory must preserve the {parsed.model_id} code/documentation threshold pair "
            f"({expectation['code_threshold']} / {expectation['documented_threshold']})"
        )
    for field in expectation["unknown_fields"]:
        if getattr(parsed, field) != "Unknown":
            raise ContractError(f"Unknown {field} must not be invented")
        if field not in parsed.unknowns:
            raise ContractError(f"Unknown field {field} must be listed in unknowns")
    if len(parsed.conflicts) < int(expectation["min_conflicts"]):
        raise ContractError(f"Inventory for {parsed.model_id} is missing its documented conflict")
    covered = {source.path for source in parsed.sources}
    if not set(expectation["sources"]) <= covered:
        raise ContractError("Every model source must appear at least once in sources")
    inventory = ModelInventory(
        schema_version="1",
        run_id=run_id,
        **parsed.model_dump(),
        review_status="PENDING",
    ).model_dump()
    write_json(output_path, inventory)
    return inventory


def load_inventory(path: Path, run_id: str) -> dict:
    inventory = ModelInventory.model_validate(read_json(path)).model_dump()
    if inventory["run_id"] != run_id:
        raise ContractError("Inventory run_id mismatch")
    return inventory
