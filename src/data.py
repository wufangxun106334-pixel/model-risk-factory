from __future__ import annotations

import hashlib
import hmac
import io
import json
import re
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import numpy as np
import pandas as pd

SCHEMA_VERSION = "1"
MODEL_ID = "MDL_CREDIT_V1"
DEFAULT_SEED = 42
TOTAL_ROWS = 30000
SPLIT_SIZES = {"train": 15000, "dev": 6000, "holdout": 6000, "shift_pool": 3000}
DEFAULT_RATE_TOLERANCE = 0.01
UCI_LANDING_URL = "https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients"
UCI_ZIP_URL = "https://archive.ics.uci.edu/static/public/350/default+of+credit+card+clients.zip"
UCI_CITATION = (
    "Yeh, I-C. & Lien, C-H. (2009). The comparisons of data mining techniques "
    "for the predictive accuracy of probability of default of credit card clients. "
    "Expert Systems with Applications, 36(2)."
)

RAW_COLUMNS = [
    "ID",
    "LIMIT_BAL",
    "SEX",
    "EDUCATION",
    "MARRIAGE",
    "AGE",
    "PAY_0",
    *[f"PAY_{month}" for month in range(2, 7)],
    *[f"BILL_AMT{month}" for month in range(1, 7)],
    *[f"PAY_AMT{month}" for month in range(1, 7)],
    "default payment next month",
]

COLUMN_RENAME = {
    "ID": "client_id",
    "LIMIT_BAL": "limit_bal",
    "SEX": "sex",
    "EDUCATION": "education",
    "MARRIAGE": "marriage",
    "AGE": "age",
    "PAY_0": "pay_status_1",
    **{f"PAY_{month}": f"pay_status_{month}" for month in range(2, 7)},
    **{f"BILL_AMT{month}": f"bill_amt_{month}" for month in range(1, 7)},
    **{f"PAY_AMT{month}": f"pay_amt_{month}" for month in range(1, 7)},
    "default payment next month": "default_flag",
}

RENAMED_COLUMNS = [COLUMN_RENAME[column] for column in RAW_COLUMNS]
DERIVED_COLUMNS = [
    "log_limit",
    *[f"delay_{month}" for month in range(1, 7)],
    *[f"util_{month}" for month in range(1, 7)],
    *[f"log_pay_{month}" for month in range(1, 7)],
    "age_band",
]
OUTPUT_COLUMNS = [*RENAMED_COLUMNS, *DERIVED_COLUMNS]
AUDIT_COLUMNS = ["sex", "education", "marriage", "age", "age_band"]
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


def _config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "data_config.json"


def _load_config() -> tuple[dict, str]:
    config_bytes = _config_path().read_bytes()
    config = json.loads(config_bytes)
    seed = config.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 1:
        # The campaign seed is the only free parameter: it is fixed per campaign and
        # recorded in every data manifest, so a new campaign must be declared in config.
        raise ValueError("Frozen data configuration mismatch: seed")
    expected = {
        "total_rows": TOTAL_ROWS,
        "split_sizes": SPLIT_SIZES,
        "max_default_rate_difference": DEFAULT_RATE_TOLERANCE,
        "uci_landing_url": UCI_LANDING_URL,
        "uci_zip_url": UCI_ZIP_URL,
    }
    for key, value in expected.items():
        if config.get(key) != value:
            raise ValueError(f"Frozen data configuration mismatch: {key}")
    return config, hashlib.sha256(config_bytes).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _generate_synthetic_raw(rng: np.random.Generator) -> pd.DataFrame:
    rows = TOTAL_ROWS
    limits = rng.choice(
        np.array([10000, 20000, 30000, 50000, 80000, 100000, 150000, 200000, 300000, 500000, 800000, 1000000]),
        size=rows,
        p=np.array([0.03, 0.05, 0.06, 0.10, 0.08, 0.18, 0.13, 0.15, 0.11, 0.06, 0.03, 0.02]),
    )
    sex = rng.choice([1, 2], size=rows, p=[0.4, 0.6])
    education = rng.choice(
        [0, 1, 2, 3, 4, 5, 6],
        size=rows,
        p=[0.005, 0.30, 0.45, 0.18, 0.05, 0.01, 0.005],
    )
    marriage = rng.choice([0, 1, 2, 3], size=rows, p=[0.005, 0.45, 0.50, 0.045])
    age = rng.integers(21, 81, size=rows)

    status_values = np.array([-2, -1, 0, 1, 2, 3, 4, 5, 6, 7, 8])
    status_probabilities = np.array([0.08, 0.23, 0.49, 0.08, 0.05, 0.03, 0.015, 0.01, 0.008, 0.005, 0.002])
    statuses = np.empty((rows, 6), dtype=np.int64)
    statuses[:, 0] = rng.choice(status_values, size=rows, p=status_probabilities)
    for month in range(1, 6):
        change = rng.choice([-1, 0, 1], size=rows, p=[0.12, 0.76, 0.12])
        statuses[:, month] = np.clip(statuses[:, month - 1] + change, -2, 8)

    baseline_utilization = rng.uniform(0.0, 1.15, size=rows)
    bills = np.empty((rows, 6), dtype=np.int64)
    payments = np.empty((rows, 6), dtype=np.int64)
    for month in range(6):
        utilization = baseline_utilization + rng.normal(0.0, 0.12, size=rows)
        bill = np.rint(limits * utilization + rng.normal(0.0, 1000.0, size=rows))
        refund = rng.random(rows) < 0.04
        bill = np.where(refund, -np.abs(bill) - rng.integers(100, 5000, size=rows), bill)
        bills[:, month] = bill.astype(np.int64)
        payment_fraction = rng.choice([0.0, 0.05, 0.2, 0.5, 1.0], size=rows, p=[0.15, 0.25, 0.30, 0.20, 0.10])
        payments[:, month] = np.rint(np.abs(bill) * payment_fraction).astype(np.int64)

    risk_group = np.select(
        [statuses[:, 0] <= -2, statuses[:, 0] == -1, statuses[:, 0] == 0, statuses[:, 0] == 1, statuses[:, 0] >= 2],
        [0, 1, 2, 3, 4],
    )
    group_default_frequencies = np.array([0.04, 0.08, 0.16, 0.30, 0.50])
    default_flag = (rng.random(rows) < group_default_frequencies[risk_group]).astype(np.int64)
    if not np.any(default_flag == 0):
        default_flag[0] = 0
    if not np.any(default_flag == 1):
        default_flag[1] = 1

    values = {
        "ID": np.arange(1, rows + 1, dtype=np.int64),
        "LIMIT_BAL": limits.astype(np.int64),
        "SEX": sex.astype(np.int64),
        "EDUCATION": education.astype(np.int64),
        "MARRIAGE": marriage.astype(np.int64),
        "AGE": age.astype(np.int64),
        "PAY_0": statuses[:, 0],
        **{f"PAY_{month}": statuses[:, month - 1] for month in range(2, 7)},
        **{f"BILL_AMT{month}": bills[:, month - 1] for month in range(1, 7)},
        **{f"PAY_AMT{month}": payments[:, month - 1] for month in range(1, 7)},
        "default payment next month": default_flag,
    }
    return pd.DataFrame(values, columns=RAW_COLUMNS)


def _transform_raw(raw: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in RAW_COLUMNS if column not in raw.columns]
    if missing:
        raise ValueError(f"Missing UCI columns: {missing}")

    frame = raw.loc[:, RAW_COLUMNS].rename(columns=COLUMN_RENAME).copy()
    for column in RENAMED_COLUMNS:
        numeric = pd.to_numeric(frame[column], errors="raise")
        values = numeric.to_numpy(dtype=np.float64)
        if not np.all(np.isfinite(values)):
            raise ValueError(f"Non-finite values in {column}")
        if not np.all(values == np.floor(values)):
            raise ValueError(f"Non-integer values in {column}")
        frame[column] = values.astype(np.int64)

    if frame["client_id"].duplicated().any():
        raise ValueError("client_id values must be unique")
    if not frame["default_flag"].isin([0, 1]).all():
        raise ValueError("default_flag must contain only 0 and 1")
    if (frame["limit_bal"] <= 0).any():
        raise ValueError("limit_bal must be positive")
    if (frame[[f"pay_amt_{month}" for month in range(1, 7)]] < 0).any().any():
        raise ValueError("pay_amt values must be non-negative")
    if (frame["age"] < 21).any():
        raise ValueError("age must be at least 21")

    frame["education"] = frame["education"].replace({0: 4, 5: 4, 6: 4})
    frame["marriage"] = frame["marriage"].replace({0: 3})
    frame["log_limit"] = np.log1p(frame["limit_bal"].astype(np.float64))
    for month in range(1, 7):
        frame[f"delay_{month}"] = frame[f"pay_status_{month}"].clip(lower=0)
        utilization = frame[f"bill_amt_{month}"].astype(np.float64) / frame["limit_bal"].astype(np.float64)
        frame[f"util_{month}"] = utilization.clip(0.0, 2.0)
        frame[f"log_pay_{month}"] = np.log1p(frame[f"pay_amt_{month}"].astype(np.float64))

    age = frame["age"]
    frame["age_band"] = np.select(
        [age.between(21, 25), age.between(26, 35), age.between(36, 50), age >= 51],
        ["21-25", "26-35", "36-50", "51+"],
        default=None,
    )
    if frame["age_band"].isna().any():
        raise ValueError("Could not assign age_band")
    return frame.loc[:, OUTPUT_COLUMNS]


def _stratified_counts(available: dict[int, int], size: int) -> dict[int, int]:
    total = sum(available.values())
    if size < 0 or size > total or total == 0:
        raise ValueError("Invalid stratified split size")
    quotas = {label: size * count / total for label, count in available.items()}
    counts = {label: int(np.floor(quota)) for label, quota in quotas.items()}
    remainder = size - sum(counts.values())
    order = sorted(available, key=lambda label: (-(quotas[label] - counts[label]), label))
    while remainder:
        progressed = False
        for label in order:
            if counts[label] < available[label] and remainder:
                counts[label] += 1
                remainder -= 1
                progressed = True
        if not progressed:
            raise ValueError("Could not allocate stratified split")
    return counts


def _excluded_holdout_ids(config: dict) -> tuple[set[str], list[dict]]:
    """Load previously consumed Holdout ids so the next Holdout cannot reuse them."""

    specification = config.get("holdout_exclusion")
    if not isinstance(specification, dict) or specification.get("enabled") is not True:
        return set(), []
    sources = specification.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("holdout_exclusion.sources must list the consumed Holdout files")
    repository = _config_path().parents[1]
    identifiers: set[str] = set()
    records: list[dict] = []
    for relative in sources:
        path = (repository / str(relative)).resolve()
        if not path.is_file():
            raise ValueError(f"Consumed Holdout source is missing: {relative}")
        values = pd.read_csv(path, usecols=["client_id"])["client_id"].astype(str)
        identifiers.update(values.tolist())
        records.append({"path": str(relative), "sha256": _sha256_file(path), "rows": int(len(values)), "ids": set(values.tolist())})
    return identifiers, records


def _holdout_exclusion_block(config: dict, frames: dict[str, pd.DataFrame], records: list[dict]) -> dict:
    specification = config.get("holdout_exclusion") or {}
    holdout_ids = set(frames["holdout"]["client_id"].astype(str).tolist())
    return {
        "enabled": bool(specification.get("enabled")),
        "rule": specification.get("rule"),
        "sources": [{key: value for key, value in record.items() if key != "ids"} for record in records],
        "holdout_rows": int(len(holdout_ids)),
        "overlap": {record["path"]: int(len(holdout_ids & record["ids"])) for record in records},
        "overlap_total": int(sum(len(holdout_ids & record["ids"]) for record in records)),
    }


def _split_frame(frame: pd.DataFrame, rng: np.random.Generator, excluded_client_ids=frozenset()) -> dict[str, pd.DataFrame]:
    """Stratified split with an optional exclusion set for previously consumed Holdouts.

    The Holdout is drawn first, and only from rows that no earlier campaign has
    already consumed as a Holdout. The remaining split sizes are unchanged, so
    the exclusion changes which rows form the Holdout, not the split contract.
    """

    if len(frame) != TOTAL_ROWS:
        raise ValueError(f"Expected exactly {TOTAL_ROWS} rows, got {len(frame)}")
    if frame["client_id"].duplicated().any():
        raise ValueError("client_id values must be unique")
    if set(frame["default_flag"].unique()) != {0, 1}:
        raise ValueError("Both default classes are required")

    labels = frame["default_flag"].to_numpy()
    excluded_mask = frame["client_id"].astype(str).isin(excluded_client_ids).to_numpy()
    allowed_positions = np.flatnonzero(~excluded_mask)
    if len(allowed_positions) < SPLIT_SIZES["holdout"]:
        raise ValueError("Too few rows remain once consumed Holdout rows are excluded")

    holdout_pools = {
        label: rng.permutation(allowed_positions[labels[allowed_positions] == label])
        for label in (0, 1)
    }
    holdout_counts = _stratified_counts(
        {label: len(pool) for label, pool in holdout_pools.items()}, SPLIT_SIZES["holdout"]
    )
    holdout_positions = np.concatenate(
        [holdout_pools[label][: holdout_counts[label]] for label in sorted(holdout_pools)]
    )
    holdout_mask = np.zeros(len(frame), dtype=bool)
    holdout_mask[holdout_positions] = True

    rest_positions = np.flatnonzero(~holdout_mask)
    rest_labels = labels[rest_positions]
    remaining = {
        label: rng.permutation(np.flatnonzero(rest_labels == label))
        for label in (0, 1)
    }
    splits = {
        "holdout": frame.iloc[np.sort(holdout_positions)]
        .sort_values("client_id", kind="mergesort")
        .reset_index(drop=True)
    }
    for split_name in ("train", "dev", "shift_pool"):
        available = {label: len(indices) for label, indices in remaining.items()}
        counts = _stratified_counts(available, SPLIT_SIZES[split_name])
        selected = {label: remaining[label][: counts[label]] for label in remaining}
        remaining = {label: remaining[label][counts[label]:] for label in remaining}
        positions = np.concatenate([selected[label] for label in sorted(selected)])
        splits[split_name] = (
            frame.iloc[rest_positions[positions]]
            .sort_values("client_id", kind="mergesort")
            .reset_index(drop=True)
        )
    return {name: splits[name] for name in SPLIT_SIZES}


def validate_splits(frames: dict[str, pd.DataFrame]) -> dict:
    errors = []
    row_counts = {}
    identifiers = {}
    default_rates = {}
    for split_name, expected_size in SPLIT_SIZES.items():
        if split_name not in frames:
            errors.append(f"Missing split: {split_name}")
            row_counts[split_name] = 0
            identifiers[split_name] = set()
            default_rates[split_name] = None
            continue
        frame = frames[split_name]
        row_counts[split_name] = int(len(frame))
        if len(frame) != expected_size:
            errors.append(f"{split_name}: expected {expected_size} rows, got {len(frame)}")
        required = {"client_id", "default_flag"}
        if not required.issubset(frame.columns):
            errors.append(f"{split_name}: missing client_id or default_flag")
            identifiers[split_name] = set()
            default_rates[split_name] = None
            continue
        if frame["client_id"].isna().any():
            errors.append(f"{split_name}: null client_id")
        identifiers[split_name] = set(frame["client_id"].dropna().tolist())
        if len(identifiers[split_name]) != len(frame):
            errors.append(f"{split_name}: duplicate client_id")
        labels = frame["default_flag"]
        if labels.isna().any() or not labels.isin([0, 1]).all():
            errors.append(f"{split_name}: default_flag must contain only 0 and 1")
            default_rates[split_name] = None
        elif frame.empty:
            errors.append(f"{split_name}: empty split")
            default_rates[split_name] = None
        else:
            default_rates[split_name] = float(labels.mean())

    for unexpected in sorted(set(frames) - set(SPLIT_SIZES)):
        errors.append(f"Unexpected split: {unexpected}")
    names = list(SPLIT_SIZES)
    mutually_exclusive = True
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            if identifiers[left] & identifiers[right]:
                mutually_exclusive = False
                errors.append(f"Overlapping client_id values: {left}/{right}")

    total_rows = sum(row_counts.values())
    if total_rows != TOTAL_ROWS:
        errors.append(f"Expected {TOTAL_ROWS} total rows, got {total_rows}")
    rates_available = all(default_rates[name] is not None for name in names)
    if rates_available:
        combined = pd.concat([frames[name]["default_flag"] for name in names], ignore_index=True)
        overall_default_rate = float(combined.mean())
        max_difference = float(max(abs(default_rates[name] - overall_default_rate) for name in names))
        rates_within_tolerance = max_difference <= DEFAULT_RATE_TOLERANCE
        if not rates_within_tolerance:
            errors.append("A split default rate differs from overall by more than 0.01")
    else:
        overall_default_rate = None
        max_difference = None
        rates_within_tolerance = False

    return {
        "valid": not errors,
        "errors": errors,
        "row_counts": row_counts,
        "total_rows": int(total_rows),
        "mutually_exclusive": mutually_exclusive,
        "default_rates": default_rates,
        "overall_default_rate": overall_default_rate,
        "max_abs_default_rate_difference": max_difference,
        "default_rate_tolerance": DEFAULT_RATE_TOLERANCE,
        "default_rates_within_tolerance": rates_within_tolerance,
    }


def _encoding_counts(frame: pd.DataFrame) -> dict[str, dict[str, int]]:
    columns = ["sex", "education", "marriage", *[f"pay_status_{month}" for month in range(1, 7)]]
    result = {}
    for column in columns:
        counts = frame[column].value_counts().sort_index()
        result[column] = {str(int(code)): int(count) for code, count in counts.items()}
    return result


def _encoding_recodes(raw: pd.DataFrame) -> dict[str, dict[str, int]]:
    return {
        "education": {
            f"{code}_to_4": int((raw["EDUCATION"] == code).sum())
            for code in [0, 5, 6]
        },
        "marriage": {"0_to_3": int((raw["MARRIAGE"] == 0).sum())},
    }


def _data_dictionary(data_kind: str, synthetic: bool) -> dict:
    descriptions = {
        "client_id": ("ID", "Unique row identifier", "identifier"),
        "limit_bal": ("LIMIT_BAL", "Credit limit in NT dollars", "feature"),
        "sex": ("SEX", "1=male, 2=female", "audit_only"),
        "education": ("EDUCATION", "1=graduate, 2=university, 3=high school, 4=other", "audit_only"),
        "marriage": ("MARRIAGE", "1=married, 2=single, 3=other", "audit_only"),
        "age": ("AGE", "Age in years", "audit_only"),
        "default_flag": ("default payment next month", "1=default in the next month", "target"),
    }
    columns = {}
    for raw_name, name in COLUMN_RENAME.items():
        if name in descriptions:
            source, description, usage = descriptions[name]
        elif name.startswith("pay_status_"):
            source, description, usage = raw_name, "Repayment status; -2 and 0 have no official definition", "feature"
        elif name.startswith("bill_amt_"):
            source, description, usage = raw_name, "Bill amount in NT dollars; negative values are valid", "feature"
        else:
            source, description, usage = raw_name, "Payment amount in NT dollars", "feature"
        columns[name] = {"source": source, "description": description, "usage": usage}

    columns["log_limit"] = {"formula": "log1p(limit_bal)", "usage": "feature"}
    for month in range(1, 7):
        columns[f"delay_{month}"] = {"formula": f"max(pay_status_{month}, 0)", "usage": "feature"}
        columns[f"util_{month}"] = {"formula": f"clip(bill_amt_{month} / limit_bal, 0, 2)", "usage": "feature"}
        columns[f"log_pay_{month}"] = {"formula": f"log1p(pay_amt_{month})", "usage": "feature"}
    columns["age_band"] = {"formula": "21-25, 26-35, 36-50, 51+", "usage": "audit_only"}
    return {
        "schema_version": SCHEMA_VERSION,
        "model_id": MODEL_ID,
        "data_kind": data_kind,
        "synthetic": synthetic,
        "raw_fields": RAW_COLUMNS,
        "column_order": OUTPUT_COLUMNS,
        "columns": columns,
        "audit_only_columns": AUDIT_COLUMNS,
        "encoding_recodes": {
            "education": {"0": 4, "5": 4, "6": 4},
            "marriage": {"0": 3},
        },
        "pay_status_note": "PAY_0 maps to pay_status_1; PAY_2 through PAY_6 map to pay_status_2 through pay_status_6.",
        "limitations": (
            "Synthetic development data only; no real customer records and no formal-model label formula."
            if synthetic
            else "Taiwanese 2005 credit card data; demographic columns are for audit only and are not model features."
        ),
    }


def _source_text(
    data_kind: str,
    seed: int,
    input_path: Path | None = None,
    source_path: Path | None = None,
    original_sha256: str | None = None,
) -> str:
    if data_kind == "synthetic":
        return (
            "# Data source\n\n"
            "Data kind: **synthetic**.\n\n"
            f"Generated locally with NumPy `default_rng({seed})` for development only. "
            "No UCI file, real customer record, or real UCI data row was read or used. "
            "Labels use categorical frequencies, not a formal model formula. "
            "Formal status: **BLOCKED**.\n"
        )
    provenance = source_path or input_path
    assert provenance is not None
    downloaded = datetime.fromtimestamp(provenance.stat().st_mtime, timezone.utc).date().isoformat()
    processed = datetime.now(timezone.utc).date().isoformat()
    return (
        "# Data source\n\n"
        "Dataset: Default of Credit Card Clients, UCI Machine Learning Repository (ID 350).\n\n"
        f"Landing page: {UCI_LANDING_URL}\n\n"
        f"Original publication: {UCI_CITATION}\n\n"
        "License: **CC BY 4.0** (https://creativecommons.org/licenses/by/4.0/).\n\n"
        f"Local source: `{provenance}`\n\n"
        f"Download date (UTC date of the local source file timestamp): {downloaded}\n\n"
        f"Processing date (UTC): {processed}\n\n"
        f"Original input SHA-256: `{original_sha256}`\n\n"
        "Processing: .xls read with header=1, documented recodes and derivations applied, "
        "then stratified deterministic splitting. Demographic fields are retained for audit only.\n"
    )


def _write_outputs(
    frames: dict[str, pd.DataFrame],
    raw: pd.DataFrame,
    output_dir: Path,
    seed: int,
    data_kind: str,
    synthetic: bool,
    config_sha256: str,
    input_path: Path | None = None,
    source_path: Path | None = None,
    original_sha256: str | None = None,
) -> dict:
    validation = validate_splits(frames)
    if not validation["valid"]:
        raise ValueError(f"Invalid data splits: {validation['errors']}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for split_name, frame in frames.items():
        filename = f"{split_name}.csv"
        path = output_dir / filename
        frame.to_csv(path, index=False, lineterminator="\n", float_format="%.17g")
        files[filename] = {
            "sha256": _sha256_file(path),
            "rows": int(len(frame)),
            "default_rate": float(frame["default_flag"].mean()),
        }

    dictionary = _data_dictionary(data_kind, synthetic)
    _write_json(output_dir / "data_dictionary.json", dictionary)
    (output_dir / "SOURCE.md").write_text(
        _source_text(data_kind, seed, input_path, source_path, original_sha256),
        encoding="utf-8",
    )

    combined = pd.concat(list(frames.values()), ignore_index=True)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "model_id": MODEL_ID,
        "data_kind": data_kind,
        "synthetic": synthetic,
        "formal_status": "BLOCKED" if synthetic else "APPROVED",
        "seed": int(seed),
        "files": files,
        "overall": {
            "rows": int(len(combined)),
            "unique_client_ids": int(combined["client_id"].nunique()),
            "default_count": int(combined["default_flag"].sum()),
            "default_rate": float(combined["default_flag"].mean()),
        },
        "config_sha256": config_sha256,
        "encoding_counts": _encoding_counts(combined),
        "encoding_recodes": _encoding_recodes(raw),
        "split_validation": validation,
        "source": {
            "contains_real_data": not synthetic,
            "landing_url": None if synthetic else UCI_LANDING_URL,
            "license": None if synthetic else "CC BY 4.0",
            "original_sha256": original_sha256,
        },
    }
    _write_json(output_dir / "data_manifest.json", manifest)
    return manifest


def prepare_synthetic(output_dir: Path, seed: int = DEFAULT_SEED) -> dict:
    _, config_sha256 = _load_config()
    rng = np.random.default_rng(seed)
    raw = _generate_synthetic_raw(rng)
    frame = _transform_raw(raw)
    frames = _split_frame(frame, rng, frozenset())
    return _write_outputs(
        frames,
        raw,
        Path(output_dir),
        int(seed),
        "synthetic",
        True,
        config_sha256,
    )


def _validate_zip_member(info: zipfile.ZipInfo) -> None:
    name = info.filename
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or path.is_absolute()
        or ".." in path.parts
        or (path.parts and path.parts[0].endswith(":"))
        or stat.S_ISLNK(info.external_attr >> 16)
    ):
        raise ValueError(f"Unsafe ZIP member: {name!r}")


def _read_uci_zip(input_path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(input_path) as archive:
        members = archive.infolist()
        for member in members:
            _validate_zip_member(member)
        xls_members = [
            member
            for member in members
            if not member.is_dir() and PurePosixPath(member.filename).suffix.lower() == ".xls"
        ]
        if len(xls_members) != 1:
            raise ValueError(f"Expected exactly one .xls file in ZIP, found {len(xls_members)}")
        content = archive.read(xls_members[0])
    return pd.read_excel(io.BytesIO(content), header=1, engine="xlrd")


def _read_uci(input_path: Path) -> pd.DataFrame:
    suffix = input_path.suffix.lower()
    if suffix == ".xls":
        return pd.read_excel(input_path, header=1, engine="xlrd")
    if suffix == ".zip":
        return _read_uci_zip(input_path)
    raise ValueError("UCI input must be an .xls file or a .zip containing exactly one .xls file")


def prepare_uci(
    input_path: Path,
    output_dir: Path,
    approved: bool,
    expected_sha256: str,
    source_path: Path | None = None,
    run_id: str | None = None,
) -> dict:
    if not approved:
        raise PermissionError("UCI competition use has not been approved")
    if expected_sha256 is None or not str(expected_sha256).strip():
        raise ValueError("expected_sha256 is required before reading UCI data")
    expected = str(expected_sha256).strip().lower()
    if not SHA256_PATTERN.fullmatch(expected):
        raise ValueError("expected_sha256 must be a 64-character hexadecimal SHA-256 digest")

    input_path = Path(input_path)
    actual_sha256 = _sha256_file(input_path)
    if not hmac.compare_digest(actual_sha256, expected):
        raise ValueError(
            f"UCI input SHA-256 mismatch: expected {expected}, got {actual_sha256}"
        )
    raw = _read_uci(input_path)
    frame = _transform_raw(raw)
    config, config_sha256 = _load_config()
    seed = int(config["seed"])
    rng = np.random.default_rng(seed)
    excluded_ids, exclusion_records = _excluded_holdout_ids(config)
    frames = _split_frame(frame, rng, excluded_ids)
    provenance = Path(source_path) if source_path is not None else input_path
    manifest = _write_outputs(
        frames,
        raw,
        Path(output_dir),
        seed,
        "uci",
        False,
        config_sha256,
        input_path,
        provenance,
        actual_sha256,
    )
    approval = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "model_id": MODEL_ID,
        "approved": True,
        "approved_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "declaration": "Operator confirmed the organiser permits UCI data use for this entry (--approve-uci-use)",
        "license": "CC BY 4.0",
        "landing_url": UCI_LANDING_URL,
        "expected_sha256": expected,
        "input_sha256": actual_sha256,
        "source_path": str(provenance),
    }
    _write_json(Path(output_dir) / "uci_approval.json", approval)
    manifest["uci_approval_sha256"] = _sha256_file(Path(output_dir) / "uci_approval.json")
    manifest["holdout_exclusion"] = _holdout_exclusion_block(config, frames, exclusion_records)
    _write_json(Path(output_dir) / "data_manifest.json", manifest)
    return manifest


def download_uci(
    output_path: Path,
    approved: bool,
    expected_sha256: str,
    url: str = UCI_ZIP_URL,
    timeout_seconds: int = 60,
) -> dict:
    if not approved:
        raise PermissionError("UCI competition use has not been approved; download is disabled")
    expected = str(expected_sha256 or "").strip().lower()
    if not SHA256_PATTERN.fullmatch(expected):
        raise ValueError("expected_sha256 must be a 64-character hexadecimal SHA-256 digest")
    if not url.startswith("https://"):
        raise ValueError("UCI download URL must use HTTPS")
    import urllib.request

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".partial")
    temporary.unlink(missing_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response, temporary.open("wb") as handle:
            total = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > 100 * 1024 * 1024:
                    raise ValueError("UCI download exceeds the 100 MiB safety limit")
                handle.write(chunk)
            request_id = response.headers.get("x-request-id")
        actual = _sha256_file(temporary)
        if not hmac.compare_digest(actual, expected):
            raise ValueError(f"UCI download SHA-256 mismatch: expected {expected}, got {actual}")
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"url": url, "path": str(output_path), "sha256": actual, "bytes": output_path.stat().st_size, "request_id": request_id}
