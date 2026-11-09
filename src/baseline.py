from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from src.common import ContractError, file_record, read_json, sha256_file, utc_now, write_json


def run_r_baseline(repository: Path, run_dir: Path, runtime_config: Path) -> dict:
    config = read_json(runtime_config)
    data_dir = run_dir / "data"
    reference_dir = run_dir / "reference"
    reference_dir.mkdir(parents=True, exist_ok=True)
    required = [data_dir / f"{name}.csv" for name in ("train", "dev", "holdout")]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ContractError(f"Missing prepared datasets: {missing}")
    image = config["r_image"]
    command = [
        "docker", "run", "--rm", "--network", "none", "--read-only",
        "--user", f"{os.getuid()}:{os.getgid()}", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m",
        "-v", f"{repository / 'legacy'}:/legacy:ro",
        "-v", f"{data_dir / 'train.csv'}:/data/train.csv:ro",
        "-v", f"{data_dir / 'dev.csv'}:/data/dev.csv:ro",
        "-v", f"{data_dir / 'holdout.csv'}:/data/holdout.csv:ro",
        "-v", f"{reference_dir}:/out:rw",
        image, "Rscript", "/legacy/credit_v1.R", "/data/train.csv", "/out", "/data/dev.csv", "/data/holdout.csv",
    ]
    started = time.monotonic()
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=config["r_timeout_seconds"], check=False)
        status = "PASS" if result.returncode == 0 else "EXECUTION_ERROR"
        exit_code = result.returncode
        stdout, stderr = result.stdout, result.stderr
    except subprocess.TimeoutExpired as error:
        status = "TIMEOUT"
        exit_code = None
        stdout = error.stdout or ""
        stderr = error.stderr or ""
    (reference_dir / "r_stdout.txt").write_text(stdout, encoding="utf-8")
    (reference_dir / "r_stderr.txt").write_text(stderr, encoding="utf-8")
    expected = ["model.json", "train_predictions.csv", "dev_predictions.csv", "holdout_predictions.csv", "sessionInfo.txt", "baseline_manifest.json"]
    artifacts = [file_record(reference_dir / name, base=run_dir) for name in expected if (reference_dir / name).is_file()]
    execution = {
        "schema_version": "1",
        "run_id": read_json(run_dir / "run_manifest.json")["run_id"],
        "timestamp": utc_now(),
        "status": status,
        "exit_code": exit_code,
        "duration_seconds": round(time.monotonic() - started, 6),
        "r_image": image,
        "r_script_sha256": sha256_file(repository / "legacy" / "credit_v1.R"),
        "network": "none",
        "artifacts": artifacts,
    }
    write_json(reference_dir / "r_execution.json", execution)
    if status != "PASS":
        raise ContractError(f"R baseline failed with status {status}; see {reference_dir / 'r_stderr.txt'}")
    missing_outputs = [name for name in expected if not (reference_dir / name).is_file()]
    if missing_outputs:
        raise ContractError(f"R baseline did not produce: {missing_outputs}")
    return execution
