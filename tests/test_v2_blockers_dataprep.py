"""Release blocker 5: a clean checkout must be able to prepare the formal split.

The exclusion set is rebuilt from the approved UCI ZIP plus the committed ledger
and verified against the recorded split hashes. Nothing is read from `runs/`, and
no rows or ids are stored in the repository.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from src import data
from src.common import read_json
from src.holdout_ledger import LEDGER_PATH, load_ledger, recover_historical_splits, verify_ledger

REPOSITORY = Path(__file__).resolve().parents[1]
RAW_ZIP = REPOSITORY / "data" / "raw" / "default_of_credit_card_clients.zip"
DATASET_SHA = "56c885f84457f6680f8438f02bfcdac9579323d8a94465ee5f26e32baa727602"

pytestmark = pytest.mark.skipif(not RAW_ZIP.is_file(), reason="approved UCI ZIP is not on this machine")


def clean_repository(tmp_path: Path) -> Path:
    """A checkout-shaped repository: config only, no runs/ and no delivery/."""

    repo = tmp_path / "clean"
    (repo / "config").mkdir(parents=True)
    for name in ("data_config.json", "holdout_ledger.json"):
        shutil.copyfile(REPOSITORY / "config" / name, repo / "config" / name)
    return repo


def test_ledger_rebuilds_every_consumed_split_byte_for_byte(tmp_path):
    summary = verify_ledger(REPOSITORY, RAW_ZIP)
    ledger = load_ledger(REPOSITORY / LEDGER_PATH)
    # Every campaign recorded in the ledger must rebuild, in ledger order.
    assert [c["campaign_id"] for c in summary["campaigns"]] == [c["campaign_id"] for c in ledger["campaigns"]]
    assert all(c["verified"] for c in summary["campaigns"])
    assert [c["seed"] for c in summary["campaigns"]] == [c["seed"] for c in ledger["campaigns"]]
    # The exclusion union grows with each campaign and never exceeds the dataset.
    assert 0 < summary["unique_excluded_rows"] <= 30000


def test_ledger_records_hashes_only(tmp_path):
    text = (REPOSITORY / LEDGER_PATH).read_text(encoding="utf-8")
    ledger = json.loads(text)
    for campaign in ledger["campaigns"]:
        assert set(campaign["splits"]) == {"train.csv", "dev.csv", "holdout.csv", "shift_pool.csv"}
        assert not any(key in campaign for key in ("client_id", "ids", "rows_data"))
    assert "client_id" not in text


def test_tampered_ledger_hash_is_rejected(tmp_path):
    repo = clean_repository(tmp_path)
    ledger = read_json(repo / "config" / "holdout_ledger.json")
    ledger["campaigns"][0]["splits"]["holdout.csv"] = "0" * 64
    (repo / "config" / "holdout_ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
    with pytest.raises(Exception, match="refusing to derive an exclusion set"):
        recover_historical_splits(RAW_ZIP, load_ledger(repo / "config" / "holdout_ledger.json"))


def test_wrong_dataset_zip_is_rejected(tmp_path):
    other = tmp_path / "other.zip"
    other.write_bytes(b"not the approved archive")
    with pytest.raises(Exception, match="does not match the approved dataset hash"):
        recover_historical_splits(other, load_ledger(REPOSITORY / LEDGER_PATH))


def test_exclusion_requires_a_forward_dependency_order(tmp_path):
    repo = clean_repository(tmp_path)
    ledger = read_json(repo / "config" / "holdout_ledger.json")
    ledger["campaigns"][0]["excluded_campaigns"] = ["MDL_CREDIT_V1:uci:seed-44"]
    (repo / "config" / "holdout_ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
    with pytest.raises(Exception, match="not recorded earlier"):
        load_ledger(repo / "config" / "holdout_ledger.json")


def test_clean_checkout_reproduces_a_historical_split_from_the_ledger(tmp_path, monkeypatch):
    """As of the seed 46 run the ledger held seeds 42-45; a clean checkout must reproduce it."""

    repo = clean_repository(tmp_path)
    ledger_path = repo / "config" / "holdout_ledger.json"
    ledger = read_json(ledger_path)
    consumed = [campaign for campaign in ledger["campaigns"] if campaign["seed"] != 46]
    assert [campaign["seed"] for campaign in consumed] == [42, 43, 44, 45]
    ledger["campaigns"] = consumed
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    config = read_json(repo / "config" / "data_config.json")
    config["holdout_exclusion"]["campaigns"] = [campaign["campaign_id"] for campaign in consumed]
    config["seed"] = 46
    (repo / "config" / "data_config.json").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(data, "_config_path", lambda: repo / "config" / "data_config.json")

    manifest = data.prepare_uci(RAW_ZIP, tmp_path / "data", True, DATASET_SHA, run_id="clean-checkout")
    assert manifest["seed"] == 46
    assert {name: entry["rows"] for name, entry in manifest["files"].items()} == {
        "train.csv": 15000,
        "dev.csv": 6000,
        "holdout.csv": 6000,
        "shift_pool.csv": 3000,
    }
    # The rebuilt split is byte-identical to the one the seed 46 run used.
    recorded = next(c for c in load_ledger(REPOSITORY / LEDGER_PATH)["campaigns"] if c["seed"] == 46)
    for name, digest in recorded["splits"].items():
        assert manifest["files"][name]["sha256"] == digest, name
    exclusion = manifest["holdout_exclusion"]
    assert exclusion["overlap_total"] == 0
    assert not any("runs/" in json.dumps(source) for source in exclusion["sources"])


def test_prepare_now_refuses_because_only_1199_rows_were_never_consumed(tmp_path, monkeypatch):
    """Documents the data exhaustion: no further 6,000-row formal split is possible."""

    repo = clean_repository(tmp_path)
    monkeypatch.setattr(data, "_config_path", lambda: repo / "config" / "data_config.json")
    ledger = load_ledger(repo / "config" / "holdout_ledger.json")
    consumed: set[str] = set()
    from src.holdout_ledger import recover_historical_splits

    for campaign in recover_historical_splits(RAW_ZIP, ledger).values():
        consumed |= campaign["holdout_ids"]
    assert len(consumed) == 28801
    assert 30000 - len(consumed) == 1199
    with pytest.raises(ValueError, match="Too few rows remain"):
        data.prepare_uci(RAW_ZIP, tmp_path / "data2", True, DATASET_SHA, run_id="exhausted")
    assert not (tmp_path / "data2" / "holdout.csv").exists()


def test_prepare_without_the_zip_cannot_apply_the_exclusion(tmp_path, monkeypatch):
    repo = clean_repository(tmp_path)
    monkeypatch.setattr(data, "_config_path", lambda: repo / "config" / "data_config.json")
    config = read_json(repo / "config" / "data_config.json")
    with pytest.raises(ValueError, match="approved UCI ZIP"):
        data._excluded_holdout_ids(config, None)
