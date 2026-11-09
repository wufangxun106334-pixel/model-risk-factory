from __future__ import annotations

import hashlib
import os
import stat
import zipfile
from pathlib import Path, PurePosixPath

from src.common import file_record, sha256_file, utc_now, write_json

_ALLOWED_EXTENSIONS = {
    ".csv",
    ".diff",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".py",
    ".txt",
    ".yaml",
    ".yml",
}

_ROOT_ALLOWED = {
    "acceptance.json",
    "agent_audit_log.jsonl",
    "command_log_snapshot.jsonl",
    "context_manifest.json",
    "environment.json",
    "migration_result.json",
    "model_inventory.json",
    "review_log.json",
    "run_manifest.json",
    "source_snapshot.json",
    "test_summary.json",
}
_DIRECT_ALLOWED = {
    "candidates": {"candidate.json"},
    "data": {"SOURCE.md", "data_dictionary.json", "data_manifest.json", "download.json", "uci_approval.json"},
    "frozen": {"frozen.json"},
    "mutation": {"mutant_parity_summary.json", "mutation_summary.json"},
    "provider": {"capability_check.json", "request_log.jsonl"},
    "reference": {"baseline_manifest.json", "model.json", "r_execution.json", "sessionInfo.txt"},
}
_SUMMARY_ALLOWED = {"execution.json", "fixture_summary.json", "parity_summary.json"}
_RUNNER_ALLOWED = {"execution.json", "integration_summary.json", "parity_summary.json"}
_LIVE_COMMAND_LOG = "command_log.jsonl"
_COMMAND_LOG_SNAPSHOT = "command_log_snapshot.jsonl"
_EVIDENCE_MANIFEST = "evidence_manifest.json"
_EXPORT_RECORD = "export_verified.json"
_EXPORT_EXCLUDED = {_EVIDENCE_MANIFEST, _EXPORT_RECORD, "acceptance.json"}


def is_allowed(relative: PurePosixPath) -> bool:
    parts = relative.parts
    if not parts or relative.is_absolute() or any(part in {"", ".", ".."} for part in parts):
        return False
    if any(part == "__pycache__" or part.startswith(".") for part in parts):
        return False
    name = parts[-1]
    if len(parts) == 1:
        return name in _ROOT_ALLOWED
    top = parts[0]
    if top in _DIRECT_ALLOWED:
        return len(parts) == 2 and name in _DIRECT_ALLOWED[top]
    if top in {"parity", "dev", "holdout"}:
        return name in _SUMMARY_ALLOWED
    if top == "runner_integration":
        return name in _RUNNER_ALLOWED
    if top == "cli_output":
        return len(parts) == 2 and name.endswith(".json")
    return False


def _validated_entry(path: Path, root: Path) -> int:
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode):
        raise ValueError(f"evidence contains a symbolic link: {path}")
    if not stat.S_ISREG(mode) and not stat.S_ISDIR(mode):
        raise ValueError(f"evidence contains an unsupported file type: {path}")
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"evidence entry resolves outside run_dir: {path}") from exc
    return mode


def _evidence_files(root: Path, manifest_path: Path) -> list[Path]:
    files = []
    directories = [root]
    while directories:
        directory = directories.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                mode = _validated_entry(path, root)
                if stat.S_ISDIR(mode):
                    directories.append(path)
                    continue
                relative = PurePosixPath(path.relative_to(root).as_posix())
                if (
                    path != manifest_path
                    and relative.as_posix() not in _EXPORT_EXCLUDED
                    and path.suffix.lower() in _ALLOWED_EXTENSIONS
                    and is_allowed(relative)
                ):
                    files.append(path)
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def _archive_digest(archive: Path) -> str:
    digest = hashlib.sha256()
    with archive.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_archive(archive: Path, run_id: str, files: list[dict], manifest_path: Path) -> None:
    expected = {f"{run_id}/{record['path']}" for record in files}
    expected.add(f"{run_id}/{_EVIDENCE_MANIFEST}")
    recorded = {record["path"]: record for record in files}
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        if names != expected:
            missing = sorted(expected - names)[:5]
            extra = sorted(names - expected)[:5]
            raise ValueError(f"evidence archive entries do not match the manifest: missing={missing} extra={extra}")
        for name in names:
            payload = bundle.read(name)
            relative = name.split("/", 1)[1]
            if relative == _EVIDENCE_MANIFEST:
                if hashlib.sha256(payload).hexdigest() != sha256_file(manifest_path):
                    raise ValueError("evidence archive manifest does not match the exported manifest")
                continue
            if hashlib.sha256(payload).hexdigest() != recorded[relative]["sha256"]:
                raise ValueError(f"evidence archive hash mismatch: {relative}")


def export_evidence(run_dir: Path, run_id: str, delivery_dir: Path) -> dict:
    from src.environment import capture_environment

    run_dir = Path(run_dir)
    if not stat.S_ISDIR(run_dir.lstat().st_mode):
        raise ValueError("run_dir is not a regular directory")
    root = run_dir.resolve(strict=True)
    manifest_path = root / _EVIDENCE_MANIFEST
    _evidence_files(root, manifest_path)

    live_log = root / _LIVE_COMMAND_LOG
    if live_log.is_file():
        (root / _COMMAND_LOG_SNAPSHOT).write_bytes(live_log.read_bytes())
    capture_environment(root)
    paths = _evidence_files(root, manifest_path)
    if not paths:
        raise ValueError("no whitelisted evidence files were found")
    files = [file_record(path, base=root) for path in paths]
    manifest = {
        "schema_version": "1",
        "run_id": run_id,
        "exported_at": utc_now(),
        "file_count": len(files),
        "files": files,
        "excluded": {
            "reason": "line-level splits, labels, baseline answers, prediction details, row diffs, candidate-controlled code/output and stdout/stderr stay local",
            "paths": sorted(_EXPORT_EXCLUDED),
        },
    }
    write_json(manifest_path, manifest)
    if not stat.S_ISREG(_validated_entry(manifest_path, root)):
        raise ValueError("evidence manifest is not a regular file")

    delivery_dir = Path(delivery_dir)
    delivery_dir.mkdir(parents=True, exist_ok=True)
    archive = delivery_dir / f"{run_id}_evidence.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in paths:
            _validated_entry(path, root)
            bundle.write(
                path,
                arcname=f"{run_id}/{path.relative_to(root).as_posix()}",
            )
        bundle.write(manifest_path, arcname=f"{run_id}/{_EVIDENCE_MANIFEST}")
    _verify_archive(archive, run_id, files, manifest_path)
    export_verified = {
        "schema_version": "1",
        "run_id": run_id,
        "verified": True,
        "verified_at": utc_now(),
        "archive": str(archive),
        "archive_sha256": _archive_digest(archive),
        "manifest_sha256": sha256_file(manifest_path),
        "file_count": len(files),
    }
    write_json(root / _EXPORT_RECORD, export_verified)
    return {
        "manifest": str(manifest_path),
        "archive": str(archive),
        "file_count": len(files),
        "export_verified": str(root / _EXPORT_RECORD),
    }
