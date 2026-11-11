"""Validate a hand-written model inventory against the frozen Gate A contract.

This is the stopwatch "stop" check for the manual arm of the V3-04 paired study
(rows T11-T13 in ``materials/impact_measurements.csv``). It applies exactly the
same rules as the Agent path (``src.inventory.build_inventory``) with no
relaxation, and never writes into ``runs/`` or ``dev_runs/``.

Usage:
    .venv/bin/python scripts/validate_inventory.py my_inventory.json [more.json ...]

The input may be either the payload form (what a person writes: ``model_id``,
``model_type``, ``owner``, ``training_date``, ``feature_order``,
``code_threshold``, ``documented_threshold``, ``unknowns``, ``conflicts`` as
``[{"field": ...}]``, ``sources``) or a full inventory artifact; the run-level
fields of an artifact are ignored. Exit status is 0 only if every file passes.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from src.common import ContractError  # noqa: E402
from src.inventory import build_inventory  # noqa: E402

ARTIFACT_ONLY_FIELDS = ("schema_version", "run_id", "review_status")


def to_payload(document: dict) -> dict:
    """Reduce a full inventory artifact to the payload a human is asked to write."""

    payload = {key: value for key, value in document.items() if key not in ARTIFACT_ONLY_FIELDS}
    payload["conflicts"] = [{"field": item["field"]} for item in payload.get("conflicts", [])]
    return payload


def validate_file(path: Path) -> tuple[bool, str]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return False, f"cannot read JSON: {error}"
    if not isinstance(document, dict):
        return False, "top-level JSON value must be an object"
    with tempfile.TemporaryDirectory() as scratch:
        try:
            inventory = build_inventory(
                "manual-validation", to_payload(document), REPOSITORY, Path(scratch) / "inventory.json"
            )
        except ContractError as error:
            return False, str(error)
        except ValueError as error:  # pydantic ValidationError is a ValueError
            return False, " ".join(str(error).split())
    conflicts = ", ".join(item["field"] for item in inventory["conflicts"]) or "none"
    return True, f"{inventory['model_id']}: {len(inventory['sources'])} sources, conflicts: {conflicts}"


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    failed = 0
    for name in argv:
        ok, message = validate_file(Path(name))
        print(f"{'PASS' if ok else 'FAIL'}  {name}  {message}")
        failed += not ok
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
