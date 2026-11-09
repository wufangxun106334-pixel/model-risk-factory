from __future__ import annotations

import hashlib
from pathlib import Path

from src.common import file_record, read_json, sha256_file, tree_records, utc_now, write_json

REPOSITORY_ASSETS = [
    "legacy/credit_v1.R",
    "config/data_config.json",
    "config/model_config.json",
    "config/candidate_contract.json",
    "config/candidate_schema.json",
    "config/inventory_schema.json",
    "config/provider_config.json",
    "config/runtime_config.json",
    "requirements.txt",
]
RUN_ASSETS = [
    "data/train.csv",
    "data/dev.csv",
    "data/holdout.csv",
    "data/shift_pool.csv",
    "reference/model.json",
    "reference/train_predictions.csv",
    "reference/dev_predictions.csv",
    "reference/holdout_predictions.csv",
    "reference/baseline_manifest.json",
]


def _combined(records) -> str:
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda item: item["path"]):
        digest.update(record["path"].encode("utf-8"))
        digest.update(record["sha256"].encode("ascii"))
    return digest.hexdigest()


def create_context(repository: Path, run_dir: Path) -> dict:
    run_id = read_json(run_dir / "run_manifest.json")["run_id"]
    assets = []
    for relative in REPOSITORY_ASSETS:
        assets.append({"scope": "repository", **file_record(repository / relative, base=repository)})
    for relative in RUN_ASSETS:
        assets.append({"scope": "run", **file_record(run_dir / relative, base=run_dir)})
    tests = tree_records(repository / "tests", base=repository)
    trusted_source = tree_records(repository / "src", base=repository)
    context = {
        "schema_version": "1",
        "run_id": run_id,
        "model_id": "MDL_CREDIT_V1",
        "created_at": utc_now(),
        "assets": assets,
        "trusted_tests_sha256": _combined(tests),
        "trusted_source_sha256": _combined(trusted_source),
    }
    write_json(run_dir / "context_manifest.json", context)
    return context


def verify_context(repository: Path, run_dir: Path, run_id: str) -> bool:
    path = run_dir / "context_manifest.json"
    if not path.is_file():
        return False
    try:
        context = read_json(path)
        if context.get("run_id") != run_id:
            return False
        for asset in context["assets"]:
            root = repository if asset["scope"] == "repository" else run_dir
            target = root / asset["path"]
            if not target.is_file() or target.is_symlink() or sha256_file(target) != asset["sha256"]:
                return False
        if context.get("trusted_tests_sha256") is not None and context["trusted_tests_sha256"] != _combined(tree_records(repository / "tests", base=repository)):
            return False
        if context.get("trusted_source_sha256") is not None and context["trusted_source_sha256"] != _combined(tree_records(repository / "src", base=repository)):
            return False
        return True
    except (OSError, KeyError, TypeError, ValueError):
        return False
