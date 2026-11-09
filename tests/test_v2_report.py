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

RUN_ID = "v2-report-test"


def _metric(value, status="OK", reason=None, **extra):
    return {"value": value, "status": status, "reason": reason, **extra}


def metrics_fixture() -> dict:
    deciles = [
        {
            "decile": index,
            "rows": 600,
            "mean_probability": 0.02 * index,
            "observed_default_rate": 0.01 * index,
            "min_probability": 0.001 * index,
            "max_probability": 0.3 * index,
            "absolute_gap": 0.01 * index,
        }
        for index in range(1, 11)
    ]
    return {
        "schema_version": "1",
        "run_id": RUN_ID,
        "model_id": "MDL_CREDIT_V1",
        "generated_at": "2026-11-10T00:00:00Z",
        "threshold": 0.35,
        "candidate_sha256": "a" * 64,
        "frozen_attempt": 0,
        "datasets": {
            "train": {"path": "data/train.csv", "sha256": "b" * 64, "rows": 15000},
            "dev": {"path": "data/dev.csv", "sha256": "c" * 64, "rows": 6000},
            "holdout": {"path": "data/holdout.csv", "sha256": "d" * 64, "rows": 6000},
            "shift_pool": {"path": "data/shift_pool.csv", "sha256": "e" * 64, "rows": 3000},
            "shifted": {"path": "data/shifted.csv", "sha256": "f" * 64, "rows": 2000},
        },
        "rules": {
            "min_group_rows": 30,
            "min_class_rows": 5,
            "psi_bins": 10,
            "psi_pseudocount": 0.5,
            "psi_attention": 0.1,
            "psi_review": 0.25,
            "max_abs_diff": 1e-08,
            "mean_abs_diff": 1e-10,
        },
        "parity": {
            "dev": {"status": "PASS", "rows": 6000, "max_abs_diff": 0.0, "mean_abs_diff": 0.0, "classification_mismatch_count": 0, "behaviour_mismatch_count": 0, "limits": {"max_abs_diff": 1e-08, "mean_abs_diff": 1e-10}},
            "holdout": {"status": "PASS", "rows": 6000, "max_abs_diff": 2.2e-16, "mean_abs_diff": 0.0, "classification_mismatch_count": 0, "behaviour_mismatch_count": 0, "limits": {"max_abs_diff": 1e-08, "mean_abs_diff": 1e-10}},
            "status": "PASS",
        },
        "performance": {
            "dev": {
                "rows": 6000,
                "positive_rows": 1327,
                "negative_rows": 4673,
                "observed_default_rate": 0.2212,
                "roc_auc": _metric(0.7123),
                "brier_score": _metric(0.1512),
                "confusion_matrix": _metric({"true_positive": 900, "false_positive": 1400, "true_negative": 3273, "false_negative": 427}),
                "calibration": _metric(deciles),
            },
            "holdout": {
                "rows": 6000,
                "positive_rows": 1327,
                "negative_rows": 4673,
                "observed_default_rate": 0.2212,
                "roc_auc": _metric(0.7044),
                "brier_score": _metric(0.1531),
                "confusion_matrix": _metric({"true_positive": 880, "false_positive": 1450, "true_negative": 3223, "false_negative": 447}),
                "calibration": _metric(deciles),
            },
            "shifted": {
                "rows": 2000,
                "positive_rows": 780,
                "negative_rows": 1220,
                "observed_default_rate": 0.39,
                "roc_auc": _metric(0.6801),
                "brier_score": _metric(0.2011),
                "confusion_matrix": _metric({"true_positive": 620, "false_positive": 500, "true_negative": 720, "false_negative": 160}),
                "calibration": _metric(deciles),
            },
        },
        "stability": {
            "status": "REVIEW_HIGHLIGHTED",
            "reference": "dev",
            "scenario": "A",
            "features": {
                "util_1": _metric(0.4212, bins=10, state="REVALIDATION_REQUIRED"),
                "limit_bal": _metric(0.1811, bins=10, state="REVIEW_HIGHLIGHTED"),
            },
            "prediction": _metric(0.2211, bins=10, state="REVIEW_HIGHLIGHTED"),
        },
        "fairness": {
            "status": "OK",
            "dataset": "holdout",
            "reference_groups": {"age_band": "26-35", "sex": "2"},
            "attributes": {
                "age_band": {
                    "status": "OK",
                    "reference_group": "26-35",
                    "groups": {
                        "26-35": {"rows": 2500, "positive_rows": 560, "negative_rows": 1940, "tpr": _metric(0.61), "fpr": _metric(0.21), "sample_status": "OK"},
                        "51+": {"rows": 700, "positive_rows": 140, "negative_rows": 560, "tpr": _metric(0.58), "fpr": _metric(0.24), "sample_status": "OK"},
                    },
                    "differences": {
                        "26-35": {"tpr": _metric(0.0), "fpr": _metric(0.0)},
                        "51+": {"tpr": _metric(-0.03), "fpr": _metric(0.03)},
                    },
                },
                "sex": {
                    "status": "OK",
                    "reference_group": "2",
                    "groups": {
                        "1": {"rows": 3000, "positive_rows": 660, "negative_rows": 2340, "tpr": _metric(0.6), "fpr": _metric(0.22), "sample_status": "OK"},
                        "2": {"rows": 3000, "positive_rows": 667, "negative_rows": 2333, "tpr": _metric(0.62), "fpr": _metric(0.21), "sample_status": "OK"},
                    },
                    "differences": {
                        "1": {"tpr": _metric(-0.02), "fpr": _metric(0.01)},
                        "2": {"tpr": _metric(0.0), "fpr": _metric(0.0)},
                    },
                },
            },
        },
    }


def prepared_run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    write_json(run / "run_manifest.json", {"run_id": RUN_ID})
    write_json(run / "context_manifest.json", {"run_id": RUN_ID, "assets": []})
    write_json(run / "review_log.json", {"schema_version": "1", "run_id": RUN_ID, "reviews": []})
    write_json(run / "validation_metrics.json", metrics_fixture())
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
    assert any("modified" in reason for reason in status["reasons"])


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
