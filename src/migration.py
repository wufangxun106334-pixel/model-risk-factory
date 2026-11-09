from __future__ import annotations

import difflib
import shutil
from pathlib import Path

from src.common import ContractError, GateError, read_json, sha256_bytes, sha256_file, utc_now, write_json
from src.contracts import MigrationResult
from src.review import require_approval


def candidate_dir(run_dir: Path, attempt: int) -> Path:
    if attempt < 0 or attempt > 2:
        raise ContractError("Migration attempts are limited to initial generation plus two repairs")
    return run_dir / "candidates" / f"attempt_{attempt:03d}"


def save_candidate(run_dir: Path, run_id: str, code: str, attempt: int, api_evidence: dict, generation_mode: str = "UNATTESTED") -> dict:
    inventory_path = run_dir / "model_inventory.json"
    require_approval(run_dir, run_id, "Gate_A", inventory_path)
    directory = candidate_dir(run_dir, attempt)
    if directory.exists():
        raise ContractError(f"Candidate attempt already exists: {attempt}")
    if attempt > 0 and not candidate_dir(run_dir, attempt - 1).is_dir():
        raise ContractError("Candidate attempts must be sequential")
    directory.mkdir(parents=True)
    normalized = code if code.endswith("\n") else code + "\n"
    source = directory / "credit_v1.py"
    source.write_text(normalized, encoding="utf-8")
    digest = sha256_file(source)
    previous = candidate_dir(run_dir, attempt - 1) / "credit_v1.py" if attempt else None
    old_lines = previous.read_text(encoding="utf-8").splitlines(keepends=True) if previous and previous.exists() else []
    diff = "".join(difflib.unified_diff(old_lines, normalized.splitlines(keepends=True), fromfile=str(previous) if previous else "/dev/null", tofile=f"attempt_{attempt:03d}/credit_v1.py"))
    (directory / "candidate.diff").write_text(diff, encoding="utf-8")
    if generation_mode not in {"REAL_API", "TEST_DOUBLE", "UNATTESTED"}:
        raise ContractError("Unknown candidate generation mode")
    context_sha256 = sha256_file(run_dir / "context_manifest.json")
    metadata = {
        "schema_version": "1",
        "run_id": run_id,
        "model_id": "MDL_CREDIT_V1",
        "attempt": attempt,
        "candidate_sha256": digest,
        "created_at": utc_now(),
        "generation_mode": generation_mode,
        "context_sha256": context_sha256,
        "api_evidence": api_evidence,
        "gate_b_status": "NOT_REVIEWED",
    }
    write_json(directory / "candidate.json", metadata)
    result = MigrationResult(run_id=run_id, model_id="MDL_CREDIT_V1", candidate_sha256=digest, attempt=attempt, dev_status="NOT_RUN", final_status="NOT_RUN", diagnostics_ref=None, context_sha256=context_sha256)
    write_json(run_dir / "migration_result.json", result.model_dump())
    return metadata


def load_candidate(run_dir: Path, attempt: int | None = None) -> tuple[Path, dict]:
    if attempt is None:
        attempts = sorted(path for path in (run_dir / "candidates").glob("attempt_*") if path.is_dir()) if (run_dir / "candidates").is_dir() else []
        if not attempts:
            raise ContractError("No migration candidate exists")
        directory = attempts[-1]
    else:
        directory = candidate_dir(run_dir, attempt)
    metadata = read_json(directory / "candidate.json")
    source = directory / "credit_v1.py"
    if sha256_file(source) != metadata["candidate_sha256"]:
        raise ContractError("Candidate source hash does not match its metadata")
    return directory, metadata


def update_dev_result(run_dir: Path, run_id: str, attempt: int, status: str, diagnostics_ref: str | None) -> dict:
    directory, metadata = load_candidate(run_dir, attempt)
    result = MigrationResult(run_id=run_id, model_id="MDL_CREDIT_V1", candidate_sha256=metadata["candidate_sha256"], attempt=attempt, dev_status=status, final_status="NOT_RUN", diagnostics_ref=diagnostics_ref, context_sha256=metadata["context_sha256"])
    write_json(run_dir / "migration_result.json", result.model_dump())
    return result.model_dump()


def freeze_candidate(run_dir: Path, run_id: str, attempt: int) -> dict:
    directory, metadata = load_candidate(run_dir, attempt)
    require_approval(run_dir, run_id, "Gate_A", run_dir / "model_inventory.json")
    result = read_json(run_dir / "migration_result.json")
    context_sha256 = sha256_file(run_dir / "context_manifest.json")
    if result["candidate_sha256"] != metadata["candidate_sha256"] or result["dev_status"] != "PASS":
        raise GateError("Only the latest candidate with PASS development parity can be frozen")
    if result.get("context_sha256") != context_sha256 or metadata.get("context_sha256") != context_sha256:
        raise GateError("Candidate development result belongs to an invalidated input/code/test context")
    fixture_path = run_dir / "dev" / f"attempt_{attempt:03d}" / "fixture_summary.json"
    fixtures = read_json(fixture_path) if fixture_path.is_file() else {}
    if fixtures.get("run_id") != run_id or fixtures.get("candidate_sha256") != metadata["candidate_sha256"] or fixtures.get("status") != "PASS":
        raise GateError("Candidate must pass the fixed behaviour fixtures in Docker before freezing")
    require_approval(run_dir, run_id, "Gate_B", directory / "credit_v1.py")
    frozen_dir = run_dir / "frozen"
    if frozen_dir.exists():
        raise ContractError("A candidate is already frozen for this run")
    frozen_dir.mkdir(parents=True)
    shutil.copyfile(directory / "credit_v1.py", frozen_dir / "credit_v1.py")
    frozen = {"schema_version": "1", "run_id": run_id, "model_id": "MDL_CREDIT_V1", "attempt": attempt, "candidate_sha256": metadata["candidate_sha256"], "context_sha256": context_sha256, "frozen_at": utc_now(), "source_candidate": str(directory.relative_to(run_dir))}
    write_json(frozen_dir / "frozen.json", frozen)
    return frozen


def load_frozen(run_dir: Path, run_id: str) -> dict:
    frozen = read_json(run_dir / "frozen" / "frozen.json")
    if frozen["run_id"] != run_id:
        raise ContractError("Frozen candidate run_id mismatch")
    source = run_dir / "frozen" / "credit_v1.py"
    if sha256_file(source) != frozen["candidate_sha256"]:
        raise ContractError("Frozen candidate hash mismatch")
    return frozen


def sha256_code(code: str) -> str:
    normalized = code if code.endswith("\n") else code + "\n"
    return sha256_bytes(normalized.encode("utf-8"))
