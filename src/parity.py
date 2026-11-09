#!/usr/bin/env python3
"""Trusted, independent CSV parity checks for the credit model baseline."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

OUTPUT_COLUMNS = [
    "client_id",
    "probability",
    "classification",
    "status",
    "error_code",
    "limit_bal_imputed",
    "pay_status_1_imputed",
    "bill_amt_1_imputed",
    "pay_amt_1_imputed",
]
FLAG_COLUMNS = OUTPUT_COLUMNS[5:]
BEHAVIOUR_COLUMNS = ["status", "error_code", *FLAG_COLUMNS]
DIFF_COLUMNS = ["client_id", "field", "baseline_value", "candidate_value", "abs_diff", "reason"]
ERROR_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _new_summary() -> dict[str, Any]:
    return {
        "status": "FAIL",
        "n": 0,
        "max_abs_diff": None,
        "mean_abs_diff": None,
        "classification_mismatch_count": 0,
        "behaviour_mismatch_count": 0,
        "baseline_row_count": 0,
        "candidate_row_count": 0,
        "baseline_id_unique": False,
        "candidate_id_unique": False,
        "baseline_ids_nonempty": False,
        "candidate_ids_nonempty": False,
        "id_sets_match": False,
        "id_order_match": False,
        "input_row_count": None,
        "input_id_unique": None,
        "input_ids_nonempty": None,
        "input_baseline_ids_match": None,
        "input_candidate_ids_match": None,
        "input_ids_match": None,
        "valid_probability_pairs": 0,
        "reasons": [],
        "execution_error": False,
    }


def _reason(summary: dict[str, Any], code: str) -> None:
    if code not in summary["reasons"]:
        summary["reasons"].append(code)


def _difference(
    differences: list[dict[str, str]],
    client_id: Any,
    field: str,
    baseline_value: Any,
    candidate_value: Any,
    reason: str,
    abs_diff: Any = "",
) -> None:
    differences.append(
        {
            "client_id": "" if client_id is None else str(client_id),
            "field": field,
            "baseline_value": "" if baseline_value is None else str(baseline_value),
            "candidate_value": "" if candidate_value is None else str(candidate_value),
            "abs_diff": "" if abs_diff is None else str(abs_diff),
            "reason": reason,
        }
    )


def _read_prediction_file(
    path: Path,
    side: str,
    summary: dict[str, Any],
    differences: list[dict[str, str]],
) -> dict[str, Any]:
    result = {"rows": [], "fieldnames": [], "readable": True}
    prefix = side.upper()
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            fieldnames = reader.fieldnames
            if fieldnames is None:
                _reason(summary, f"{prefix}_EMPTY")
                _reason(summary, f"{prefix}_SCHEMA_MISMATCH")
                _difference(differences, "", "schema", "MISSING", "", f"{prefix}_EMPTY")
                return result
            result["fieldnames"] = fieldnames
            if fieldnames != OUTPUT_COLUMNS:
                _reason(summary, f"{prefix}_SCHEMA_MISMATCH")
                _difference(
                    differences,
                    "",
                    "schema",
                    ",".join(fieldnames) if side == "baseline" else ",".join(OUTPUT_COLUMNS),
                    ",".join(fieldnames) if side == "candidate" else ",".join(OUTPUT_COLUMNS),
                    f"{prefix}_SCHEMA_MISMATCH",
                )
            if len(fieldnames) != len(set(fieldnames)):
                _reason(summary, f"{prefix}_DUPLICATE_COLUMN")
            rows = []
            for line_number, row in enumerate(reader, start=2):
                if None in row or any(value is None for value in row.values()):
                    _reason(summary, f"{prefix}_MALFORMED_ROW")
                    _difference(
                        differences,
                        row.get("client_id", ""),
                        "__row__",
                        row if side == "baseline" else "",
                        row if side == "candidate" else "",
                        f"{prefix}_MALFORMED_ROW_AT_{line_number}",
                    )
                rows.append(dict(row))
            result["rows"] = rows
    except (OSError, UnicodeError, csv.Error) as error:
        result["readable"] = False
        summary["execution_error"] = True
        _reason(summary, f"{prefix}_READ_ERROR")
        _difference(
            differences,
            "",
            "__file__",
            str(path) if side == "baseline" else "",
            str(path) if side == "candidate" else "",
            f"{prefix}_READ_ERROR: {error}",
        )
        return result

    if not rows:
        _reason(summary, f"{prefix}_EMPTY")
        _difference(differences, "", "__file__", str(path), str(path), f"{prefix}_EMPTY")
    summary[f"{side}_row_count"] = len(rows)
    summary["n"] = summary["baseline_row_count"]

    ids = [str(row.get("client_id") or "") for row in rows]
    nonempty = bool(ids) and all(value.strip() for value in ids)
    unique = bool(ids) and len(ids) == len(set(ids))
    summary[f"{side}_ids_nonempty"] = nonempty
    summary[f"{side}_id_unique"] = unique
    if not nonempty:
        _reason(summary, f"{prefix}_EMPTY_CLIENT_ID")
        for row in rows:
            if not str(row.get("client_id") or "").strip():
                _difference(
                    differences,
                    "",
                    "client_id",
                    row.get("client_id", "") if side == "baseline" else "",
                    row.get("client_id", "") if side == "candidate" else "",
                    f"{prefix}_EMPTY_CLIENT_ID",
                )
    counts = Counter(ids)
    for client_id, count in counts.items():
        if client_id and count > 1:
            _reason(summary, f"{prefix}_DUPLICATE_ID")
            _difference(
                differences,
                client_id,
                "client_id",
                count if side == "baseline" else "",
                count if side == "candidate" else "",
                f"{prefix}_DUPLICATE_ID",
            )
    return result


def _read_input_ids(
    path: Path,
    summary: dict[str, Any],
    differences: list[dict[str, str]],
) -> list[str]:
    summary["input_row_count"] = 0
    summary["input_id_unique"] = False
    summary["input_ids_nonempty"] = False
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            fieldnames = reader.fieldnames
            if fieldnames is None:
                _reason(summary, "INPUT_EMPTY")
                _reason(summary, "INPUT_SCHEMA_MISMATCH")
                _difference(differences, "", "schema", "", "", "INPUT_EMPTY")
                return []
            if "client_id" not in fieldnames:
                _reason(summary, "INPUT_SCHEMA_MISMATCH")
                _difference(differences, "", "schema", ",".join(fieldnames), "", "INPUT_MISSING_CLIENT_ID")
            if len(fieldnames) != len(set(fieldnames)):
                _reason(summary, "INPUT_DUPLICATE_COLUMN")
            rows = []
            for line_number, row in enumerate(reader, start=2):
                if None in row or any(value is None for value in row.values()):
                    _reason(summary, "INPUT_MALFORMED_ROW")
                    _difference(
                        differences,
                        row.get("client_id", ""),
                        "__input_row__",
                        "",
                        "",
                        f"INPUT_MALFORMED_ROW_AT_{line_number}",
                    )
                rows.append(row)
    except (OSError, UnicodeError, csv.Error) as error:
        summary["execution_error"] = True
        _reason(summary, "INPUT_READ_ERROR")
        _difference(differences, "", "__input_file__", str(path), "", f"INPUT_READ_ERROR: {error}")
        return []

    ids = [str(row.get("client_id") or "") for row in rows]
    summary["input_row_count"] = len(rows)
    summary["input_ids_nonempty"] = bool(ids) and all(value.strip() for value in ids)
    summary["input_id_unique"] = bool(ids) and len(ids) == len(set(ids))
    if not rows:
        _reason(summary, "INPUT_EMPTY")
        _difference(differences, "", "__input_file__", str(path), "", "INPUT_EMPTY")
    if not summary["input_ids_nonempty"]:
        _reason(summary, "INPUT_EMPTY_CLIENT_ID")
        for client_id in ids:
            if not client_id.strip():
                _difference(differences, "", "client_id", "", "", "INPUT_EMPTY_CLIENT_ID")
    counts = Counter(ids)
    for client_id, count in counts.items():
        if client_id and count > 1:
            _reason(summary, "INPUT_DUPLICATE_ID")
            _difference(differences, client_id, "client_id", "", "", "INPUT_DUPLICATE_ID")
    return ids


def _probability(value: Any) -> float | None:
    if not isinstance(value, str) or value.strip() == "":
        return None
    try:
        number = float(value.strip())
    except (ValueError, OverflowError):
        return None
    if not math.isfinite(number) or not 0 <= number <= 1:
        return None
    return number


def _validate_record(
    row: dict,
    client_id: str,
    side: str,
    threshold: float,
    summary: dict[str, Any],
    differences: list[dict[str, str]],
) -> float | None:
    prefix = side.upper()
    other = "candidate" if side == "baseline" else "baseline"

    def value(field: str) -> Any:
        return row.get(field, "")

    def baseline_value(field: str) -> Any:
        return value(field) if side == "baseline" else ""

    def candidate_value(field: str) -> Any:
        return value(field) if side == "candidate" else ""

    status = value("status")
    if status not in {"VALID", "REJECTED"}:
        _reason(summary, f"{prefix}_INVALID_STATUS")
        _difference(
            differences,
            client_id,
            "status",
            baseline_value("status"),
            candidate_value("status"),
            f"{prefix}_INVALID_STATUS",
        )
    for field in FLAG_COLUMNS:
        if value(field) not in {"0", "1"}:
            _reason(summary, f"{prefix}_INVALID_IMPUTATION_FLAG")
            _difference(
                differences,
                client_id,
                field,
                baseline_value(field),
                candidate_value(field),
                f"{prefix}_INVALID_IMPUTATION_FLAG",
            )

    error_code = value("error_code")
    probability_text = value("probability")
    classification = value("classification")
    probability = _probability(probability_text)

    if status == "VALID":
        if error_code != "":
            _reason(summary, f"{prefix}_VALID_ERROR_CODE")
            _difference(
                differences,
                client_id,
                "error_code",
                baseline_value("error_code"),
                candidate_value("error_code"),
                f"{prefix}_VALID_ERROR_CODE",
            )
        if probability is None:
            _reason(summary, f"{prefix}_INVALID_PROBABILITY")
            _difference(
                differences,
                client_id,
                "probability",
                baseline_value("probability"),
                candidate_value("probability"),
                f"{prefix}_INVALID_PROBABILITY",
            )
        if classification not in {"0", "1"}:
            _reason(summary, f"{prefix}_INVALID_CLASSIFICATION")
            _difference(
                differences,
                client_id,
                "classification",
                baseline_value("classification"),
                candidate_value("classification"),
                f"{prefix}_INVALID_CLASSIFICATION",
            )
        elif probability is not None:
            expected = "1" if probability >= threshold else "0"
            if classification != expected:
                _reason(summary, f"{prefix}_THRESHOLD_CLASSIFICATION_ERROR")
                _difference(
                    differences,
                    client_id,
                    "classification",
                    baseline_value("classification"),
                    candidate_value("classification"),
                    f"{prefix}_EXPECTED_CLASSIFICATION_{expected}",
                )
    elif status == "REJECTED":
        if not isinstance(error_code, str) or not ERROR_CODE_PATTERN.fullmatch(error_code):
            _reason(summary, f"{prefix}_INVALID_REJECTION_CODE")
            _difference(
                differences,
                client_id,
                "error_code",
                baseline_value("error_code"),
                candidate_value("error_code"),
                f"{prefix}_INVALID_REJECTION_CODE",
            )
        for field, field_value in (("probability", probability_text), ("classification", classification)):
            if field_value != "":
                _reason(summary, f"{prefix}_REJECTED_VALUE_NOT_EMPTY")
                _difference(
                    differences,
                    client_id,
                    field,
                    baseline_value(field),
                    candidate_value(field),
                    f"{prefix}_REJECTED_VALUE_NOT_EMPTY",
                )
    return probability


def _write_evidence(
    summary_path: Path,
    diff_path: Path,
    summary: dict[str, Any],
    differences: list[dict[str, str]],
) -> None:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    with diff_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DIFF_COLUMNS, extrasaction="raise")
        writer.writeheader()
        writer.writerows(differences)
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def compare_files(
    baseline_path: Path,
    candidate_path: Path,
    summary_path: Path,
    diff_path: Path,
    max_abs_diff: float = 1e-8,
    mean_abs_diff: float = 1e-10,
    threshold: float = 0.35,
    run_id: str | None = None,
    input_path: Path | None = None,
) -> dict:
    """Compare two prediction CSVs by client ID and write JSON/CSV evidence."""

    baseline_path = Path(baseline_path)
    candidate_path = Path(candidate_path)
    summary_path = Path(summary_path)
    diff_path = Path(diff_path)
    summary = _new_summary()
    summary["run_id"] = run_id
    differences: list[dict[str, str]] = []

    try:
        limits = (float(max_abs_diff), float(mean_abs_diff), float(threshold))
    except (TypeError, ValueError, OverflowError):
        limits = (math.nan, math.nan, math.nan)
    if (
        not all(math.isfinite(value) for value in limits)
        or limits[0] < 0
        or limits[1] < 0
        or not 0 <= limits[2] <= 1
    ):
        summary["execution_error"] = True
        _reason(summary, "INVALID_COMPARISON_CONFIG")
        _difference(differences, "", "__config__", "", "", "INVALID_COMPARISON_CONFIG")
        _write_evidence(summary_path, diff_path, summary, differences)
        return summary
    max_abs_diff, mean_abs_diff, threshold = limits

    baseline = _read_prediction_file(baseline_path, "baseline", summary, differences)
    candidate = _read_prediction_file(candidate_path, "candidate", summary, differences)
    baseline_rows = baseline["rows"]
    candidate_rows = candidate["rows"]
    baseline_ids = [str(row.get("client_id") or "") for row in baseline_rows]
    candidate_ids = [str(row.get("client_id") or "") for row in candidate_rows]
    baseline_counts = Counter(baseline_ids)
    candidate_counts = Counter(candidate_ids)
    baseline_id_set = set(baseline_ids)
    candidate_id_set = set(candidate_ids)
    summary["id_sets_match"] = bool(baseline_rows) and bool(candidate_rows) and baseline_id_set == candidate_id_set
    summary["id_order_match"] = bool(baseline_rows) and baseline_ids == candidate_ids

    if input_path is not None:
        input_ids = _read_input_ids(Path(input_path), summary, differences)
        input_id_set = set(input_ids)
        has_input = bool(input_ids)
        input_baseline_match = has_input and input_id_set == baseline_id_set
        input_candidate_match = has_input and input_id_set == candidate_id_set
        summary["input_baseline_ids_match"] = input_baseline_match
        summary["input_candidate_ids_match"] = input_candidate_match
        summary["input_ids_match"] = input_baseline_match and input_candidate_match
        if len(input_ids) != len(baseline_rows):
            _reason(summary, "INPUT_BASELINE_ROW_COUNT_MISMATCH")
        if len(input_ids) != len(candidate_rows):
            _reason(summary, "INPUT_CANDIDATE_ROW_COUNT_MISMATCH")
        if not input_baseline_match:
            _reason(summary, "INPUT_ID_SET_MISMATCH")
            _reason(summary, "INPUT_BASELINE_ID_SET_MISMATCH")
            for client_id in sorted(input_id_set - baseline_id_set):
                candidate_value = "PRESENT" if client_id in candidate_id_set else "MISSING"
                _difference(differences, client_id, "__row__", "MISSING", candidate_value, "INPUT_ID_MISSING_FROM_BASELINE")
            for client_id in sorted(baseline_id_set - input_id_set):
                candidate_value = "PRESENT" if client_id in candidate_id_set else "MISSING"
                _difference(differences, client_id, "__row__", "PRESENT", candidate_value, "BASELINE_ID_MISSING_FROM_INPUT")
        if not input_candidate_match:
            _reason(summary, "INPUT_ID_SET_MISMATCH")
            _reason(summary, "INPUT_CANDIDATE_ID_SET_MISMATCH")
            for client_id in sorted(input_id_set - candidate_id_set):
                baseline_value = "PRESENT" if client_id in baseline_id_set else "MISSING"
                _difference(differences, client_id, "__row__", baseline_value, "MISSING", "INPUT_ID_MISSING_FROM_CANDIDATE")
            for client_id in sorted(candidate_id_set - input_id_set):
                baseline_value = "PRESENT" if client_id in baseline_id_set else "MISSING"
                _difference(differences, client_id, "__row__", baseline_value, "PRESENT", "CANDIDATE_ID_MISSING_FROM_INPUT")

    if len(baseline_rows) != len(candidate_rows):
        _reason(summary, "ROW_COUNT_MISMATCH")
        _difference(
            differences,
            "",
            "__row_count__",
            len(baseline_rows),
            len(candidate_rows),
            "ROW_COUNT_MISMATCH",
        )
    if not summary["id_sets_match"]:
        _reason(summary, "ID_SET_MISMATCH")
        for client_id in sorted(baseline_id_set - candidate_id_set):
            _difference(differences, client_id, "__row__", "PRESENT", "MISSING", "MISSING_CANDIDATE_ROW")
        for client_id in sorted(candidate_id_set - baseline_id_set):
            _difference(differences, client_id, "__row__", "MISSING", "PRESENT", "UNEXPECTED_CANDIDATE_ROW")

    probability_differences: list[float] = []
    can_align = "client_id" in baseline["fieldnames"] and "client_id" in candidate["fieldnames"]
    if can_align:
        baseline_by_id = {str(row.get("client_id") or ""): row for row in baseline_rows}
        candidate_by_id = {str(row.get("client_id") or ""): row for row in candidate_rows}
        ordered_shared_ids = [
            client_id
            for client_id in baseline_ids
            if client_id in candidate_by_id
            and baseline_counts[client_id] == 1
            and candidate_counts[client_id] == 1
        ]
        for client_id in ordered_shared_ids:
            baseline_row = baseline_by_id[client_id]
            candidate_row = candidate_by_id[client_id]

            behaviour_mismatch = False
            for field in BEHAVIOUR_COLUMNS:
                baseline_value = baseline_row.get(field, "")
                candidate_value = candidate_row.get(field, "")
                if baseline_value != candidate_value:
                    behaviour_mismatch = True
                    _difference(
                        differences,
                        client_id,
                        field,
                        baseline_value,
                        candidate_value,
                        "BEHAVIOUR_MISMATCH",
                    )
            if behaviour_mismatch:
                summary["behaviour_mismatch_count"] += 1
                _reason(summary, "BEHAVIOUR_MISMATCH")

            baseline_classification = baseline_row.get("classification", "")
            candidate_classification = candidate_row.get("classification", "")
            if baseline_classification != candidate_classification:
                summary["classification_mismatch_count"] += 1
                _reason(summary, "CLASSIFICATION_MISMATCH")
                _difference(
                    differences,
                    client_id,
                    "classification",
                    baseline_classification,
                    candidate_classification,
                    "CLASSIFICATION_MISMATCH",
                )

            baseline_probability = _validate_record(
                baseline_row, client_id, "baseline", threshold, summary, differences
            )
            candidate_probability = _validate_record(
                candidate_row, client_id, "candidate", threshold, summary, differences
            )
            if (
                baseline_row.get("status") == "VALID"
                and candidate_row.get("status") == "VALID"
                and baseline_probability is not None
                and candidate_probability is not None
            ):
                absolute_difference = abs(baseline_probability - candidate_probability)
                probability_differences.append(absolute_difference)
                if absolute_difference > max_abs_diff:
                    _difference(
                        differences,
                        client_id,
                        "probability",
                        baseline_row.get("probability", ""),
                        candidate_row.get("probability", ""),
                        "PROBABILITY_DIFF_EXCEEDS_MAX",
                        format(absolute_difference, ".17g"),
                    )
            elif (
                baseline_row.get("probability", "") != candidate_row.get("probability", "")
                and (
                    baseline_row.get("status") == "REJECTED"
                    or candidate_row.get("status") == "REJECTED"
                )
            ):
                _difference(
                    differences,
                    client_id,
                    "probability",
                    baseline_row.get("probability", ""),
                    candidate_row.get("probability", ""),
                    "PROBABILITY_PRESENCE_MISMATCH",
                )

    summary["valid_probability_pairs"] = len(probability_differences)
    if probability_differences:
        maximum = max(probability_differences)
        mean = math.fsum(probability_differences) / len(probability_differences)
        summary["max_abs_diff"] = maximum
        summary["mean_abs_diff"] = mean
        if maximum > max_abs_diff:
            _reason(summary, "MAX_ABS_DIFF_EXCEEDED")
        if mean > mean_abs_diff:
            _reason(summary, "MEAN_ABS_DIFF_EXCEEDED")
            _difference(
                differences,
                "",
                "mean_abs_diff",
                format(mean, ".17g"),
                format(mean_abs_diff, ".17g"),
                "MEAN_ABS_DIFF_EXCEEDED",
                format(mean, ".17g"),
            )
    else:
        _reason(summary, "NO_VALID_RECORD_PAIRS")

    if not summary["reasons"]:
        summary["status"] = "PASS"
    _write_evidence(summary_path, diff_path, summary, differences)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare credit-model prediction CSV files")
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("summary", type=Path)
    parser.add_argument("diff", type=Path)
    parser.add_argument("--max-abs-diff", type=float, default=1e-8)
    parser.add_argument("--mean-abs-diff", type=float, default=1e-10)
    parser.add_argument("--threshold", type=float, default=0.35)
    parser.add_argument("--input", dest="input_path", type=Path)
    arguments = parser.parse_args(argv)
    try:
        summary = compare_files(
            arguments.baseline,
            arguments.candidate,
            arguments.summary,
            arguments.diff,
            max_abs_diff=arguments.max_abs_diff,
            mean_abs_diff=arguments.mean_abs_diff,
            threshold=arguments.threshold,
            input_path=arguments.input_path,
        )
    except (OSError, UnicodeError, csv.Error, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    if summary["status"] == "PASS":
        return 0
    if summary.get("execution_error"):
        print(f"ERROR: {', '.join(summary['reasons'])}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
