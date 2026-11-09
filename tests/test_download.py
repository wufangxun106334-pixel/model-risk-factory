from __future__ import annotations

import hashlib
import io

import pytest

from src.data import download_uci


class FakeResponse(io.BytesIO):
    def __init__(self, content: bytes):
        super().__init__(content)
        self.headers = {"x-request-id": "offline-test-request"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_download_requires_permission_before_network(tmp_path, monkeypatch):
    called = False

    def unexpected(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("network must not be used")

    monkeypatch.setattr("urllib.request.urlopen", unexpected)
    with pytest.raises(PermissionError):
        download_uci(tmp_path / "uci.zip", False, "0" * 64)
    assert called is False


def test_download_checks_hash_and_does_not_leave_partial_file(tmp_path, monkeypatch):
    content = b"offline fixture bytes, not UCI"
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: FakeResponse(content))
    target = tmp_path / "uci.zip"
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        download_uci(target, True, "0" * 64)
    assert not target.exists()
    assert not (tmp_path / "uci.zip.partial").exists()
    result = download_uci(target, True, hashlib.sha256(content).hexdigest())
    assert result["request_id"] == "offline-test-request"
    assert target.read_bytes() == content
