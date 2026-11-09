from __future__ import annotations

import csv
import json
import math
from pathlib import Path

INPUT_COLUMNS = ["client_id", "limit_bal", "pay_status_1", "bill_amt_1", "pay_amt_1"]


def _write(path: Path, rows: list[dict], columns: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns or INPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_fixtures(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    rows = [
        {"client_id": "FX-NORMAL", "limit_bal": "100000", "pay_status_1": "0", "bill_amt_1": "5000", "pay_amt_1": "1000"},
        {"client_id": "FX-MISSING-LIMIT", "limit_bal": "", "pay_status_1": "1", "bill_amt_1": "6000", "pay_amt_1": "1000"},
        {"client_id": "FX-MISSING-STATUS", "limit_bal": "120000", "pay_status_1": "", "bill_amt_1": "6000", "pay_amt_1": "1000"},
        {"client_id": "FX-MISSING-BILL", "limit_bal": "120000", "pay_status_1": "1", "bill_amt_1": "", "pay_amt_1": "1000"},
        {"client_id": "FX-MISSING-PAYMENT", "limit_bal": "120000", "pay_status_1": "1", "bill_amt_1": "6000", "pay_amt_1": ""},
        {"client_id": "FX-NEGATIVE-BILL", "limit_bal": "120000", "pay_status_1": "-2", "bill_amt_1": "-6000", "pay_amt_1": "1000"},
        {"client_id": "FX-ZERO-LIMIT", "limit_bal": "0", "pay_status_1": "0", "bill_amt_1": "6000", "pay_amt_1": "1000"},
        {"client_id": "FX-STATUS-HIGH", "limit_bal": "120000", "pay_status_1": "10", "bill_amt_1": "6000", "pay_amt_1": "1000"},
        {"client_id": "FX-STATUS-FRACTION", "limit_bal": "120000", "pay_status_1": "1.5", "bill_amt_1": "6000", "pay_amt_1": "1000"},
        {"client_id": "FX-NEGATIVE-PAYMENT", "limit_bal": "120000", "pay_status_1": "0", "bill_amt_1": "6000", "pay_amt_1": "-1"},
        {"client_id": "FX-NONNUMERIC", "limit_bal": "not-a-number", "pay_status_1": "0", "bill_amt_1": "6000", "pay_amt_1": "1000"},
    ]
    paths = []
    behavior = directory / "behavior.csv"
    _write(behavior, rows)
    paths.append(behavior)
    reordered = directory / "column_reordered.csv"
    _write(reordered, rows[:2], list(reversed(INPUT_COLUMNS)))
    paths.append(reordered)
    row_reordered = directory / "row_reordered.csv"
    _write(row_reordered, list(reversed(rows[:2])))
    paths.append(row_reordered)
    duplicate = directory / "duplicate_ids.csv"
    _write(duplicate, [rows[0], rows[0]])
    paths.append(duplicate)
    missing = directory / "missing_column.csv"
    _write(missing, rows[:1], INPUT_COLUMNS[:-1])
    paths.append(missing)
    empty = directory / "empty.csv"
    _write(empty, [])
    paths.append(empty)
    return paths


def _load_threshold_coefficients(model_path: Path) -> dict[str, float]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"Invalid model number {value}")

    try:
        with model_path.open("r", encoding="utf-8") as handle:
            model = json.load(handle, parse_constant=reject_constant)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Unable to read threshold fixture model: {error}") from error
    feature_order = ["delay_1", "log_limit", "util_1", "log_pay_1"]
    if not isinstance(model, dict) or model.get("feature_order") != feature_order:
        raise ValueError("Threshold fixture model has an invalid feature_order")
    try:
        threshold = float(model.get("threshold"))
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("Threshold fixture model has an invalid threshold") from error
    if not math.isfinite(threshold) or threshold != 0.35:
        raise ValueError("Threshold fixture requires a model threshold of 0.35")
    coefficients = model.get("coefficients")
    if not isinstance(coefficients, dict):
        raise ValueError("Threshold fixture model coefficients must be an object")
    result = {}
    for name in ["intercept", *feature_order]:
        value = coefficients.get(name)
        if isinstance(value, bool):
            raise ValueError(f"Threshold fixture coefficient {name} must be numeric")
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(f"Threshold fixture coefficient {name} must be numeric") from error
        if not math.isfinite(number):
            raise ValueError(f"Threshold fixture coefficient {name} must be finite")
        result[name] = number
    return result


def _threshold_features(row: dict[str, float]) -> dict[str, float]:
    return {
        "delay_1": max(row["pay_status_1"], 0.0),
        "log_limit": math.log1p(row["limit_bal"]),
        "util_1": min(max(row["bill_amt_1"] / row["limit_bal"], 0.0), 2.0),
        "log_pay_1": math.log1p(row["pay_amt_1"]),
    }


def _threshold_eta(coefficients: dict[str, float], row: dict[str, float]) -> float:
    features = _threshold_features(row)
    return coefficients["intercept"] + sum(
        coefficients[name] * features[name]
        for name in ["delay_1", "log_limit", "util_1", "log_pay_1"]
    )


def _threshold_probability(eta: float) -> float:
    if eta >= 0:
        return 1.0 / (1.0 + math.exp(-eta))
    exponential = math.exp(eta)
    return exponential / (1.0 + exponential)


def _serialize_threshold_row(client_id: str, row: dict[str, float]) -> dict[str, str]:
    serialized = {"client_id": client_id}
    for field in INPUT_COLUMNS[1:]:
        value = row[field]
        if not math.isfinite(value):
            raise ValueError(f"Threshold fixture produced non-finite {field}")
        serialized[field] = format(value, ".17g")
    return serialized


def _solve_threshold_rows(
    coefficients: dict[str, float],
    solved_feature: str,
    targets: list[tuple[str, float]],
) -> list[dict[str, str]]:
    coefficient = coefficients[solved_feature]
    if coefficient == 0:
        raise ValueError(f"{solved_feature} coefficient is zero")
    base = {
        "limit_bal": 100000.0,
        "pay_status_1": 0.0,
        "bill_amt_1": 5000.0,
        "pay_amt_1": 1000.0,
    }
    raw_field = {"util_1": "bill_amt_1", "log_limit": "limit_bal", "log_pay_1": "pay_amt_1"}[solved_feature]
    rows = []
    for label, target_eta in targets:
        row = dict(base)
        base_features = _threshold_features(row)
        fixed_eta = coefficients["intercept"] + sum(
            coefficients[name] * base_features[name]
            for name in ["delay_1", "log_limit", "util_1", "log_pay_1"]
            if name != solved_feature
        )
        solved_value = (target_eta - fixed_eta) / coefficient
        if not math.isfinite(solved_value):
            raise ValueError(f"{solved_feature} solution is non-finite")
        if solved_feature == "util_1":
            if not 0 < solved_value < 2:
                raise ValueError(f"util_1 solution {solved_value} would be clipped")
            row[raw_field] = base["limit_bal"] * solved_value
        else:
            if solved_value < 0 or (solved_feature == "log_limit" and solved_value == 0):
                raise ValueError(f"{solved_feature} solution is outside its legal domain")
            try:
                row[raw_field] = math.expm1(solved_value)
            except OverflowError as error:
                raise ValueError(f"{solved_feature} solution overflows") from error
        if not math.isfinite(row[raw_field]) or row[raw_field] < 0 or row["limit_bal"] <= 0:
            raise ValueError(f"{solved_feature} produced an invalid raw value")

        client_id = f"FX-THRESHOLD-{label.upper()}"
        for _ in range(16):
            serialized = _serialize_threshold_row(client_id, row)
            serialized_row = {field: float(serialized[field]) for field in INPUT_COLUMNS[1:]}
            if serialized_row["limit_bal"] <= 0 or serialized_row["pay_amt_1"] < 0:
                raise ValueError("Threshold fixture serialization produced an invalid raw value")
            actual_features = _threshold_features(serialized_row)
            if solved_feature == "util_1" and not 0 < actual_features["util_1"] < 2:
                raise ValueError("Threshold fixture serialization reached a util_1 clip boundary")
            actual_eta = _threshold_eta(coefficients, serialized_row)
            probability = _threshold_probability(actual_eta)
            if label != "exact" or probability >= 0.35:
                break
            direction = math.inf if coefficient > 0 else -math.inf
            row[raw_field] = math.nextafter(row[raw_field], direction)
        else:
            raise ValueError("Unable to serialize the exact threshold row")

        if not math.isfinite(actual_eta) or abs(actual_eta - target_eta) > 1e-12:
            raise ValueError(f"{label} row did not preserve its target eta")
        if label == "below" and not probability < 0.35:
            raise ValueError("Below-threshold row did not classify as 0")
        if label == "exact" and not probability >= 0.35:
            raise ValueError("Exact-threshold row did not classify as 1")
        if label == "above" and not probability > 0.35:
            raise ValueError("Above-threshold row did not classify as 1")
        rows.append(serialized)
    return rows


def write_threshold_fixture(model_path: Path, output_path: Path) -> Path:
    """Write below, exact, and above rows derived from an exported 0.35 model."""

    model_path = Path(model_path)
    output_path = Path(output_path)
    if model_path.resolve() == output_path.resolve():
        raise ValueError("Threshold fixture output must not overwrite the model")
    coefficients = _load_threshold_coefficients(model_path)
    threshold_eta = math.log(0.35 / 0.65)
    targets = [
        ("below", threshold_eta - 1e-7),
        ("exact", threshold_eta),
        ("above", threshold_eta + 1e-7),
    ]
    errors = []
    for feature in ["util_1", "log_limit", "log_pay_1"]:
        try:
            rows = _solve_threshold_rows(coefficients, feature, targets)
        except (ValueError, OverflowError) as error:
            errors.append(f"{feature}: {error}")
            continue
        _write(output_path, rows)
        return output_path
    raise ValueError("Unable to construct threshold fixture; " + "; ".join(errors))
