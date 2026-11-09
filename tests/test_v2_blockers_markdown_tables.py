"""Release blocker 1 (this round): tables must be recognised by Markdown semantics.

The parser used to require a leading and trailing pipe, so a second table with the
same header rendered without outer pipes was invisible to the cell check: appending
a swapped hold-out row as "bare" Markdown passed. These tests pin GFM semantics.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src import cli
from src.acceptance_v2 import _v2_07
from src.common import read_json, sha256_file, write_json
from src.report import parse_markdown_tables, render_report, verify_report_cells

from v2_metrics import metrics_fixture

RUN_ID = "v2-md-tables"
REPOSITORY = Path(__file__).resolve().parents[1]
# A full table rendered without outer pipes: same header as the real performance
# table, with the hold-out ROC-AUC and Brier swapped.
BARE_HOLDOUT = (
    "dataset | rows | positives | negatives | ROC-AUC | Brier | AUC status",
    "--- | --- | --- | --- | --- | --- | ---",
    "holdout | 6000 | 1327 | 4673 | 0.1531 | 0.7044 | OK",
)


def strip_outer_pipes(line: str) -> str:
    """Render a row without outer pipes, keeping a leading empty cell possible.

    GFM needs the leading pipe when the first cell is empty, otherwise the row
    would lose that cell, so such rows keep their framing.
    """

    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return line
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    if cells and cells[0] == "":
        return stripped
    return " | ".join(cells)


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


def report_path(run: Path) -> Path:
    return run / "report" / "validation_report.md"


def refresh_manifest(run: Path) -> None:
    manifest = read_json(run / "report" / "review_manifest.json")
    manifest["report_sha256"] = sha256_file(report_path(run))
    write_json(run / "report" / "review_manifest.json", manifest)


def approve_gate_c(run: Path) -> int:
    return cli.main([
        "approve", "--run-id", RUN_ID, "--gate", "Gate_C",
        "--sha256", sha256_file(run / "report" / "review_manifest.json"),
        "--reviewer", "agent-delegated", "--comment", "delegated report review",
    ])


def test_parser_follows_markdown_semantics():
    with_pipes = "| a | b |\n| --- | --- |\n| 1 | 2 |"
    without_pipes = "a | b\n--- | ---\n1 | 2"
    aligned = "| a | b |\n|:---|---:|\n| 1 | 2 |"
    with_empty = "| a | b |\n| --- | --- |\n|  | 2 |"
    prose_with_pipe = "a | b\n1 | 2"

    assert parse_markdown_tables(with_pipes) == [{"header": ["a", "b"], "rows": [["1", "2"]]}]
    assert parse_markdown_tables(without_pipes) == [{"header": ["a", "b"], "rows": [["1", "2"]]}]
    assert parse_markdown_tables(aligned) == [{"header": ["a", "b"], "rows": [["1", "2"]]}]
    assert parse_markdown_tables(with_empty) == [{"header": ["a", "b"], "rows": [["", "2"]]}]
    # Without a delimiter row this is prose, not a table.
    assert parse_markdown_tables(prose_with_pipe) == []


def test_original_report_passes(cli_roots):
    run = cli_roots
    assert verify_report_cells(run) == []
    assert approve_gate_c(run) == 0
    assert cli.main(["approve-report", "--run-id", RUN_ID]) == 0
    verdict, actual = _v2_07(REPOSITORY, run, RUN_ID)
    assert verdict == "PASS", actual


def test_bare_pipe_table_with_swapped_holdout_values_is_rejected(cli_roots):
    run = cli_roots
    index_before = (run / "report" / "values_index.csv").read_bytes()
    original = report_path(run).read_text(encoding="utf-8")
    assert approve_gate_c(run) == 0

    # Keep the correct table and append a second full table with the same header,
    # no outer pipes, and the hold-out ROC-AUC/Brier swapped.
    appended = original.rstrip("\n") + "\n\n" + "\n".join(BARE_HOLDOUT) + "\n"
    report_path(run).write_text(appended, encoding="utf-8")
    assert (run / "report" / "values_index.csv").read_bytes() == index_before
    refresh_manifest(run)

    problems = verify_report_cells(run)
    assert any("appears 2 times" in problem for problem in problems), problems
    assert cli.main([
        "approve", "--run-id", RUN_ID, "--gate", "Gate_C",
        "--sha256", sha256_file(run / "report" / "review_manifest.json"),
        "--reviewer", "agent-delegated", "--comment", "attempt to approve a bare-pipe duplicate table",
    ]) == 2
    verdict, actual = _v2_07(REPOSITORY, run, RUN_ID)
    assert verdict == "FAIL"
    assert "appears 2 times" in actual


def test_bare_pipe_duplicate_is_detected_even_when_it_replaces_nothing(cli_roots):
    run = cli_roots
    original = report_path(run).read_text(encoding="utf-8")
    lines = original.splitlines()
    # Remove the pipe framing from the existing table and append the forged bare one.
    bare_lines = [strip_outer_pipes(line) for line in lines]
    report_path(run).write_text("\n".join(bare_lines) + "\n\n" + "\n".join(BARE_HOLDOUT) + "\n", encoding="utf-8")
    refresh_manifest(run)
    problems = verify_report_cells(run)
    assert problems, "a bare-pipe duplicate must not be ignored"
    assert any("appears 2 times" in problem or "does not match the metrics" in problem for problem in problems), problems


def test_report_rendered_without_outer_pipes_still_passes(cli_roots):
    run = cli_roots
    lines = [strip_outer_pipes(line) for line in report_path(run).read_text(encoding="utf-8").splitlines()]
    report_path(run).write_text("\n".join(lines) + "\n", encoding="utf-8")
    refresh_manifest(run)
    # Every value is unchanged, so a semantic check must still pass.
    assert verify_report_cells(run) == []
    assert approve_gate_c(run) == 0
