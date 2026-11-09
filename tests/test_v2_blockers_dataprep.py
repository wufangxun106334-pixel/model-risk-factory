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


def test_clean_checkout_prepares_the_formal_split_with_zero_overlap(tmp_path, monkeypatch):
    repo = clean_repository(tmp_path)
    monkeypatch.setattr(data, "_config_path", lambda: repo / "config" / "data_config.json")
    output = tmp_path / "data"
    manifest = data.prepare_uci(RAW_ZIP, output, True, DATASET_SHA, run_id="clean-checkout")

    config = read_json(repo / "config" / "data_config.json")
    assert manifest["seed"] == config["seed"]
    assert manifest["seed"] > max(c["seed"] for c in load_ledger(repo / "config" / "holdout_ledger.json")["campaigns"])
    assert {name: entry["rows"] for name, entry in manifest["files"].items()} == {
        "train.csv": 15000,
        "dev.csv": 6000,
        "holdout.csv": 6000,
        "shift_pool.csv": 3000,
    }
    exclusion = manifest["holdout_exclusion"]
    assert exclusion["enabled"] is True
    assert all(value == 0 for value in exclusion["overlap"].values()), exclusion["overlap"]
    assert exclusion["overlap_total"] == 0
    # The manifest cites campaign ids and hashes, never local run paths.
    assert not any("runs/" in json.dumps(source) for source in exclusion["sources"])

    rebuilt = recover_historical_splits(RAW_ZIP, load_ledger(repo / "config" / "holdout_ledger.json"))
    holdout = pd.read_csv(output / "holdout.csv")
    for campaign_id, value in rebuilt.items():
        assert len(set(holdout["client_id"].astype(str)) & value["holdout_ids"]) == 0, campaign_id


def test_prepare_without_the_zip_cannot_apply_the_exclusion(tmp_path, monkeypatch):
    repo = clean_repository(tmp_path)
    monkeypatch.setattr(data, "_config_path", lambda: repo / "config" / "data_config.json")
    config = read_json(repo / "config" / "data_config.json")
    with pytest.raises(ValueError, match="approved UCI ZIP"):
        data._excluded_holdout_ids(config, None)
