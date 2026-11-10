"""Read-only view model for the Streamlit demo (``app.py``).

The UI never writes run artifacts itself. Every action (Gate approvals, candidate
generation, export ...) is executed through ``python -m src.cli`` so the command
log, gate checks and hash bindings are exactly those of the CLI. This module only
reads run directories and builds the CLI argument lists; it does not import
Streamlit, so it is covered by the normal pytest suite.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from src.common import read_json
from src.inventory import inventory_path
from src.review import artifact_digest, current_decision

REPOSITORY = Path(__file__).resolve().parents[1]
MODEL_IDS = ("MDL_CREDIT_V1", "MDL_CREDIT_V2", "MDL_CREDIT_TREE")
MIGRATED_MODEL = "MDL_CREDIT_V1"


def _read(path: Path) -> Any:
    try:
        return read_json(path)
    except (OSError, ValueError):
        return None


def runs_root(name: str = "runs") -> Path:
    """``runs`` holds formal runs; ``dev_runs`` holds synthetic dry runs."""

    if name not in {"runs", "dev_runs"}:
        raise ValueError("runs root must be 'runs' or 'dev_runs'")
    return REPOSITORY / name


def list_runs(root: Path) -> list[dict]:
    """Newest first; one row per run directory that has a manifest."""

    rows = []
    if not root.is_dir():
        return rows
    for directory in root.iterdir():
        manifest = _read(directory / "run_manifest.json") if directory.is_dir() else None
        if not isinstance(manifest, dict):
            continue
        acceptance = _read(directory / "acceptance.json")
        rows.append({
            "run_id": manifest.get("run_id", directory.name),
            "mode": manifest.get("mode"),
            "state": manifest.get("state", "INITIALIZED"),
            "created_at": manifest.get("created_at"),
            "git_commit_at_init": (manifest.get("git_commit_at_init") or "")[:12],
            "worktree_clean_at_init": manifest.get("worktree_clean_at_init"),
            "release_approved": acceptance.get("release_approved") if isinstance(acceptance, dict) else None,
        })
    return sorted(rows, key=lambda row: row.get("created_at") or "", reverse=True)


def model_rows(run_dir: Path, run_id: str) -> list[dict]:
    """Inventory status of the three models, with the exact Gate A hash to approve."""

    rows = []
    for model_id in MODEL_IDS:
        path = inventory_path(run_dir, model_id)
        row: dict[str, Any] = {"model_id": model_id, "migrated": model_id == MIGRATED_MODEL, "path": path}
        inventory = _read(path) if path.is_file() else None
        if not isinstance(inventory, dict):
            row.update({"exists": False, "gate_a": "NOT_RUN"})
        else:
            row.update({
                "exists": True,
                "inventory": inventory,
                "artifact_sha256": artifact_digest(path, "Gate_A"),
                "gate_a": current_decision(run_dir, run_id, "Gate_A", path),
                "conflicts": len(inventory.get("conflicts") or []),
                "unknowns": len(inventory.get("unknowns") or []),
                "sources": len(inventory.get("sources") or []),
            })
        rows.append(row)
    return rows


def candidate_rows(run_dir: Path, run_id: str) -> list[dict]:
    rows = []
    root = run_dir / "candidates"
    if not root.is_dir():
        return rows
    for directory in sorted(path for path in root.glob("attempt_*") if path.is_dir()):
        metadata = _read(directory / "candidate.json")
        if not isinstance(metadata, dict):
            continue
        source = directory / "credit_v1.py"
        rows.append({
            "attempt": metadata.get("attempt"),
            "candidate_sha256": metadata.get("candidate_sha256"),
            "source": source,
            "diff": directory / "candidate.diff",
            "gate_b": current_decision(run_dir, run_id, "Gate_B", source) if source.is_file() else "NOT_RUN",
            "dev_status": metadata.get("dev_status") or metadata.get("status"),
        })
    return rows


def report_paths(run_dir: Path) -> dict[str, Path]:
    report = run_dir / "report"
    return {
        "report": report / "validation_report.md",
        "tables": report / "validation_tables.md",
        "values_index": report / "values_index.csv",
        "review_manifest": report / "review_manifest.json",
        "approval": report / "approval.json",
        "metrics": run_dir / "validation_metrics.json",
    }


def gate_c_state(run_dir: Path, run_id: str) -> dict:
    manifest = report_paths(run_dir)["review_manifest"]
    if not manifest.is_file():
        return {"exists": False, "decision": "NOT_RUN"}
    return {
        "exists": True,
        "artifact_sha256": artifact_digest(manifest, "Gate_C"),
        "decision": current_decision(run_dir, run_id, "Gate_C", manifest),
    }


def acceptance_records(run_dir: Path) -> tuple[bool | None, list[dict]]:
    acceptance = _read(run_dir / "acceptance.json")
    if not isinstance(acceptance, dict):
        return None, []
    return acceptance.get("release_approved"), list(acceptance.get("records") or [])


DATA_KIND_LABELS = {"synthetic": "SYNTHETIC", "uci": "UCI"}


def run_facts(run_dir: Path) -> dict:
    """Facts that let a reviewer tell a synthetic dry run from a formal one.

    Everything comes from files in the run, so the badge cannot claim a state the
    artifacts do not support.
    """

    manifest = _read(run_dir / "run_manifest.json")
    manifest = manifest if isinstance(manifest, dict) else {}
    data = _read(run_dir / "data" / "data_manifest.json")
    data_kind = str((data or {}).get("data_kind") or "").lower() if isinstance(data, dict) else ""
    release_approved, _records = acceptance_records(run_dir)
    return {
        "data_kind": DATA_KIND_LABELS.get(data_kind, "DATA UNKNOWN"),
        "data_kind_raw": data_kind or None,
        "mode": manifest.get("mode"),
        "commit": (manifest.get("git_commit_at_init") or "")[:12] or None,
        "clean_at_init": manifest.get("worktree_clean_at_init"),
        "release_approved": release_approved,
    }


def status_badges(run_dir: Path, *, live: bool = False) -> list[str]:
    """Badges shown above every page: data kind, live/replay, release state, commit."""

    facts = run_facts(run_dir)
    badges = [facts["data_kind"]]
    badges.append("LIVE" if live else "REPLAY")
    # This badge reports the run's own acceptance record only. A published release
    # additionally needs `release-check` -> APPROVED on the release commit, which is
    # deliberately not claimed here.
    if facts["release_approved"] is True:
        badges.append("ACCEPTANCE PASSED")
    elif facts["release_approved"] is False:
        badges.append("ACCEPTANCE NOT PASSED")
    else:
        badges.append("NO ACCEPTANCE RECORD")
    if facts["commit"]:
        badges.append(f"COMMIT {facts['commit']}")
    return badges


STATUS_BADGE_HELP = (
    "SYNTHETIC/UCI comes from the run's data manifest. REPLAY means these are stored results read from "
    "the run directory; LIVE means a CLI action ran against this run in this browser session."
)


def downloads(run_dir: Path, run_id: str) -> list[Path]:
    """Files the reviewer can download: report, tables, metrics and the sealed evidence ZIP."""

    candidates = [*report_paths(run_dir).values(), REPOSITORY / "delivery" / f"{run_id}_evidence.zip"]
    return [path for path in candidates if path.is_file()]


def approve_args(run_id: str, gate: str, sha256: str, reviewer: str, comment: str,
                 decision: str = "APPROVED", model: str | None = None, attempt: int | None = None) -> list[str]:
    if gate not in {"Gate_A", "Gate_B", "Gate_C"}:
        raise ValueError(f"unknown gate {gate}")
    if decision not in {"APPROVED", "REJECTED"}:
        raise ValueError(f"unknown decision {decision}")
    if not reviewer.strip():
        raise ValueError("reviewer is required")
    if len(sha256) != 64:
        raise ValueError("the full 64-character artifact hash is required")
    args = ["approve", "--run-id", run_id, "--gate", gate, "--sha256", sha256,
            "--decision", decision, "--reviewer", reviewer.strip(), "--comment", comment]
    if model is not None:
        args += ["--model", model]
    if attempt is not None:
        args += ["--attempt", str(attempt)]
    return args


def run_cli(args: list[str], root: Path, timeout: int = 900) -> dict:
    """Run one CLI command with the selected runs root; return exit code and output."""

    env = {**os.environ, "MRF_RUNS_ROOT": str(root)}
    completed = subprocess.run(
        [sys.executable, "-m", "src.cli", *args],
        cwd=REPOSITORY, env=env, capture_output=True, text=True, timeout=timeout, check=False,
    )
    return {"returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr,
            "command": ["python", "-m", "src.cli", *args]}


# ---------------------------------------------------------------- chart data
# Pure pandas shaping for the charts in app.py. Values are copied from the run's
# JSON/CSV artifacts unchanged; None stays None so the charts can show gaps.

DATASETS = ("dev", "holdout", "shifted")


def load_metrics(run_dir: Path) -> dict | None:
    metrics = _read(run_dir / "validation_metrics.json")
    return metrics if isinstance(metrics, dict) else None


def _value(entry: Any) -> Any:
    return entry.get("value") if isinstance(entry, dict) else None


def _status(entry: Any) -> Any:
    return entry.get("status") if isinstance(entry, dict) else None


def performance_rows(metrics: dict) -> list[dict]:
    rows = []
    for dataset in DATASETS:
        block = (metrics.get("performance") or {}).get(dataset)
        if not isinstance(block, dict):
            continue
        rows.append({
            "dataset": dataset,
            "rows": block.get("rows"),
            "defaults": block.get("positive_rows"),
            "observed_default_rate": block.get("observed_default_rate"),
            "roc_auc": _value(block.get("roc_auc")),
            "roc_auc_status": _status(block.get("roc_auc")),
            "brier_score": _value(block.get("brier_score")),
            "brier_status": _status(block.get("brier_score")),
        })
    return rows


def calibration_rows(metrics: dict) -> list[dict]:
    rows = []
    for dataset in DATASETS:
        block = (metrics.get("performance") or {}).get(dataset)
        deciles = _value(block.get("calibration")) if isinstance(block, dict) else None
        for decile in deciles or []:
            rows.append({
                "dataset": dataset,
                "decile": decile.get("decile"),
                "rows": decile.get("rows"),
                "mean_probability": decile.get("mean_probability"),
                "observed_default_rate": decile.get("observed_default_rate"),
            })
    return rows


def confusion_rows(metrics: dict, dataset: str = "holdout") -> list[dict]:
    block = (metrics.get("performance") or {}).get(dataset)
    matrix = _value(block.get("confusion_matrix")) if isinstance(block, dict) else None
    if not isinstance(matrix, dict):
        return []
    cells = [
        ("default (1)", "predicted default", "true_positive"),
        ("default (1)", "predicted no default", "false_negative"),
        ("no default (0)", "predicted default", "false_positive"),
        ("no default (0)", "predicted no default", "true_negative"),
    ]
    return [{"actual": actual, "predicted": predicted, "cell": key, "count": matrix.get(key)} for actual, predicted, key in cells]


def psi_rows(metrics: dict) -> list[dict]:
    stability = metrics.get("stability") or {}
    entries = [(name, "feature", entry) for name, entry in (stability.get("features") or {}).items()]
    if isinstance(stability.get("prediction"), dict):
        entries.append(("prediction (probability)", "prediction", stability["prediction"]))
    return [{"name": name, "kind": kind, "psi": _value(entry), "state": entry.get("state") or _status(entry)}
            for name, kind, entry in entries]


def psi_thresholds(metrics: dict) -> dict:
    rules = metrics.get("rules") or {}
    return {"attention": rules.get("psi_attention", 0.1), "review": rules.get("psi_review", 0.25)}


def fairness_rows(metrics: dict) -> list[dict]:
    rows = []
    attributes = ((metrics.get("fairness") or {}).get("attributes")) or {}
    for attribute, block in attributes.items():
        reference = block.get("reference_group")
        for group, values in (block.get("groups") or {}).items():
            for rate in ("tpr", "fpr"):
                rows.append({
                    "attribute": attribute,
                    "group": str(group),
                    "rate": rate.upper(),
                    "value": _value(values.get(rate)),
                    "status": _status(values.get(rate)),
                    "rows": values.get("rows"),
                    "sample_status": values.get("sample_status"),
                    "reference": str(group) == str(reference),
                })
    return rows


def parity_paths(run_dir: Path, stage: str, attempt: int | None = None) -> dict[str, Path]:
    if stage == "dev":
        if attempt is None:
            raise ValueError("dev parity needs an attempt")
        work = run_dir / "dev" / f"attempt_{attempt:03d}"
        reference = run_dir / "reference" / "dev_predictions.csv"
    elif stage == "holdout":
        work = run_dir / "holdout"
        reference = run_dir / "reference" / "holdout_predictions.csv"
    else:
        raise ValueError("stage must be 'dev' or 'holdout'")
    return {"reference": reference, "candidate": work / "output" / "predictions.csv", "summary": work / "parity_summary.json"}


def parity_frame(run_dir: Path, stage: str, attempt: int | None = None):
    """R baseline vs Python candidate probabilities, joined on client_id; None if not run yet."""

    import pandas as pd

    paths = parity_paths(run_dir, stage, attempt)
    if not (paths["reference"].is_file() and paths["candidate"].is_file()):
        return None
    columns = ["client_id", "probability", "classification", "status"]
    reference = pd.read_csv(paths["reference"], dtype={"client_id": str}, usecols=columns)
    candidate = pd.read_csv(paths["candidate"], dtype={"client_id": str}, usecols=columns)
    merged = reference.merge(candidate, on="client_id", how="outer", suffixes=("_r", "_python"), indicator=True)
    merged["abs_diff"] = (merged["probability_r"] - merged["probability_python"]).abs()
    merged["class_match"] = merged["classification_r"] == merged["classification_python"]
    return merged


def parity_summary(run_dir: Path, stage: str, attempt: int | None = None) -> dict | None:
    summary = _read(parity_paths(run_dir, stage, attempt)["summary"])
    return summary if isinstance(summary, dict) else None
