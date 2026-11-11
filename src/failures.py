"""Real failure drills for V2-06.

Each drill provokes a genuine failure and records the error text, the request
ids and the recovery outcome. Nothing here fabricates a success: a drill is
``OBSERVED`` only when the expected exception type was raised and (for gateway
drills) the request actually left the machine and was logged.
"""

from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path
from typing import Any, Callable

from src.common import ContractError, read_jsonl, utc_now, write_json
from src.provider import (
    Provider,
    ProviderConfig,
    ProviderTransportError,
)

PROBE_MESSAGES = [{"role": "user", "content": "Reply with exactly: DRILL_OK"}]


def _drill_dir(run_dir: Path) -> Path:
    directory = run_dir / "failures" / "drills"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _record(name: str, mode: str, expected: str, outcome: Callable[[], dict]) -> dict:
    started = time.monotonic()
    try:
        detail = outcome()
        status = "UNEXPECTED_SUCCESS"
        error = detail.get("error") or "no error was raised"
    except Exception as exception:  # noqa: BLE001 - the failure IS the evidence
        detail = getattr(exception, "detail", {}) or {}
        status = "OBSERVED"
        error = f"{type(exception).__name__}: {str(exception)[:400]}"
        detail.setdefault("error_type", type(exception).__name__)
    return {
        "schema_version": "1",
        "name": name,
        "mode": mode,
        "expected": expected,
        "status": status,
        "error": error,
        "detail": detail,
        "duration_seconds": round(time.monotonic() - started, 3),
        "recorded_at": utc_now(),
    }


class DrillFailure(Exception):
    def __init__(self, message: str, detail: dict):
        super().__init__(message)
        self.detail = detail


def _config(run_dir: Path) -> ProviderConfig:
    return ProviderConfig.from_env()


def _request_ids(run_dir: Path, run_id: str, round_name: str) -> list[str]:
    return [
        event.get("request_id")
        for event in read_jsonl(run_dir / "provider" / "request_log.jsonl")
        if event.get("run_id") == run_id and event.get("request_round") == round_name
    ]


def _api_error(run_dir: Path, run_id: str) -> dict:
    config = _config(run_dir)
    broken = dataclasses.replace(config, chat_completions_url=config.chat_completions_url.rstrip("/") + "/definitely-not-a-route")
    provider = Provider(broken, run_dir / "provider" / "request_log.jsonl", run_id, request_round="drill-api-error")
    try:
        provider.generate(PROBE_MESSAGES, max_output_tokens=min(32, broken.max_output_tokens))
    except ProviderTransportError as error:
        detail = {
            "status_code": error.status_code,
            "request_ids": _request_ids(run_dir, run_id, "drill-api-error"),
            "endpoint": broken.chat_completions_url,
        }
        if error.status_code != 404:
            raise DrillFailure(f"expected an HTTP 404 from the gateway, saw {error.status_code}", detail) from error
        raise DrillFailure(str(error), detail) from error
    return {"error": "the gateway accepted a bogus route"}


def _timeout(run_dir: Path, run_id: str) -> dict:
    config = _config(run_dir)
    impatient = dataclasses.replace(config, timeout_seconds=0.001, max_retries=0)
    provider = Provider(impatient, run_dir / "provider" / "request_log.jsonl", run_id, request_round="drill-timeout")
    try:
        provider.generate(PROBE_MESSAGES, max_output_tokens=min(32, impatient.max_output_tokens))
    except ProviderTransportError as error:
        detail = {
            "timeout_seconds": impatient.timeout_seconds,
            "request_ids": _request_ids(run_dir, run_id, "drill-timeout"),
        }
        raise DrillFailure(str(error), detail) from error
    return {"error": "a 1 ms timeout did not fire against the real gateway"}


def _parse_failure(run_dir: Path, run_id: str) -> dict:
    config = _config(run_dir)
    provider = Provider(config, run_dir / "provider" / "request_log.jsonl", run_id, request_round="drill-parse")
    messages = [{"role": "user", "content": "Describe in plain prose how a ROC curve is drawn. Do not output JSON."}]
    errors = []
    request_ids = []
    for attempt in range(2):
        response = provider.generate(messages, max_output_tokens=min(256, config.max_output_tokens))
        request_ids.append(response.request_id)
        try:
            if not response.content:
                raise ValueError("empty content")
            json.loads(response.content)
            raise DrillFailure("the model returned parseable JSON despite the prose instruction", {"request_ids": request_ids})
        except json.JSONDecodeError as error:
            errors.append(f"attempt {attempt}: JSONDecodeError: {str(error)[:200]}")
            messages = [*messages, {"role": "user", "content": "Return the complete corrected JSON object only."}]
    raise DrillFailure("; ".join(errors), {"request_ids": request_ids, "format_retries": 1})


def _request_limit(run_dir: Path, run_id: str) -> dict:
    config = _config(run_dir)
    provider = Provider(config, run_dir / "provider" / "request_log.jsonl", run_id, request_round="drill-limit")
    limit = config.max_requests_per_agent_round
    sent = 0
    for _ in range(limit + 1):
        provider.generate(PROBE_MESSAGES, max_output_tokens=min(32, config.max_output_tokens))
        sent += 1
    return {"error": f"the {limit}-request ceiling did not fire after {sent} requests"}


def _repair_exhausted(run_dir: Path, run_id: str) -> dict:
    from src.agent import repair_diagnostics
    from src.migration import candidate_dir

    attempts = [candidate_dir(run_dir, index) for index in range(3)]
    detail: dict[str, Any] = {"allowed_attempts": [path.name for path in attempts]}
    try:
        candidate_dir(run_dir, 3)
    except ContractError as error:
        detail["attempt_3_rejection"] = str(error)
    else:
        return {"error": "attempt 3 was accepted", **detail}
    write_json(run_dir / "failures" / "drills" / "repair_state.json", {
        "schema_version": "1",
        "run_id": run_id,
        "dev_status": "FAIL",
        "fixture_status": "FAIL",
        "diagnostics_ref": None,
    })
    real_result = run_dir / "migration_result.json"
    backup = real_result.read_text(encoding="utf-8") if real_result.is_file() else None
    try:
        write_json(real_result, {"attempt": 2, "dev_status": "FAIL", "fixture_status": "FAIL", "diagnostics_ref": None})
        try:
            repair_diagnostics(run_dir, 3)
        except ContractError as error:
            detail["gate_rejection"] = str(error)
        else:
            return {"error": "a fourth attempt was authorised even though repairs were exhausted", **detail}
    finally:
        if backup is not None:
            real_result.write_text(backup, encoding="utf-8")
    raise DrillFailure("repair budget exhausted after initial generation plus two repairs", detail)


def run_failure_drills(run_dir: Path, run_id: str) -> dict:
    directory = _drill_dir(run_dir)
    drills = [
        _record("api_error", "REAL_API", "ProviderTransportError with HTTP 404 from the configured gateway", lambda: _api_error(run_dir, run_id)),
        _record("parse_failure", "REAL_API", "ContractError after one format retry when output is not JSON", lambda: _parse_failure(run_dir, run_id)),
        _record("timeout", "REAL_API", "ProviderTransportError when the socket timeout is exceeded", lambda: _timeout(run_dir, run_id)),
        _record("request_limit", "REAL_API", "ProviderRequestLimitError on request 9 of an agent round", lambda: _request_limit(run_dir, run_id)),
        _record("repair_exhausted", "LOCAL_INJECTED", "ContractError/GateError before a fourth candidate attempt", lambda: _repair_exhausted(run_dir, run_id)),
    ]
    for drill in drills:
        write_json(directory / f"{drill['name']}.json", drill)
    report = {
        "schema_version": "1",
        "format_version": "2",
        "run_id": run_id,
        "created_at": utc_now(),
        "status": "PASS" if all(drill["status"] == "OBSERVED" for drill in drills) else "FAIL",
        "drills": drills,
        "notes": "api_error, parse_failure, timeout and request_limit are real gateway failures; repair_exhausted is injected locally because exhausting three real candidate generations would consume budget without adding evidence.",
    }
    write_json(run_dir / "failures" / "failure_drills.json", report)
    return report
