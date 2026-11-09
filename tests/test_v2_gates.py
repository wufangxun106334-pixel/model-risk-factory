"""V2 gate blocking tests: skipping, tampering and context invalidation (V2-04)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.common import ContractError, GateError, read_json, sha256_file, write_json
from src.inventory import build_inventory, inventory_path
from src.migration import candidate_dir, save_candidate
from src.review import artifact_digest, current_decision, record_review, require_approval

RUN_ID = "v2-gate-test"
REPOSITORY = Path(__file__).resolve().parents[1]


def make_run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    write_json(run / "run_manifest.json", {"run_id": RUN_ID})
    write_json(run / "context_manifest.json", {"run_id": RUN_ID, "assets": []})
    return run


APPROVED_PAYLOAD = {
    "model_id": "MDL_CREDIT_V2",
    "model_type": "logistic regression",
    "owner": "Unknown",
    "training_date": "Unknown",
    "feature_order": ["delay_1", "delay_2", "delay_3", "log_limit", "util_1", "util_mean_6", "log_pay_1"],
    "code_threshold": 0.3,
    "documented_threshold": 0.3,
    "unknowns": ["owner", "training_date"],
    "conflicts": [{"topic": "feature list", "code": "7 features", "note": "note lists 6"}],
    "sources": [
        {
            "path": "legacy/credit_v2.R",
            "sha256": sha256_file(REPOSITORY / "legacy/credit_v2.R"),
            "line_start": 1,
            "line_end": 8,
            "excerpt": "MODEL_ID <- \"MDL_CREDIT_V2\"",
        },
        {
            "path": "legacy/notes/credit_v2.md",
            "sha256": sha256_file(REPOSITORY / "legacy/notes/credit_v2.md"),
            "line_start": 1,
            "line_end": 9,
            "excerpt": "Decision threshold: 0.30",
        },
    ],
}


def test_inventory_validation_rejects_a_tampered_source_excerpt(tmp_path):
    run = make_run(tmp_path)
    payload = {**APPROVED_PAYLOAD, "sources": [dict(APPROVED_PAYLOAD["sources"][0]), dict(APPROVED_PAYLOAD["sources"][1])]}
    payload["sources"][1] = {**payload["sources"][1], "excerpt": "Decision threshold: 0.99"}
    with pytest.raises(ContractError):
        build_inventory(RUN_ID, payload, REPOSITORY, inventory_path(run, "MDL_CREDIT_V2"))


def test_inventory_validation_rejects_a_wrong_source_hash(tmp_path):
    run = make_run(tmp_path)
    payload = {**APPROVED_PAYLOAD, "sources": [{**APPROVED_PAYLOAD["sources"][0], "sha256": "0" * 64}, APPROVED_PAYLOAD["sources"][1]]}
    with pytest.raises(ContractError):
        build_inventory(RUN_ID, payload, REPOSITORY, inventory_path(run, "MDL_CREDIT_V2"))


def test_inventory_validation_rejects_an_invented_owner_or_lost_conflict(tmp_path):
    run = make_run(tmp_path)
    with pytest.raises(ContractError):
        build_inventory(RUN_ID, {**APPROVED_PAYLOAD, "owner": "Someone"}, REPOSITORY, inventory_path(run, "MDL_CREDIT_V2"))
    with pytest.raises(ContractError):
        build_inventory(RUN_ID, {**APPROVED_PAYLOAD, "conflicts": []}, REPOSITORY, inventory_path(run, "MDL_CREDIT_V2"))


def test_three_inventories_are_separate_artifacts(tmp_path):
    run = make_run(tmp_path)
    assert inventory_path(run, "MDL_CREDIT_V1") == run / "model_inventory.json"
    assert inventory_path(run, "MDL_CREDIT_V2") == run / "inventories" / "MDL_CREDIT_V2.json"
    assert inventory_path(run, "MDL_CREDIT_TREE") == run / "inventories" / "MDL_CREDIT_TREE.json"


def test_gate_a_for_v2_does_not_authorise_the_migrated_candidate(tmp_path):
    run = make_run(tmp_path)
    v2_path = inventory_path(run, "MDL_CREDIT_V2")
    build_inventory(RUN_ID, APPROVED_PAYLOAD, REPOSITORY, v2_path)
    record_review(run, RUN_ID, "Gate_A", v2_path, artifact_digest(v2_path, "Gate_A"), "APPROVED", "agent-delegated", "delegated inventory review")
    assert current_decision(run, RUN_ID, "Gate_A", v2_path) == "APPROVED"
    # The migration target is still MDL_CREDIT_V1 and its own Gate A is missing.
    write_json(run / "model_inventory.json", {"run_id": RUN_ID, "model_id": "MDL_CREDIT_V1", "review_status": "PENDING", "sources": []})
    with pytest.raises(GateError):
        save_candidate(run, RUN_ID, "print('no')\n", 0, {"test": True})


def test_candidate_approval_is_invalidated_by_a_context_change(tmp_path):
    run = make_run(tmp_path)
    inventory = run / "model_inventory.json"
    write_json(inventory, {"run_id": RUN_ID, "model_id": "MDL_CREDIT_V1", "review_status": "PENDING", "sources": []})
    record_review(run, RUN_ID, "Gate_A", inventory, artifact_digest(inventory, "Gate_A"), "APPROVED", "agent-delegated", "delegated inventory review")
    metadata = save_candidate(run, RUN_ID, "print('candidate')\n", 0, {"test": True})
    source = candidate_dir(run, 0) / "credit_v1.py"
    record_review(run, RUN_ID, "Gate_B", source, metadata["candidate_sha256"], "APPROVED", "agent-delegated", "delegated code review")
    require_approval(run, RUN_ID, "Gate_B", source)

    write_json(run / "context_manifest.json", {"run_id": RUN_ID, "assets": [], "changed": True})
    assert current_decision(run, RUN_ID, "Gate_B", source) in {"INVALIDATED", "NOT_REVIEWED"}
    with pytest.raises(GateError):
        require_approval(run, RUN_ID, "Gate_B", source)


def test_tampered_candidate_needs_a_new_gate_b(tmp_path):
    run = make_run(tmp_path)
    inventory = run / "model_inventory.json"
    write_json(inventory, {"run_id": RUN_ID, "model_id": "MDL_CREDIT_V1", "review_status": "PENDING", "sources": []})
    record_review(run, RUN_ID, "Gate_A", inventory, artifact_digest(inventory, "Gate_A"), "APPROVED", "agent-delegated", "delegated inventory review")
    metadata = save_candidate(run, RUN_ID, "print('candidate')\n", 0, {"test": True})
    source = candidate_dir(run, 0) / "credit_v1.py"
    record_review(run, RUN_ID, "Gate_B", source, metadata["candidate_sha256"], "APPROVED", "agent-delegated", "delegated code review")
    source.write_text("print('tampered')\n", encoding="utf-8")
    assert current_decision(run, RUN_ID, "Gate_B", source) == "NOT_REVIEWED"
    with pytest.raises(GateError):
        require_approval(run, RUN_ID, "Gate_B", source)


def test_gate_c_is_required_before_a_report_can_be_approved(tmp_path):
    from src.report import report_status, write_approval

    run = make_run(tmp_path)
    write_json(run / "validation_metrics.json", {"run_id": RUN_ID})
    (run / "report").mkdir(parents=True, exist_ok=True)
    (run / "report" / "validation_report.md").write_text("report body\n", encoding="utf-8")
    (run / "report" / "values_index.csv").write_text("section,label,json_path,text\n", encoding="utf-8")
    (run / "report" / "validation_tables.md").write_text("# tables\n", encoding="utf-8")
    write_json(run / "report" / "review_manifest.json", {
        "schema_version": "1",
        "run_id": RUN_ID,
        "report_sha256": sha256_file(run / "report" / "validation_report.md"),
        "metrics_sha256": sha256_file(run / "validation_metrics.json"),
        "values_index_sha256": sha256_file(run / "report" / "values_index.csv"),
        "tables_sha256": sha256_file(run / "report" / "validation_tables.md"),
        "value_count": 1,
        "unresolved_numbers": [],
    })
    assert report_status(run, RUN_ID)["gate_c"] == "NOT_REVIEWED"
    with pytest.raises(GateError):
        write_approval(run, RUN_ID)

    manifest = run / "report" / "review_manifest.json"
    record_review(run, RUN_ID, "Gate_C", manifest, artifact_digest(manifest, "Gate_C"), "APPROVED", "agent-delegated", "delegated report review")
    assert read_json(run / "review_log.json")["reviews"][-1]["gate"] == "Gate_C"
    write_approval(run, RUN_ID)
    assert report_status(run, RUN_ID)["status"] == "APPROVED"

    # Tampering with the reviewed report invalidates the approval immediately.
    (run / "report" / "validation_report.md").write_text("edited body\n", encoding="utf-8")
    assert report_status(run, RUN_ID)["status"] == "DRAFT"
    # A bound file that disappears also drops the report back to DRAFT.
    (run / "report" / "values_index.csv").unlink()
    assert any("values index" in reason for reason in report_status(run, RUN_ID)["reasons"])
