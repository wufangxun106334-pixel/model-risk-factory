"""Release check: does the published tree actually match the acceptance evidence?

Two things have to be true before a tag may claim a release:

* the evidence was produced from a committed, clean tree (``git_commit_at_init``
  equals the released commit and ``worktree_clean_at_init`` is true), and
* the published tree still satisfies that run's context and its own test suite.

Everything here is computed from the published tree, so later commits cannot
silently invalidate the answer.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree

import json

from src.common import read_json, sha256_file
from src.outputs import check_output_destination, create_new_output
from src.context import materialize_tree, verify_context_at


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(["git", *arguments], cwd=repository, capture_output=True, text=True, check=False)
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _run_tree_tests(tree: Path, timeout_seconds: int) -> dict:
    """Run the full suite in the published tree and classify every outcome."""

    report = tree / "pytest-junit.xml"
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider", f"--junit-xml={report}"],
        cwd=tree,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(Path.home()), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    passed: list[str] = []
    failed: list[str] = []
    skipped: list[str] = []
    if report.is_file():
        try:
            root = ElementTree.parse(report).getroot()
        except ElementTree.ParseError:
            root = None
        if root is not None:
            for case in root.iter("testcase"):
                name = f"{case.get('classname', '')}::{case.get('name', '')}".strip(":")
                if case.find("skipped") is not None:
                    skipped.append(name)
                elif case.find("failure") is not None or case.find("error") is not None:
                    failed.append(name)
                else:
                    passed.append(name)
    summary = [line for line in completed.stdout.strip().splitlines() if line.strip()][-1:] or [""]
    totals = {"passed": len(passed), "failed": len(failed), "skipped": len(skipped)}
    return {
        # Full pass means nothing failed and nothing was skipped: a skipped required
        # test is a release gap, not a pass.
        # A non-zero exit (collection error, internal error, plugin failure) blocks
        # the release even when every reported test case passed.
        "passed": completed.returncode == 0 and totals["failed"] == 0 and totals["skipped"] == 0 and bool(passed or failed or skipped),
        "exit_code": completed.returncode,
        "totals": totals,
        "failed_tests": failed[:10],
        "skipped_tests": skipped[:10],
        "summary": summary[0][:200],
    }


def _provision_approved_zip(repository: Path, tree: Path, run_dir: Path, zip_path: Path | None) -> list[str]:
    """Copy the approved UCI ZIP into the isolated tree so data tests really run."""

    ledger_path = tree / "config" / "holdout_ledger.json"
    if not ledger_path.is_file():
        return ["published tree has no config/holdout_ledger.json, so the approved dataset cannot be provisioned"]
    expected = read_json(ledger_path).get("dataset", {}).get("zip_sha256")
    source = Path(zip_path) if zip_path is not None else repository / "data" / "raw" / "default_of_credit_card_clients.zip"
    if not isinstance(expected, str) or len(expected) != 64:
        return ["published ledger does not declare the approved dataset hash"]
    if not source.is_file():
        return [f"approved UCI ZIP not found at {source}; data-dependent tests cannot run"]
    if sha256_file(source) != expected:
        return [f"local UCI ZIP hash does not match the approved ledger hash ({expected[:12]}…)"]
    destination = tree / "data" / "raw" / "default_of_credit_card_clients.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return []


def compare_command_log(run_dir: Path, save_copy: Path | None = None, protected_roots: Iterable[Path | tuple[Path, str]] = ()) -> dict:
    """Compare the live command log with the export snapshot without writing the run.

    The snapshot is the sealed record and the live log may have grown after export.
    Besides reading it, the only supported inspection is saving a copy of the
    snapshot as a new file outside every protected directory (see src/outputs.py):
    an existing destination, including a hard link to a live log, is refused.
    """

    live_path = run_dir / "command_log.jsonl"
    snapshot_path = run_dir / "command_log_snapshot.jsonl"
    if not snapshot_path.is_file():
        raise ValueError("command_log_snapshot.jsonl is required")
    snapshot = snapshot_path.read_text(encoding="utf-8").splitlines()
    live = live_path.read_text(encoding="utf-8").splitlines() if live_path.is_file() else []
    prefix_matches = live[: len(snapshot)] == snapshot
    if prefix_matches:
        extra = live[len(snapshot) :]
        missing = snapshot[len(live) :] if len(live) < len(snapshot) else []
    else:
        extra = [line for line in live if line not in snapshot]
        missing = [line for line in snapshot if line not in live]

    def commands(lines: list[str]) -> list[str]:
        names: list[str] = []
        for line in lines:
            try:
                payload = json.loads(line)
            except ValueError:
                names.append("<unparsable>")
                continue
            argv = payload.get("argv") if isinstance(payload, dict) else None
            names.append(str(argv[3]) if isinstance(argv, list) and len(argv) > 3 else "<unknown>")
        return names

    result = {
        "run_id": read_json(run_dir / "run_manifest.json").get("run_id") if (run_dir / "run_manifest.json").is_file() else None,
        "status": "MATCH" if live == snapshot else "DIFFERS",
        "snapshot_lines": len(snapshot),
        "live_lines": len(live),
        "prefix_matches": prefix_matches,
        "extra_live_lines": len(extra),
        "missing_live_lines": len(missing),
        "extra_commands": commands(extra),
        "missing_commands": commands(missing),
        "snapshot_sha256": sha256_file(snapshot_path),
        "live_sha256": sha256_file(live_path) if live_path.is_file() else None,
    }
    if save_copy is not None:
        roots = [*run_protected_roots(run_dir), *protected_roots]
        check_output_destination(save_copy, roots)
        payload = snapshot_path.read_bytes()
        destination = create_new_output(save_copy, payload, roots)
        result["saved_copy"] = str(destination)
        result["saved_copy_sha256"] = hashlib.sha256(payload).hexdigest()
    return result


def run_protected_roots(run_dir: Path) -> list[tuple[Path, str]]:
    """The inspected run and its sibling runs are always protected."""

    run_dir = Path(run_dir)
    return [(run_dir, "the run directory"), (run_dir.parent, "the runs root (other runs)")]


REQUIRED_RECORDS = tuple(
    [("v1", f"V1-{index:02d}") for index in range(1, 8)] + [("v2", f"V2-{index:02d}") for index in range(1, 8)]
)


def label(record_key: tuple[str, str]) -> str:
    return f"{record_key[1]} ({record_key[0]})"


def _acceptance_gaps(run_dir: Path, run_id: str, commit: str) -> list[str]:
    acceptance_path = run_dir / "acceptance.json"
    if not acceptance_path.is_file():
        return ["acceptance.json missing"]
    acceptance = read_json(acceptance_path)
    gaps: list[str] = []
    if acceptance.get("run_id") != run_id:
        gaps.append(f"acceptance run_id {acceptance.get('run_id')!r} does not match the target run {run_id!r}")
    if acceptance.get("release_approved") is not True:
        gaps.append("acceptance.release_approved is not true")

    manifest_path = run_dir / "evidence_manifest.json"
    export_path = run_dir / "export_verified.json"
    manifest = read_json(manifest_path) if manifest_path.is_file() else None
    export = read_json(export_path) if export_path.is_file() else None
    sealed: dict[str, str] = {}
    if manifest is not None:
        files = manifest.get("files")
        if isinstance(files, list):
            paths = [record.get("path") for record in files]
            duplicates = sorted({path for path in paths if path is not None and paths.count(path) > 1})
            if duplicates:
                gaps.append("evidence manifest lists duplicate paths: " + ",".join(str(path) for path in duplicates[:5]))
            sealed = {
                record["path"]: record["sha256"]
                for record in files
                if isinstance(record.get("path"), str) and isinstance(record.get("sha256"), str)
            }
            # The manifest itself is sealed too: it is a ZIP member and its hash is
            # recorded by the export, even though it does not list itself in files.
            sealed.setdefault("evidence_manifest.json", sha256_file(manifest_path))

    records = acceptance.get("records")
    if not isinstance(records, list):
        return gaps + ["acceptance.records is missing"]
    expected = set(REQUIRED_RECORDS)
    seen: dict[tuple[str, str], list[dict]] = {}
    for record in records:
        key = (str(record.get("version")), str(record.get("acceptance_id")))
        if key not in expected:
            gaps.append(f"unexpected acceptance record {label(key)}")
            continue
        seen.setdefault(key, []).append(record)

    for key in REQUIRED_RECORDS:
        found = seen.get(key, [])
        if not found:
            gaps.append(f"missing acceptance record {label(key)}")
            continue
        if len(found) > 1:
            gaps.append(f"duplicate acceptance record {label(key)} ({len(found)} occurrences)")
            continue
        record = found[0]
        if record.get("status") != "PASS":
            gaps.append(f"{label(key)} status is {record.get('status')!r}, not PASS")
        recorded_commit = record.get("commit_sha")
        if recorded_commit != commit:
            gaps.append(
                f"{label(key)} recorded commit {str(recorded_commit)[:8]} does not match the released commit {commit[:8]}"
            )
        evidence = record.get("evidence_path")
        if not evidence:
            gaps.append(f"{label(key)} has no evidence path")
            continue
        target = (run_dir / evidence).resolve()
        run_root = run_dir.resolve()
        if run_root not in target.parents and target != run_root:
            gaps.append(f"{label(key)} evidence path escapes the run: {evidence}")
        elif not target.is_file():
            gaps.append(f"{label(key)} evidence file is missing: {evidence}")
        elif evidence not in sealed:
            gaps.append(f"{label(key)} evidence is not part of the sealed evidence: {evidence}")
        elif sha256_file(target) != sealed[evidence]:
            gaps.append(f"{label(key)} evidence hash does not match the sealed manifest: {evidence}")

    if export is None:
        return gaps + ["export_verified.json missing"]
    if manifest is None:
        return gaps + ["evidence_manifest.json missing"]
    if export.get("run_id") != run_id:
        gaps.append(f"export_verified run_id {export.get('run_id')!r} does not match the target run {run_id!r}")
    if export.get("verified") is not True:
        gaps.append("export_verified.verified is not true")
    if manifest.get("run_id") != run_id:
        gaps.append("evidence_manifest run_id mismatch")
    if export.get("manifest_sha256") != sha256_file(manifest_path):
        gaps.append("export record manifest hash does not match the manifest on disk")
    if export.get("file_count") != manifest.get("file_count"):
        gaps.append("export record file count does not match the manifest")
    archive = Path(export.get("archive", ""))
    if not archive.is_absolute():
        archive = run_dir / archive
    if not archive.is_file():
        return gaps + [f"evidence archive missing: {archive}"]
    if sha256_file(archive) != export.get("archive_sha256"):
        gaps.append("evidence archive hash does not match the export record")
    broken = [
        record["path"]
        for record in manifest.get("files", [])
        if not (run_dir / record["path"]).is_file() or sha256_file(run_dir / record["path"]) != record.get("sha256")
    ]
    if broken:
        gaps.append("evidence files changed: " + ",".join(broken[:5]))
    gaps.extend(_zip_gaps(archive, run_id, manifest, manifest_path))
    return gaps


def _zip_gaps(archive: Path, run_id: str, manifest: dict, manifest_path: Path) -> list[str]:
    """Verify the exported ZIP member by member, not just its own hash."""

    gaps: list[str] = []
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        return ["evidence manifest lists no files"]
    intended = {f"{run_id}/{record['path']}" for record in files}
    intended.add(f"{run_id}/evidence_manifest.json")
    recorded = {record["path"]: record["sha256"] for record in files}
    manifest_digest = sha256_file(manifest_path)
    try:
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            duplicates = sorted({name for name in names if names.count(name) > 1})
            if duplicates:
                gaps.append("evidence archive has duplicate members: " + ",".join(duplicates[:5]))
            present = set(names)
            missing = sorted(intended - present)
            extra = sorted(present - intended)
            if missing:
                gaps.append("evidence archive is missing members: " + ",".join(missing[:5]))
            if extra:
                gaps.append("evidence archive has unexpected members: " + ",".join(extra[:5]))
            for name in sorted(intended & present):
                relative = name.split("/", 1)[1]
                expected = manifest_digest if relative == "evidence_manifest.json" else recorded.get(relative)
                payload = bundle.read(name)
                if expected is None or hashlib.sha256(payload).hexdigest() != expected:
                    gaps.append(f"evidence archive member content changed: {relative}")
    except (zipfile.BadZipFile, OSError):
        gaps.append("evidence archive is not a readable ZIP")
    return gaps


def release_check(repository: Path, ref: str, run_dir: Path, run_id: str, *, timeout_seconds: int = 1800, zip_path: Path | None = None) -> dict:
    repository = Path(repository)
    run_dir = Path(run_dir)
    commit = _git(repository, "rev-parse", f"{ref}^{{commit}}")
    if not commit:
        return {"status": "BLOCKED", "ref": ref, "gaps": [f"cannot resolve git ref {ref}"], "run_id": run_id}

    context = verify_context_at(repository, run_dir, run_id, ref)
    tree = materialize_tree(repository, ref)
    try:
        dataset_gaps = _provision_approved_zip(repository, Path(tree.name), run_dir, zip_path)
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
    gaps.extend(dataset_gaps)
    if tests["totals"]["failed"]:
        gaps.append(f"test suite fails on the published tree: {tests['totals']['failed']} failing ({', '.join(tests['failed_tests'][:5])})")
    if tests["exit_code"] != 0 and not tests["totals"]["failed"]:
        gaps.append(
            f"pytest exited with {tests['exit_code']} on the published tree even though JUnit reports "
            f"{tests['totals']['passed']} passed; a non-zero exit blocks the release"
        )
    if tests["totals"]["skipped"]:
        gaps.append(
            f"required tests were skipped on the published tree: {tests['totals']['skipped']} skipped "
            f"({', '.join(tests['skipped_tests'][:5])})"
        )
    if not tests["totals"]["passed"] and not tests["totals"]["failed"] and not tests["totals"]["skipped"]:
        gaps.append("no tests were collected on the published tree")
    gaps.extend(_acceptance_gaps(run_dir, run_id, commit))

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
