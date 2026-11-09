from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.common import ContractError, GateError, read_json, read_jsonl, sha256_file, write_json
from src.migration import freeze_candidate, load_frozen, save_candidate, update_dev_result
from src.workflow import run_holdout
from src.review import artifact_digest, current_decision, record_review, require_approval


def make_run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    run.mkdir()
    write_json(run / "run_manifest.json", {"run_id": "test-run"})
    write_json(run / "context_manifest.json", {"run_id": "test-run", "assets": []})
    return run


def make_inventory(run: Path) -> Path:
    path = run / "model_inventory.json"
    write_json(path, {"run_id": "test-run", "model_id": "MDL_CREDIT_V1", "review_status": "PENDING", "sources": []})
    return path


def approve(run: Path, gate: str, artifact: Path) -> str:
    digest = artifact_digest(artifact, gate)
    record_review(run, "test-run", gate, artifact, digest, "APPROVED", "test-reviewer", "automated unit test")
    return digest


def test_gate_a_is_required_and_review_does_not_change_payload_hash(tmp_path):
    run = make_run(tmp_path)
    inventory = make_inventory(run)
    with pytest.raises(GateError):
        save_candidate(run, "test-run", "print('no')\n", 0, {"test": True})
    digest = approve(run, "Gate_A", inventory)
    assert read_json(inventory)["review_status"] == "APPROVED"
    assert artifact_digest(inventory, "Gate_A") == digest
    assert current_decision(run, "test-run", "Gate_A", inventory) == "APPROVED"
    save_candidate(run, "test-run", "print('yes')\n", 0, {"test": True})


def fixtures(run: Path, attempt: int, candidate_sha256: str, status: str = "PASS") -> Path:
    path = run / "dev" / f"attempt_{attempt:03d}" / "fixture_summary.json"
    write_json(path, {"run_id": "test-run", "candidate_sha256": candidate_sha256, "status": status, "records": []})
    return path


def test_gate_b_binds_exact_candidate_and_freeze_requires_dev_pass(tmp_path):
    run = make_run(tmp_path)
    inventory = make_inventory(run)
    approve(run, "Gate_A", inventory)
    candidate = save_candidate(run, "test-run", "print('candidate')\n", 0, {"test": True})
    source = run / "candidates" / "attempt_000" / "credit_v1.py"
    require_approval(run, "test-run", "Gate_A", inventory)
    with pytest.raises(GateError):
        require_approval(run, "test-run", "Gate_B", source)
    with pytest.raises(GateError):
        record_review(run, "test-run", "Gate_B", source, "0" * 64, "APPROVED", "test-reviewer", "wrong hash")
    with pytest.raises(GateError):
        freeze_candidate(run, "test-run", 0)
    approve(run, "Gate_B", source)
    with pytest.raises(GateError):
        freeze_candidate(run, "test-run", 0)
    update_dev_result(run, "test-run", 0, "PASS", "dev/parity_summary.json")
    with pytest.raises(GateError, match="fixtures"):
        freeze_candidate(run, "test-run", 0)
    fixtures(run, 0, candidate["candidate_sha256"], "FAIL")
    with pytest.raises(GateError, match="fixtures"):
        freeze_candidate(run, "test-run", 0)
    fixtures(run, 0, "0" * 64)
    with pytest.raises(GateError, match="fixtures"):
        freeze_candidate(run, "test-run", 0)
    fixtures(run, 0, candidate["candidate_sha256"])
    frozen = freeze_candidate(run, "test-run", 0)
    assert frozen["candidate_sha256"] == candidate["candidate_sha256"]
    assert sha256_file(run / "frozen" / "credit_v1.py") == candidate["candidate_sha256"]
    assert load_frozen(run, "test-run")["attempt"] == 0


def test_changed_candidate_needs_new_gate_b(tmp_path):
    run = make_run(tmp_path)
    approve(run, "Gate_A", make_inventory(run))
    save_candidate(run, "test-run", "print('initial')\n", 0, {"test": True})
    first = run / "candidates" / "attempt_000" / "credit_v1.py"
    approve(run, "Gate_B", first)
    save_candidate(run, "test-run", "print('repair')\n", 1, {"test": True})
    second = run / "candidates" / "attempt_001" / "credit_v1.py"
    with pytest.raises(GateError):
        require_approval(run, "test-run", "Gate_B", second)
    assert artifact_digest(first, "Gate_B") != artifact_digest(second, "Gate_B")


def test_gate_a_withdrawal_blocks_freeze(tmp_path):
    run = make_run(tmp_path)
    inventory = make_inventory(run)
    approve(run, "Gate_A", inventory)
    candidate = save_candidate(run, "test-run", "print('candidate')\n", 0, {"test": True})
    approve(run, "Gate_B", run / "candidates" / "attempt_000" / "credit_v1.py")
    update_dev_result(run, "test-run", 0, "PASS", "dev/parity_summary.json")
    fixtures(run, 0, candidate["candidate_sha256"])
    digest = artifact_digest(inventory, "Gate_A")
    record_review(run, "test-run", "Gate_A", inventory, digest, "REJECTED", "test-reviewer", "withdrawn after review")
    with pytest.raises(GateError, match="Gate_A"):
        freeze_candidate(run, "test-run", 0)


def test_inventory_change_invalidates_gate_a_and_blocks_candidate_generation(tmp_path):
    run = make_run(tmp_path)
    inventory = make_inventory(run)
    approve(run, "Gate_A", inventory)
    write_json(inventory, {"run_id": "test-run", "model_id": "MDL_CREDIT_V1", "review_status": "APPROVED", "sources": ["changed"]})
    assert current_decision(run, "test-run", "Gate_A", inventory) != "APPROVED"
    with pytest.raises(GateError):
        save_candidate(run, "test-run", "print('no')\n", 0, {"test": True})


def make_repo_run(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    run = repo / "runs" / "run"
    run.mkdir(parents=True)
    write_json(run / "run_manifest.json", {"run_id": "test-run"})
    write_json(run / "context_manifest.json", {"run_id": "test-run", "assets": []})
    write_json(repo / "config" / "runtime_config.json", {"runner_image": "model-risk-factory-runner:v1"})
    for name in ("dev", "holdout"):
        (run / "data").mkdir(parents=True, exist_ok=True)
        (run / "data" / f"{name}.csv").write_text(f"client_id,default_flag\n{name},0\n", encoding="utf-8")
    write_json(run / "data" / "data_manifest.json", {
        "files": {
            "dev.csv": {"sha256": sha256_file(run / "data" / "dev.csv")},
            "holdout.csv": {"sha256": sha256_file(run / "data" / "holdout.csv")},
        }
    })
    return repo, run


def test_holdout_requires_gate_a_fixtures_and_dev_execution(tmp_path, monkeypatch):
    from src import workflow

    repo, run = make_repo_run(tmp_path)
    inventory = make_inventory(run)
    approve(run, "Gate_A", inventory)
    candidate = save_candidate(run, "test-run", "print('candidate')\n", 0, {"test": True})
    source = run / "candidates" / "attempt_000" / "credit_v1.py"
    approve(run, "Gate_B", source)
    update_dev_result(run, "test-run", 0, "PASS", "dev/parity_summary.json")
    write_json(run / "dev" / "attempt_000" / "execution.json", {"status": "PASS", "exit_code": 0, "image": "model-risk-factory-runner:v1"})
    fixtures(run, 0, candidate["candidate_sha256"])

    def forbidden(*args, **kwargs):
        raise AssertionError("Holdout must not execute before all preconditions pass")

    monkeypatch.setattr(workflow, "run_candidate", forbidden)
    monkeypatch.setattr(workflow, "consume_holdout", forbidden)

    freeze_candidate(run, "test-run", 0)
    migrated = read_json(run / "migration_result.json")
    migrated["dev_status"] = "FAIL"
    write_json(run / "migration_result.json", migrated)
    with pytest.raises(GateError, match="development parity"):
        workflow.run_holdout(run, "test-run")

    migrated["dev_status"] = "PASS"
    write_json(run / "migration_result.json", migrated)
    write_json(run / "dev" / "attempt_000" / "execution.json", {"status": "PASS", "exit_code": 0, "image": "other-image:v1"})
    with pytest.raises(ContractError, match="image"):
        workflow.run_holdout(run, "test-run")

    write_json(run / "dev" / "attempt_000" / "execution.json", {"status": "PASS", "exit_code": 0, "image": "model-risk-factory-runner:v1"})
    fixtures(run, 0, candidate["candidate_sha256"], "FAIL")
    with pytest.raises(GateError, match="fixtures"):
        workflow.run_holdout(run, "test-run")


def _prepare_holdout_run(tmp_path):
    repo, run = make_repo_run(tmp_path)
    inventory = make_inventory(run)
    approve(run, "Gate_A", inventory)
    candidate = save_candidate(run, "test-run", "print('candidate')\n", 0, {"test": True})
    approve(run, "Gate_B", run / "candidates" / "attempt_000" / "credit_v1.py")
    update_dev_result(run, "test-run", 0, "PASS", "dev/parity_summary.json")
    write_json(run / "dev" / "attempt_000" / "execution.json", {"status": "PASS", "exit_code": 0, "image": "model-risk-factory-runner:v1"})
    fixtures(run, 0, candidate["candidate_sha256"])
    freeze_candidate(run, "test-run", 0)
    return repo, run


def test_holdout_is_consumed_once_and_rejects_replay(tmp_path, monkeypatch):
    from src import workflow

    repo, run = _prepare_holdout_run(tmp_path)
    calls = []

    def fake_candidate(source, model, input_path, work_dir, **kwargs):
        work_dir.mkdir(parents=True, exist_ok=True)
        calls.append(kwargs.get("image"))
        return {"status": "EXECUTION_ERROR", "exit_code": 1, "image": kwargs.get("image"), "docker": {}}

    monkeypatch.setattr(workflow, "run_candidate", fake_candidate)

    first = run_holdout(run, "test-run")
    assert first["status"] == "FAIL"
    assert calls == ["model-risk-factory-runner:v1"]
    ledger = read_jsonl(run.parent / "holdout_consumption.jsonl")
    assert len(ledger) == 1
    assert ledger[0]["run_id"] == "test-run"
    with pytest.raises(ContractError, match="already been attempted"):
        run_holdout(run, "test-run")
    assert len(calls) == 1


def test_rejected_review_is_not_approval(tmp_path):
    run = make_run(tmp_path)
    inventory = make_inventory(run)
    digest = artifact_digest(inventory, "Gate_A")
    record_review(run, "test-run", "Gate_A", inventory, digest, "REJECTED", "test-reviewer", "revise")
    assert read_json(inventory)["review_status"] == "REJECTED"
    with pytest.raises(GateError):
        require_approval(run, "test-run", "Gate_A", inventory)


def test_candidate_fixtures_summary_is_where_freeze_reads_it(tmp_path, monkeypatch):
    from src import workflow

    repo, run = make_repo_run(tmp_path)
    inventory = make_inventory(run)
    approve(run, "Gate_A", inventory)
    candidate = save_candidate(run, "test-run", "print('candidate')\n", 0, {"test": True})
    approve(run, "Gate_B", run / "candidates" / "attempt_000" / "credit_v1.py")
    update_dev_result(run, "test-run", 0, "PASS", "dev/parity_summary.json")
    for name in workflow.ROW_FIXTURES:
        reference = run / "fixtures" / name / "r" / "dev_predictions.csv"
        reference.parent.mkdir(parents=True, exist_ok=True)
        reference.write_text("client_id,probability,classification\nx,0.5,1\n", encoding="utf-8")

    def fake_candidate(source, model, input_path, work_dir, **kwargs):
        work_dir.mkdir(parents=True, exist_ok=True)
        if input_path.stem in workflow.REJECTION_FIXTURES:
            return {"status": "EXECUTION_ERROR", "exit_code": 2, "image": kwargs.get("image")}
        return {"status": "PASS", "exit_code": 0, "image": kwargs.get("image")}

    def fake_compare(baseline_path, candidate_path, summary_path, diff_path, **kwargs):
        write_json(summary_path, {"run_id": "test-run", "status": "PASS"})
        return {"status": "PASS", "max_abs_diff": 0.0, "mean_abs_diff": 0.0,
                "classification_mismatch_count": 0, "behaviour_mismatch_count": 0}

    monkeypatch.setattr(workflow, "run_candidate", fake_candidate)
    monkeypatch.setattr(workflow, "compare_files", fake_compare)

    summary = workflow.run_candidate_fixtures(run, "test-run", 0)
    assert summary["status"] == "PASS"
    assert workflow.fixture_summary_path(run, 0) == run / "dev" / "attempt_000" / "fixture_summary.json"
    assert read_json(workflow.fixture_summary_path(run, 0))["candidate_sha256"] == candidate["candidate_sha256"]

    frozen = freeze_candidate(run, "test-run", 0)
    assert frozen["candidate_sha256"] == candidate["candidate_sha256"]
