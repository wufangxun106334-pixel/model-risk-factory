from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.common import sha256_file, write_json
from src.validation import (
    LOW_SAMPLE,
    MIN_CLASS_ROWS,
    MIN_GROUP_ROWS,
    MISSING_LABELS,
    NOT_ASSESSABLE,
    OK,
    SINGLE_CLASS,
    ZERO_DENOMINATOR,
    brier_score,
    build_shifted_batch,
    calibration_deciles,
    confusion_matrix,
    fairness_metrics,
    group_rates,
    performance_metrics,
    psi,
    reference_groups_from_train,
    roc_auc,
)


def test_roc_auc_matches_the_rank_definition():
    labels = np.array([0, 0, 1, 1])
    probabilities = np.array([0.1, 0.4, 0.35, 0.8])
    # Pairs: (0.1,0.35) (0.1,0.8) (0.4,0.8) correct, (0.4,0.35) wrong -> 3/4
    assert roc_auc(labels, probabilities) == pytest.approx(0.75)


def test_roc_auc_handles_ties_with_average_ranks():
    labels = np.array([0, 1, 0, 1])
    probabilities = np.array([0.5, 0.5, 0.5, 0.5])
    assert roc_auc(labels, probabilities) == pytest.approx(0.5)


def test_brier_and_confusion_matrix_are_plain_arithmetic():
    labels = np.array([1, 0, 1, 0])
    probabilities = np.array([0.9, 0.2, 0.4, 0.6])
    assert brier_score(labels, probabilities) == pytest.approx((0.01 + 0.04 + 0.36 + 0.36) / 4)
    matrix = confusion_matrix(labels, (probabilities >= 0.35).astype(int))
    assert matrix == {"true_positive": 2, "false_positive": 1, "true_negative": 1, "false_negative": 0}


def test_calibration_uses_ten_equal_frequency_groups():
    labels = np.array([0] * 50 + [1] * 50)
    probabilities = np.linspace(0.01, 0.99, 100)
    rows = calibration_deciles(labels, probabilities, np.arange(100))
    assert len(rows) == 10
    assert sum(row["rows"] for row in rows) == 100
    assert all(row["rows"] == 10 for row in rows)
    assert rows[0]["mean_probability"] < rows[-1]["mean_probability"]
    assert rows[-1]["observed_default_rate"] == pytest.approx(1.0)


def test_performance_reports_single_class_as_not_assessable():
    labels = np.array([1, 1, 1, 1])
    probabilities = np.array([0.2, 0.6, 0.7, 0.9])
    result = performance_metrics(labels, probabilities, 0.35)
    assert result["roc_auc"]["status"] == SINGLE_CLASS
    assert result["roc_auc"]["value"] is None
    assert result["brier_score"]["status"] == OK


def test_performance_reports_missing_labels_explicitly():
    labels = np.array([np.nan, np.nan])
    result = performance_metrics(labels, np.array([0.2, 0.3]), 0.35)
    assert result["roc_auc"]["status"] == MISSING_LABELS
    assert result["confusion_matrix"]["value"] is None
    assert result["calibration"]["value"] is None


def test_performance_ignores_rows_without_a_probability():
    labels = np.array([0, 1, 0])
    probabilities = np.array([0.2, np.nan, 0.7])
    result = performance_metrics(labels, probabilities, 0.35)
    assert result["rows"] == 2


def test_psi_is_zero_for_identical_distributions_and_large_for_a_shift():
    rng = np.random.default_rng(7)
    reference = rng.normal(0, 1, 2000)
    same = psi(reference, reference)
    assert same["status"] == OK
    assert same["value"] == pytest.approx(0.0, abs=1e-9)
    shifted = psi(reference, reference + 3.0)
    assert shifted["value"] > 0.25
    assert shifted["bins"] <= 10
    assert shifted["pseudocount"] > 0


def test_psi_deduplicates_repeated_quantiles():
    reference = np.array([0.0] * 100 + [1.0] * 100)
    result = psi(reference, reference)
    assert result["status"] == OK
    # Repeated quantile edges are merged, so fewer than the requested bins remain.
    assert result["bins"] < 10
    assert result["value"] == pytest.approx(0.0, abs=1e-9)


def test_psi_refuses_to_score_an_empty_side():
    assert psi(np.array([]), np.array([1.0, 2.0]))["status"] == NOT_ASSESSABLE


def test_group_rates_apply_the_small_sample_and_zero_denominator_rules():
    small = group_rates(np.array([1, 0]), np.array([1, 0]))
    assert small["sample_status"] == LOW_SAMPLE
    assert small["tpr"]["status"] == LOW_SAMPLE

    usable = np.array([1] * 10 + [0] * 30)
    usable_predictions = np.array([1] * 8 + [0] * 2 + [1] * 3 + [0] * 27)
    rates = group_rates(usable, usable_predictions)
    assert rates["sample_status"] == OK
    assert rates["tpr"]["value"] == pytest.approx(0.8)
    assert rates["fpr"]["value"] == pytest.approx(0.1)

    no_positives = group_rates(np.zeros(MIN_GROUP_ROWS, dtype=int), np.zeros(MIN_GROUP_ROWS, dtype=int))
    assert no_positives["tpr"]["status"] == ZERO_DENOMINATOR
    assert no_positives["fpr"]["status"] == OK

    few_positives = group_rates(
        np.concatenate([np.ones(MIN_CLASS_ROWS - 1, dtype=int), np.zeros(MIN_GROUP_ROWS, dtype=int)]),
        np.zeros(MIN_GROUP_ROWS + MIN_CLASS_ROWS - 1, dtype=int),
    )
    assert few_positives["tpr"]["status"] == LOW_SAMPLE

    no_negatives = group_rates(np.ones(MIN_GROUP_ROWS, dtype=int), np.ones(MIN_GROUP_ROWS, dtype=int))
    assert no_negatives["fpr"]["status"] == ZERO_DENOMINATOR


def _fairness_frame():
    rows = []
    for band, count in (("26-35", 120), ("36-50", 60), ("51+", 5)):
        for index in range(count):
            rows.append({
                "age_band": band,
                "sex": "1" if index % 2 else "2",
                "probability": 0.6 if index % 3 else 0.1,
                "default_flag": 1 if index % 4 == 0 else 0,
            })
    return pd.DataFrame(rows)


def test_fairness_uses_the_train_reference_group_and_flags_low_sample():
    frame = _fairness_frame()
    train = pd.DataFrame({"age_band": ["26-35"] * 10 + ["36-50"] * 3, "sex": ["2"] * 9 + ["1"] * 4})
    reference = reference_groups_from_train(train)
    assert reference == {"age_band": "26-35", "sex": "2"}
    report = fairness_metrics(frame, 0.35, reference)
    assert report["age_band"]["reference_group"] == "26-35"
    assert "51+" in report["age_band"]["groups"]
    assert report["age_band"]["groups"]["51+"]["sample_status"] == LOW_SAMPLE
    assert report["age_band"]["differences"]["26-35"]["tpr"]["value"] == pytest.approx(0.0)
    assert report["sex"]["groups"]["1"]["rows"] > 0


def test_fairness_marks_differences_not_assessable_when_the_reference_is_missing():
    frame = _fairness_frame()
    report = fairness_metrics(frame, 0.35, {"age_band": "absent", "sex": "1"})
    assert report["age_band"]["differences"]["26-35"]["tpr"]["status"] == NOT_ASSESSABLE


def test_shifted_batch_is_deterministic_and_keeps_real_labels(tmp_path):
    rng = np.random.default_rng(11)
    frame = pd.DataFrame({
        "client_id": [str(index) for index in range(300)],
        "limit_bal": rng.integers(10000, 500000, 300),
        "util_1": rng.uniform(0, 2, 300),
        "default_flag": rng.integers(0, 2, 300),
    })
    frame.to_csv(tmp_path / "shift_pool.csv", index=False)
    settings = {"rows": 100, "seed": 5, "util_weight": 2.0, "limit_weight": 1.5}
    first = build_shifted_batch(tmp_path, tmp_path / "a.csv", settings)
    second = build_shifted_batch(tmp_path, tmp_path / "b.csv", settings)
    assert first["output_sha256"] == second["output_sha256"]
    assert first["rows"] == 100
    selected = pd.read_csv(tmp_path / "a.csv")
    assert set(selected["default_flag"]) <= {0, 1}
    assert selected["client_id"].is_unique
    assert first["default_rate"] == pytest.approx(float(selected["default_flag"].mean()))
    assert math.isclose(sum(1 for _ in selected.iterrows()), 100)


def test_shifted_batch_refuses_to_be_larger_than_the_pool(tmp_path):
    pd.DataFrame({"client_id": ["1"], "limit_bal": [1.0], "util_1": [0.0], "default_flag": [0]}).to_csv(tmp_path / "shift_pool.csv", index=False)
    with pytest.raises(Exception):
        build_shifted_batch(tmp_path, tmp_path / "a.csv", {"rows": 5, "seed": 1, "util_weight": 1.0, "limit_weight": 1.0})
