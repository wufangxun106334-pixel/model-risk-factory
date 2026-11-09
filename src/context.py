from __future__ import annotations

import hashlib
import io
import subprocess
import tarfile
import tempfile
from pathlib import Path

from src.common import file_record, read_json, sha256_file, tree_records, utc_now, write_json

REPOSITORY_ASSETS = [
    # Every legacy asset an inventory cites, so a Gate A review is bound to the
    # exact sources a reviewer read.
    "legacy/credit_v1.R",
    "legacy/credit_v2.R",
    "legacy/credit_tree.R",
    "legacy/notes/credit_v1.md",
    "legacy/notes/credit_v2.md",
    "legacy/notes/credit_tree.md",
    "config/data_config.json",
    "config/model_config.json",
    "config/candidate_contract.json",
    "config/candidate_schema.json",
    "config/inventory_schema.json",
    "config/inventory_expectations.json",
    "config/holdout_ledger.json",
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


def materialize_tree(repository: Path, ref: str) -> tempfile.TemporaryDirectory:
    """Check out ``ref`` into a temporary directory without touching the worktree."""

    archived = subprocess.run(
        ["git", "archive", "--format=tar", ref],
        cwd=repository,
        capture_output=True,
        check=False,
    )
    if archived.returncode != 0:
        raise ValueError(f"Cannot read git ref {ref}: {archived.stderr.decode('utf-8', 'replace')[:200]}")
    directory = tempfile.TemporaryDirectory(prefix="mrf-context-")
    with tarfile.open(fileobj=io.BytesIO(archived.stdout)) as archive:
        archive.extractall(directory.name, filter="data")
    return directory


def verify_context_at(repository: Path, run_dir: Path, run_id: str, ref: str) -> dict:
    """Read-only verification of a run's context against the tree of ``ref``.

    A run records the source/test tree it was produced from. Later commits change
    the worktree, so verification has to be done against the published tree rather
    than the current files.
    """

    tree = materialize_tree(repository, ref)
    try:
        root = Path(tree.name)
        verified = verify_context(root, run_dir, run_id)
        context = read_json(run_dir / "context_manifest.json")
        assets = context.get("assets") or []
        asset_mismatches = []
        for asset in assets:
            if asset.get("scope") != "repository":
                continue
            target = root / asset["path"]
            if not target.is_file() or sha256_file(target) != asset["sha256"]:
                asset_mismatches.append(asset["path"])
        return {
            "run_id": run_id,
            "ref": ref,
            "verified": verified,
            "source_matches": context.get("trusted_source_sha256") == _combined(tree_records(root / "src", base=root)),
            "tests_matches": context.get("trusted_tests_sha256") == _combined(tree_records(root / "tests", base=root)),
            "asset_mismatches": asset_mismatches,
            "asset_count": len(assets),
            "missing_assets": [path for path in asset_mismatches if not (root / path).is_file()],
        }
    finally:
        tree.cleanup()
