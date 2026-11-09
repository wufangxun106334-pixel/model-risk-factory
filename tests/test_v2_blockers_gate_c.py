"""Release blocker 2: Gate C must work through the real CLI on one artifact path.

The v2 release had to fake `report/report_review.json` because `approve --gate
Gate_C` and `report_status` disagreed about the reviewed artifact. These tests
drive the actual CLI entry point and assert the unified path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src import cli
from src.common import read_json, sha256_file, write_json
from src.report import report_status

from v2_metrics import metrics_fixture

RUN_ID = "v2-gate-c-cli"


def build_run(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    runs = repo / "runs"
    run = runs / RUN_ID
    run.mkdir(parents=True)
    write_json(run / "run_manifest.json", {"run_id": RUN_ID})
    write_json(run / "context_manifest.json", {"run_id": RUN_ID, "assets": []})
    write_json(run / "review_log.json", {"schema_version": "1", "run_id": RUN_ID, "reviews": []})
    write_json(run / "validation_metrics.json", metrics_fixture(RUN_ID))
    write_json(run / "report" / "agent_summary.json", {
        "schema_version": "1",
        "run_id": RUN_ID,
        "headline": "The migrated scorecard reproduces the reference probabilities.",
        "results": ["Hold-out discrimination is stable."],
        "limitations": ["The drift batch is a sensitivity analysis."],
        "evidence_gaps": ["No cross-time back-test exists."],
        "request_id": "req-summary",
        "request_event_id": "event-summary",
        "model": "deepseek-v4.1-flash:1017",
    })
    for model_id, relative in (("MDL_CREDIT_V1", "model_inventory.json"), ("MDL_CREDIT_V2", "inventories/MDL_CREDIT_V2.json"), ("MDL_CREDIT_TREE", "inventories/MDL_CREDIT_TREE.json")):
        write_json(run / relative, {"run_id": RUN_ID, "model_id": model_id, "review_status": "PENDING", "sources": []})
    return repo, run


@pytest.fixture(autouse=True)
def cli_roots(tmp_path, monkeypatch):
    repo, run = build_run(tmp_path)
    monkeypatch.setattr(cli, "RUNS_ROOT", run.parent)
    monkeypatch.setattr(cli, "REPOSITORY", Path(__file__).resolve().parents[1])
    return repo, run


def test_report_approve_and_status_use_the_review_manifest(cli_roots):
    repo, run = cli_roots
    assert cli.main(["report", "--run-id", RUN_ID]) == 0
    manifest = run / "report" / "review_manifest.json"
    assert manifest.is_file()
    assert not (run / "report" / "report_review.json").exists()
    recorded = read_json(manifest)
    bound = {
        "report_sha256": "report/validation_report.md",
        "metrics_sha256": "validation_metrics.json",
        "values_index_sha256": "report/values_index.csv",
        "tables_sha256": "report/validation_tables.md",
        "agent_summary_sha256": "report/agent_summary.json",
    }
    for key, relative in bound.items():
        assert recorded[key] == sha256_file(run / relative), key

    digest = sha256_file(manifest)
    assert cli.main([
        "approve", "--run-id", RUN_ID, "--gate", "Gate_C", "--sha256", digest,
        "--reviewer", "agent-delegated", "--comment", "delegated review of report and metrics evidence",
    ]) == 0
    assert cli.main(["approve-report", "--run-id", RUN_ID]) == 0
    approval = read_json(run / "report" / "approval.json")
    assert approval["status"] == "APPROVED"
    assert approval["report_sha256"] == recorded["report_sha256"]
    assert approval["metrics_sha256"] == recorded["metrics_sha256"]
    assert report_status(run, RUN_ID)["status"] == "APPROVED"
    assert cli.main(["report-status", "--run-id", RUN_ID]) == 0


def test_approve_report_is_refused_until_gate_c_is_recorded(cli_roots):
    repo, run = cli_roots
    assert cli.main(["report", "--run-id", RUN_ID]) == 0
    status = report_status(run, RUN_ID)
    assert status["gate_c"] == "NOT_REVIEWED"
    assert cli.main(["approve-report", "--run-id", RUN_ID]) == 2
    assert not (run / "report" / "approval.json").exists()


def test_tampered_or_missing_bound_files_drop_the_report_to_draft(cli_roots):
    repo, run = cli_roots
    assert cli.main(["report", "--run-id", RUN_ID]) == 0
    manifest = run / "report" / "review_manifest.json"
    assert cli.main([
        "approve", "--run-id", RUN_ID, "--gate", "Gate_C", "--sha256", sha256_file(manifest),
        "--reviewer", "agent-delegated", "--comment", "delegated review",
    ]) == 0
    assert cli.main(["approve-report", "--run-id", RUN_ID]) == 0

    metrics = read_json(run / "validation_metrics.json")
    metrics["threshold"] = 0.99
    write_json(run / "validation_metrics.json", metrics)
    status = report_status(run, RUN_ID)
    assert status["status"] == "DRAFT"
    assert any("metrics changed" in reason for reason in status["reasons"])
    assert cli.main(["approve-report", "--run-id", RUN_ID]) == 2

    # Restore the metrics, then remove a different bound file.
    write_json(run / "validation_metrics.json", metrics_fixture(RUN_ID))
    (run / "report" / "validation_tables.md").unlink()
    status = report_status(run, RUN_ID)
    assert status["status"] == "DRAFT"
    assert any("tables missing" in reason for reason in status["reasons"])


def test_missing_agent_summary_is_reported_as_draft(cli_roots):
    repo, run = cli_roots
    assert cli.main(["report", "--run-id", RUN_ID]) == 0
    manifest = run / "report" / "review_manifest.json"
    assert cli.main([
        "approve", "--run-id", RUN_ID, "--gate", "Gate_C", "--sha256", sha256_file(manifest),
        "--reviewer", "agent-delegated", "--comment", "delegated review",
    ]) == 0
    assert cli.main(["approve-report", "--run-id", RUN_ID]) == 0
    (run / "report" / "agent_summary.json").unlink()
    status = report_status(run, RUN_ID)
    assert status["status"] == "DRAFT"
    assert any("agent summary missing" in reason for reason in status["reasons"])
