from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.acceptance import evaluate_acceptance
from src.agent import _read_repository_asset, generate_candidate
from src.common import ContractError, GateError, read_json, write_json
from src.provider import ProviderResponse, ToolCall
from src.review import artifact_digest, record_review


class FakeProvider:
    def __init__(self):
        self.calls = []

    def generate(self, messages, tools=None):
        self.calls.append({"messages": list(messages), "tools": tools})
        if len(self.calls) == 1:
            call = ToolCall("call-submit", "submit_candidate", json.dumps({"model_id": "MDL_CREDIT_V1", "code": "print('fixture only; never executed')\n"}))
            return ProviderResponse(None, (call,), "tool_calls", "req-fixture-tool", "event-tool")
        return ProviderResponse("done", (), "stop", "req-fixture-final", "event-final")


def prepared_run(tmp_path, monkeypatch, approve=True):
    run = tmp_path / "run"
    run.mkdir()
    write_json(run / "run_manifest.json", {"run_id": "security-test"})
    write_json(run / "context_manifest.json", {"run_id": "security-test", "assets": []})
    write_json(run / "provider" / "capability_check.json", {"status": "PASS", "request_ids": ["capability-fixture"]})
    write_json(run / "reference" / "model.json", {"coefficients": {"intercept": 0}, "feature_order": ["delay_1", "log_limit", "util_1", "log_pay_1"], "medians": {}, "threshold": 0.35})
    inventory = run / "model_inventory.json"
    write_json(inventory, {"run_id": "security-test", "model_id": "MDL_CREDIT_V1", "review_status": "PENDING"})
    if approve:
        digest = artifact_digest(inventory, "Gate_A")
        record_review(run, "security-test", "Gate_A", inventory, digest, "APPROVED", "unit-test", "not a human or real migration approval")
    provider = FakeProvider()
    monkeypatch.setattr("src.agent._provider", lambda *args: provider)
    return run, provider


def test_candidate_submission_does_not_execute_and_has_no_dataset_artifacts(tmp_path, monkeypatch):
    run, provider = prepared_run(tmp_path, monkeypatch)
    metadata = generate_candidate(Path.cwd(), run, "security-test", 0)
    assert metadata["generation_mode"] == "TEST_DOUBLE"
    assert len(provider.calls) == 1
    assert not (run / "dev").exists()
    assert not (run / "holdout").exists()
    payload = json.dumps(provider.calls, ensure_ascii=False)
    assert "holdout.csv" not in payload
    assert "holdout_predictions.csv" not in payload
    assert "dev_predictions.csv" not in payload
    assert "parity_diff.csv" not in payload


def test_test_double_candidate_can_never_pass_v1_06(tmp_path, monkeypatch):
    run, _ = prepared_run(tmp_path, monkeypatch)
    metadata = generate_candidate(Path.cwd(), run, "security-test", 0)
    assert metadata["generation_mode"] == "TEST_DOUBLE"
    write_json(run / "holdout" / "parity_summary.json", {"status": "PASS"})
    result = read_json(run / "migration_result.json")
    result["dev_status"] = "PASS"
    result["final_status"] = "PASS"
    write_json(run / "migration_result.json", result)
    records = {record["acceptance_id"]: record for record in evaluate_acceptance(Path.cwd(), run, "security-test")}
    assert records["V1-06"]["status"] != "PASS"
    assert records["V1-06"]["status"] == "FAIL"
    assert "real_api_candidate=False" in records["V1-06"]["actual"]


def test_gate_a_blocks_before_agent_request(tmp_path, monkeypatch):
    run, provider = prepared_run(tmp_path, monkeypatch, approve=False)
    with pytest.raises(GateError):
        generate_candidate(__import__("pathlib").Path.cwd(), run, "security-test", 0)
    assert provider.calls == []


def test_unsafe_repair_diagnostics_block_before_agent_request(tmp_path, monkeypatch):
    run, provider = prepared_run(tmp_path, monkeypatch)
    write_json(run / "migration_result.json", {"attempt": 0, "dev_status": "FAIL", "diagnostics_ref": "unsafe.json"})
    write_json(run / "unsafe.json", {"contains_raw_rows": True, "contains_baseline_answers": False})
    with pytest.raises(ContractError):
        generate_candidate(__import__("pathlib").Path.cwd(), run, "security-test", 1)
    assert provider.calls == []


def test_read_asset_rejects_data_and_test_sources(tmp_path):
    with pytest.raises(ContractError):
        _read_repository_asset(tmp_path, "data/holdout.csv", {"legacy/credit_v1.R"})
    with pytest.raises(ContractError):
        _read_repository_asset(tmp_path, "tests/test_reference_parity.py", {"legacy/credit_v1.R"})
