"""Deterministic validation metrics for v2 (SOP §9 / V2-03).

Every number in ``validation_metrics.json`` is computed here from files on disk:
parity is recomputed from the reference and candidate prediction files, and
performance, calibration, stability and fairness are computed with plain NumPy
so the arithmetic has no hidden model or library default. Each metric carries a
``value``, a ``status`` and a ``reason`` so that a missing label, a single class,
a zero denominator or a small group is reported instead of silently producing a
number.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from src.common import ContractError, read_json, sha256_file, utc_now, write_json
from src.parity import compare_files
from src.runner import run_candidate

OK = "OK"
NOT_ASSESSABLE = "NOT_ASSESSABLE"
LOW_SAMPLE = "LOW_SAMPLE"
MISSING_LABELS = "MISSING_LABELS"
SINGLE_CLASS = "SINGLE_CLASS"
ZERO_DENOMINATOR = "ZERO_DENOMINATOR"
FAIL = "FAIL"

MIN_GROUP_ROWS = 30
MIN_CLASS_ROWS = 5
PSI_BINS = 10
PSI_PSEUDOCOUNT = 0.5
PSI_ATTENTION = 0.10
PSI_REVIEW = 0.25
PSI_FEATURES = ("limit_bal", "log_limit", "util_1", "delay_1", "log_pay_1")
AUDIT_ATTRIBUTES = ("age_band", "sex")


def metric(value, status: str = OK, reason: str | None = None, **extra) -> dict:
    return {"value": value, "status": status, "reason": reason, **extra}


def _finite(value: float | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _read_predictions(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    for column in ("client_id", "probability", "classification", "status"):
        if column not in frame.columns:
            raise ContractError(f"{path.name} is missing the {column} column")
    frame["probability"] = pd.to_numeric(frame["probability"], errors="coerce")
    return frame


def _labels(frame: pd.DataFrame) -> pd.Series:
    if "default_flag" not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="Float64")
    return pd.to_numeric(frame["default_flag"], errors="coerce")


def _joined(dataset: Path, predictions: Path) -> pd.DataFrame:
    # client_id is written as an integer by the data pipeline and as text in the
    # prediction files; both sides must be strings before the join.
    data = pd.read_csv(dataset, dtype={"client_id": str})
    predicted = _read_predictions(predictions)
    merged = data.merge(predicted[["client_id", "probability", "classification", "status"]], on="client_id", how="left", validate="one_to_one")
    return merged


def roc_auc(labels: np.ndarray, probabilities: np.ndarray) -> float:
    """Rank-based (Mann-Whitney) AUC with average ranks for ties."""

    order = np.argsort(probabilities, kind="mergesort")
    ranks = np.empty(len(probabilities), dtype=float)
    sorted_probabilities = probabilities[order]
    start = 0
    while start < len(sorted_probabilities):
        end = start
        while end + 1 < len(sorted_probabilities) and sorted_probabilities[end + 1] == sorted_probabilities[start]:
            end += 1
        average_rank = (start + end) / 2.0 + 1.0
        ranks[order[start : end + 1]] = average_rank
        start = end + 1
    positives = int(labels.sum())
    negatives = len(labels) - positives
    rank_sum = float(ranks[labels == 1].sum())
    return (rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)


def brier_score(labels: np.ndarray, probabilities: np.ndarray) -> float:
    return float(np.mean((probabilities - labels) ** 2))


def confusion_matrix(labels: np.ndarray, predictions: np.ndarray) -> dict:
    tp = int(np.sum((labels == 1) & (predictions == 1)))
    fp = int(np.sum((labels == 0) & (predictions == 1)))
    tn = int(np.sum((labels == 0) & (predictions == 0)))
    fn = int(np.sum((labels == 1) & (predictions == 0)))
    return {"true_positive": tp, "false_positive": fp, "true_negative": tn, "false_negative": fn}


def calibration_deciles(labels: np.ndarray, probabilities: np.ndarray, client_ids: np.ndarray) -> list[dict]:
    order = np.lexsort((client_ids.astype(str), probabilities))
    groups = np.array_split(order, 10)
    rows = []
    for index, positions in enumerate(groups, start=1):
        if len(positions) == 0:
            rows.append({"decile": index, "rows": 0, "mean_probability": None, "observed_default_rate": None, "min_probability": None, "max_probability": None})
            continue
        group_probability = probabilities[positions]
        group_labels = labels[positions]
        rows.append({
            "decile": index,
            "rows": int(len(positions)),
            "mean_probability": _finite(group_probability.mean()),
            "observed_default_rate": _finite(group_labels.mean()),
            "min_probability": _finite(group_probability.min()),
            "max_probability": _finite(group_probability.max()),
            "absolute_gap": _finite(abs(group_probability.mean() - group_labels.mean())),
        })
    return rows


def performance_metrics(labels, probabilities, threshold: float) -> dict:
    labels_series = pd.Series(labels)
    usable = labels_series.notna().to_numpy() & np.isfinite(probabilities)
    labels_clean = labels_series.fillna(0).to_numpy().astype(int)[usable]
    probabilities_clean = probabilities[usable]
    rows = int(len(labels_clean))
    positives = int(labels_clean.sum()) if rows else 0
    negatives = rows - positives
    result = {
        "rows": rows,
        "positive_rows": positives,
        "negative_rows": negatives,
        "observed_default_rate": _finite(positives / rows) if rows else None,
        "threshold": threshold,
        "roc_auc": metric(None),
        "brier_score": metric(None),
        "confusion_matrix": metric(None),
        "calibration": metric(None),
    }
    if rows == 0:
        result["roc_auc"] = metric(None, MISSING_LABELS, "no labelled rows with a usable probability")
        result["brier_score"] = metric(None, MISSING_LABELS, "no labelled rows with a usable probability")
        result["confusion_matrix"] = metric(None, MISSING_LABELS, "no labelled rows")
        result["calibration"] = metric(None, MISSING_LABELS, "no labelled rows")
        return result
    if positives == 0 or negatives == 0:
        result["roc_auc"] = metric(None, SINGLE_CLASS, "ROC-AUC needs both classes")
    else:
        result["roc_auc"] = metric(_finite(roc_auc(labels_clean, probabilities_clean)))
    result["brier_score"] = metric(_finite(brier_score(labels_clean, probabilities_clean)))
    predictions = (probabilities_clean >= threshold).astype(int)
    matrix = confusion_matrix(labels_clean, predictions)
    result["confusion_matrix"] = metric(matrix)
    result["calibration"] = metric(calibration_deciles(labels_clean, probabilities_clean, np.arange(rows)))
    return result


def psi(reference: np.ndarray, comparison: np.ndarray, bins: int = PSI_BINS, pseudocount: float = PSI_PSEUDOCOUNT) -> dict:
    reference = reference[np.isfinite(reference)]
    comparison = comparison[np.isfinite(comparison)]
    if len(reference) == 0 or len(comparison) == 0:
        return metric(None, NOT_ASSESSABLE, "one side of the comparison has no finite values")
    quantiles = np.unique(np.quantile(reference, np.linspace(0, 1, bins + 1)))
    if len(quantiles) < 3:
        return metric(None, NOT_ASSESSABLE, "the reference distribution has fewer than two distinct values")
    edges = quantiles.copy()
    edges[0] = -np.inf
    edges[-1] = np.inf
    reference_counts = np.histogram(reference, bins=edges)[0].astype(float)
    comparison_counts = np.histogram(comparison, bins=edges)[0].astype(float)
    reference_share = (reference_counts + pseudocount) / (reference_counts.sum() + pseudocount * len(edges[:-1]))
    comparison_share = (comparison_counts + pseudocount) / (comparison_counts.sum() + pseudocount * len(edges[:-1]))
    value = float(np.sum((comparison_share - reference_share) * np.log(comparison_share / reference_share)))
    return metric(
        _finite(value),
        **{
            "bins": int(len(edges) - 1),
            "requested_bins": bins,
            "pseudocount": pseudocount,
            "reference_rows": int(len(reference)),
            "comparison_rows": int(len(comparison)),
            "reference_share": [_finite(item) for item in reference_share],
            "comparison_share": [_finite(item) for item in comparison_share],
            "edges": [(_finite(edge) if np.isfinite(edge) else None) for edge in edges],
        },
    )


def _psi_state(value: dict) -> str:
    if value["status"] != OK or value["value"] is None:
        return value["status"]
    if value["value"] >= PSI_REVIEW:
        return "REVALIDATION_REQUIRED"
    if value["value"] >= PSI_ATTENTION:
        return "REVIEW_HIGHLIGHTED"
    return OK


def group_rates(labels: np.ndarray, predictions: np.ndarray) -> dict:
    positives = labels == 1
    negatives = labels == 0
    tp = int(np.sum(positives & (predictions == 1)))
    fn = int(np.sum(positives & (predictions == 0)))
    fp = int(np.sum(negatives & (predictions == 1)))
    tn = int(np.sum(negatives & (predictions == 0)))
    rows = int(len(labels))
    result = {
        "rows": rows,
        "positive_rows": int(positives.sum()),
        "negative_rows": int(negatives.sum()),
        "true_positive": tp,
        "false_positive": fp,
        "true_negative": tn,
        "false_negative": fn,
        "tpr": metric(None),
        "fpr": metric(None),
    }
    if rows < MIN_GROUP_ROWS:
        result["sample_status"] = LOW_SAMPLE
        result["sample_reason"] = f"fewer than {MIN_GROUP_ROWS} labelled rows"
    else:
        result["sample_status"] = OK
        result["sample_reason"] = None
    if result["positive_rows"] == 0:
        result["tpr"] = metric(None, ZERO_DENOMINATOR, "group has no positive rows")
    elif result["positive_rows"] < MIN_CLASS_ROWS:
        result["tpr"] = metric(None, LOW_SAMPLE, f"fewer than {MIN_CLASS_ROWS} positive rows")
    else:
        result["tpr"] = metric(_finite(tp / (tp + fn)))
    if result["negative_rows"] == 0:
        result["fpr"] = metric(None, ZERO_DENOMINATOR, "group has no negative rows")
    elif result["negative_rows"] < MIN_CLASS_ROWS:
        result["fpr"] = metric(None, LOW_SAMPLE, f"fewer than {MIN_CLASS_ROWS} negative rows")
    else:
        result["fpr"] = metric(_finite(fp / (fp + tn)))
    return result


def fairness_metrics(frame: pd.DataFrame, threshold: float, reference_groups: dict) -> dict:
    labels = _labels(frame)
    probabilities = frame["probability"].astype(float).to_numpy()
    usable = labels.notna().to_numpy() & np.isfinite(probabilities)
    labels_clean = labels.fillna(0).to_numpy().astype(int)[usable]
    probabilities_clean = probabilities[usable]
    predictions = (probabilities_clean >= threshold).astype(int)
    subset = frame.loc[usable]
    report = {}
    for attribute in AUDIT_ATTRIBUTES:
        reference_group = reference_groups.get(attribute)
        groups = {}
        if attribute not in subset.columns:
            report[attribute] = metric(None, NOT_ASSESSABLE, f"{attribute} is not present in the dataset")
            continue
        values = subset[attribute].astype(str).to_numpy()
        for value in sorted(set(values)):
            mask = values == value
            groups[value] = group_rates(labels_clean[mask], predictions[mask])
        baseline = groups.get(reference_group) if reference_group is not None else None
        differences = {}
        for value, rates in groups.items():
            entry = {}
            for name in ("tpr", "fpr"):
                if baseline is None or rates[name]["value"] is None or baseline[name]["value"] is None:
                    entry[name] = metric(None, NOT_ASSESSABLE, "reference group metric is not assessable")
                else:
                    entry[name] = metric(_finite(rates[name]["value"] - baseline[name]["value"]), OK, f"difference from {reference_group}")
            differences[value] = entry
        report[attribute] = {
            "status": OK,
            "reference_group": reference_group,
            "reference_source": "train.csv",
            "groups": groups,
            "differences": differences,
        }
    return report


def reference_groups_from_train(train: pd.DataFrame) -> dict:
    reference = {}
    for attribute in AUDIT_ATTRIBUTES:
        if attribute not in train.columns:
            reference[attribute] = None
            continue
        counts = train[attribute].astype(str).value_counts()
        reference[attribute] = str(counts.idxmax()) if len(counts) else None
    return reference


def build_shifted_batch(data_dir: Path, output_path: Path, settings: dict) -> dict:
    """Scenario A: weighted sample of ``shift_pool`` that keeps the real labels."""

    source = data_dir / "shift_pool.csv"
    if not source.is_file():
        raise ContractError("shift_pool.csv is required to build the drift batch")
    frame = pd.read_csv(source)
    rows = int(settings["rows"])
    seed = int(settings["seed"])
    util_weight = float(settings["util_weight"])
    limit_weight = float(settings["limit_weight"])
    if rows > len(frame):
        raise ContractError("The drift batch is larger than the shift pool")
    limit = frame["limit_bal"].astype(float).to_numpy()
    util = frame["util_1"].astype(float).to_numpy()
    scale = float(np.max(limit)) if len(limit) else 1.0
    weights = (1.0 + util_weight * np.clip(util, 0, 2)) * (1.0 + limit_weight * (1.0 - limit / scale))
    weights = weights / weights.sum()
    rng = np.random.default_rng(seed)
    positions = rng.choice(len(frame), size=rows, replace=False, p=weights)
    selected = frame.iloc[np.sort(positions)].reset_index(drop=True)
    selected.to_csv(output_path, index=False, lineterminator="\n", float_format="%.17g")
    return {
        "scenario": "A",
        "description": "weighted subsample of shift_pool biased towards high util_1 and low limit_bal; real labels retained",
        "source": source.name,
        "source_sha256": sha256_file(source),
        "rows": int(len(selected)),
        "seed": seed,
        "weights": {"util_weight": util_weight, "limit_weight": limit_weight, "formula": "(1 + util_weight*clip(util_1,0,2)) * (1 + limit_weight*(1 - limit_bal/max_limit_bal))"},
        "selected_weights_sha256": None,
        "output_sha256": sha256_file(output_path),
        "output_path": output_path.name,
        "default_rate": _finite(float(selected["default_flag"].mean())),
    }


def _parity_entry(run_dir: Path, reference_path: Path, candidate_path: Path, dataset_path: Path, output_dir: Path, label: str, tolerances: dict, run_id: str) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "parity_summary.json"
    diff_path = output_dir / "parity_diff.csv"
    summary = compare_files(reference_path, candidate_path, summary_path, diff_path, run_id=run_id, input_path=dataset_path)
    return {
        "dataset": label,
        "status": summary["status"],
        "max_abs_diff": _finite(summary.get("max_abs_diff")),
        "mean_abs_diff": _finite(summary.get("mean_abs_diff")),
        "classification_mismatch_count": summary.get("classification_mismatch_count"),
        "behaviour_mismatch_count": summary.get("behaviour_mismatch_count"),
        "valid_probability_pairs": summary.get("valid_probability_pairs"),
        "id_sets_match": summary.get("id_sets_match"),
        "rows": summary.get("n"),
        "reasons": summary.get("reasons", []),
        "limits": {"max_abs_diff": tolerances["max_abs_diff"], "mean_abs_diff": tolerances["mean_abs_diff"]},
        "evidence": {
            "summary": str(summary_path.relative_to(run_dir)),
            "summary_sha256": sha256_file(summary_path),
            "diff": str(diff_path.relative_to(run_dir)),
            "diff_sha256": sha256_file(diff_path),
            "reference": str(reference_path.relative_to(run_dir)),
            "reference_sha256": sha256_file(reference_path),
            "candidate": str(candidate_path.relative_to(run_dir)),
            "candidate_sha256": sha256_file(candidate_path),
        },
    }


def _numeric_series(frame: pd.DataFrame, column: str) -> np.ndarray:
    if column not in frame.columns:
        return np.array([np.nan])
    return pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float)


def verified_metric_inputs(run_dir: Path, run_id: str) -> dict:
    """Everything a metrics run must be true *before* any candidate execution.

    This reuses the trusted gate helpers instead of re-implementing them: the
    context must verify, the frozen source must hash to the frozen digest, Gate A
    and Gate B must approve those exact hashes, and the frozen attempt must be
    the one whose development parity passed under the current context.
    """

    from src.context import verify_context
    from src.migration import load_candidate, load_frozen
    from src.review import current_decision, require_approval
    from src.workflow import verified_split_hash

    repository = run_dir.parent.parent
    if not verify_context(repository, run_dir, run_id):
        raise ContractError("Validation metrics require a valid frozen baseline context")
    frozen = load_frozen(run_dir, run_id)
    attempt = int(frozen["attempt"])
    directory, metadata = load_candidate(run_dir, attempt)
    if metadata.get("run_id") != run_id:
        raise ContractError("Frozen candidate metadata belongs to another run")
    if metadata["candidate_sha256"] != frozen["candidate_sha256"]:
        raise ContractError("Frozen hash is not the approved candidate hash")
    source = directory / "credit_v1.py"
    if sha256_file(source) != frozen["candidate_sha256"]:
        raise ContractError("Candidate source no longer matches the frozen digest")
    if sha256_file(run_dir / "frozen" / "credit_v1.py") != frozen["candidate_sha256"]:
        raise ContractError("Frozen copy no longer matches the frozen digest")
    context_sha256 = sha256_file(run_dir / "context_manifest.json")
    if frozen.get("context_sha256") != context_sha256:
        raise ContractError("Frozen candidate belongs to an invalidated context")
    require_approval(run_dir, run_id, "Gate_A", run_dir / "model_inventory.json")
    require_approval(run_dir, run_id, "Gate_B", source)
    if current_decision(run_dir, run_id, "Gate_B", run_dir / "frozen" / "credit_v1.py") != "APPROVED":
        raise ContractError("Frozen copy has no Gate B approval for its hash")
    migration = read_json(run_dir / "migration_result.json")
    if migration.get("attempt") != attempt or migration.get("candidate_sha256") != frozen["candidate_sha256"]:
        raise ContractError("Migration result does not describe the frozen attempt")
    if migration.get("dev_status") != "PASS":
        raise ContractError("Validation metrics require a candidate whose development parity passed")
    if migration.get("context_sha256") != context_sha256:
        raise ContractError("Migration result belongs to an invalidated context")
    fixtures = run_dir / "dev" / f"attempt_{attempt:03d}" / "fixture_summary.json"
    if not fixtures.is_file():
        raise ContractError("Frozen attempt has no behaviour fixture summary")
    fixture_summary = read_json(fixtures)
    if fixture_summary.get("status") != "PASS" or fixture_summary.get("candidate_sha256") != frozen["candidate_sha256"] or fixture_summary.get("run_id") != run_id:
        raise ContractError("Frozen attempt did not pass the behaviour fixtures")
    splits = {name: verified_split_hash(run_dir, name) for name in ("train", "dev", "holdout", "shift_pool")}
    return {
        "attempt": attempt,
        "candidate_sha256": frozen["candidate_sha256"],
        "context_sha256": context_sha256,
        "source": source,
        "frozen_source": run_dir / "frozen" / "credit_v1.py",
        "model": run_dir / "reference" / "model.json",
        "splits": splits,
    }


def _verify_cached_shifted(run_dir: Path, predictions: Path, execution_path: Path, verified: dict, shifted_path: Path) -> dict:
    execution = read_json(execution_path)
    if execution.get("status") != "PASS":
        raise ContractError("The recorded drift-batch execution did not pass")
    expected = {
        "candidate": (execution.get("candidate_sha256"), verified["candidate_sha256"], "frozen candidate"),
        "model": (execution.get("model_sha256"), sha256_file(verified["model"]), "reference model"),
        "input": (execution.get("input_sha256"), sha256_file(shifted_path), "drift batch input"),
        "output": (execution.get("output_sha256"), sha256_file(predictions), "drift batch predictions"),
    }
    for label, (recorded, actual, description) in expected.items():
        if recorded is None:
            raise ContractError(f"Cached drift-batch execution has no {label} hash")
        if recorded != actual:
            raise ContractError(f"Cached drift-batch {description} hash does not match the file on disk")
    return execution


def _predict_shifted(run_dir: Path, shifted_path: Path, output_root: Path, image: str, verified: dict) -> tuple[Path, dict]:
    """Execute the frozen candidate on the drift batch inside the hardened container.

    A cached execution is reused only after every hash it claims is re-checked
    against the files on disk; a mismatch is a hard failure, never a silent
    re-run.
    """

    work_dir = output_root / "shifted_execution"
    predictions = output_root / "shifted_predictions.csv"
    execution_path = work_dir / "execution.json"
    if predictions.is_file() or execution_path.is_file():
        if not (predictions.is_file() and execution_path.is_file()):
            raise ContractError("Cached drift-batch artefacts are incomplete; refusing to reuse or overwrite them")
        return predictions, _verify_cached_shifted(run_dir, predictions, execution_path, verified, shifted_path)
    execution = run_candidate(
        verified["frozen_source"],
        verified["model"],
        shifted_path,
        work_dir,
        image=image,
    )
    write_json(execution_path, execution)
    if execution.get("status") != "PASS":
        raise ContractError(f"Frozen candidate could not score the drift batch: {execution.get('error')}")
    if execution.get("candidate_sha256") != verified["candidate_sha256"]:
        raise ContractError("Drift-batch execution did not run the frozen candidate")
    predictions.write_bytes((work_dir / "output" / "predictions.csv").read_bytes())
    return predictions, execution


def compute_validation_metrics(
    run_dir: Path,
    run_id: str,
    *,
    threshold: float,
    tolerances: dict,
    image: str | None = None,
) -> dict:
    from src.workflow import runner_image

    verified = verified_metric_inputs(run_dir, run_id)
    attempt = verified["attempt"]
    frozen = {"attempt": attempt, "candidate_sha256": verified["candidate_sha256"]}
    output_root = run_dir / "validation"
    output_root.mkdir(parents=True, exist_ok=True)
    selected_image = image or runner_image(run_dir)

    datasets = {}
    for name, digest in verified["splits"].items():
        datasets[name] = {
            "path": f"data/{name}.csv",
            "sha256": digest,
            "rows": int(len(pd.read_csv(run_dir / "data" / f"{name}.csv"))),
        }

    parity = {
        "dev": _parity_entry(
            run_dir,
            run_dir / "reference" / "dev_predictions.csv",
            run_dir / "dev" / f"attempt_{attempt:03d}" / "output" / "predictions.csv",
            run_dir / "data" / "dev.csv",
            output_root / "parity_dev",
            "dev",
            tolerances,
            run_id,
        ),
        "holdout": _parity_entry(
            run_dir,
            run_dir / "reference" / "holdout_predictions.csv",
            run_dir / "holdout" / "output" / "predictions.csv",
            run_dir / "data" / "holdout.csv",
            output_root / "parity_holdout",
            "holdout",
            tolerances,
            run_id,
        ),
    }
    parity["status"] = "PASS" if all(parity[name]["status"] == "PASS" for name in ("dev", "holdout")) else FAIL

    config = read_json(run_dir.parent.parent / "config" / "data_config.json")
    shift_settings = config.get("shift_scenario_a")
    if not isinstance(shift_settings, dict):
        raise ContractError("config/data_config.json must declare shift_scenario_a")
    shifted_path = run_dir / "data" / "shifted.csv"
    shift_manifest = build_shifted_batch(run_dir / "data", shifted_path, shift_settings)
    shifted_frame = pd.read_csv(shifted_path)
    shift_manifest["overlap"] = {}
    for name in ("train", "dev", "holdout"):
        other = pd.read_csv(run_dir / "data" / f"{name}.csv", usecols=["client_id"])
        shift_manifest["overlap"][name] = int(len(set(shifted_frame["client_id"]) & set(other["client_id"])))
    shift_manifest["output_sha256"] = sha256_file(shifted_path)
    datasets["shifted"] = {"path": "data/shifted.csv", "sha256": shift_manifest["output_sha256"], "rows": int(len(shifted_frame))}
    write_json(output_root / "shifted_manifest.json", {"schema_version": "1", "run_id": run_id, **shift_manifest})

    shifted_predictions, shifted_execution = _predict_shifted(run_dir, shifted_path, output_root, selected_image, verified)

    dev_frame = _joined(run_dir / "data" / "dev.csv", run_dir / "dev" / f"attempt_{attempt:03d}" / "output" / "predictions.csv")
    holdout_frame = _joined(run_dir / "data" / "holdout.csv", run_dir / "holdout" / "output" / "predictions.csv")
    shifted_joined = _joined(shifted_path, shifted_predictions)

    performance = {}
    for name, frame in (("dev", dev_frame), ("holdout", holdout_frame), ("shifted", shifted_joined)):
        entry = performance_metrics(
            _labels(frame).to_numpy(),
            frame["probability"].astype(float).to_numpy(),
            threshold,
        )
        entry["dataset_sha256"] = datasets[name]["sha256"]
        entry["dataset"] = name
        performance[name] = entry

    reference_groups = reference_groups_from_train(pd.read_csv(run_dir / "data" / "train.csv", usecols=list(AUDIT_ATTRIBUTES)))
    fairness_attributes = fairness_metrics(holdout_frame, threshold, reference_groups)

    stability = {"status": OK, "reference": "dev", "scenario": "A", "features": {}, "prediction": metric(None)}
    for column in PSI_FEATURES:
        entry = psi(_numeric_series(dev_frame, column), _numeric_series(shifted_joined, column))
        entry["state"] = _psi_state(entry)
        stability["features"][column] = entry
    prediction_entry = psi(
        dev_frame["probability"].astype(float).to_numpy(),
        shifted_joined["probability"].astype(float).to_numpy(),
    )
    prediction_entry["state"] = _psi_state(prediction_entry)
    stability["prediction"] = prediction_entry
    states = [entry["state"] for entry in stability["features"].values()] + [prediction_entry["state"]]
    if any(state in {NOT_ASSESSABLE, FAIL} for state in states):
        stability["status"] = NOT_ASSESSABLE
    elif "REVALIDATION_REQUIRED" in states:
        stability["status"] = "REVALIDATION_REQUIRED"
    elif "REVIEW_HIGHLIGHTED" in states:
        stability["status"] = "REVIEW_HIGHLIGHTED"

    metrics = {
        "schema_version": "1",
        "run_id": run_id,
        "model_id": "MDL_CREDIT_V1",
        "generated_at": utc_now(),
        "threshold": threshold,
        "candidate_sha256": frozen["candidate_sha256"],
        "frozen_attempt": attempt,
        "datasets": datasets,
        "rules": {
            "min_group_rows": MIN_GROUP_ROWS,
            "min_class_rows": MIN_CLASS_ROWS,
            "psi_bins": PSI_BINS,
            "psi_pseudocount": PSI_PSEUDOCOUNT,
            "psi_attention": PSI_ATTENTION,
            "psi_review": PSI_REVIEW,
            "max_abs_diff": tolerances["max_abs_diff"],
            "mean_abs_diff": tolerances["mean_abs_diff"],
        },
        "parity": parity,
        "performance": performance,
        "stability": stability,
        "fairness": {
            "status": OK if all(isinstance(value, dict) and value.get("status") == OK for value in fairness_attributes.values()) else NOT_ASSESSABLE,
            "dataset": "holdout",
            "reference_groups": reference_groups,
            "attributes": fairness_attributes,
        },
        "evidence": {
            "reference_dev_predictions": "reference/dev_predictions.csv",
            "reference_holdout_predictions": "reference/holdout_predictions.csv",
            "dev_predictions": f"dev/attempt_{attempt:03d}/output/predictions.csv",
            "holdout_predictions": "holdout/output/predictions.csv",
            "shifted_predictions": "validation/shifted_predictions.csv",
            "shifted_manifest": "validation/shifted_manifest.json",
            "shifted_execution": "validation/shifted_execution/execution.json",
            "shifted_execution_status": shifted_execution.get("status"),
        },
    }
    write_json(run_dir / "validation_metrics.json", metrics)
    return metrics
