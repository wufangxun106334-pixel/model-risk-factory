from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "1"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SENSITIVE_ARGUMENTS = {"--api-key", "--token", "--authorization", "--secret"}


class ContractError(ValueError):
    pass


class GateError(PermissionError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def write_json(path: str | Path, value: Any) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(value)
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=destination.name + ".", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
    os.replace(temporary, destination)
    return destination


def read_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle, parse_constant=lambda value: (_ for _ in ()).throw(ContractError(f"Invalid JSON constant: {value}")))


def append_jsonl(path: str | Path, value: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(payload + "\n")


def read_jsonl(path: str | Path) -> list[Any]:
    source = Path(path)
    if not source.exists():
        return []
    with source.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def file_record(path: str | Path, base: str | Path | None = None) -> dict[str, Any]:
    source = Path(path)
    recorded_path = source.relative_to(Path(base)).as_posix() if base is not None else source.as_posix()
    return {"path": recorded_path, "sha256": sha256_file(source), "bytes": source.stat().st_size}


def tree_records(root: str | Path, base: str | Path | None = None) -> list[dict[str, Any]]:
    directory = Path(root)
    if not directory.exists():
        return []
    return [file_record(path, base=base) for path in sorted(directory.rglob("*")) if path.is_file() and "__pycache__" not in path.parts]


def current_git_commit(repository: Path) -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repository, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else "UNKNOWN"


def source_snapshot(repository: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for name in ("src", "tests", "legacy", "config", "docker"):
        records.extend(tree_records(repository / name, base=repository))
    for name in ("requirements.txt", "README.md", "docs/02_项目SOP.md"):
        path = repository / name
        if path.exists():
            records.append(file_record(path, base=repository))
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda item: item["path"]):
        digest.update(record["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(record["sha256"].encode("ascii"))
        digest.update(b"\n")
    return {"combined_sha256": digest.hexdigest(), "files": records}


def validate_run_id(run_id: str) -> str:
    if not RUN_ID_PATTERN.fullmatch(run_id) or run_id in {".", ".."}:
        raise ContractError("run_id contains unsupported characters")
    return run_id


def run_directory(runs_root: str | Path, run_id: str) -> Path:
    validate_run_id(run_id)
    return Path(runs_root) / run_id


def create_run(runs_root: str | Path, repository: Path, mode: str) -> dict[str, Any]:
    run_id = f"v2-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    directory = run_directory(runs_root, run_id)
    directory.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": utc_now(),
        "mode": mode,
        "model_id": "MDL_CREDIT_V1",
        "git_commit_at_init": current_git_commit(repository),
        "source_snapshot_at_init": source_snapshot(repository),
        "state": "INITIALIZED",
        "artifacts": {},
    }
    write_json(directory / "run_manifest.json", manifest)
    return manifest


def load_run(runs_root: str | Path, run_id: str) -> tuple[Path, dict[str, Any]]:
    directory = run_directory(runs_root, run_id)
    manifest_path = directory / "run_manifest.json"
    if not manifest_path.is_file():
        raise ContractError(f"Run does not exist: {run_id}")
    return directory, read_json(manifest_path)


def register_artifact(directory: Path, name: str, path: str | Path) -> None:
    manifest_path = directory / "run_manifest.json"
    manifest = read_json(manifest_path)
    manifest.setdefault("artifacts", {})[name] = file_record(path, base=directory)
    manifest["updated_at"] = utc_now()
    write_json(manifest_path, manifest)


def update_run_state(directory: Path, state: str) -> None:
    manifest_path = directory / "run_manifest.json"
    manifest = read_json(manifest_path)
    manifest["state"] = state
    manifest["updated_at"] = utc_now()
    write_json(manifest_path, manifest)


def redact_arguments(arguments: Iterable[str]) -> list[str]:
    redacted: list[str] = []
    hide_next = False
    for argument in arguments:
        if hide_next:
            redacted.append("<REDACTED>")
            hide_next = False
            continue
        if argument in SENSITIVE_ARGUMENTS:
            redacted.append(argument)
            hide_next = True
            continue
        if any(argument.startswith(name + "=") for name in SENSITIVE_ARGUMENTS):
            redacted.append(argument.split("=", 1)[0] + "=<REDACTED>")
            continue
        redacted.append(re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1<REDACTED>", argument))
    return redacted
