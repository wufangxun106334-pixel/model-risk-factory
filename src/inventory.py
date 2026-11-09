from __future__ import annotations

from pathlib import Path

from src.common import ContractError, read_json, sha256_file, write_json
from src.contracts import InventoryPayload, ModelInventory

ALLOWED_INVENTORY_SOURCES = {"legacy/credit_v1.R", "legacy/notes/credit_v1.md"}
EXPECTED_FEATURES = ["delay_1", "log_limit", "util_1", "log_pay_1"]


def validate_sources(sources, repository: Path) -> None:
    for source in sources:
        source.validate_range()
        if source.path not in ALLOWED_INVENTORY_SOURCES:
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
    validate_sources(parsed.sources, repository)
    if parsed.feature_order != EXPECTED_FEATURES:
        raise ContractError("Inventory feature order does not match the frozen MDL_CREDIT_V1 contract")
    if parsed.code_threshold != 0.35 or parsed.documented_threshold != 0.50:
        raise ContractError("Inventory must preserve the 0.35 code / 0.50 documentation conflict")
    if parsed.owner != "Unknown" or parsed.training_date != "Unknown":
        raise ContractError("Unknown owner and training date must not be invented")
    if not parsed.conflicts:
        raise ContractError("Inventory threshold conflict is missing")
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
