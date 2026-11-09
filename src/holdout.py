from __future__ import annotations

import fcntl
from pathlib import Path

from src.common import GateError, append_jsonl, read_json, read_jsonl, sha256_file, utc_now


def consume_holdout(run_dir: Path, run_id: str, candidate_sha256: str) -> dict:
    dataset_sha256 = sha256_file(run_dir / "data" / "holdout.csv")
    data = read_json(run_dir / "data" / "data_manifest.json")
    campaign_id = f"MDL_CREDIT_V1:{data.get('data_kind', 'UNKNOWN')}:seed-{data.get('seed', 'UNKNOWN')}"
    ledger = run_dir.parent / "holdout_consumption.jsonl"
    lock_path = run_dir.parent / "holdout_consumption.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            existing = read_jsonl(ledger)
            if any(event.get("model_id") == "MDL_CREDIT_V1" and event.get("dataset_sha256") == dataset_sha256 and event.get("campaign_id") == campaign_id for event in existing):
                raise GateError("This Holdout has already been consumed in the same campaign; no retry or repair is permitted")
            record = {
                "schema_version": "1",
                "run_id": run_id,
                "model_id": "MDL_CREDIT_V1",
                "campaign_id": campaign_id,
                "dataset_sha256": dataset_sha256,
                "candidate_sha256": candidate_sha256,
                "consumed_at": utc_now(),
                "status": "CONSUMED",
            }
            append_jsonl(ledger, record)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return record
