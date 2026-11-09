from __future__ import annotations

from pathlib import Path

import pytest

from src.common import ContractError, GateError, read_json, sha256_file, write_json
from src.report import (
    render_report,
    report_status,
    verify_provenance,
    write_approval,
)
from src.review import artifact_digest, record_review

from v2_metrics import metrics_fixture

RUN_ID = "v2-report-test"


def _metric(value, status="OK", reason=None, **extra):
    return {"value": value, "status": status, "reason": reason, **extra}


def prepared_run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
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
    return run


def test_every_reported_number_resolves_to_a_metrics_path(tmp_path):
    run = prepared_run(tmp_path)
    rendered = render_report(run, RUN_ID, agent_summary=read_json(run / "report" / "agent_summary.json"), inventories={"MDL_CREDIT_V1": "APPROVED"})
    assert rendered["unresolved_numbers"] == []
    assert rendered["value_count"] > 30
    text = (run / "report" / "validation_report.md").read_text()
    assert "0.7044" in text
    index = (run / "report" / "values_index.csv").read_text()
    assert "performance.holdout.roc_auc.value" in index
    manifest = read_json(run / "report" / "review_manifest.json")
    assert manifest["report_sha256"] == sha256_file(run / "report" / "validation_report.md")
    assert manifest["metrics_sha256"] == sha256_file(run / "validation_metrics.json")


def test_a_number_without_a_path_is_detected(tmp_path):
    run = prepared_run(tmp_path)
    render_report(run, RUN_ID, agent_summary=None, inventories={})
    report_path = run / "report" / "validation_report.md"
    report_path.write_text(report_path.read_text() + "\nInjected figure: 0.9876\n", encoding="utf-8")
    status = report_status(run, RUN_ID)
    assert status["status"] == "DRAFT"
    assert any("report" in reason and ("modified" in reason or "changed" in reason) for reason in status["reasons"])


def test_report_cannot_be_approved_before_gate_c(tmp_path):
    run = prepared_run(tmp_path)
    render_report(run, RUN_ID, agent_summary=None, inventories={})
    status = report_status(run, RUN_ID)
    assert status["status"] == "DRAFT"
    assert "Gate_C=NOT_REVIEWED" in status["reasons"]
    with pytest.raises(GateError):
        write_approval(run, RUN_ID)

    manifest = run / "report" / "review_manifest.json"
    digest = artifact_digest(manifest, "Gate_C")
    record_review(run, RUN_ID, "Gate_C", manifest, digest, "APPROVED", "agent-delegated", "delegated review of report and metrics evidence")
    assert report_status(run, RUN_ID)["status"] == "DRAFT"
    approval = write_approval(run, RUN_ID)
    assert approval["status"] == "APPROVED"
    assert report_status(run, RUN_ID)["status"] == "APPROVED"


def test_changing_the_metrics_after_render_invalidates_the_approval(tmp_path):
    run = prepared_run(tmp_path)
    render_report(run, RUN_ID, agent_summary=None, inventories={})
    manifest = run / "report" / "review_manifest.json"
    record_review(run, RUN_ID, "Gate_C", manifest, artifact_digest(manifest, "Gate_C"), "APPROVED", "agent-delegated", "delegated review")
    write_approval(run, RUN_ID)
    assert report_status(run, RUN_ID)["status"] == "APPROVED"

    metrics = read_json(run / "validation_metrics.json")
    metrics["performance"]["holdout"]["roc_auc"]["value"] = 0.99
    write_json(run / "validation_metrics.json", metrics)
    status = report_status(run, RUN_ID)
    assert status["status"] == "DRAFT"
    assert any("metrics changed" in reason for reason in status["reasons"])


def test_compliance_wording_is_rejected_before_rendering(tmp_path):
    run = prepared_run(tmp_path)
    summary = read_json(run / "report" / "agent_summary.json")
    summary["limitations"] = ["The model is regulatory compliant."]
    write_json(run / "report" / "agent_summary.json", summary)
    with pytest.raises(ContractError):
        render_report(run, RUN_ID, agent_summary=summary, inventories={})


def test_provenance_helper_ignores_identifiers_but_flags_bare_numbers():
    index = [{"json_path": "a.b", "text": "0.5"}]
    assert verify_provenance("value 0.5 and MDL_CREDIT_V1", index) == []
    assert verify_provenance("value 0.5 and 42", index) == ["42"]
