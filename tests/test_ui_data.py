"""The Streamlit shell only reads runs and builds CLI arguments; these checks cover that layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import ui_data
from src.cli import _parser


def _run(root: Path, run_id: str, created_at: str, **extra) -> Path:
    directory = root / run_id
    directory.mkdir(parents=True)
    manifest = {"run_id": run_id, "mode": "synthetic", "created_at": created_at, "git_commit_at_init": "a" * 40, **extra}
    (directory / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return directory


def test_list_runs_is_newest_first_and_skips_non_runs(tmp_path):
    _run(tmp_path, "v2-old", "2026-11-09T10:00:00Z")
    newest = _run(tmp_path, "v2-new", "2026-11-10T10:00:00Z", worktree_clean_at_init=True)
    (newest / "acceptance.json").write_text(json.dumps({"release_approved": True, "records": []}), encoding="utf-8")
    (tmp_path / "not-a-run").mkdir()
    (tmp_path / "stray.txt").write_text("x", encoding="utf-8")

    rows = ui_data.list_runs(tmp_path)
    assert [row["run_id"] for row in rows] == ["v2-new", "v2-old"]
    assert rows[0]["release_approved"] is True
    assert rows[0]["worktree_clean_at_init"] is True
    assert rows[1]["release_approved"] is None
    assert rows[0]["git_commit_at_init"] == "a" * 12
    assert ui_data.list_runs(tmp_path / "missing") == []


def test_empty_run_reports_every_stage_as_not_run(tmp_path):
    run_dir = _run(tmp_path, "v2-empty", "2026-11-10T10:00:00Z")
    models = ui_data.model_rows(run_dir, "v2-empty")
    assert [row["model_id"] for row in models] == list(ui_data.MODEL_IDS)
    assert all(row["gate_a"] == "NOT_RUN" and row["exists"] is False for row in models)
    assert [row["migrated"] for row in models] == [True, False, False]
    assert ui_data.candidate_rows(run_dir, "v2-empty") == []
    assert ui_data.gate_c_state(run_dir, "v2-empty") == {"exists": False, "decision": "NOT_RUN"}
    assert ui_data.acceptance_records(run_dir) == (None, [])
    assert ui_data.downloads(run_dir, "v2-empty") == []


def test_approve_args_are_accepted_by_the_cli_parser():
    args = ui_data.approve_args("run-1", "Gate_A", "b" * 64, " alex ", "checked sources", model="MDL_CREDIT_V2")
    parsed = _parser().parse_args(args)
    assert (parsed.command, parsed.gate, parsed.model, parsed.reviewer, parsed.decision) == (
        "approve", "Gate_A", "MDL_CREDIT_V2", "alex", "APPROVED")
    parsed = _parser().parse_args(ui_data.approve_args("run-1", "Gate_B", "c" * 64, "agent-delegated", "", "REJECTED", attempt=1))
    assert (parsed.attempt, parsed.decision) == (1, "REJECTED")


@pytest.mark.parametrize("change", [
    {"gate": "Gate_D"},
    {"sha256": "abc"},
    {"reviewer": "   "},
    {"decision": "MAYBE"},
])
def test_approve_args_reject_incomplete_reviews(change):
    values = {"run_id": "run-1", "gate": "Gate_C", "sha256": "d" * 64, "reviewer": "alex", "comment": "", "decision": "APPROVED", **change}
    with pytest.raises(ValueError):
        ui_data.approve_args(**values)


def test_runs_root_only_allows_the_two_known_roots():
    assert ui_data.runs_root("runs").name == "runs"
    assert ui_data.runs_root("dev_runs").name == "dev_runs"
    with pytest.raises(ValueError):
        ui_data.runs_root("../elsewhere")


def test_run_cli_uses_the_selected_runs_root(tmp_path):
    result = ui_data.run_cli(["status", "--run-id", "does-not-exist"], tmp_path, timeout=120)
    assert result["returncode"] != 0
    assert result["command"][:3] == ["python", "-m", "src.cli"]
    assert not any(tmp_path.iterdir())


def test_chart_rows_follow_the_metrics_json():
    from v2_metrics import metrics_fixture

    metrics = metrics_fixture()
    performance = ui_data.performance_rows(metrics)
    assert [row["dataset"] for row in performance] == ["dev", "holdout", "shifted"]
    assert performance[1]["roc_auc"] == 0.7044 and performance[1]["brier_score"] == 0.1531
    calibration = ui_data.calibration_rows(metrics)
    assert len(calibration) == 30 and {row["dataset"] for row in calibration} == {"dev", "holdout", "shifted"}
    confusion = {row["cell"]: row["count"] for row in ui_data.confusion_rows(metrics, "holdout")}
    assert confusion == {"true_positive": 880, "false_negative": 447, "false_positive": 1450, "true_negative": 3223}
    psi = {row["name"]: (row["psi"], row["state"]) for row in ui_data.psi_rows(metrics)}
    assert psi["util_1"] == (0.4212, "REVALIDATION_REQUIRED")
    assert psi["prediction (probability)"] == (0.2211, "REVIEW_HIGHLIGHTED")
    assert ui_data.psi_thresholds(metrics) == {"attention": 0.1, "review": 0.25}
    fairness = ui_data.fairness_rows(metrics)
    assert len(fairness) == 8
    reference = [row for row in fairness if row["reference"]]
    assert {(row["attribute"], row["group"]) for row in reference} == {("age_band", "26-35"), ("sex", "2")}


def test_chart_rows_tolerate_missing_blocks():
    assert ui_data.performance_rows({}) == []
    assert ui_data.calibration_rows({"performance": {"dev": {"calibration": {"value": None}}}}) == []
    assert ui_data.confusion_rows({}) == []
    assert ui_data.psi_rows({}) == []
    assert ui_data.fairness_rows({}) == []


def test_parity_frame_joins_r_and_python_predictions(tmp_path):
    run_dir = tmp_path / "run"
    (run_dir / "reference").mkdir(parents=True)
    (run_dir / "dev" / "attempt_001" / "output").mkdir(parents=True)
    header = "client_id,probability,classification,status,error_code\n"
    (run_dir / "reference" / "dev_predictions.csv").write_text(header + "1,0.25,0,VALID,\n2,0.5,1,VALID,\n", encoding="utf-8")
    (run_dir / "dev" / "attempt_001" / "output" / "predictions.csv").write_text(header + "2,0.5,1,VALID,\n1,0.2500001,0,VALID,\n", encoding="utf-8")
    frame = ui_data.parity_frame(run_dir, "dev", 1).set_index("client_id")
    assert frame.loc["1", "abs_diff"] == pytest.approx(1e-7)
    assert frame.loc["2", "abs_diff"] == 0
    assert frame["class_match"].all()
    assert ui_data.parity_frame(run_dir, "holdout") is None
    assert ui_data.parity_summary(run_dir, "dev", 1) is None
    with pytest.raises(ValueError):
        ui_data.parity_paths(run_dir, "dev")
