"""Release blocker (this round): table bodies must be read the way GFM renders them.

The parser stopped reading a table body at the first row whose cell count differed
from the header. GitHub Flavored Markdown renders such a row anyway: a short row is
padded with empty cells and the excess cells of a wide row are dropped. Appending a
wide row with the hold-out ROC-AUC and Brier swapped therefore rendered a second,
contradictory hold-out row that the cell check never saw. These tests drive the
normal CLI path (approve --gate Gate_C, approve-report, report-status, V2-07) and
cover the other body shapes a renderer still shows.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import cli
from src.acceptance_v2 import _v2_07
from src.common import read_json, sha256_file, write_json
from src.report import parse_markdown_tables, verify_report_cells

from test_v2_blockers_markdown_tables import REPOSITORY, RUN_ID, build_run, refresh_manifest, report_path

PERFORMANCE_HEADER = "| dataset | rows | positives | negatives | ROC-AUC | Brier | AUC status |"
CORRECT_HOLDOUT = "| holdout | 6000 | 1327 | 4673 | 0.7044 | 0.1531 | OK |"
# Hold-out ROC-AUC and Brier swapped, plus one extra cell GFM silently drops.
SWAPPED_WIDE_HOLDOUT = "| holdout | 6000 | 1327 | 4673 | 0.1531 | 0.7044 | OK | reviewed |"


@pytest.fixture(autouse=True)
def run(tmp_path, monkeypatch):
    built = build_run(tmp_path)
    monkeypatch.setattr(cli, "RUNS_ROOT", built.parent)
    monkeypatch.setattr(cli, "REPOSITORY", REPOSITORY)
    return built


def performance_body_end(lines: list[str]) -> int:
    start = lines.index(PERFORMANCE_HEADER)
    end = start + 2
    while end < len(lines) and lines[end].strip():
        end += 1
    return end


def insert_after_performance_body(run: Path, *new_lines: str) -> None:
    lines = report_path(run).read_text(encoding="utf-8").splitlines()
    assert CORRECT_HOLDOUT in lines
    end = performance_body_end(lines)
    lines[end:end] = list(new_lines)
    report_path(run).write_text("\n".join(lines) + "\n", encoding="utf-8")
    refresh_manifest(run)


def manifest_sha(run: Path) -> str:
    return sha256_file(run / "report" / "review_manifest.json")


def cli_json(capsys, arguments: list[str]) -> tuple[int, dict]:
    capsys.readouterr()
    code = cli.main(arguments)
    output = capsys.readouterr().out.strip()
    return code, json.loads(output) if output.startswith("{") else {}


def assert_rejected_by_every_gate(run: Path, capsys, expected: str) -> None:
    problems = verify_report_cells(run)
    assert any(expected in problem for problem in problems), problems
    code = cli.main([
        "approve", "--run-id", RUN_ID, "--gate", "Gate_C", "--sha256", manifest_sha(run),
        "--reviewer", "agent-delegated", "--comment", "attempt to approve a forged report",
    ])
    assert code == 2
    assert cli.main(["approve-report", "--run-id", RUN_ID]) == 2
    assert not (run / "report" / "approval.json").exists()
    _code, status = cli_json(capsys, ["report-status", "--run-id", RUN_ID])
    assert status.get("status") == "DRAFT", status
    verdict, actual = _v2_07(REPOSITORY, run, RUN_ID)
    assert verdict == "FAIL"
    assert expected in actual


def test_parser_pads_short_rows_and_drops_excess_cells():
    text = "\n".join([
        "| a | b | c |",
        "| --- | --- | --- |",
        "| 1 | 2 | 3 |",
        "| 4 | 5 |",
        "| 6 | 7 | 8 | 9 |",
        "10",
        "| --- | --- | --- |",
        "",
        "after",
    ])
    assert parse_markdown_tables(text) == [{
        "header": ["a", "b", "c"],
        "rows": [["1", "2", "3"], ["4", "5", ""], ["6", "7", "8"], ["10", "", ""], ["---", "---", "---"]],
    }]


def test_parser_honours_escaped_pipes_and_block_terminators():
    escaped = "| a | b |\n| --- | --- |\n| x \\| y | z |"
    assert parse_markdown_tables(escaped) == [{"header": ["a", "b"], "rows": [["x | y", "z"]]}]
    for terminator in ("## next", "```", "***", "---"):
        text = f"| a | b |\n| --- | --- |\n| 1 | 2 |\n{terminator}\n| 3 | 4 |"
        assert parse_markdown_tables(text) == [{"header": ["a", "b"], "rows": [["1", "2"]]}], terminator


def test_parser_sees_tables_nested_in_containers():
    quoted = "> | a | b |\n> | --- | --- |\n> | 1 | 2 |"
    listed = "- | a | b |\n  | --- | --- |\n  | 1 | 2 |"
    assert parse_markdown_tables(quoted) == [{"header": ["a", "b"], "rows": [["1", "2"]]}]
    assert parse_markdown_tables(listed) == [{"header": ["a", "b"], "rows": [["1", "2"]]}]


def test_wide_swapped_holdout_row_is_rejected_through_the_cli(run, capsys):
    """The reported counterexample: keep the correct table, append a wide swapped row."""

    index_before = (run / "report" / "values_index.csv").read_bytes()
    insert_after_performance_body(run, SWAPPED_WIDE_HOLDOUT)
    assert (run / "report" / "values_index.csv").read_bytes() == index_before
    assert_rejected_by_every_gate(run, capsys, "duplicate row labels ['holdout']")


def test_wide_swapped_row_after_an_approved_report_drops_it_to_draft(run, capsys):
    code = cli.main([
        "approve", "--run-id", RUN_ID, "--gate", "Gate_C", "--sha256", manifest_sha(run),
        "--reviewer", "agent-delegated", "--comment", "delegated review of the original report",
    ])
    assert code == 0
    assert cli.main(["approve-report", "--run-id", RUN_ID]) == 0
    insert_after_performance_body(run, SWAPPED_WIDE_HOLDOUT)
    _code, status = cli_json(capsys, ["report-status", "--run-id", RUN_ID])
    assert status["status"] == "DRAFT"
    assert any("duplicate row labels ['holdout']" in reason for reason in status["reasons"]), status
    assert cli.main(["approve-report", "--run-id", RUN_ID]) == 2
    verdict, _actual = _v2_07(REPOSITORY, run, RUN_ID)
    assert verdict == "FAIL"


@pytest.mark.parametrize("forged", [
    "| holdout | 6000 | 1327 | 4673 | 0.1531 |",
    "holdout | 6000 | 1327 | 4673 | 0.1531 | 0.7044 | OK | x | y",
    "| holdout \\| 6000 | 1327 | 4673 | 0.1531 | 0.7044 | OK |",
    "holdout",
])
def test_other_rendered_extra_rows_are_rejected(run, capsys, forged):
    insert_after_performance_body(run, forged)
    problems = verify_report_cells(run)
    assert problems, forged
    assert any("holdout" in problem for problem in problems), problems
    assert cli.main([
        "approve", "--run-id", RUN_ID, "--gate", "Gate_C", "--sha256", manifest_sha(run),
        "--reviewer", "agent-delegated", "--comment", "attempt to approve a forged report",
    ]) == 2
    assert _v2_07(REPOSITORY, run, RUN_ID)[0] == "FAIL"


def test_replacing_the_holdout_row_with_a_wide_swapped_row_is_a_cell_mismatch(run, capsys):
    text = report_path(run).read_text(encoding="utf-8").replace(CORRECT_HOLDOUT, SWAPPED_WIDE_HOLDOUT)
    report_path(run).write_text(text, encoding="utf-8")
    refresh_manifest(run)
    assert_rejected_by_every_gate(run, capsys, "row 'holdout' column 'ROC-AUC'")


def test_duplicate_table_hidden_in_a_block_quote_is_counted(run, capsys):
    lines = report_path(run).read_text(encoding="utf-8").splitlines()
    end = performance_body_end(lines)
    quoted = [
        "",
        "> " + PERFORMANCE_HEADER,
        "> | --- | --- | --- | --- | --- | --- | --- |",
        "> | holdout | 6000 | 1327 | 4673 | 0.1531 | 0.7044 | OK |",
    ]
    lines[end:end] = quoted
    report_path(run).write_text("\n".join(lines) + "\n", encoding="utf-8")
    refresh_manifest(run)
    assert_rejected_by_every_gate(run, capsys, "appears 2 times")


def test_duplicate_table_with_emphasised_header_is_rejected(run, capsys):
    path = report_path(run)
    original = path.read_text(encoding="utf-8")
    header = PERFORMANCE_HEADER.replace("ROC-AUC", "**ROC-AUC**")
    delimiter = "| --- | --- | --- | --- | --- | --- | --- |"
    holdout = SWAPPED_WIDE_HOLDOUT.replace(" reviewed |", "")
    path.write_text(f"{original}\n\n{header}\n{delimiter}\n{holdout}\n", encoding="utf-8")
    refresh_manifest(run)
    assert_rejected_by_every_gate(run, capsys, "unexpected table with header")


@pytest.mark.parametrize(("filename", "digest", "reason"), [
    ("validation_report.md", "report_sha256", "report Markdown differs"),
    ("validation_tables.md", "tables_sha256", "validation tables Markdown differs"),
    ("values_index.csv", "values_index_sha256", "values index differs"),
])
def test_gate_c_rejects_rehashed_changes_to_generated_artifacts(run, capsys, filename, digest, reason):
    path = run / "report" / filename
    original = path.read_text(encoding="utf-8")
    if filename == "values_index.csv":
        header, _removed, rest = original.split("\n", 2)
        modified = f"{header}\n{rest}"
    else:
        modified = original + "\n<table><tr><td>Holdout ROC-AUC</td><td>0.1531</td></tr></table>\n"
    path.write_text(modified, encoding="utf-8")
    manifest_path = run / "report" / "review_manifest.json"
    manifest = read_json(manifest_path)
    manifest[digest] = sha256_file(path)
    if filename == "values_index.csv":
        manifest["value_count"] -= 1
    write_json(manifest_path, manifest)

    code, result = cli_json(capsys, [
        "approve", "--run-id", RUN_ID, "--gate", "Gate_C", "--sha256", manifest_sha(run),
        "--reviewer", "agent-delegated", "--comment", "review generated artifacts",
    ])
    assert code == 2
    assert reason in result["error"]
    assert cli.main(["approve-report", "--run-id", RUN_ID]) == 2
    assert not (run / "report" / "approval.json").exists()
    verdict, actual = _v2_07(REPOSITORY, run, RUN_ID)
    assert verdict == "FAIL"
    assert reason in actual


def test_original_report_still_passes_the_cli_path(run, capsys):
    assert verify_report_cells(run) == []
    assert cli.main([
        "approve", "--run-id", RUN_ID, "--gate", "Gate_C", "--sha256", manifest_sha(run),
        "--reviewer", "agent-delegated", "--comment", "delegated review of the original report",
    ]) == 0
    assert cli.main(["approve-report", "--run-id", RUN_ID]) == 0
    _code, status = cli_json(capsys, ["report-status", "--run-id", RUN_ID])
    assert status["status"] == "APPROVED", status
    assert _v2_07(REPOSITORY, run, RUN_ID)[0] == "PASS"
