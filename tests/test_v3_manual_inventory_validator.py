"""The manual-arm validator applies the same Gate A rules as the Agent path."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from tests.test_v3_gap_inventory_conflicts import CONFIRMED_FIELDS, REPOSITORY, TREE, V1, V2, payload

SPEC = importlib.util.spec_from_file_location("validate_inventory", REPOSITORY / "scripts" / "validate_inventory.py")
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def write(tmp_path: Path, name: str, document) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def conflicts(model_id: str) -> list[dict]:
    return [{"field": field} for field in CONFIRMED_FIELDS[model_id]]


@pytest.mark.parametrize("model_id", [V1, V2, TREE])
def test_a_correct_hand_written_payload_passes(tmp_path, model_id):
    path = write(tmp_path, "inv.json", payload(model_id, conflicts(model_id)))
    assert validator.main([str(path)]) == 0


def test_a_full_inventory_artifact_is_accepted_as_input(tmp_path):
    artifact = payload(V1, conflicts(V1))
    artifact.update(schema_version="1", run_id="some-run", review_status="APPROVED")
    artifact["conflicts"] = [{"field": "decision_threshold", "description": "free text", "sources": []}]
    ok, message = validator.validate_file(write(tmp_path, "artifact.json", artifact))
    assert ok, message


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"code_threshold": 0.5}, "threshold pair"),
        ({"owner": "Jane"}, "must not be invented"),
        ({"feature_order": ["log_limit", "delay_1", "util_1", "log_pay_1"]}, "feature order"),
    ],
)
def test_contract_violations_fail_with_the_reason(tmp_path, overrides, reason):
    ok, message = validator.validate_file(write(tmp_path, "bad.json", payload(V1, conflicts(V1), **overrides)))
    assert not ok and reason in message


def test_missing_conflict_and_bad_json_fail_and_set_exit_status(tmp_path):
    missing = write(tmp_path, "missing.json", payload(V2, []))
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    good = write(tmp_path, "good.json", payload(V1, conflicts(V1)))
    assert validator.main([str(good), str(missing), str(broken)]) == 1
