from __future__ import annotations

import os
import subprocess
from pathlib import Path

from src.common import read_json, sha256_file, write_json
from src.parity import compare_files
from src.reference import InputContractError, predict_file

VALID_FIXTURES = ["behavior", "column_reordered", "row_reordered"]
STRUCTURAL_FIXTURES = ["duplicate_ids", "missing_column", "empty"]


def _r_fixture(repository: Path, run_dir: Path, fixture: Path, output_dir: Path, image: str) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        "docker", "run", "--rm", "--network", "none", "--read-only",
        "--user", f"{os.getuid()}:{os.getgid()}", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
        "-v", f"{repository / 'legacy'}:/legacy:ro",
        "-v", f"{run_dir / 'data' / 'train.csv'}:/data/train.csv:ro",
        "-v", f"{fixture}:/data/input.csv:ro",
        "-v", f"{output_dir}:/out:rw",
        image, "Rscript", "/legacy/credit_v1.R", "/data/train.csv", "/out", "/data/input.csv",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    (output_dir / "stdout.txt").write_text(result.stdout, encoding="utf-8")
    (output_dir / "stderr.txt").write_text(result.stderr, encoding="utf-8")
    return {"exit_code": result.returncode, "stderr_sha256": sha256_file(output_dir / "stderr.txt")}


def run_fixture_parity(repository: Path, run_dir: Path) -> dict:
    image = read_json(repository / "config" / "runtime_config.json")["r_image"]
    fixtures = run_dir / "data" / "fixtures"
    output_root = run_dir / "fixtures"
    parity_root = run_dir / "parity" / "reference_fixtures"
    records = []
    for name in VALID_FIXTURES:
        r_dir = output_root / name / "r"
        r_result = _r_fixture(repository, run_dir, fixtures / f"{name}.csv", r_dir, image)
        python_dir = output_root / name / "python"
        python_dir.mkdir(parents=True, exist_ok=True)
        python_error = None
        try:
            predict_file(run_dir / "reference" / "model.json", fixtures / f"{name}.csv", python_dir / "predictions.csv")
            python_exit = 0
        except InputContractError as error:
            python_exit = 2
            python_error = str(error)
        parity = None
        if r_result["exit_code"] == 0 and python_exit == 0:
            parity_dir = parity_root / name
            parity = compare_files(r_dir / "dev_predictions.csv", python_dir / "predictions.csv", parity_dir / "parity_summary.json", parity_dir / "parity_diff.csv", run_id=read_json(run_dir / "run_manifest.json")["run_id"])
        records.append({"name": name, "kind": "ROW_BEHAVIOUR", "r_exit_code": r_result["exit_code"], "python_exit_code": python_exit, "python_error": python_error, "parity_status": parity["status"] if parity else "FAIL", "parity": parity})
    for name in STRUCTURAL_FIXTURES:
        r_dir = output_root / name / "r"
        r_result = _r_fixture(repository, run_dir, fixtures / f"{name}.csv", r_dir, image)
        python_error = None
        try:
            predict_file(run_dir / "reference" / "model.json", fixtures / f"{name}.csv", output_root / name / "python" / "predictions.csv")
            python_exit = 0
        except InputContractError as error:
            python_exit = 2
            python_error = str(error)
        records.append({"name": name, "kind": "STRUCTURAL_REJECTION", "r_exit_code": r_result["exit_code"], "python_exit_code": python_exit, "python_error": python_error, "parity_status": "PASS" if r_result["exit_code"] == python_exit == 2 else "FAIL"})
    status = "PASS" if all(record["parity_status"] == "PASS" for record in records) else "FAIL"
    summary = {"schema_version": "1", "run_id": read_json(run_dir / "run_manifest.json")["run_id"], "status": status, "records": records, "contains_synthetic_fixtures_only": True}
    write_json(parity_root / "fixture_summary.json", summary)
    return summary
