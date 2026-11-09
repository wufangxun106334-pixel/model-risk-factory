from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import urllib.request
from dataclasses import replace

import pytest

from src.provider import Provider, ProviderConfig, ProviderRequestLimitError, TransportResponse


@pytest.fixture(autouse=True)
def block_real_http(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("Real HTTP is forbidden in provider round tests")

    monkeypatch.setattr(urllib.request, "urlopen", fail_if_called)


def config():
    return replace(ProviderConfig.from_env({
        "LLM_BASE_URL": "https://sa.kaiwen.dev",
        "LLM_CHAT_COMPLETIONS_URL": "https://sa.kaiwen.dev/confirmed/chat/completions",
        "LLM_PROTOCOL": "openai_chat_completions",
        "LLM_MODEL": "test-model",
        "LLM_API_KEY": "not-persisted",
        "LLM_TIMEOUT_SECONDS": "10",
        "LLM_MAX_OUTPUT_TOKENS": "10",
    }), max_requests_per_agent_round=1)


def response():
    return TransportResponse(200, json.dumps({"id": "req", "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}).encode())


class Transport:
    def request(self, **kwargs):
        return response()


def test_request_cap_is_per_agent_round_not_entire_run(tmp_path):
    request_log = tmp_path / "request_log.jsonl"
    first = Provider(config(), request_log, "same-run", Transport(), request_round="inventory")
    second = Provider(config(), request_log, "same-run", Transport(), request_round="candidate-0")
    first.generate([{"role": "user", "content": "one"}])
    second.generate([{"role": "user", "content": "two"}])
    with pytest.raises(ProviderRequestLimitError):
        first.generate([{"role": "user", "content": "over limit"}])
    events = [json.loads(line) for line in request_log.read_text().splitlines()]
    assert {event["run_id"] for event in events} == {"same-run"}
    assert {event["request_round"] for event in events} == {"inventory", "candidate-0"}


def test_concurrent_providers_share_the_same_round_limit(tmp_path):
    request_log = tmp_path / "request_log.jsonl"
    started = Event()
    finish = Event()

    class WaitingTransport:
        def request(self, **kwargs):
            started.set()
            assert finish.wait(timeout=5)
            return response()

    first = Provider(config(), request_log, "same-run", WaitingTransport(), request_round="inventory")
    second = Provider(config(), request_log, "same-run", Transport(), request_round="inventory")
    messages = [{"role": "user", "content": "test"}]
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(first.generate, messages)
        try:
            assert started.wait(timeout=5)
            with pytest.raises(ProviderRequestLimitError):
                second.generate(messages)
        finally:
            finish.set()
        assert pending.result(timeout=5).request_id == "req"

    events = [json.loads(line) for line in request_log.read_text().splitlines()]
    assert [event["status"] for event in events] == ["STARTED", "REQUEST_LIMIT_EXCEEDED", "SUCCEEDED"]
