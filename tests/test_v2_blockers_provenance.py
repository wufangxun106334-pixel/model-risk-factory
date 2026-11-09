"""Release blocker 3: provenance must re-resolve every index row, not just match tokens.

A forged path, two swapped values or an edited index row all used to pass because
the acceptance check only asked whether the digits appeared somewhere in the
index. These tests require the reviewer's actual check: resolve the path, read the
JSON value, and compare it with the rendered text at that precision.
"""

from __future__ import annotations

import csv
from pathlib import Path

from src.common import read_json, write_json
from src.report import index_mismatches, index_not_in_report, render_report, text_matches_value, verify_provenance

from v2_metrics import metrics_fixture

RUN_ID = "v2-provenance"


def prepared(tmp_path: Path) -> Path:
    run = tmp_path / "repo" / "runs" / RUN_ID
    run.mkdir(parents=True)
    write_json(run / "run_manifest.json", {"run_id": RUN_ID})
    write_json(run / "context_manifest.json", {"run_id": RUN_ID, "assets": []})
    write_json(run / "validation_metrics.json", metrics_fixture(RUN_ID))
    render_report(run, RUN_ID, agent_summary=None, inventories={"MDL_CREDIT_V1": "APPROVED"})
    return run


def rewrite_index(run: Path, mutate) -> None:
    path = run / "report" / "values_index.csv"
    with path.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        rows = [dict(row) for row in reader]
    mutate(rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_rendered_index_matches_the_metrics_and_the_report(tmp_path):
    run = prepared(tmp_path)
    text = (run / "report" / "validation_report.md").read_text(encoding="utf-8")
    metrics = read_json(run / "validation_metrics.json")
    assert index_mismatches(run, metrics) == []
    assert index_not_in_report(text, run) == []
    rows = [{"json_path": row["json_path"], "text": row["text"]} for row in csv.DictReader((run / "report" / "values_index.csv").open())]
    assert verify_provenance(text, rows) == []


def test_forged_path_is_rejected(tmp_path):
    run = prepared(tmp_path)
    metrics = read_json(run / "validation_metrics.json")

    def mutate(rows):
        rows[0]["json_path"] = "performance.holdout.roc_auc.missing"

    rewrite_index(run, mutate)
    problems = index_mismatches(run, metrics)
    assert any("does not resolve" in problem for problem in problems), problems


def test_path_that_resolves_to_another_value_is_rejected(tmp_path):
    run = prepared(tmp_path)
    metrics = read_json(run / "validation_metrics.json")

    def mutate(rows):
        rows[0]["json_path"] = "performance.holdout.roc_auc.value"

    rewrite_index(run, mutate)
    problems = index_mismatches(run, metrics)
    assert any("does not match the metrics value" in problem for problem in problems), problems


def test_two_swapped_values_are_rejected(tmp_path):
    run = prepared(tmp_path)
    metrics = read_json(run / "validation_metrics.json")

    def mutate(rows):
        first = next(row for row in rows if row["json_path"] == "performance.dev.roc_auc.value")
        second = next(row for row in rows if row["json_path"] == "performance.holdout.roc_auc.value")
        first["text"], second["text"] = second["text"], first["text"]

    rewrite_index(run, mutate)
    problems = index_mismatches(run, metrics)
    assert sum("does not match the metrics value" in problem for problem in problems) >= 2, problems


def test_edited_index_row_is_rejected(tmp_path):
    run = prepared(tmp_path)
    metrics = read_json(run / "validation_metrics.json")

    def mutate(rows):
        row = next(row for row in rows if row["json_path"] == "performance.holdout.roc_auc.value")
        row["text"] = "0.9999"

    rewrite_index(run, mutate)
    problems = index_mismatches(run, metrics)
    assert any("does not match the metrics value" in problem for problem in problems), problems


def test_contradictory_duplicate_paths_are_rejected(tmp_path):
    run = prepared(tmp_path)
    metrics = read_json(run / "validation_metrics.json")

    def mutate(rows):
        duplicated = next(row for row in rows if row["json_path"] == "performance.holdout.brier_score.value")
        rows.append({**duplicated, "label": "forged duplicate", "text": "0.1000"})

    rewrite_index(run, mutate)
    problems = index_mismatches(run, metrics)
    assert any("contradictory index rows" in problem for problem in problems), problems


def test_index_row_absent_from_the_report_is_rejected(tmp_path):
    run = prepared(tmp_path)
    text = (run / "report" / "validation_report.md").read_text(encoding="utf-8")

    def mutate(rows):
        rows.append({
            "section": "performance",
            "label": "phantom",
            "json_path": "performance.holdout.rows",
            "text": "424242",
        })

    rewrite_index(run, mutate)
    missing = index_not_in_report(text, run)
    assert any("424242" in problem for problem in missing), missing


def test_format_helpers_accept_only_faithful_renderings():
    assert text_matches_value(0.7463269179647353, "0.7463")
    assert text_matches_value(6000, "6000")
    assert text_matches_value(2.220446049250313e-16, "2.220e-16")
    assert text_matches_value(None, "—")
    assert text_matches_value({"26-35": {}, "51+": {}}, "26-35")
    assert not text_matches_value(0.7463, "0.9")
    assert not text_matches_value(0.7463, "0.75")  # not a canonical renderer format
    assert not text_matches_value(3, "3.0")
