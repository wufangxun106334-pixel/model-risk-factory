"""Read-only readiness check before the one formal UCI run (hand-off H-01..H-04).

``formal-preflight`` never creates a run, never writes a command log and never
touches the Holdout. It only reports whether the preconditions that are otherwise
written in prose are actually true on this machine, so a formal run cannot start
on a dirty tree, the wrong root, an unapproved dataset or an already consumed seed.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from src.common import current_git_commit, git_worktree_clean, read_json, read_jsonl, sha256_file

DEFAULT_ZIP = Path("data") / "raw" / "default_of_credit_card_clients.zip"
REQUIRED_IMAGES = ("rocker/r-ver:4.4.2", "model-risk-factory-runner:v1")

Runner = Callable[[list[str]], int]


def _run(command: list[str]) -> int:
    try:
        return subprocess.run(command, capture_output=True, check=False, timeout=60).returncode
    except (OSError, subprocess.TimeoutExpired):
        return 1


def _check(name: str, ok: bool, detail: str) -> dict[str, str]:
    return {"check": name, "status": "PASS" if ok else "FAIL", "detail": detail}


def _campaign_id(seed: int) -> str:
    return f"MDL_CREDIT_V1:uci:seed-{seed}"


def run_preflight(
    repository: Path,
    runs_root: Path,
    *,
    expected_sha: str | None = None,
    raw_zip: Path | None = None,
    environ: Mapping[str, str] | None = None,
    runner: Runner = _run,
    verify_ledger: Callable[[Path, Path], dict] | None = None,
) -> dict[str, Any]:
    repository = Path(repository).resolve()
    runs_root = Path(runs_root).resolve()
    environ = os.environ if environ is None else environ
    raw_zip = repository / DEFAULT_ZIP if raw_zip is None else Path(raw_zip)
    checks: list[dict[str, str]] = []

    clean = git_worktree_clean(repository)
    checks.append(_check("worktree_clean", clean, "git status --porcelain is empty" if clean else "uncommitted or untracked files present"))
    head = current_git_commit(repository)
    if expected_sha:
        checks.append(_check("head_matches_expected", head == expected_sha, f"HEAD={head} expected={expected_sha}"))

    formal_root = (repository / "runs").resolve()
    checks.append(_check("formal_runs_root", runs_root == formal_root, f"runs root {runs_root}; formal root is {formal_root}"))

    config = read_json(repository / "config" / "data_config.json")
    seed = int(config["seed"])
    checks.append(_check("campaign_seed", seed == 47, f"config/data_config.json seed={seed}; the remaining formal campaign is 47"))
    approved = config.get("uci_competition_use_approved") is True
    checks.append(_check(
        "uci_use_approved",
        approved,
        "uci_competition_use_approved=true" if approved
        else "uci_competition_use_approved is not true; record the organiser's written permission first (H-01)",
    ))

    ledger = read_json(repository / "config" / "holdout_ledger.json")
    expected_zip = ledger["dataset"]["zip_sha256"]
    if raw_zip.is_file():
        actual_zip = sha256_file(raw_zip)
        checks.append(_check("uci_zip_hash", actual_zip == expected_zip, f"{raw_zip.name} sha256={actual_zip} ledger={expected_zip}"))
        if actual_zip == expected_zip:
            if verify_ledger is None:
                from src.holdout_ledger import verify_ledger as verify_ledger
            try:
                summary = verify_ledger(repository, raw_zip)
                count = len(summary["campaigns"])
                checks.append(_check("holdout_ledger_rebuild", True, f"{count} historical campaigns rebuilt and verified"))
            except Exception as error:  # every rebuild failure blocks the run
                checks.append(_check("holdout_ledger_rebuild", False, str(error)))
    else:
        checks.append(_check("uci_zip_hash", False, f"approved ZIP not found at {raw_zip}"))

    campaign = _campaign_id(seed)
    committed = [entry.get("campaign_id") for entry in ledger.get("campaigns", [])]
    checks.append(_check("seed_unused_in_committed_ledger", campaign not in committed, f"{campaign} in config/holdout_ledger.json: {campaign in committed}"))
    consumption = runs_root / "holdout_consumption.jsonl"
    consumed = [event.get("campaign_id") for event in read_jsonl(consumption)] if consumption.is_file() else []
    checks.append(_check(
        "seed_unused_in_local_ledger",
        campaign not in consumed,
        f"{campaign} in {consumption.name}: {campaign in consumed} ({len(consumed)} records); "
        "the team's authoritative ledger must also be confirmed (H-02)",
    ))

    from src.provider import ProviderConfig, ProviderConfigurationError

    try:
        ProviderConfig.from_env(environ)
        checks.append(_check("llm_configuration", True, "LLM_* settings are present and well formed (values not shown)"))
    except ProviderConfigurationError as error:
        checks.append(_check("llm_configuration", False, str(error)))

    docker_ok = runner(["docker", "info"]) == 0
    checks.append(_check("docker_daemon", docker_ok, "docker info succeeded" if docker_ok else "docker info failed"))
    for image in REQUIRED_IMAGES:
        present = docker_ok and runner(["docker", "image", "inspect", image]) == 0
        checks.append(_check(f"image {image}", present, "present" if present else "missing or Docker unavailable"))

    failed = [check["check"] for check in checks if check["status"] != "PASS"]
    return {
        "status": "PASS" if not failed else "FAIL",
        "head": head,
        "campaign_id": campaign,
        "failed_checks": failed,
        "checks": checks,
        "note": "Read-only: no run was created and no Holdout was touched.",
    }
