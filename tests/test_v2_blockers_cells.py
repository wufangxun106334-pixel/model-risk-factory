"""Release blocker 2 (this round): a report cell must be bound to its own metrics path.

The previous check only asked whether a number appears somewhere in the index, so
swapping two cells in the Markdown kept every index row valid. These tests require
the report to be re-derived from validation_metrics.json and compared cell by cell.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src import cli
from src.acceptance_v2 import _v2_07
from src.common import read_json, sha256_file, write_json
from src.report import render_report, report_status, verify_report_cells

from v2_metrics import metrics_fixture

RUN_ID = "v2-cells"
REPOSITORY = Path(__file__).resolve().parents[1]


def build_run(tmp_path: Path) -> Path:
    run = tmp_path / "repo" / "runs" / RUN_ID
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
    for model_id, relative in (
        ("MDL_CREDIT_V1", "model_inventory.json"),
        ("MDL_CREDIT_V2", "inventories/MDL_CREDIT_V2.json"),
        ("MDL_CREDIT_TREE", "inventories/MDL_CREDIT_TREE.json"),
    ):
        write_json(run / relative, {"run_id": RUN_ID, "model_id": model_id, "review_status": "APPROVED", "sources": []})
    render_report(run, RUN_ID, agent_summary=read_json(run / "report" / "agent_summary.json"), inventories={"MDL_CREDIT_V1": "APPROVED"})
    return run


@pytest.fixture(autouse=True)
def cli_roots(tmp_path, monkeypatch):
    run = build_run(tmp_path)
    monkeypatch.setattr(cli, "RUNS_ROOT", run.parent)
    monkeypatch.setattr(cli, "REPOSITORY", REPOSITORY)
    return run


def approve_gate_c(run: Path) -> int:
    return cli.main([
        "approve", "--run-id", RUN_ID, "--gate", "Gate_C",
        "--sha256", sha256_file(run / "report" / "review_manifest.json"),
        "--reviewer", "agent-delegated", "--comment", "delegated report review",
    ])


def rewrite_cell(run: Path, row_label: str, column_index: int, value: str, *, swap_with: int | None = None) -> None:
    """Edit one table cell (or swap two cells) inside the rendered Markdown."""

    path = run / "report" / "validation_report.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells or cells[0] != row_label:
            continue
        if swap_with is None:
            cells[column_index] = value
        else:
            cells[column_index], cells[swap_with] = cells[swap_with], cells[column_index]
        lines[index] = "| " + " | ".join(cells) + " |"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return
    raise AssertionError(f"row {row_label!r} not found in the report")


def refresh_manifest(run: Path) -> None:
    manifest = read_json(run / "report" / "review_manifest.json")
    manifest["report_sha256"] = sha256_file(run / "report" / "validation_report.md")
    write_json(run / "report" / "review_manifest.json", manifest)


def test_untampered_report_cells_match_the_metrics(cli_roots):
    run = cli_roots
    assert verify_report_cells(run) == []
    assert approve_gate_c(run) == 0
    assert cli.main(["approve-report", "--run-id", RUN_ID]) == 0
    assert report_status(run, RUN_ID)["status"] == "APPROVED"


def test_swapping_holdout_auc_and_brier_is_rejected_even_with_a_recomputed_manifest_hash(cli_roots):
    run = cli_roots
    assert approve_gate_c(run) == 0
    index_before = (run / "report" / "values_index.csv").read_bytes()
    index_rows_before = list(csv.DictReader((run / "report" / "values_index.csv").open()))

    # Swap the hold-out ROC-AUC and Brier cells: columns 4 and 5 of the performance table.
    rewrite_cell(run, "holdout", 4, "", swap_with=5)
    assert (run / "report" / "values_index.csv").read_bytes() == index_before
    assert list(csv.DictReader((run / "report" / "values_index.csv").open())) == index_rows_before
    refresh_manifest(run)

    problems = verify_report_cells(run)
    assert any("ROC-AUC" in problem or "Brier" in problem for problem in problems), problems
    assert cli.main([
        "approve", "--run-id", RUN_ID, "--gate", "Gate_C",
        "--sha256", sha256_file(run / "report" / "review_manifest.json"),
        "--reviewer", "agent-delegated", "--comment", "attempted approval of a tampered table",
    ]) == 2
    status = report_status(run, RUN_ID)
    assert status["status"] == "DRAFT"
    assert any("cell mismatch" in reason for reason in status["reasons"]), status
    verdict, actual = _v2_07(REPOSITORY, run, RUN_ID)
    assert verdict == "FAIL"
    assert "table" in actual


def test_editing_a_single_cell_is_rejected(cli_roots):
    run = cli_roots
    rewrite_cell(run, "holdout", 4, "0.9999")
    refresh_manifest(run)
    problems = verify_report_cells(run)
    assert any("0.9999" in problem for problem in problems), problems


def test_renaming_a_row_label_is_rejected(cli_roots):
    run = cli_roots
    rewrite_cell(run, "holdout", 0, "holdout-renamed")
    refresh_manifest(run)
    problems = verify_report_cells(run)
    assert any("holdout-renamed" in problem or "row" in problem for problem in problems), problems


def test_dropping_a_table_is_rejected(cli_roots):
    run = cli_roots
    path = run / "report" / "validation_report.md"
    text = path.read_text(encoding="utf-8")
    start = text.index("| signal | PSI | state |")
    end = text.index("## Fairness audit", start)
    path.write_text(text[:start] + text[end:], encoding="utf-8")
    refresh_manifest(run)
    problems = verify_report_cells(run)
    assert any("not found in the report" in problem for problem in problems), problems
