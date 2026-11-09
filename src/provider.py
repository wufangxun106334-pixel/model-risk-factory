from __future__ import annotations

import fcntl
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union


StrPath = Union[str, os.PathLike[str]]
SUPPORTED_PROTOCOL = "openai_chat_completions"
SCHEMA_VERSION = "1"
_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "provider_config.json"
_ENV_NAMES = (
    "LLM_BASE_URL",
    "LLM_CHAT_COMPLETIONS_URL",
    "LLM_PROTOCOL",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_TIMEOUT_SECONDS",
    "LLM_MAX_OUTPUT_TOKENS",
)


class ProviderError(Exception):
    pass


class ProviderConfigurationError(ProviderError, ValueError):
    def __init__(self, variable_names: Sequence[str]):
        self.variable_names = tuple(dict.fromkeys(str(name) for name in variable_names))
        super().__init__(
            "Missing or invalid provider configuration; check variables: "
            + ", ".join(self.variable_names)
        )


class ProviderRequestError(ProviderError, ValueError):
    pass


class ProviderRequestLimitError(ProviderError):
    pass


class ProviderTransportError(ProviderError):
    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        request_id: Optional[str] = None,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.request_id = request_id
        self.retryable = retryable


class ProviderResponseError(ProviderError):
    pass


class ProviderRequestLogError(ProviderError):
    pass


class CapabilityError(ProviderError):
    pass


def _finite_number(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _valid_https_url(value: str, *, complete_endpoint: bool) -> bool:
    try:
        parsed = urllib.parse.urlsplit(value)
        _ = parsed.port
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    if parsed.query or parsed.fragment:
        return False
    if complete_endpoint and parsed.path in ("", "/"):
        return False
    return True


def _runtime_settings() -> dict[str, Any]:
    try:
        with _CONFIG_PATH.open("r", encoding="utf-8") as handle:
            settings = json.load(handle)
        if not isinstance(settings, dict):
            raise ValueError
        default_model = settings["default_model"]
        timeout_seconds = _finite_number(settings["timeout_seconds"])
        backoff = _finite_number(settings["retry_backoff_seconds"])
        max_requests = settings["max_requests_per_agent_round"]
        max_retries = settings["max_retries"]
        min_candidate_tokens = settings["min_candidate_output_tokens"]
        if (
            not isinstance(default_model, str)
            or not default_model.strip()
            or timeout_seconds is None
            or backoff is None
            or timeout_seconds <= 0
            or backoff < 0
            or isinstance(max_requests, bool)
            or not isinstance(max_requests, int)
            or max_requests != 8
            or isinstance(max_retries, bool)
            or not isinstance(max_retries, int)
            or max_retries < 0
            or isinstance(min_candidate_tokens, bool)
            or not isinstance(min_candidate_tokens, int)
            or min_candidate_tokens <= 0
        ):
            raise ValueError
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise ProviderConfigurationError(("config/provider_config.json",)) from None
    return settings


@dataclass(frozen=True)
class ProviderConfig:
    base_url: str
    chat_completions_url: str
    protocol: str
    model: str
    api_key: str = field(repr=False)
    timeout_seconds: float
    max_output_tokens: int
    max_requests_per_agent_round: int
    max_retries: int
    retry_backoff_seconds: float

    @classmethod
    def from_env(
        cls, environ: Optional[Mapping[str, str]] = None
    ) -> "ProviderConfig":
        source = os.environ if environ is None else environ
        values = {
            name: str(source[name]) if name in source and source[name] is not None else ""
            for name in _ENV_NAMES
        }
        settings = _runtime_settings()
        values["LLM_MODEL"] = values["LLM_MODEL"].strip() or settings["default_model"]
        problems = [name for name in _ENV_NAMES if not values[name].strip()]

        base_url = values["LLM_BASE_URL"].strip()
        if base_url and not _valid_https_url(base_url, complete_endpoint=False):
            problems.append("LLM_BASE_URL")
        chat_url = values["LLM_CHAT_COMPLETIONS_URL"].strip()
        if chat_url and not _valid_https_url(chat_url, complete_endpoint=True):
            problems.append("LLM_CHAT_COMPLETIONS_URL")
        protocol = values["LLM_PROTOCOL"].strip()
        if protocol and protocol != SUPPORTED_PROTOCOL:
            problems.append("LLM_PROTOCOL")

        timeout = (
            _finite_number(values["LLM_TIMEOUT_SECONDS"])
            if values["LLM_TIMEOUT_SECONDS"].strip()
            else None
        )
        configured_timeout = _finite_number(settings["timeout_seconds"])
        if values["LLM_TIMEOUT_SECONDS"].strip() and (
            timeout is None
            or timeout <= 0
            or configured_timeout is None
            or timeout > configured_timeout
        ):
            problems.append("LLM_TIMEOUT_SECONDS")

        max_output_tokens: Optional[int] = None
        if values["LLM_MAX_OUTPUT_TOKENS"].strip():
            try:
                max_output_tokens = int(values["LLM_MAX_OUTPUT_TOKENS"].strip())
                if str(max_output_tokens) != values["LLM_MAX_OUTPUT_TOKENS"].strip():
                    raise ValueError
                if max_output_tokens <= 0:
                    raise ValueError
            except ValueError:
                problems.append("LLM_MAX_OUTPUT_TOKENS")

        if problems:
            raise ProviderConfigurationError(problems)

        return cls(
            base_url=base_url,
            chat_completions_url=chat_url,
            protocol=protocol,
            model=values["LLM_MODEL"].strip(),
            api_key=values["LLM_API_KEY"],
            timeout_seconds=float(timeout),
            max_output_tokens=max_output_tokens,
            max_requests_per_agent_round=settings["max_requests_per_agent_round"],
            max_retries=settings["max_retries"],
            retry_backoff_seconds=float(settings["retry_backoff_seconds"]),
        )


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ProviderResponse:
    content: Optional[str]
    tool_calls: tuple[ToolCall, ...]
    finish_reason: Optional[str]
    request_id: Optional[str]
    request_event_id: str


@dataclass(frozen=True)
class TransportResponse:
    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


class UrllibTransport:
    def request(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout: float,
    ) -> TransportResponse:
        request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return TransportResponse(
                    status=response.getcode(),
                    body=response.read(),
                    headers=dict(response.headers.items()),
                )
        except urllib.error.HTTPError as exc:
            return TransportResponse(
                status=exc.code,
                body=exc.read(),
                headers=dict(exc.headers.items()) if exc.headers else {},
            )
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ProviderTransportError(
                "LLM transport request failed", retryable=True
            ) from None


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise ProviderRequestError("Request payload must contain finite JSON values") from None


def _redact_text(value: Any, secret: str = "") -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    if secret:
        text = text.replace(secret, "[REDACTED]")
    text = re.sub(
        r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+",
        r"\1[REDACTED]",
        text,
    )
    text = "".join(character for character in text if character.isprintable())
    return text[:512]


def _header_value(headers: Mapping[str, str], name: str) -> Optional[str]:
    for key, value in headers.items():
        if str(key).lower() == name.lower():
            return str(value)
    return None


class Provider:
    def __init__(
        self,
        config: ProviderConfig,
        request_log_path: StrPath,
        run_id: str,
        transport: Optional[Any] = None,
        request_round: Optional[str] = None,
    ):
        if config.protocol != SUPPORTED_PROTOCOL:
            raise ProviderConfigurationError(("LLM_PROTOCOL",))
        if not isinstance(run_id, str) or not run_id.strip():
            raise ProviderRequestError("run_id must be a non-empty string")
        self.config = config
        self.request_log_path = Path(request_log_path)
        self.run_id = run_id
        self.request_round = request_round or run_id
        self.transport = UrllibTransport() if transport is None else transport

    @contextmanager
    def _request_log_lock(self):
        self.request_log_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.request_log_path.with_suffix(".lock")
        with lock_path.open("a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _append_request_event(
        self, event_id: str, kind: str, status: str, request_id: Optional[str] = None
    ) -> None:
        secret = self.config.api_key
        event = {
            "schema_version": SCHEMA_VERSION,
            "run_id": _redact_text(self.run_id, secret),
            "request_round": _redact_text(self.request_round, secret),
            "event_id": event_id,
            "timestamp": _utc_timestamp(),
            "request_id": _redact_text(request_id, secret),
            "model": _redact_text(self.config.model, secret),
            "transport": "HTTP" if isinstance(self.transport, UrllibTransport) else "TEST_DOUBLE",
            "kind": kind,
            "status": status,
        }
        with self.request_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")

    def _start_request(self, kind: str) -> str:
        event_id = str(uuid.uuid4())
        secret = self.config.api_key
        run_id = _redact_text(self.run_id, secret)
        request_round = _redact_text(self.request_round, secret)
        with self._request_log_lock():
            count = 0
            if self.request_log_path.is_file():
                try:
                    with self.request_log_path.open("r", encoding="utf-8") as handle:
                        for line in handle:
                            if not line.strip():
                                continue
                            event = json.loads(line)
                            if (
                                event["status"] == "STARTED"
                                and event["run_id"] == run_id
                                and event["request_round"] == request_round
                            ):
                                count += 1
                except (OSError, KeyError, TypeError, ValueError):
                    raise ProviderRequestLogError("Request log is unreadable or malformed") from None
            if count >= self.config.max_requests_per_agent_round:
                self._append_request_event(event_id, kind, "REQUEST_LIMIT_EXCEEDED")
                raise ProviderRequestLimitError("Agent round request limit reached; request not sent")
            self._append_request_event(event_id, kind, "STARTED")
        return event_id

    def _finish_request(
        self, event_id: str, kind: str, status: str, request_id: Optional[str]
    ) -> None:
        with self._request_log_lock():
            self._append_request_event(event_id, kind, status, request_id)

    def _call_transport(self, *, body: bytes) -> TransportResponse:
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        request_method = getattr(self.transport, "request", None)
        if request_method is None:
            if not callable(self.transport):
                raise TypeError("transport must be callable or provide request()")
            request_method = self.transport
        response = request_method(
            url=self.config.chat_completions_url,
            headers=headers,
            body=body,
            timeout=self.config.timeout_seconds,
        )
        if isinstance(response, TransportResponse):
            return response
        if isinstance(response, Mapping):
            return TransportResponse(status=200, body=_json_bytes(response))
        raise TypeError("transport returned an unsupported response")

    @staticmethod
    def _request_id_from_headers(headers: Mapping[str, str]) -> Optional[str]:
        return _header_value(headers, "x-request-id") or _header_value(headers, "request-id")

    def _parse_response(
        self, response: TransportResponse
    ) -> tuple[Optional[str], tuple[ToolCall, ...], Optional[str], Optional[str]]:
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            raise ProviderResponseError("LLM response was not valid UTF-8 JSON") from None
        if not isinstance(payload, dict):
            raise ProviderResponseError("LLM response JSON must be an object")
        request_id = payload.get("id") or self._request_id_from_headers(response.headers)
        try:
            choices = payload["choices"]
            if not isinstance(choices, list) or not choices:
                raise ValueError
            choice = choices[0]
            message = choice["message"]
            if not isinstance(message, dict):
                raise ValueError
            content = message.get("content")
            if content is not None and not isinstance(content, str):
                raise ValueError
            finish_reason = choice.get("finish_reason")
            if finish_reason is not None and not isinstance(finish_reason, str):
                raise ValueError
            raw_tool_calls = message.get("tool_calls") or []
            if not isinstance(raw_tool_calls, list):
                raise ValueError
            tool_calls = []
            for raw_call in raw_tool_calls:
                if not isinstance(raw_call, dict) or raw_call.get("type") != "function":
                    raise ValueError
                function = raw_call["function"]
                call_id = raw_call["id"]
                if (
                    not isinstance(function, dict)
                    or not isinstance(call_id, str)
                    or not call_id
                    or not isinstance(function.get("name"), str)
                    or not isinstance(function.get("arguments"), str)
                ):
                    raise ValueError
                tool_calls.append(
                    ToolCall(
                        id=call_id,
                        name=function["name"],
                        arguments=function["arguments"],
                    )
                )
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderResponseError("LLM response does not match chat completions shape") from None

        return (
            content,
            tuple(tool_calls),
            finish_reason,
            _redact_text(request_id, self.config.api_key),
        )

    def _generate(
        self,
        *,
        messages: Sequence[Mapping[str, Any]],
        max_output_tokens: Optional[int],
        tools: Optional[Sequence[Mapping[str, Any]]],
        tool_choice: Optional[Any],
        kind: str,
    ) -> ProviderResponse:
        output_limit = self.config.max_output_tokens if max_output_tokens is None else max_output_tokens
        if (
            isinstance(output_limit, bool)
            or not isinstance(output_limit, int)
            or output_limit <= 0
            or output_limit > self.config.max_output_tokens
        ):
            raise ProviderRequestError(
                "max_output_tokens must be positive and no greater than LLM_MAX_OUTPUT_TOKENS"
            )
        if isinstance(messages, (str, bytes)) or not isinstance(messages, Sequence) or not messages:
            raise ProviderRequestError("messages must be a non-empty sequence of objects")
        if not all(isinstance(message, Mapping) for message in messages):
            raise ProviderRequestError("messages must be a non-empty sequence of objects")
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": list(messages),
            "max_tokens": output_limit,
        }
        if tools is not None:
            payload["tools"] = list(tools)
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        body = _json_bytes(payload)

        retries = 0
        while True:
            event_id = self._start_request(kind)
            request_id = None
            try:
                transport_response = self._call_transport(body=body)
                request_id = _redact_text(
                    self._request_id_from_headers(transport_response.headers),
                    self.config.api_key,
                )
                if not 200 <= transport_response.status < 300:
                    raise ProviderTransportError(
                        f"LLM HTTP request failed with status {transport_response.status}",
                        status_code=transport_response.status,
                        request_id=request_id,
                        retryable=transport_response.status == 429
                        or transport_response.status >= 500,
                    )
            except Exception as exc:
                status_code = getattr(exc, "status_code", None)
                request_id = _redact_text(
                    getattr(exc, "request_id", None) or request_id,
                    self.config.api_key,
                )
                self._finish_request(event_id, kind, "FAILED", request_id)
                retryable = bool(getattr(exc, "retryable", False)) or (
                    isinstance(status_code, int)
                    and (status_code == 429 or status_code >= 500)
                )
                if retryable and retries < self.config.max_retries:
                    retries += 1
                    time.sleep(self.config.retry_backoff_seconds * (2 ** (retries - 1)))
                    continue
                if isinstance(status_code, int):
                    message = f"LLM HTTP request failed with status {status_code}"
                else:
                    message = "LLM transport request failed"
                raise ProviderTransportError(
                    message,
                    status_code=status_code if isinstance(status_code, int) else None,
                    request_id=request_id,
                    retryable=retryable,
                ) from None

            try:
                content, tool_calls, finish_reason, response_request_id = self._parse_response(
                    transport_response
                )
            except ProviderResponseError:
                self._finish_request(event_id, kind, "FAILED", request_id)
                raise
            request_id = response_request_id or request_id
            self._finish_request(event_id, kind, "SUCCEEDED", request_id)
            return ProviderResponse(
                content=content,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                request_id=request_id,
                request_event_id=event_id,
            )

    def generate(
        self,
        messages: Sequence[Mapping[str, Any]],
        max_output_tokens: Optional[int] = None,
        tools: Optional[Sequence[Mapping[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
    ) -> ProviderResponse:
        return self._generate(
            messages=messages,
            max_output_tokens=max_output_tokens,
            tools=tools,
            tool_choice=tool_choice,
            kind="GENERATE",
        )

    def tool_roundtrip(
        self, tool_name: str = "echo_capability", argument: Optional[Any] = None
    ) -> tuple[ProviderResponse, ProviderResponse]:
        if tool_name != "echo_capability":
            raise CapabilityError("Only the fixed echo_capability tool is permitted")
        if argument is None:
            argument = {"message": "provider_capability_check"}
        if not isinstance(argument, Mapping):
            raise CapabilityError("echo_capability argument must be a JSON object")
        argument_payload = _json_bytes(argument)
        expected_argument = json.loads(argument_payload.decode("utf-8"))
        tool_definition = {
            "type": "function",
            "function": {
                "name": "echo_capability",
                "description": "Return the supplied JSON object without changing it.",
                "parameters": {"type": "object", "additionalProperties": True},
            },
        }
        messages: list[Mapping[str, Any]] = [
            {
                "role": "system",
                "content": "Call echo_capability exactly once with the JSON object supplied by the user.",
            },
            {
                "role": "user",
                "content": argument_payload.decode("utf-8"),
            },
        ]
        first = self._generate(
            messages=messages,
            max_output_tokens=None,
            tools=[tool_definition],
            tool_choice={"type": "function", "function": {"name": "echo_capability"}},
            kind="TOOL_ROUNDTRIP_REQUEST",
        )
        if len(first.tool_calls) != 1:
            raise CapabilityError("Model did not make exactly one tool call")
        call = first.tool_calls[0]
        if call.name != "echo_capability":
            raise CapabilityError("Model requested a tool other than echo_capability")
        try:
            supplied_argument = json.loads(call.arguments)
        except json.JSONDecodeError:
            raise CapabilityError("Tool call arguments were not valid JSON") from None
        if supplied_argument != expected_argument:
            raise CapabilityError("Tool call arguments did not match the requested echo input")

        assistant_message = {
            "role": "assistant",
            "content": first.content,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
            ],
        }
        tool_message = {
            "role": "tool",
            "tool_call_id": call.id,
            "name": "echo_capability",
            "content": json.dumps(
                supplied_argument, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ),
        }
        second_messages = [*messages, assistant_message, tool_message]
        final = self._generate(
            messages=second_messages,
            max_output_tokens=None,
            tools=None,
            tool_choice=None,
            kind="TOOL_ROUNDTRIP_FINAL",
        )
        if final.tool_calls:
            raise CapabilityError("Final tool-roundtrip response requested another tool call")
        if final.finish_reason != "stop" or not final.content or not final.content.strip():
            raise CapabilityError("Final tool-roundtrip response was not a completed text answer")
        return first, final

    def write_capability_check(
        self,
        path: StrPath,
        *,
        request_ids: Optional[Sequence[str]] = None,
        request_status: str = "NOT_RUN",
        tool_status: str = "NOT_RUN",
        output_parse_status: str = "NOT_RUN",
    ) -> dict[str, Any]:
        return write_capability_check(
            path,
            config=self.config,
            run_id=self.run_id,
            request_ids=request_ids,
            request_status=request_status,
            tool_status=tool_status,
            output_parse_status=output_parse_status,
        )


_CAPABILITY_STATUSES = {"PASS", "FAIL", "BLOCKED", "NOT_RUN"}


def write_capability_check(
    path: StrPath,
    config_error: Optional[Exception] = None,
    *,
    config: Optional[ProviderConfig] = None,
    run_id: Optional[str] = None,
    request_ids: Optional[Sequence[str]] = None,
    request_status: str = "NOT_RUN",
    tool_status: str = "NOT_RUN",
    output_parse_status: str = "NOT_RUN",
) -> dict[str, Any]:
    statuses = (request_status, tool_status, output_parse_status)
    if any(status not in _CAPABILITY_STATUSES for status in statuses):
        raise ValueError("Unknown capability check status")
    blocked = config is None or config_error is not None
    if blocked:
        overall_status = "BLOCKED"
    elif all(status == "PASS" for status in statuses):
        overall_status = "PASS"
    elif any(status == "FAIL" for status in statuses):
        overall_status = "FAIL"
    elif any(status == "BLOCKED" for status in statuses):
        overall_status = "BLOCKED"
    else:
        overall_status = "NOT_RUN"
    secret = config.api_key if config is not None else ""
    variables = (
        list(getattr(config_error, "variable_names", ())) if config_error is not None else []
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "run_id": _redact_text(run_id, secret),
        "timestamp": _utc_timestamp(),
        "status": overall_status,
        "base_url": _redact_text(config.base_url, secret) if config is not None else None,
        "chat_completions_url": (
            _redact_text(config.chat_completions_url, secret) if config is not None else None
        ),
        "protocol": config.protocol if config is not None else None,
        "model": _redact_text(config.model, secret) if config is not None else None,
        "request_ids": [
            _redact_text(request_id, secret) for request_id in (request_ids or ())
        ],
        "configuration": {
            "status": "BLOCKED" if blocked else "PASS",
            "variables": variables,
        },
        "request": {"status": request_status},
        "tool": {"status": tool_status},
        "output_parse": {"status": output_parse_status},
    }
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report
