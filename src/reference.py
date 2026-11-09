#!/usr/bin/env python3
"""Hand-written standard-library reference for MDL_CREDIT_V1."""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

FEATURE_ORDER = ["delay_1", "log_limit", "util_1", "log_pay_1"]
RAW_FIELDS = ["limit_bal", "pay_status_1", "bill_amt_1", "pay_amt_1"]
INPUT_COLUMNS = ["client_id", *RAW_FIELDS]
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


class InputContractError(ValueError):
    """The input data or serialized model violates the prediction contract."""


def _model_number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise InputContractError(f"Model value {name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise InputContractError(f"Model value {name} must be numeric") from error
    if not math.isfinite(number):
        raise InputContractError(f"Model value {name} must be finite")
    return number


def _validate_model(model: dict) -> tuple[dict[str, float], dict[str, float], float]:
    if not isinstance(model, dict):
        raise InputContractError("Model must be a JSON object")
    if model.get("feature_order") != FEATURE_ORDER:
        raise InputContractError("Model feature_order does not match MDL_CREDIT_V1")
    coefficients_object = model.get("coefficients")
    medians_object = model.get("medians")
    if not isinstance(coefficients_object, dict) or not isinstance(medians_object, dict):
        raise InputContractError("Model coefficients and medians must be objects")

    coefficients = {
        name: _model_number(coefficients_object.get(name), f"coefficients.{name}")
        for name in ["intercept", *FEATURE_ORDER]
    }
    medians = {
        field: _model_number(medians_object.get(field), f"medians.{field}")
        for field in RAW_FIELDS
    }
    if medians["limit_bal"] <= 0:
        raise InputContractError("Model median limit_bal must be positive")
    status_median = medians["pay_status_1"]
    if not -2 <= status_median <= 9:
        raise InputContractError("Model median pay_status_1 must be in -2..9")
    if medians["pay_amt_1"] < 0:
        raise InputContractError("Model median pay_amt_1 must be non-negative")
    threshold = _model_number(model.get("threshold"), "threshold")
    if not 0 <= threshold <= 1:
        raise InputContractError("Model threshold must be in [0, 1]")
    return coefficients, medians, threshold


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _input_number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(field)
    try:
        number = float(value.strip() if isinstance(value, str) else value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(field) from error
    if not math.isfinite(number):
        raise ValueError(field)
    return number


def _field_is_valid(field: str, value: float) -> bool:
    if field == "limit_bal":
        return value > 0
    if field == "pay_status_1":
        return -2 <= value <= 9 and value.is_integer()
    if field == "pay_amt_1":
        return value >= 0
    return True


def _validate_rows(rows: list[dict]) -> None:
    if not isinstance(rows, list) or not rows:
        raise InputContractError("Input must contain at least one data row")
    if any(not isinstance(row, dict) for row in rows):
        raise InputContractError("Every input row must be an object")
    missing = [
        column
        for column in INPUT_COLUMNS
        if any(column not in row for row in rows)
    ]
    if missing:
        raise InputContractError(f"Missing required columns: {', '.join(missing)}")
    ids = []
    for row in rows:
        value = row["client_id"]
        if value is None or str(value).strip() == "":
            raise InputContractError("client_id must be non-empty")
        ids.append(str(value))
    if len(ids) != len(set(ids)):
        raise InputContractError("client_id values must be unique")


def _stable_logistic(eta: float) -> float:
    if eta >= 0:
        return 1.0 / (1.0 + math.exp(-eta))
    exponential = math.exp(eta)
    return exponential / (1.0 + exponential)


def predict_rows(model: dict, rows: list[dict]) -> list[dict]:
    """Predict CSV-contract records without fitting or changing model parameters."""

    coefficients, medians, threshold = _validate_model(model)
    _validate_rows(rows)
    output = []
    for row in rows:
        values: dict[str, float] = {}
        flags: dict[str, int] = {}
        error_code = ""
        for field in RAW_FIELDS:
            raw_value = row[field]
            if _is_missing(raw_value):
                values[field] = medians[field]
                flags[f"{field}_imputed"] = 1
                continue
            flags[f"{field}_imputed"] = 0
            try:
                value = _input_number(raw_value, field)
            except ValueError:
                value = math.nan
            values[field] = value
            if not error_code and (
                not math.isfinite(value) or not _field_is_valid(field, value)
            ):
                error_code = f"INVALID_{field.upper()}"

        result = {
            "client_id": str(row["client_id"]),
            "probability": "",
            "classification": "",
            "status": "REJECTED" if error_code else "VALID",
            "error_code": error_code,
            **{f"{field}_imputed": str(flags[f"{field}_imputed"]) for field in RAW_FIELDS},
        }
        if not error_code:
            features = {
                "delay_1": max(values["pay_status_1"], 0.0),
                "log_limit": math.log1p(values["limit_bal"]),
                "util_1": min(max(values["bill_amt_1"] / values["limit_bal"], 0.0), 2.0),
                "log_pay_1": math.log1p(values["pay_amt_1"]),
            }
            eta = coefficients["intercept"] + sum(
                coefficients[name] * features[name] for name in FEATURE_ORDER
            )
            if math.isnan(eta):
                raise InputContractError("Model produced a non-finite linear predictor")
            probability = _stable_logistic(eta)
            result["probability"] = format(probability, ".17g")
            result["classification"] = "1" if probability >= threshold else "0"
        output.append(result)
    return output


def _read_csv_rows(path: Path) -> list[dict]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            fieldnames = reader.fieldnames
            if fieldnames is None:
                raise InputContractError("Input CSV has no header or data rows")
            if len(fieldnames) != len(set(fieldnames)):
                raise InputContractError("Duplicate CSV column names are not allowed")
            missing = [column for column in INPUT_COLUMNS if column not in fieldnames]
            if missing:
                raise InputContractError(f"Missing required columns: {', '.join(missing)}")
            rows = []
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise InputContractError("Input CSV contains a malformed row")
                rows.append(dict(row))
    except InputContractError:
        raise
    except (OSError, UnicodeError, csv.Error) as error:
        raise InputContractError(f"Unable to read input CSV: {error}") from error
    if not rows:
        raise InputContractError("Input CSV has no data rows")
    return rows


def _load_model(path: Path) -> dict:
    def reject_constant(value: str) -> None:
        raise InputContractError(f"Model JSON contains invalid number {value}")

    try:
        with path.open("r", encoding="utf-8") as handle:
            model = json.load(handle, parse_constant=reject_constant)
    except InputContractError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise InputContractError(f"Unable to read model JSON: {error}") from error
    if not isinstance(model, dict):
        raise InputContractError("Model must be a JSON object")
    return model


def predict_file(model_path: Path, input_path: Path, output_path: Path) -> list[dict]:
    """Read a model and CSV, predict every row, and write the strict output schema."""

    model_path = Path(model_path)
    input_path = Path(input_path)
    output_path = Path(output_path)
    results = predict_rows(_load_model(model_path), _read_csv_rows(input_path))
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, extrasaction="raise")
            writer.writeheader()
            writer.writerows(results)
    except (OSError, csv.Error) as error:
        raise InputContractError(f"Unable to write output CSV: {error}") from error
    return results


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) == 6 and arguments[0::2] == ["--model", "--input", "--output"]:
        paths = arguments[1::2]
    elif len(arguments) == 3 and not any(value.startswith("--") for value in arguments):
        paths = arguments
    else:
        print("Usage: python src/reference.py MODEL INPUT OUTPUT or --model MODEL --input INPUT --output OUTPUT", file=sys.stderr)
        return 2
    try:
        predict_file(Path(paths[0]), Path(paths[1]), Path(paths[2]))
    except InputContractError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
