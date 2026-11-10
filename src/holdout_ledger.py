"""Reconstructible record of every consumed formal Holdout (release blocker 5).

The consumed Holdout files live only on this machine, so a teammate with a clean
checkout cannot read them. Instead this module rebuilds each historical split from
the approved UCI ZIP plus the parameters recorded in
``config/holdout_ledger.json`` and verifies the rebuilt files against the recorded
hashes. A mismatch is a hard error: the exclusion set is never guessed.

Only hashes and parameters are committed; no rows, ids or labels leave this
machine.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

from src.common import ContractError, read_json

LEDGER_PATH = Path("config") / "holdout_ledger.json"
SPLIT_NAMES = ("train", "dev", "holdout", "shift_pool")
REQUIRED_CAMPAIGN_FIELDS = ("campaign_id", "seed", "algorithm", "excluded_campaigns", "splits")


def _split_v1_sequential(frame, rng, split_sizes):
    """The v1 split order: train, dev, holdout, shift_pool, no exclusion."""

    import numpy as np

    from src.data import _stratified_counts

    remaining = {
        label: rng.permutation(np.flatnonzero(frame["default_flag"].to_numpy() == label))
        for label in (0, 1)
    }
    splits = {}
    names = list(split_sizes)
    for name in names:
        if name == names[-1]:
            selected = remaining
        else:
            counts = _stratified_counts({label: len(indices) for label, indices in remaining.items()}, split_sizes[name])
            selected = {label: remaining[label][: counts[label]] for label in remaining}
            remaining = {label: remaining[label][counts[label]:] for label in remaining}
        positions = np.concatenate([selected[label] for label in sorted(selected)])
        splits[name] = frame.iloc[positions].sort_values("client_id", kind="mergesort").reset_index(drop=True)
    return {name: splits[name] for name in split_sizes}


ALGORITHMS = {
    "split-v1-sequential": _split_v1_sequential,
    "split-v2-holdout-first": None,  # bound lazily to src.data._split_frame
}


def _algorithm(name: str):
    if name not in ALGORITHMS:
        raise ContractError(f"Unknown split algorithm in the Holdout ledger: {name}")
    if ALGORITHMS[name] is None:
        from src.data import _split_frame

        return _split_frame
    return ALGORITHMS[name]


def load_ledger(path: Path) -> dict:
    if not path.is_file():
        raise ContractError(f"Holdout ledger is missing: {path}")
    ledger = read_json(path)
    if ledger.get("schema_version") != "1":
        raise ContractError("Holdout ledger schema_version must be 1")
    dataset = ledger.get("dataset") or {}
    if not isinstance(dataset.get("zip_sha256"), str) or len(dataset["zip_sha256"]) != 64:
        raise ContractError("Holdout ledger must record the approved dataset ZIP sha256")
    campaigns = ledger.get("campaigns")
    if not isinstance(campaigns, list) or not campaigns:
        raise ContractError("Holdout ledger must list at least one campaign")
    seen: list[str] = []
    for campaign in campaigns:
        missing = [field for field in REQUIRED_CAMPAIGN_FIELDS if field not in campaign]
        if missing:
            raise ContractError(f"Holdout ledger campaign is missing {missing}")
        if not isinstance(campaign["seed"], int) or isinstance(campaign["seed"], bool) or campaign["seed"] < 1:
            raise ContractError("Holdout ledger campaign seed must be a positive integer")
        if campaign["campaign_id"] in seen:
            raise ContractError(f"Duplicate Holdout ledger campaign: {campaign['campaign_id']}")
        unknown = [other for other in campaign["excluded_campaigns"] if other not in seen]
        if unknown:
            raise ContractError(
                f"{campaign['campaign_id']} excludes campaigns that are not recorded earlier: {unknown}"
            )
        splits = campaign["splits"]
        if not isinstance(splits, dict) or set(splits) != {f"{name}.csv" for name in SPLIT_NAMES}:
            raise ContractError(f"{campaign['campaign_id']} must record exactly the four split hashes")
        for name, digest in splits.items():
            if not isinstance(digest, str) or len(digest) != 64:
                raise ContractError(f"{campaign['campaign_id']} has an invalid {name} hash")
        seen.append(campaign["campaign_id"])
    return ledger


def _serialize(frame) -> bytes:
    buffer = io.BytesIO()
    frame.to_csv(buffer, index=False, lineterminator="\n", float_format="%.17g")
    return buffer.getvalue()


def recover_historical_splits(raw_zip: Path, ledger: dict, ledger_path: Path | None = None) -> dict:
    """Rebuild every recorded split from the approved ZIP and verify its hash."""

    import numpy as np

    from src.data import LEGACY_SPLIT_SIZES, _load_config, _read_uci, _transform_raw

    raw_zip = Path(raw_zip)
    if not raw_zip.is_file():
        raise ContractError(f"Approved UCI ZIP is missing: {raw_zip}")
    digest = hashlib.sha256(raw_zip.read_bytes()).hexdigest()
    if digest != ledger["dataset"]["zip_sha256"]:
        raise ContractError("The UCI ZIP does not match the approved dataset hash in the Holdout ledger")

    _config, _config_sha = _load_config()
    frame = _transform_raw(_read_uci(raw_zip))
    recovered: dict[str, dict] = {}
    for campaign in ledger["campaigns"]:
        excluded: set[str] = set()
        for other in campaign["excluded_campaigns"]:
            if other not in recovered:
                raise ContractError(f"Cannot rebuild {campaign['campaign_id']} before {other}")
            excluded |= recovered[other]["holdout_ids"]
        rng = np.random.default_rng(int(campaign["seed"]))
        algorithm = _algorithm(campaign["algorithm"])
        if campaign["algorithm"] == "split-v1-sequential":
            splits = algorithm(frame, rng, LEGACY_SPLIT_SIZES)
        else:
            splits = algorithm(frame, rng, excluded, LEGACY_SPLIT_SIZES)
        for name, expected in campaign["splits"].items():
            actual = hashlib.sha256(_serialize(splits[name.replace(".csv", "")])).hexdigest()
            if actual != expected:
                raise ContractError(
                    f"{campaign['campaign_id']} {name} rebuilt to {actual} but the ledger records {expected}; "
                    "refusing to derive an exclusion set from an unverified history"
                )
        recovered[campaign["campaign_id"]] = {
            "campaign_id": campaign["campaign_id"],
            "seed": campaign["seed"],
            "algorithm": campaign["algorithm"],
            "holdout_sha256": campaign["splits"]["holdout.csv"],
            "holdout_rows": int(len(splits["holdout"])),
            "holdout_ids": set(splits["holdout"]["client_id"].astype(str).tolist()),
        }
    return recovered


def exclusion_ids(recovered: dict, campaign_ids: list[str]) -> set[str]:
    ids: set[str] = set()
    for campaign_id in campaign_ids:
        if campaign_id not in recovered:
            raise ContractError(f"Exclusion source {campaign_id} was not recovered from the ledger")
        ids |= recovered[campaign_id]["holdout_ids"]
    return ids


def verify_ledger(repository: Path, raw_zip: Path) -> dict:
    """Return a summary of the rebuilt campaigns, for CLI evidence and tests."""

    ledger = load_ledger(repository / LEDGER_PATH)
    recovered = recover_historical_splits(raw_zip, ledger)
    return {
        "dataset_zip_sha256": ledger["dataset"]["zip_sha256"],
        "campaigns": [
            {
                "campaign_id": value["campaign_id"],
                "seed": value["seed"],
                "algorithm": value["algorithm"],
                "holdout_sha256": value["holdout_sha256"],
                "holdout_rows": value["holdout_rows"],
                "verified": True,
            }
            for value in recovered.values()
        ],
        "unique_excluded_rows": len(set().union(*(value["holdout_ids"] for value in recovered.values()))),
    }
