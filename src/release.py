"""Release check: does the published tree actually match the acceptance evidence?

Two things have to be true before a tag may claim a release:

* the evidence was produced from a committed, clean tree (``git_commit_at_init``
  equals the released commit and ``worktree_clean_at_init`` is true), and
* the published tree still satisfies that run's context and its own test suite.

Everything here is computed from the published tree, so later commits cannot
silently invalidate the answer.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from src.common import read_json, sha256_file
from src.context import materialize_tree, verify_context_at


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(["git", *arguments], cwd=repository, capture_output=True, text=True, check=False)
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _run_tree_tests(tree: Path, timeout_seconds: int) -> dict:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q"],
        cwd=tree,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(Path.home()), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    summary = [line for line in completed.stdout.strip().splitlines() if line.strip()][-1:] or [""]
    return {
        "passed": completed.returncode == 0,
        "exit_code": completed.returncode,
        "summary": summary[0][:200],
    }


def _acceptance_gaps(run_dir: Path, run_id: str) -> list[str]:
    gaps: list[str] = []
    acceptance_path = run_dir / "acceptance.json"
    if not acceptance_path.is_file():
        return ["acceptance.json missing"]
    acceptance = read_json(acceptance_path)
    if acceptance.get("run_id") != run_id:
        gaps.append("acceptance run_id mismatch")
    if acceptance.get("release_approved") is not True:
        failing = [record["acceptance_id"] for record in acceptance.get("records", []) if record.get("status") != "PASS"]
        gaps.append("acceptance not approved: " + ",".join(failing[:6]))
    export_path = run_dir / "export_verified.json"
    if not export_path.is_file():
        gaps.append("export_verified.json missing")
        return gaps
    export = read_json(export_path)
    archive = Path(export.get("archive", ""))
    if not archive.is_absolute():
        archive = run_dir / archive
    if not archive.is_file():
        gaps.append(f"evidence archive missing: {archive}")
    elif sha256_file(archive) != export.get("archive_sha256"):
        gaps.append("evidence archive hash does not match the export record")
    manifest_path = run_dir / "evidence_manifest.json"
    if not manifest_path.is_file():
        gaps.append("evidence_manifest.json missing")
        return gaps
    manifest = read_json(manifest_path)
    broken = [record["path"] for record in manifest.get("files", []) if not (run_dir / record["path"]).is_file() or sha256_file(run_dir / record["path"]) != record.get("sha256")]
    if broken:
        gaps.append("evidence files changed: " + ",".join(broken[:5]))
    return gaps


def release_check(repository: Path, ref: str, run_dir: Path, run_id: str, *, timeout_seconds: int = 1800) -> dict:
    repository = Path(repository)
    run_dir = Path(run_dir)
    commit = _git(repository, "rev-parse", f"{ref}^{{commit}}")
    if not commit:
        return {"status": "BLOCKED", "ref": ref, "gaps": [f"cannot resolve git ref {ref}"], "run_id": run_id}

    context = verify_context_at(repository, run_dir, run_id, ref)
    tree = materialize_tree(repository, ref)
    try:
        tests = _run_tree_tests(Path(tree.name), timeout_seconds)
    finally:
        tree.cleanup()

    manifest = read_json(run_dir / "run_manifest.json") if (run_dir / "run_manifest.json").is_file() else {}
    gaps: list[str] = []
    if context["verified"] is not True:
        if not context.get("source_matches"):
            gaps.append("published src/ does not match the run's trusted_source_sha256")
        if not context.get("tests_matches"):
            gaps.append("published tests/ does not match the run's trusted_tests_sha256")
        if context.get("asset_mismatches"):
            gaps.append("published repository assets differ: " + ",".join(context["asset_mismatches"][:6]))
        if not gaps:
            gaps.append("published tree fails verify_context for this run")
    if manifest.get("git_commit_at_init") != commit:
        gaps.append(f"run was initialised at {manifest.get('git_commit_at_init')}, not at the released commit {commit}")
    if manifest.get("worktree_clean_at_init") is not True:
        gaps.append("the worktree was dirty when the run was initialised, so the evidence does not belong to any commit")
    if not tests["passed"]:
        gaps.append(f"full test suite fails on the published tree: {tests['summary']}")
    gaps.extend(_acceptance_gaps(run_dir, run_id))

    return {
        "schema_version": "1",
        "run_id": run_id,
        "ref": ref,
        "commit": commit,
        "status": "APPROVED" if not gaps else "BLOCKED",
        "gaps": gaps,
        "context": context,
        "historical_evidence": {
            "run_git_commit_at_init": manifest.get("git_commit_at_init"),
            "worktree_clean_at_init": manifest.get("worktree_clean_at_init"),
            "acceptance_release_approved": (read_json(run_dir / "acceptance.json").get("release_approved") if (run_dir / "acceptance.json").is_file() else None),
        },
        "new_commit_checks": {"tests_on_published_tree": tests},
    }
