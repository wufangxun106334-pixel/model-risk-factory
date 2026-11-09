import json
import urllib.request
from dataclasses import replace

import pytest

from src.acceptance import _capability
from src.agent import check_provider
from src.provider import (
    CapabilityError,
    Provider,
    ProviderConfig,
    ProviderConfigurationError,
    ProviderRequestLimitError,
    ProviderTransportError,
    TransportResponse,
    UrllibTransport,
    write_capability_check,
)


SECRET = "test-api-key-that-must-never-be-persisted"
REQUEST_LOG_FIELDS = {
    "schema_version", "run_id", "request_round", "event_id", "timestamp",
    "request_id", "model", "transport", "kind", "status",
}


@pytest.fixture(autouse=True)
def block_real_http(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("Real HTTP is forbidden in provider tests")

    monkeypatch.setattr(urllib.request, "urlopen", fail_if_called)


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, *, url, headers, body, timeout):
        self.calls.append(
            {"url": url, "headers": dict(headers), "body": body, "timeout": timeout}
        )
        if not self.responses:
            raise AssertionError("Unexpected fake transport request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def environment(**overrides):
    values = {
        "LLM_BASE_URL": "https://sa.kaiwen.dev",
        "LLM_CHAT_COMPLETIONS_URL": "https://sa.kaiwen.dev/confirmed/chat/completions",
        "LLM_PROTOCOL": "openai_chat_completions",
        "LLM_MODEL": "confirmed-test-model",
        "LLM_API_KEY": SECRET,
        "LLM_TIMEOUT_SECONDS": "12",
        "LLM_MAX_OUTPUT_TOKENS": "100",
    }
    values.update(overrides)
    return values


def make_config(**overrides):
    return ProviderConfig.from_env(environment(**overrides))


def chat_response(
    *,
    content="parsed answer",
    request_id="req_test",
    tool_calls=None,
    finish_reason="stop",
    status=200,
    headers=None,
):
    payload = {
        "id": request_id,
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
    }
    if tool_calls is not None:
        payload["choices"][0]["message"]["tool_calls"] = tool_calls
    return TransportResponse(
        status=status,
        body=json.dumps(payload).encode("utf-8"),
        headers=headers or {},
    )


def read_events(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_missing_configuration_makes_zero_requests_and_writes_blocked_check(tmp_path):
    transport = FakeTransport()
    with pytest.raises(ProviderConfigurationError) as caught:
        ProviderConfig.from_env({"LLM_API_KEY": SECRET})

    assert "LLM_BASE_URL" in caught.value.variable_names
    assert "LLM_CHAT_COMPLETIONS_URL" in caught.value.variable_names
    assert "LLM_PROTOCOL" in caught.value.variable_names
    assert "LLM_MAX_OUTPUT_TOKENS" in caught.value.variable_names
    assert SECRET not in str(caught.value)
    assert transport.calls == []

    report_path = tmp_path / "capability_check.json"
    report = write_capability_check(report_path, config_error=caught.value)
    persisted = report_path.read_text(encoding="utf-8")
    assert report["status"] == "BLOCKED"
    assert report["configuration"]["status"] == "BLOCKED"
    assert report["request"] == {"status": "NOT_RUN"}
    assert report["tool"] == {"status": "NOT_RUN"}
    assert "LLM_BASE_URL" in persisted
    assert SECRET not in persisted
    assert transport.calls == []


@pytest.mark.parametrize(
    "overrides, expected_variables",
    [
        ({"LLM_BASE_URL": "http://sa.kaiwen.dev"}, {"LLM_BASE_URL"}),
        (
            {"LLM_CHAT_COMPLETIONS_URL": "https://sa.kaiwen.dev"},
            {"LLM_CHAT_COMPLETIONS_URL"},
        ),
        ({"LLM_PROTOCOL": "unverified_protocol"}, {"LLM_PROTOCOL"}),
        ({"LLM_TIMEOUT_SECONDS": "NaN"}, {"LLM_TIMEOUT_SECONDS"}),
        ({"LLM_MAX_OUTPUT_TOKENS": "-1"}, {"LLM_MAX_OUTPUT_TOKENS"}),
    ],
)
def test_invalid_configuration_names_variables_without_echoing_values(
    overrides, expected_variables
):
    with pytest.raises(ProviderConfigurationError) as caught:
        make_config(**overrides)
    assert expected_variables <= set(caught.value.variable_names)
    for invalid_value in overrides.values():
        assert invalid_value not in str(caught.value)
    assert SECRET not in str(caught.value)
    assert SECRET not in repr(make_config())


def test_generate_parses_response_and_persists_no_prompt_content_or_auth(tmp_path):
    transport = FakeTransport(chat_response())
    request_log = tmp_path / "request_log.jsonl"
    provider = Provider(make_config(), request_log, "run-generate", transport=transport)

    response = provider.generate(
        [{"role": "user", "content": "敏感提示词"}],
        max_output_tokens=40,
    )

    assert response.content == "parsed answer"
    assert response.tool_calls == ()
    assert response.finish_reason == "stop"
    assert response.request_id == "req_test"
    call = transport.calls[0]
    assert call["url"] == "https://sa.kaiwen.dev/confirmed/chat/completions"
    assert call["headers"]["Authorization"] == f"Bearer {SECRET}"
    assert call["headers"]["Content-Type"] == "application/json"
    assert call["timeout"] == 12
    payload = json.loads(call["body"].decode("utf-8"))
    assert payload == {
        "model": "confirmed-test-model",
        "messages": [{"role": "user", "content": "敏感提示词"}],
        "max_tokens": 40,
    }

    events = read_events(request_log)
    assert len(events) == 2
    assert all(set(event) == REQUEST_LOG_FIELDS for event in events)
    assert events[0]["status"] == "STARTED"
    assert events[1]["status"] == "SUCCEEDED"
    assert events[0]["event_id"] == events[1]["event_id"] == response.request_event_id
    assert events[1]["request_id"] == "req_test"
    persisted = request_log.read_text(encoding="utf-8")
    assert SECRET not in persisted
    assert "敏感提示词" not in persisted
    assert "parsed answer" not in persisted
    assert "Authorization" not in persisted


def test_request_limit_is_enforced_per_run_id(tmp_path):
    config = replace(make_config(), max_requests_per_agent_round=0)
    transport = FakeTransport(chat_response())
    request_log = tmp_path / "request_log.jsonl"
    provider = Provider(config, request_log, "run-limit", transport=transport)

    with pytest.raises(ProviderRequestLimitError):
        provider.generate([{"role": "user", "content": "not sent"}])
    assert transport.calls == []
    assert read_events(request_log)[0]["status"] == "REQUEST_LIMIT_EXCEEDED"


def test_http_error_is_sanitized_and_logged(tmp_path):
    error_body = json.dumps(
        {"error": f"provider leaked {SECRET} and sensitive server detail"}
    ).encode("utf-8")
    transport = FakeTransport(
        TransportResponse(
            status=500,
            body=error_body,
            headers={"x-request-id": f"request-{SECRET}"},
        )
    )
    request_log = tmp_path / "request_log.jsonl"
    config = replace(make_config(), max_retries=0)
    provider = Provider(config, request_log, "run-http-error", transport=transport)

    with pytest.raises(ProviderTransportError) as caught:
        provider.generate([{"role": "user", "content": "private prompt"}])

    assert "500" in str(caught.value)
    assert SECRET not in str(caught.value)
    assert "sensitive server detail" not in str(caught.value)
    assert SECRET not in caught.value.request_id
    events = read_events(request_log)
    assert len(events) == 2
    assert events[1]["status"] == "FAILED"
    persisted = request_log.read_text(encoding="utf-8")
    assert SECRET not in persisted
    assert "sensitive server detail" not in persisted
    assert "private prompt" not in persisted


def test_tool_roundtrip_executes_only_echo_and_links_both_requests(tmp_path):
    arguments = {"value": "roundtrip-ok", "count": 2}
    call_id = "call_echo_1"
    first = chat_response(
        content=None,
        request_id="req_tool_first",
        finish_reason="tool_calls",
        tool_calls=[
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": "echo_capability",
                    "arguments": json.dumps(arguments),
                },
            }
        ],
    )
    second = chat_response(
        content="Tool roundtrip completed",
        request_id="req_tool_final",
    )
    transport = FakeTransport(first, second)
    request_log = tmp_path / "request_log.jsonl"
    provider = Provider(make_config(), request_log, "run-tool", transport=transport)

    initial, final = provider.tool_roundtrip(argument=arguments)

    assert initial.request_id == "req_tool_first"

    assert final.content == "Tool roundtrip completed"
    assert final.request_id == "req_tool_final"
    assert len(transport.calls) == 2
    first_payload = json.loads(transport.calls[0]["body"].decode("utf-8"))
    assert first_payload["tools"][0]["function"]["name"] == "echo_capability"
    assert first_payload["tool_choice"] == {
        "type": "function",
        "function": {"name": "echo_capability"},
    }
    second_payload = json.loads(transport.calls[1]["body"].decode("utf-8"))
    assert second_payload["messages"][-2]["role"] == "assistant"
    assert second_payload["messages"][-2]["tool_calls"][0]["id"] == call_id
    assert second_payload["messages"][-1] == {
        "role": "tool",
        "tool_call_id": call_id,
        "name": "echo_capability",
        "content": json.dumps(arguments, separators=(",", ":")),
    }

    events = read_events(request_log)
    assert len(events) == 4
    assert [event["kind"] for event in events] == [
        "TOOL_ROUNDTRIP_REQUEST",
        "TOOL_ROUNDTRIP_REQUEST",
        "TOOL_ROUNDTRIP_FINAL",
        "TOOL_ROUNDTRIP_FINAL",
    ]
    assert events[0]["event_id"] == events[1]["event_id"]
    assert events[2]["event_id"] == events[3]["event_id"]
    assert events[0]["event_id"] != events[2]["event_id"]
    assert {event["run_id"] for event in events} == {"run-tool"}
    assert {event["request_id"] for event in events} == {
        None,
        "req_tool_first",
        "req_tool_final",
    }
    persisted = request_log.read_text(encoding="utf-8")
    assert "roundtrip-ok" not in persisted
    assert "Tool roundtrip completed" not in persisted
    assert SECRET not in persisted


def test_tool_roundtrip_reports_capability_failure_instead_of_faking_success(tmp_path):
    transport = FakeTransport(chat_response(content="I cannot call tools"))
    request_log = tmp_path / "request_log.jsonl"
    provider = Provider(make_config(), request_log, "run-no-tool", transport=transport)

    with pytest.raises(CapabilityError, match="exactly one tool call"):
        provider.tool_roundtrip()
    assert len(transport.calls) == 1
    assert len(read_events(request_log)) == 2

    with pytest.raises(CapabilityError, match="Only the fixed"):
        provider.tool_roundtrip(tool_name="arbitrary_local_code")
    assert len(transport.calls) == 1


def test_provider_capability_report_contains_safe_metadata_and_statuses(tmp_path):
    config = make_config()
    provider = Provider(config, tmp_path / "unused.jsonl", "run-capability", FakeTransport())
    path = tmp_path / "capability_check.json"

    report = provider.write_capability_check(
        path,
        request_ids=["req_1", "req_2"],
        request_status="PASS",
        tool_status="PASS",
        output_parse_status="PASS",
    )

    assert report["status"] == "PASS"
    assert report["base_url"] == "https://sa.kaiwen.dev"
    assert report["protocol"] == "openai_chat_completions"
    assert report["model"] == "confirmed-test-model"
    assert report["request_ids"] == ["req_1", "req_2"]
    assert report["request"]["status"] == "PASS"
    assert report["tool"]["status"] == "PASS"
    assert report["output_parse"]["status"] == "PASS"
    assert SECRET not in path.read_text(encoding="utf-8")


def test_check_provider_passes_on_responses_without_token_usage(tmp_path, monkeypatch):
    for name, value in environment().items():
        monkeypatch.setenv(name, value)
    transport = FakeTransport(
        chat_response(request_id="req-short"),
        chat_response(
            request_id="req-tool",
            finish_reason="tool_calls",
            content=None,
            tool_calls=[{
                "id": "call-echo",
                "type": "function",
                "function": {
                    "name": "echo_capability",
                    "arguments": '{"message":"provider_capability_check"}',
                },
            }],
        ),
        chat_response(request_id="req-final"),
    )
    monkeypatch.setattr(UrllibTransport, "request", lambda self, **kwargs: transport.request(**kwargs))

    report = check_provider(tmp_path, "run-capability")

    assert report["status"] == "PASS"
    assert report["request_ids"] == ["req-short", "req-tool", "req-final"]
    assert _capability(tmp_path, "run-capability")[0] == "PASS"
    (tmp_path / "provider" / "request_log.jsonl").unlink()
    assert _capability(tmp_path, "run-capability")[0] == "FAIL"


def test_check_provider_marks_truncated_short_reply_as_failure_not_tool_block(tmp_path, monkeypatch):
    for name, value in environment().items():
        monkeypatch.setenv(name, value)
    transport = FakeTransport(
        chat_response(request_id="req-empty", content="", finish_reason="length")
    )
    monkeypatch.setattr(UrllibTransport, "request", lambda self, **kwargs: transport.request(**kwargs))

    report = check_provider(tmp_path, "run-truncated")

    assert report["status"] == "FAIL"
    assert report["request"] == {"status": "PASS"}
    assert report["output_parse"] == {"status": "FAIL"}
    assert report["tool"] == {"status": "NOT_RUN"}
    assert report["request_ids"] == ["req-empty"]
    assert len(transport.calls) == 1


def test_check_provider_reports_rejected_tool_roundtrip_as_failed_not_blocked(tmp_path, monkeypatch):
    for name, value in environment().items():
        monkeypatch.setenv(name, value)
    transport = FakeTransport(
        chat_response(request_id="req-short"),
        chat_response(
            request_id="req-wrong-tool",
            finish_reason="tool_calls",
            content=None,
            tool_calls=[{
                "id": "call-other",
                "type": "function",
                "function": {"name": "not_echo_capability", "arguments": "{}"},
            }],
        ),
    )
    monkeypatch.setattr(UrllibTransport, "request", lambda self, **kwargs: transport.request(**kwargs))

    report = check_provider(tmp_path, "run-wrong-tool")

    assert report["status"] == "FAIL"
    assert report["tool"] == {"status": "FAIL"}
    assert report["output_parse"] == {"status": "PASS"}


def test_check_provider_gives_short_reply_room_for_reasoning_tokens(tmp_path, monkeypatch):
    for name, value in environment(LLM_MAX_OUTPUT_TOKENS="8192").items():
        monkeypatch.setenv(name, value)
    transport = FakeTransport(
        chat_response(request_id="req-short"),
        chat_response(
            request_id="req-tool",
            finish_reason="tool_calls",
            content=None,
            tool_calls=[{
                "id": "call-echo",
                "type": "function",
                "function": {
                    "name": "echo_capability",
                    "arguments": '{"message":"provider_capability_check"}',
                },
            }],
        ),
        chat_response(request_id="req-final"),
    )
    monkeypatch.setattr(UrllibTransport, "request", lambda self, **kwargs: transport.request(**kwargs))

    report = check_provider(tmp_path, "run-budget")

    assert report["status"] == "PASS"
    short_body = json.loads(transport.calls[0]["body"].decode("utf-8"))
    assert short_body["max_tokens"] == 256
