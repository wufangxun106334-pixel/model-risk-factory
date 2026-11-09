import hashlib
import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src import data


@pytest.fixture(scope="module")
def synthetic_run(tmp_path_factory):
    output_dir = tmp_path_factory.mktemp("synthetic")
    manifest = data.prepare_synthetic(output_dir)
    frames = {
        name: pd.read_csv(output_dir / f"{name}.csv")
        for name in data.SPLIT_SIZES
    }
    return output_dir, manifest, frames


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_frozen_config():
    config = json.loads((Path(__file__).parents[1] / "config" / "data_config.json").read_text())
    assert config["model_id"] == "MDL_CREDIT_V1"
    assert config["seed"] == 42
    assert config["total_rows"] == 30000
    assert config["split_sizes"] == {
        "train": 15000,
        "dev": 6000,
        "holdout": 6000,
        "shift_pool": 3000,
    }
    assert config["max_default_rate_difference"] == 0.01
    assert config["uci_landing_url"] == data.UCI_LANDING_URL
    assert config["uci_zip_url"] == data.UCI_ZIP_URL
    assert config["uci_competition_use_approved"] is False
    assert config["uci_expected_sha256"] is None


def test_synthetic_exact_unique_mutually_exclusive_splits(synthetic_run):
    output_dir, manifest, frames = synthetic_run
    assert sum(len(frame) for frame in frames.values()) == 30000
    assert {name: len(frame) for name, frame in frames.items()} == data.SPLIT_SIZES
    assert set(data.RAW_COLUMNS) == {
        "ID", "LIMIT_BAL", "SEX", "EDUCATION", "MARRIAGE", "AGE",
        "PAY_0", "PAY_2", "PAY_3", "PAY_4", "PAY_5", "PAY_6",
        *(f"BILL_AMT{month}" for month in range(1, 7)),
        *(f"PAY_AMT{month}" for month in range(1, 7)),
        "default payment next month",
    }

    combined = pd.concat(frames.values(), ignore_index=True)
    assert combined["client_id"].is_unique
    assert set(combined["default_flag"]) == {0, 1}
    split_ids = [set(frame["client_id"]) for frame in frames.values()]
    for index, left in enumerate(split_ids):
        for right in split_ids[index + 1:]:
            assert left.isdisjoint(right)

    validation = data.validate_splits(frames)
    assert validation["valid"] is True
    assert validation["errors"] == []
    assert manifest["split_validation"] == validation
    assert manifest["data_kind"] == "synthetic"
    assert manifest["synthetic"] is True
    assert manifest["formal_status"] == "BLOCKED"
    assert manifest["overall"]["rows"] == 30000
    assert manifest["overall"]["unique_client_ids"] == 30000
    assert "Data kind: **synthetic**" in (output_dir / "SOURCE.md").read_text()


def test_split_default_rates_and_file_manifest(synthetic_run):
    output_dir, manifest, frames = synthetic_run
    overall_rate = pd.concat(frames.values())["default_flag"].mean()
    assert overall_rate == manifest["overall"]["default_rate"]
    for name, frame in frames.items():
        assert abs(frame["default_flag"].mean() - overall_rate) <= 0.01
        filename = f"{name}.csv"
        entry = manifest["files"][filename]
        assert entry["rows"] == len(frame)
        assert entry["default_rate"] == frame["default_flag"].mean()
        assert entry["sha256"] == _file_sha256(output_dir / filename)

    manifest_text = (output_dir / "data_manifest.json").read_text()
    assert "NaN" not in manifest_text
    assert "Infinity" not in manifest_text
    assert json.loads(manifest_text) == manifest
    assert len(manifest["config_sha256"]) == 64


def test_synthetic_encoding_and_derived_columns(synthetic_run):
    _, manifest, frames = synthetic_run
    frame = pd.concat(frames.values(), ignore_index=True)
    assert list(frame.columns) == data.OUTPUT_COLUMNS
    assert not frame["education"].isin([0, 5, 6]).any()
    assert not (frame["marriage"] == 0).any()
    assert all(manifest["encoding_recodes"]["education"].values())
    assert manifest["encoding_recodes"]["marriage"]["0_to_3"] > 0
    assert manifest["encoding_counts"]["education"]["4"] == int((frame["education"] == 4).sum())
    assert (frame["bill_amt_1"] < 0).any()
    assert frame["sex"].nunique() == 2
    assert set(frame["age_band"]) == {"21-25", "26-35", "36-50", "51+"}

    np.testing.assert_allclose(frame["log_limit"], np.log1p(frame["limit_bal"]), rtol=0, atol=0)
    for month in range(1, 7):
        np.testing.assert_array_equal(
            frame[f"delay_{month}"],
            frame[f"pay_status_{month}"].clip(lower=0),
        )
        expected_utilization = (frame[f"bill_amt_{month}"] / frame["limit_bal"]).clip(0, 2)
        np.testing.assert_allclose(frame[f"util_{month}"], expected_utilization, rtol=0, atol=0)
        np.testing.assert_allclose(
            frame[f"log_pay_{month}"],
            np.log1p(frame[f"pay_amt_{month}"]),
            rtol=0,
            atol=0,
        )
    expected_bands = np.select(
        [
            frame["age"].between(21, 25),
            frame["age"].between(26, 35),
            frame["age"].between(36, 50),
            frame["age"] >= 51,
        ],
        ["21-25", "26-35", "36-50", "51+"],
        default="",
    )
    np.testing.assert_array_equal(frame["age_band"], expected_bands)


def test_synthetic_csv_hashes_are_deterministic(synthetic_run, tmp_path):
    first_dir, first_manifest, _ = synthetic_run
    second_dir = tmp_path / "repeat"
    second_manifest = data.prepare_synthetic(second_dir)
    filenames = [
        *(f"{name}.csv" for name in data.SPLIT_SIZES),
        "data_dictionary.json",
        "data_manifest.json",
        "SOURCE.md",
    ]
    for filename in filenames:
        assert _file_sha256(first_dir / filename) == _file_sha256(second_dir / filename)
    assert first_manifest == second_manifest


def test_validate_splits_detects_overlap(synthetic_run):
    _, _, frames = synthetic_run
    invalid = {name: frame.copy() for name, frame in frames.items()}
    invalid["holdout"].loc[0, "client_id"] = invalid["train"].loc[0, "client_id"]
    validation = data.validate_splits(invalid)
    assert validation["valid"] is False
    assert validation["mutually_exclusive"] is False
    assert any("Overlapping client_id" in error for error in validation["errors"])


def test_uci_permission_and_hash_are_checked_before_read(tmp_path, monkeypatch):
    def unexpected_read(*args, **kwargs):
        raise AssertionError("UCI content was read before the gate passed")

    monkeypatch.setattr(data.pd, "read_excel", unexpected_read)
    missing = tmp_path / "not-present.xls"
    with pytest.raises(PermissionError):
        data.prepare_uci(missing, tmp_path / "out", False, "0" * 64)
    with pytest.raises(ValueError, match="expected_sha256"):
        data.prepare_uci(missing, tmp_path / "out", True, "")
    with pytest.raises(ValueError, match="64-character"):
        data.prepare_uci(missing, tmp_path / "out", True, "abc")

    placeholder = tmp_path / "placeholder.xls"
    placeholder.write_bytes(b"synthetic offline placeholder, not UCI data")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        data.prepare_uci(placeholder, tmp_path / "out", True, "0" * 64)


def test_uci_zip_rejects_traversal_and_multiple_xls(tmp_path):
    traversal = tmp_path / "traversal.zip"
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../outside.xls", b"not an xls")
    with pytest.raises(ValueError, match="Unsafe ZIP member"):
        data._read_uci_zip(traversal)

    multiple = tmp_path / "multiple.zip"
    with zipfile.ZipFile(multiple, "w") as archive:
        archive.writestr("first.xls", b"not an xls")
        archive.writestr("nested/second.xls", b"not an xls")
    with pytest.raises(ValueError, match="exactly one"):
        data._read_uci_zip(multiple)
