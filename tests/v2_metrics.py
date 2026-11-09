"""Shared validation_metrics fixture for the report and Gate C tests.

It mirrors the shape produced by src/validation.py closely enough to exercise the
renderer, the provenance index and the bound-file checks without running Docker.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _metric(value, status="OK", reason=None, **extra):
    return {"value": value, "status": status, "reason": reason, **extra}


def metrics_fixture(run_id: str = "v2-report-test") -> dict:
    deciles = [
        {
            "decile": index,
            "rows": 600,
            "mean_probability": 0.02 * index,
            "observed_default_rate": 0.01 * index,
            "min_probability": 0.001 * index,
            "max_probability": 0.3 * index,
            "absolute_gap": 0.01 * index,
        }
        for index in range(1, 11)
    ]
    return {
        "schema_version": "1",
        "run_id": run_id,
        "model_id": "MDL_CREDIT_V1",
        "generated_at": "2026-11-10T00:00:00Z",
        "threshold": 0.35,
        "candidate_sha256": "a" * 64,
        "frozen_attempt": 0,
        "datasets": {
            "train": {"path": "data/train.csv", "sha256": "b" * 64, "rows": 15000},
            "dev": {"path": "data/dev.csv", "sha256": "c" * 64, "rows": 6000},
            "holdout": {"path": "data/holdout.csv", "sha256": "d" * 64, "rows": 6000},
            "shift_pool": {"path": "data/shift_pool.csv", "sha256": "e" * 64, "rows": 3000},
            "shifted": {"path": "data/shifted.csv", "sha256": "f" * 64, "rows": 2000},
        },
        "rules": {
            "min_group_rows": 30,
            "min_class_rows": 5,
            "psi_bins": 10,
            "psi_pseudocount": 0.5,
            "psi_attention": 0.1,
            "psi_review": 0.25,
            "max_abs_diff": 1e-08,
            "mean_abs_diff": 1e-10,
        },
        "parity": {
            "dev": {"status": "PASS", "rows": 6000, "max_abs_diff": 0.0, "mean_abs_diff": 0.0, "classification_mismatch_count": 0, "behaviour_mismatch_count": 0, "limits": {"max_abs_diff": 1e-08, "mean_abs_diff": 1e-10}},
            "holdout": {"status": "PASS", "rows": 6000, "max_abs_diff": 2.2e-16, "mean_abs_diff": 0.0, "classification_mismatch_count": 0, "behaviour_mismatch_count": 0, "limits": {"max_abs_diff": 1e-08, "mean_abs_diff": 1e-10}},
            "status": "PASS",
        },
        "performance": {
            "dev": {
                "rows": 6000,
                "positive_rows": 1327,
                "negative_rows": 4673,
                "observed_default_rate": 0.2212,
                "roc_auc": _metric(0.7123),
                "brier_score": _metric(0.1512),
                "confusion_matrix": _metric({"true_positive": 900, "false_positive": 1400, "true_negative": 3273, "false_negative": 427}),
                "calibration": _metric(deciles),
            },
            "holdout": {
                "rows": 6000,
                "positive_rows": 1327,
                "negative_rows": 4673,
                "observed_default_rate": 0.2212,
                "roc_auc": _metric(0.7044),
                "brier_score": _metric(0.1531),
                "confusion_matrix": _metric({"true_positive": 880, "false_positive": 1450, "true_negative": 3223, "false_negative": 447}),
                "calibration": _metric(deciles),
            },
            "shifted": {
                "rows": 2000,
                "positive_rows": 780,
                "negative_rows": 1220,
                "observed_default_rate": 0.39,
                "roc_auc": _metric(0.6801),
                "brier_score": _metric(0.2011),
                "confusion_matrix": _metric({"true_positive": 620, "false_positive": 500, "true_negative": 720, "false_negative": 160}),
                "calibration": _metric(deciles),
            },
        },
        "stability": {
            "status": "REVIEW_HIGHLIGHTED",
            "reference": "dev",
            "scenario": "A",
            "features": {
                "util_1": _metric(0.4212, bins=10, state="REVALIDATION_REQUIRED"),
                "limit_bal": _metric(0.1811, bins=10, state="REVIEW_HIGHLIGHTED"),
            },
            "prediction": _metric(0.2211, bins=10, state="REVIEW_HIGHLIGHTED"),
        },
        "fairness": {
            "status": "OK",
            "dataset": "holdout",
            "reference_groups": {"age_band": "26-35", "sex": "2"},
            "attributes": {
                "age_band": {
                    "status": "OK",
                    "reference_group": "26-35",
                    "groups": {
                        "26-35": {"rows": 2500, "positive_rows": 560, "negative_rows": 1940, "tpr": _metric(0.61), "fpr": _metric(0.21), "sample_status": "OK"},
                        "51+": {"rows": 700, "positive_rows": 140, "negative_rows": 560, "tpr": _metric(0.58), "fpr": _metric(0.24), "sample_status": "OK"},
                    },
                    "differences": {
                        "26-35": {"tpr": _metric(0.0), "fpr": _metric(0.0)},
                        "51+": {"tpr": _metric(-0.03), "fpr": _metric(0.03)},
                    },
                },
                "sex": {
                    "status": "OK",
                    "reference_group": "2",
                    "groups": {
                        "1": {"rows": 3000, "positive_rows": 660, "negative_rows": 2340, "tpr": _metric(0.6), "fpr": _metric(0.22), "sample_status": "OK"},
                        "2": {"rows": 3000, "positive_rows": 667, "negative_rows": 2333, "tpr": _metric(0.62), "fpr": _metric(0.21), "sample_status": "OK"},
                    },
                    "differences": {
                        "1": {"tpr": _metric(-0.02), "fpr": _metric(0.01)},
                        "2": {"tpr": _metric(0.0), "fpr": _metric(0.0)},
                    },
                },
            },
        },
    }


