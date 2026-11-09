"""Release blocker 1 (this round): table and row identity must be unique.

A dict keyed by the first cell silently kept the last occurrence, so "wrong hold-out
row first, correct row last" passed every check. These tests pin the uniqueness rule
and the exact copy the reviewer described.
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

RUN_ID = "v2-cells-unique"
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


def report_lines(run: Path) -> list[str]:
    return (run / "report" / "validation_report.md").read_text(encoding="utf-8").splitlines()


def write_report(run: Path, lines: list[str]) -> None:
    (run / "report" / "validation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def table_block(lines: list[str], first_header: str) -> tuple[int, int]:
    """Return (start, end) line indexes of the table whose first header cell matches."""

    for index, line in enumerate(lines):
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if line.strip().startswith("|") and cells and cells[0] == first_header:
            start = index
            end = index
            while end + 1 < len(lines) and lines[end + 1].strip().startswith("|"):
                end += 1
            return start, end
    raise AssertionError(f"table {first_header!r} not found")


def refresh_manifest(run: Path) -> None:
    manifest = read_json(run / "report" / "review_manifest.json")
    manifest["report_sha256"] = sha256_file(run / "report" / "validation_report.md")
    write_json(run / "report" / "review_manifest.json", manifest)


def approve_gate_c(run: Path) -> int:
    return cli.main([
        "approve", "--run-id", RUN_ID, "--gate", "Gate_C",
        "--sha256", sha256_file(run / "report" / "review_manifest.json"),
        "--reviewer", "agent-delegated", "--comment", "delegated report review",
    ])


def test_untampered_report_passes_gate_c_and_v2_07(cli_roots):
    run = cli_roots
    assert verify_report_cells(run) == []
    assert approve_gate_c(run) == 0
    assert cli.main(["approve-report", "--run-id", RUN_ID]) == 0
    verdict, actual = _v2_07(REPOSITORY, run, RUN_ID)
    assert verdict == "PASS", actual


def test_wrong_holdout_row_before_the_correct_one_is_rejected(cli_roots):
    run = cli_roots
    index_before = (run / "report" / "values_index.csv").read_bytes()
    assert approve_gate_c(run) == 0

    lines = report_lines(run)
    start, end = table_block(lines, "dataset")
    rows = [line for line in lines[start + 1 : end + 1] if not set(line.replace("|", "").strip()) <= {"-"}]
    holdout = next(line for line in rows if line.strip().startswith("| holdout |"))
    forged = "| holdout | 6000 | 1327 | 4673 | 0.9999 | 0.0001 | OK |"
    lines.insert(lines.index(holdout), forged)  # wrong row first, correct row after
    write_report(run, lines)
    assert (run / "report" / "values_index.csv").read_bytes() == index_before
    refresh_manifest(run)

    problems = verify_report_cells(run)
    assert any("duplicate row labels" in problem and "holdout" in problem for problem in problems), problems
    assert cli.main([
        "approve", "--run-id", RUN_ID, "--gate", "Gate_C",
        "--sha256", sha256_file(run / "report" / "review_manifest.json"),
        "--reviewer", "agent-delegated", "--comment", "attempt to approve a duplicated row",
    ]) == 2
    verdict, actual = _v2_07(REPOSITORY, run, RUN_ID)
    assert verdict == "FAIL"
    assert "duplicate row labels" in actual
    assert report_status(run, RUN_ID)["status"] == "DRAFT"


def test_duplicate_table_is_rejected(cli_roots):
    run = cli_roots
    lines = report_lines(run)
    start, end = table_block(lines, "signal")
    # A blank line keeps the copy a separate table instead of merging the rows.
    lines[end + 1 : end + 1] = [""] + lines[start : end + 1]
    write_report(run, lines)
    refresh_manifest(run)
    problems = verify_report_cells(run)
    assert any("appears 2 times" in problem for problem in problems), problems


def test_duplicate_calibration_row_is_rejected(cli_roots):
    run = cli_roots
    lines = report_lines(run)
    start, end = table_block(lines, "decile")
    lines.insert(end + 1, "| 1 | 600 | 0.0200 | 0.0100 | 0.0100 |")
    write_report(run, lines)
    refresh_manifest(run)
    problems = verify_report_cells(run)
    assert any("duplicate row labels" in problem and "decile" in problem for problem in problems), problems


def test_duplicate_psi_row_is_rejected(cli_roots):
    run = cli_roots
    lines = report_lines(run)
    start, end = table_block(lines, "signal")
    lines.insert(end + 1, "| util_1 | 0.9999 | OK |")
    write_report(run, lines)
    refresh_manifest(run)
    problems = verify_report_cells(run)
    assert any("duplicate row labels" in problem and "util_1" in problem for problem in problems), problems


def test_fairness_rows_are_keyed_by_attribute_and_group(cli_roots):
    run = cli_roots
    lines = report_lines(run)
    start, end = table_block(lines, "attribute")
    # The legitimate table repeats the attribute column but each (attribute, group)
    # pair is unique, so it must pass.
    assert verify_report_cells(run) == []
    # Duplicating one (attribute, group) pair must fail.
    lines.insert(end + 1, "| age_band | 26-35 | 2500 | 560 | 0.6100 | OK | 0.2100 | OK |")
    write_report(run, lines)
    refresh_manifest(run)
    problems = verify_report_cells(run)
    assert any("duplicate row labels" in problem and "age_band/26-35" in problem for problem in problems), problems
