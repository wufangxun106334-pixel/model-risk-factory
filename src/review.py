from __future__ import annotations

from pathlib import Path
from typing import Literal

from src.common import GateError, canonical_json_bytes, read_json, sha256_bytes, sha256_file, utc_now, write_json
from src.context import verify_context
from src.contracts import ReviewEntry

Gate = Literal["Gate_A", "Gate_B"]


def artifact_digest(path: str | Path, gate: Gate) -> str:
    artifact = Path(path)
    if gate == "Gate_B":
        return sha256_file(artifact)
    inventory = read_json(artifact)
    if not isinstance(inventory, dict):
        raise GateError("Gate A artifact must be a JSON object")
    payload = {key: value for key, value in inventory.items() if key != "review_status"}
    return sha256_bytes(canonical_json_bytes(payload))


def review_log_path(run_dir: Path) -> Path:
    return run_dir / "review_log.json"


def load_reviews(run_dir: Path) -> list[dict]:
    path = review_log_path(run_dir)
    if not path.exists():
        return []
    payload = read_json(path)
    return [ReviewEntry.model_validate(item).model_dump() for item in payload["reviews"]]


def record_review(
    run_dir: Path,
    run_id: str,
    gate: Gate,
    artifact_path: Path,
    expected_sha256: str,
    decision: Literal["APPROVED", "REJECTED"],
    reviewer: str,
    comment: str,
) -> dict:
    repository = run_dir.parent.parent
    if not verify_context(repository, run_dir, run_id):
        raise GateError("Current inputs/code/tests do not match the frozen context; review is invalid")
    context_path = run_dir / "context_manifest.json"
    context_sha256 = sha256_file(context_path)
    actual_sha256 = artifact_digest(artifact_path, gate)
    if actual_sha256 != expected_sha256:
        raise GateError(f"{gate} hash mismatch: expected {expected_sha256}, actual {actual_sha256}")
    entry = ReviewEntry(
        run_id=run_id,
        gate=gate,
        decision=decision,
        reviewer=reviewer,
        timestamp=utc_now(),
        comment=comment,
        reviewed_artifact_sha256=actual_sha256,
        context_sha256=context_sha256,
    )
    reviews = load_reviews(run_dir)
    reviews.append(entry.model_dump())
    write_json(review_log_path(run_dir), {"schema_version": "1", "run_id": run_id, "reviews": reviews})
    if gate == "Gate_A":
        inventory = read_json(artifact_path)
        inventory["review_status"] = decision
        write_json(artifact_path, inventory)
    return entry.model_dump()


def current_decision(run_dir: Path, run_id: str, gate: Gate, artifact_path: Path) -> str:
    if not verify_context(run_dir.parent.parent, run_dir, run_id):
        return "INVALIDATED"
    context_sha256 = sha256_file(run_dir / "context_manifest.json")
    digest = artifact_digest(artifact_path, gate)
    matching = [entry for entry in load_reviews(run_dir) if entry["run_id"] == run_id and entry["gate"] == gate and entry["reviewed_artifact_sha256"] == digest and entry.get("context_sha256") == context_sha256]
    return matching[-1]["decision"] if matching else "NOT_REVIEWED"


def require_approval(run_dir: Path, run_id: str, gate: Gate, artifact_path: Path) -> str:
    digest = artifact_digest(artifact_path, gate)
    if current_decision(run_dir, run_id, gate, artifact_path) != "APPROVED":
        raise GateError(f"{gate} approval is required for artifact {digest}")
    return digest
