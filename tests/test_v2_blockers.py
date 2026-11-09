"""Release blockers 1: metrics must verify the frozen, gated attempt before reuse.

Covers the v2 defect where `validation-metrics` re-executed or silently reused a
cached drift-batch run without checking the context, the frozen source hash, the
current Gate A/B decisions, the split inputs or the cached output hashes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.acceptance_v2 import _v2_04
from src.common import ContractError, GateError, read_json, sha256_file, utc_now, write_json
from src.review import artifact_digest, record_review
from src.validation import _predict_shifted, verified_metric_inputs

RUN_ID = "v2-blocker-run"

EXECUTION_DOCKER = {
    "network": "none",
    "read_only": True,
    "user": "65532:65532",
    "cap_drop": ["ALL"],
    "security_opt": ["no-new-privileges"],
}


def _context(repo: Path, run: Path) -> str:
    write_json(run / "context_manifest.json", {"run_id": RUN_ID, "assets": []})
    return sha256_file(run / "context_manifest.json")


def _splits(run: Path) -> dict:
    files = {}
    for name in ("train", "dev", "holdout", "shift_pool"):
        path = run / "data" / f"{name}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"client_id,default_flag\n{name},0\n", encoding="utf-8")
        files[f"{name}.csv"] = {"sha256": sha256_file(path), "rows": 1}
    write_json(run / "data" / "data_manifest.json", {"run_id": RUN_ID, "files": files})
    return files


def _candidate(run: Path, attempt: int, context_sha: str, code: str) -> Path:
    directory = run / "candidates" / f"attempt_{attempt:03d}"
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "credit_v1.py"
    source.write_text(code, encoding="utf-8")
    write_json(directory / "candidate.json", {
        "run_id": RUN_ID,
        "attempt": attempt,
        "model_id": "MDL_CREDIT_V1",
        "candidate_sha256": sha256_file(source),
        "context_sha256": context_sha,
        "created_at": utc_now(),
    })
    return source


def build_run(tmp_path: Path, *, frozen_attempt: int = 1) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    run = repo / "runs" / RUN_ID
    run.mkdir(parents=True)
    write_json(run / "run_manifest.json", {"run_id": RUN_ID})
    context_sha = _context(repo, run)
    _splits(run)
    write_json(run / "reference" / "model.json", {"threshold": 0.35})
    inventory = run / "model_inventory.json"
    write_json(inventory, {"run_id": RUN_ID, "model_id": "MDL_CREDIT_V1", "review_status": "PENDING", "sources": []})
    record_review(run, RUN_ID, "Gate_A", inventory, artifact_digest(inventory, "Gate_A"), "APPROVED", "agent-delegated", "delegated inventory review")

    # A legal repair history: attempt 0 failed development parity, attempt 1 passed.
    _candidate(run, 0, context_sha, "print('attempt 0')\n")
    write_json(run / "dev" / "attempt_000" / "parity_summary.json", {"run_id": RUN_ID, "status": "FAIL"})
    source = _candidate(run, frozen_attempt, context_sha, "print('attempt 1')\n")
    digest = sha256_file(source)
    record_review(run, RUN_ID, "Gate_B", source, digest, "APPROVED", "agent-delegated", "delegated code review")
    (run / "frozen").mkdir(parents=True, exist_ok=True)
    (run / "frozen" / "credit_v1.py").write_text(source.read_text(), encoding="utf-8")
    write_json(run / "frozen" / "frozen.json", {
        "run_id": RUN_ID,
        "attempt": frozen_attempt,
        "candidate_sha256": digest,
        "context_sha256": context_sha,
    })
    write_json(run / "migration_result.json", {
        "run_id": RUN_ID,
        "model_id": "MDL_CREDIT_V1",
        "attempt": frozen_attempt,
        "candidate_sha256": digest,
        "dev_status": "PASS",
        "fixture_status": "PASS",
        "final_status": "PASS",
        "context_sha256": context_sha,
    })
    work = run / "dev" / f"attempt_{frozen_attempt:03d}"
    write_json(work / "parity_summary.json", {"run_id": RUN_ID, "status": "PASS"})
    write_json(work / "fixture_summary.json", {"run_id": RUN_ID, "status": "PASS", "candidate_sha256": digest})
    write_json(work / "execution.json", {
        "status": "PASS",
        "exit_code": 0,
        "started_at": utc_now(),
        "docker": EXECUTION_DOCKER,
    })

    # Gate C on the report manifest, then the approval record.
    manifest = run / "report" / "review_manifest.json"
    write_json(manifest, {"run_id": RUN_ID, "report_sha256": "a" * 64, "metrics_sha256": "b" * 64, "unresolved_numbers": []})
    write_json(run / "report" / "validation_report.md", "body\n")
    write_json(run / "report" / "validation_metrics.json", {"run_id": RUN_ID})
    record_review(run, RUN_ID, "Gate_C", manifest, artifact_digest(manifest, "Gate_C"), "APPROVED", "agent-delegated", "delegated report review")
    review = read_json(run / "review_log.json")["reviews"][-1]
    write_json(run / "report" / "approval.json", {
        "run_id": RUN_ID,
        "status": "APPROVED",
        "report_sha256": "a" * 64,
        "metrics_sha256": "b" * 64,
        "approved_at": review["timestamp"],
    })
    return repo, run


def test_verified_inputs_accept_the_frozen_passing_attempt(tmp_path):
    repo, run = build_run(tmp_path)
    verified = verified_metric_inputs(run, RUN_ID)
    assert verified["attempt"] == 1
    assert verified["candidate_sha256"] == sha256_file(run / "frozen" / "credit_v1.py")


def test_metrics_refuse_when_the_context_is_invalidated(tmp_path):
    repo, run = build_run(tmp_path)
    write_json(run / "context_manifest.json", {"run_id": RUN_ID, "assets": [], "changed": True})
    with pytest.raises(ContractError, match="context"):
        verified_metric_inputs(run, RUN_ID)


def test_metrics_refuse_when_the_frozen_source_is_tampered(tmp_path):
    repo, run = build_run(tmp_path)
    (run / "frozen" / "credit_v1.py").write_text("print('tampered')\n", encoding="utf-8")
    with pytest.raises(ContractError, match="(?i)frozen"):
        verified_metric_inputs(run, RUN_ID)


def test_metrics_refuse_when_gate_b_is_withdrawn(tmp_path):
    repo, run = build_run(tmp_path)
    source = run / "candidates" / "attempt_001" / "credit_v1.py"
    record_review(run, RUN_ID, "Gate_B", source, sha256_file(source), "REJECTED", "agent-delegated", "withdrawn after re-read")
    with pytest.raises(GateError):
        verified_metric_inputs(run, RUN_ID)


def test_metrics_refuse_when_a_split_input_changed(tmp_path):
    repo, run = build_run(tmp_path)
    (run / "data" / "dev.csv").write_text("client_id,default_flag\nreplaced,1\n", encoding="utf-8")
    with pytest.raises(ContractError, match="dev"):
        verified_metric_inputs(run, RUN_ID)


def test_metrics_refuse_when_the_frozen_attempt_did_not_pass(tmp_path):
    repo, run = build_run(tmp_path)
    result = read_json(run / "migration_result.json")
    result["dev_status"] = "FAIL"
    write_json(run / "migration_result.json", result)
    with pytest.raises(ContractError, match="development parity"):
        verified_metric_inputs(run, RUN_ID)


def test_metrics_refuse_when_a_different_candidate_was_frozen(tmp_path):
    repo, run = build_run(tmp_path)
    result = read_json(run / "migration_result.json")
    result["attempt"] = 0
    write_json(run / "migration_result.json", result)
    with pytest.raises(ContractError):
        verified_metric_inputs(run, RUN_ID)


def _cached_shifted(run: Path, verified: dict) -> tuple[Path, Path]:
    output = run / "validation"
    work = output / "shifted_execution"
    work.mkdir(parents=True, exist_ok=True)
    shifted = run / "data" / "shifted.csv"
    shifted.write_text("client_id,default_flag\nshift,1\n", encoding="utf-8")
    predictions = output / "shifted_predictions.csv"
    predictions.write_text("client_id,probability\nshift,0.5\n", encoding="utf-8")
    write_json(work / "execution.json", {
        "status": "PASS",
        "candidate_sha256": verified["candidate_sha256"],
        "model_sha256": sha256_file(verified["model"]),
        "input_sha256": sha256_file(shifted),
        "output_sha256": sha256_file(predictions),
    })
    return shifted, predictions


def test_cached_drift_output_is_reused_only_after_hash_verification(tmp_path, monkeypatch):
    repo, run = build_run(tmp_path)
    verified = verified_metric_inputs(run, RUN_ID)
    shifted, predictions = _cached_shifted(run, verified)

    monkeypatch.setattr("src.validation.run_candidate", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not re-execute")))
    path, execution = _predict_shifted(run, shifted, run / "validation", "image", verified)
    assert path == predictions and execution["status"] == "PASS"

    predictions.write_text("client_id,probability\nshift,0.9\n", encoding="utf-8")
    with pytest.raises(ContractError, match="predictions"):
        _predict_shifted(run, shifted, run / "validation", "image", verified)


def test_cached_drift_output_from_another_candidate_is_rejected(tmp_path):
    repo, run = build_run(tmp_path)
    verified = verified_metric_inputs(run, RUN_ID)
    shifted, _predictions = _cached_shifted(run, verified)
    execution_path = run / "validation" / "shifted_execution" / "execution.json"
    execution = read_json(execution_path)
    execution["candidate_sha256"] = "0" * 64
    write_json(execution_path, execution)
    with pytest.raises(ContractError, match="candidate"):
        _predict_shifted(run, shifted, run / "validation", "image", verified)


def test_incomplete_cached_drift_artefacts_are_rejected(tmp_path, monkeypatch):
    repo, run = build_run(tmp_path)
    verified = verified_metric_inputs(run, RUN_ID)
    shifted, predictions = _cached_shifted(run, verified)
    (run / "validation" / "shifted_execution" / "execution.json").unlink()
    monkeypatch.setattr("src.validation.run_candidate", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not re-execute")))
    with pytest.raises(ContractError, match="incomplete"):
        _predict_shifted(run, shifted, run / "validation", "image", verified)


def test_v2_04_binds_the_frozen_attempt_not_the_first_candidate(tmp_path):
    repo, run = build_run(tmp_path)
    status, actual = _v2_04(repo, run, RUN_ID)
    assert status == "PASS", actual
    assert "frozen attempt 1" in actual


def test_v2_04_fails_when_the_frozen_attempt_lacks_parity(tmp_path):
    repo, run = build_run(tmp_path)
    (run / "dev" / "attempt_001" / "parity_summary.json").unlink()
    status, actual = _v2_04(repo, run, RUN_ID)
    assert status == "FAIL"
    assert "development parity" in actual


def test_v2_04_fails_when_the_frozen_attempt_fixtures_failed(tmp_path):
    repo, run = build_run(tmp_path)
    summary = read_json(run / "dev" / "attempt_001" / "fixture_summary.json")
    summary["status"] = "FAIL"
    write_json(run / "dev" / "attempt_001" / "fixture_summary.json", summary)
    status, actual = _v2_04(repo, run, RUN_ID)
    assert status == "FAIL"
    assert "behaviour fixtures" in actual
