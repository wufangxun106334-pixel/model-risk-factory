from __future__ import annotations

import hashlib
from pathlib import Path

from src.common import ContractError, read_json, sha256_file, tree_records, write_json
from src.parity import compare_files
from src.reference import predict_file


def _tests_digest(repository: Path) -> str:
    digest = hashlib.sha256()
    for record in tree_records(repository / "tests", base=repository):
        digest.update(record["path"].encode("utf-8"))
        digest.update(record["sha256"].encode("ascii"))
    return digest.hexdigest()


def run_reference_parity(run_dir: Path) -> dict:
    model = run_dir / "reference" / "model.json"
    results = {}
    for dataset in ("dev", "holdout"):
        output_dir = run_dir / "parity" / f"reference_{dataset}"
        output_dir.mkdir(parents=True, exist_ok=True)
        candidate = output_dir / "python_predictions.csv"
        predict_file(model, run_dir / "data" / f"{dataset}.csv", candidate)
        results[dataset] = compare_files(
            run_dir / "reference" / f"{dataset}_predictions.csv",
            candidate,
            output_dir / "parity_summary.json",
            output_dir / "parity_diff.csv",
            run_id=read_json(run_dir / "run_manifest.json")["run_id"],
        )
    if results["dev"]["status"] != "PASS" or results["holdout"]["status"] != "PASS":
        raise ContractError("Python reference parity failed; inspect parity summaries")
    return results


def run_mutation_check(repository: Path, run_dir: Path) -> dict:
    output_dir = run_dir / "mutation"
    output_dir.mkdir(parents=True, exist_ok=True)
    original_path = run_dir / "reference" / "model.json"
    original_hash_before = sha256_file(original_path)
    tests_hash_before = _tests_digest(repository)
    model = read_json(original_path)
    if "delay_1" not in model["coefficients"]:
        raise ContractError("Cannot run mutation check without delay_1 coefficient")
    model["coefficients"]["delay_1"] = float(model["coefficients"]["delay_1"]) + 0.001
    mutant_path = output_dir / "mutant_model.json"
    write_json(mutant_path, model)
    predictions = output_dir / "mutant_predictions.csv"
    predict_file(mutant_path, run_dir / "data" / "dev.csv", predictions)
    parity = compare_files(
        run_dir / "reference" / "dev_predictions.csv",
        predictions,
        output_dir / "mutant_parity_summary.json",
        output_dir / "parity_diff.csv",
        run_id=read_json(run_dir / "run_manifest.json")["run_id"],
    )
    original_hash_after = sha256_file(original_path)
    tests_hash_after = _tests_digest(repository)
    unchanged = original_hash_before == original_hash_after and tests_hash_before == tests_hash_after
    detected = parity["status"] == "FAIL" and parity.get("max_abs_diff") is not None and parity["max_abs_diff"] > 1e-8
    summary = {
        "schema_version": "1",
        "run_id": read_json(run_dir / "run_manifest.json")["run_id"],
        "status": "PASS" if detected and unchanged else "FAIL",
        "mutation": "coefficients.delay_1 += 0.001 (isolated copy)",
        "mutation_detected": detected,
        "mutant_parity_status": parity["status"],
        "max_abs_diff": parity.get("max_abs_diff"),
        "mean_abs_diff": parity.get("mean_abs_diff"),
        "original_unchanged": unchanged,
        "original_model_sha256_before": original_hash_before,
        "original_model_sha256_after": original_hash_after,
        "tests_sha256_before": tests_hash_before,
        "tests_sha256_after": tests_hash_after,
        "mutant_model_sha256": sha256_file(mutant_path),
    }
    write_json(output_dir / "mutation_summary.json", summary)
    if summary["status"] != "PASS":
        raise ContractError("The fixed parity check did not detect the intentional mutation")
    return summary
