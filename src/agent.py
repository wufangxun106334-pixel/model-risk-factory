from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from src.common import ContractError, GateError, append_jsonl, read_json, sha256_bytes, sha256_file, utc_now, write_json
from src.context import verify_context
from src.contracts import CandidatePayload
from src.inventory import build_inventory
from src.migration import candidate_dir, save_candidate, sha256_code
from src.provider import CapabilityError, Provider, ProviderConfig, ProviderConfigurationError, ProviderResponse, UrllibTransport, write_capability_check
from src.review import artifact_digest, require_approval

READ_ASSET_TOOL = {
    "type": "function",
    "function": {
        "name": "read_asset",
        "description": "Read one explicitly allowlisted legacy model or schema asset.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["path"],
            "properties": {"path": {"type": "string"}},
        },
    },
}
VALIDATE_INVENTORY_TOOL = {
    "type": "function",
    "function": {
        "name": "validate_inventory",
        "description": "Validate an inventory payload locally without approving it.",
        "parameters": {"type": "object", "additionalProperties": False, "required": ["payload"], "properties": {"payload": {"type": "object"}}},
    },
}
SUBMIT_CANDIDATE_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_candidate",
        "description": "Submit the complete Python candidate as JSON; this does not approve or execute it.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["model_id", "code"],
            "properties": {"model_id": {"const": "MDL_CREDIT_V1"}, "code": {"type": "string"}},
        },
    },
}


def _provider(repository: Path, run_dir: Path, run_id: str, request_round: str) -> Provider:
    config = ProviderConfig.from_env()
    return Provider(config, run_dir / "provider" / "request_log.jsonl", run_id, request_round=request_round)


def _require_capability(run_dir: Path) -> dict:
    path = run_dir / "provider" / "capability_check.json"
    capability = read_json(path) if path.is_file() else {}
    if capability.get("status") != "PASS":
        raise GateError("Real Agent stages require a passing V1-01 capability check")
    return capability


def check_provider(run_dir: Path, run_id: str) -> dict:
    output = run_dir / "provider" / "capability_check.json"
    try:
        config = ProviderConfig.from_env()
    except ProviderConfigurationError as error:
        return write_capability_check(output, config_error=error, run_id=run_id)
    provider = Provider(config, output.with_name("request_log.jsonl"), run_id, request_round="capability-check")
    request_ids = []
    request_status = "NOT_RUN"
    tool_status = "NOT_RUN"
    parse_status = "NOT_RUN"
    try:
        first = provider.generate(
            [{"role": "user", "content": "Reply with exactly: CAPABILITY_OK"}],
            # Reasoning-capable gateway models may spend part of the budget on
            # reasoning tokens, so a 32-token ceiling intermittently yields an
            # empty reply. Keep the request short but large enough to be stable.
            max_output_tokens=min(256, config.max_output_tokens),
        )
        request_ids.append(first.request_id)
        request_status = "PASS" if first.request_id else "FAIL"
        parse_status = "PASS" if first.finish_reason == "stop" and first.content and first.content.strip() else "FAIL"
        if request_status != "PASS" or parse_status != "PASS":
            raise CapabilityError("The short response must have a request ID and completed text")
    except Exception:
        if request_status == "NOT_RUN":
            request_status = "FAIL"
    else:
        try:
            tool_request, final = provider.tool_roundtrip()
            request_ids.extend((tool_request.request_id, final.request_id))
            tool_status = "PASS" if tool_request.request_id and final.request_id else "FAIL"
        except CapabilityError:
            # The request was exercised and rejected: that is a real failure,
            # not a missing-configuration block.
            tool_status = "FAIL"
    return provider.write_capability_check(
        output,
        request_ids=[item for item in request_ids if item],
        request_status=request_status,
        tool_status=tool_status,
        output_parse_status=parse_status,
    )


def _audit(run_dir: Path, run_id: str, stage: str, event: str, **fields: Any) -> None:
    append_jsonl(run_dir / "agent_audit_log.jsonl", {"schema_version": "1", "run_id": run_id, "stage": stage, "event": event, "timestamp": utc_now(), **fields})


def _assistant_message(response: ProviderResponse) -> dict:
    return {
        "role": "assistant",
        "content": response.content,
        "tool_calls": [
            {"id": call.id, "type": "function", "function": {"name": call.name, "arguments": call.arguments}}
            for call in response.tool_calls
        ],
    }


def _run_stage(provider: Provider, run_dir: Path, run_id: str, stage: str, messages: list[dict], tools: list[dict], dispatcher) -> tuple[ProviderResponse, list[dict]]:
    submissions = []
    for _ in range(8):
        response = provider.generate(messages, tools=tools)
        _audit(
            run_dir,
            run_id,
            stage,
            "MODEL_RESPONSE",
            request_id=response.request_id,
            request_event_id=response.request_event_id,
            finish_reason=response.finish_reason,
            content_sha256=sha256_bytes(response.content.encode("utf-8")) if response.content else None,
            tool_names=[call.name for call in response.tool_calls],
        )
        if response.finish_reason == "length":
            _audit(run_dir, run_id, stage, "OUTPUT_TRUNCATED", request_id=response.request_id, request_event_id=response.request_event_id)
            raise ContractError(
                f"{stage}: model output hit the token ceiling (finish_reason=length); "
                "a truncated submit_candidate can never be accepted. Raise LLM_MAX_OUTPUT_TOKENS, "
                "then retry this attempt or generate the next one"
            )
        if not response.tool_calls:
            return response, submissions
        messages.append(_assistant_message(response))
        for call in response.tool_calls:
            submitted = False
            try:
                arguments = json.loads(call.arguments)
                result = dispatcher(call.name, arguments)
                if call.name == "submit_candidate" and result.get("status") == "VALID":
                    submitted = True
                    submission = {"payload": arguments, "request_id": response.request_id, "request_event_id": response.request_event_id}
                    submissions.append(submission)
                    _audit(run_dir, run_id, stage, "CANDIDATE_SUBMITTED", request_id=response.request_id, request_event_id=response.request_event_id, candidate_sha256=sha256_code(arguments["code"]), tool_call_id=call.id)
                _audit(run_dir, run_id, stage, "TOOL_CALL", tool=call.name, tool_call_id=call.id, status="PASS", result_sha256=sha256_bytes(json.dumps(result, sort_keys=True).encode()))
            except Exception as error:
                result = {"status": "ERROR", "reason": str(error)[:300]}
                _audit(run_dir, run_id, stage, "TOOL_CALL", tool=call.name, tool_call_id=call.id, status="FAIL", reason=str(error)[:300])
            messages.append({"role": "tool", "tool_call_id": call.id, "name": call.name, "content": json.dumps(result, ensure_ascii=False, allow_nan=False)})
            if submitted:
                return response, submissions
    raise ContractError("Agent stage reached eight model responses without a final answer")


def _read_repository_asset(repository: Path, relative: str, allowed: set[str]) -> dict:
    if relative not in allowed:
        raise ContractError(
            "Asset is not allowlisted for this Agent stage; path must be exactly one of: "
            + ", ".join(sorted(allowed))
        )
    path = repository / relative
    content = path.read_text(encoding="utf-8")
    return {"status": "PASS", "path": relative, "sha256": sha256_file(path), "content": content}


def extract_inventory(repository: Path, run_dir: Path, run_id: str) -> dict:
    _require_capability(run_dir)
    if not verify_context(repository, run_dir, run_id):
        raise ContractError("Inventory extraction requires a valid frozen baseline context; no API request was sent")
    output = run_dir / "model_inventory.json"
    if output.exists():
        raise ContractError("Inventory already exists for this run")
    provider = _provider(repository, run_dir, run_id, "inventory")
    _require_output_budget(repository, provider, "Inventory extraction")
    schema_path = "config/inventory_schema.json"
    schema = read_json(repository / schema_path)
    allowed = {"legacy/credit_v1.R", "legacy/notes/credit_v1.md", schema_path}

    def dispatch(name, arguments):
        if name == "read_asset":
            result = _read_repository_asset(repository, arguments["path"], allowed)
            _audit(run_dir, run_id, "inventory", "ASSET_READ", path=arguments["path"], sha256=result["sha256"])
            return result
        if name == "validate_inventory":
            build_inventory(run_id, arguments["payload"], repository, run_dir / "inventory_validation.json")
            return {"status": "VALID", "approval": "NOT_GRANTED"}
        raise ContractError(f"Tool is not available in inventory stage: {name}")

    prompt = (
        "Extract only MDL_CREDIT_V1 from the allowlisted R code and simulated legacy note. "
        "The only paths accepted by read_asset are, exactly, with no prefix or suffix added: "
        + ", ".join(sorted(allowed))
        + ". Use read_asset on the R code and on the note; do not guess other paths. "
        "Return one JSON object matching the supplied Schema, with no Markdown. "
        "Preserve owner and training_date as exactly Unknown when absent. Preserve code threshold 0.35 and documented threshold 0.50 as a conflict. "
        "Every key fact needs a source path, actual SHA-256, valid line range and verbatim excerpt. Do not infer missing facts. "
        f"JSON Schema: {json.dumps(schema, ensure_ascii=False)}"
    )
    messages = [{"role": "system", "content": "You are a constrained model inventory extraction Agent. Only use supplied tools and evidence."}, {"role": "user", "content": prompt}]
    last_error = None
    for format_attempt in range(2):
        response, _ = _run_stage(provider, run_dir, run_id, "inventory", messages, [READ_ASSET_TOOL, VALIDATE_INVENTORY_TOOL], dispatch)
        try:
            if not response.content:
                raise ContractError("Inventory response has no JSON content")
            payload = json.loads(response.content)
            inventory = build_inventory(run_id, payload, repository, output)
            _audit(run_dir, run_id, "inventory", "INVENTORY_VALIDATED", request_id=response.request_id, request_event_id=response.request_event_id, inventory_sha256=artifact_digest(output, "Gate_A"), context_sha256=sha256_file(run_dir / "context_manifest.json"), format_attempt=format_attempt)
            return inventory
        except Exception as error:
            last_error = error
            _audit(run_dir, run_id, "inventory", "OUTPUT_REJECTED", format_attempt=format_attempt, reason=str(error)[:300])
            if format_attempt == 0:
                messages = [*messages, {"role": "user", "content": f"Local validation rejected the response: {str(error)[:300]}. Return the complete corrected JSON only; do not change source facts."}]
    raise ContractError(f"Inventory extraction failed after one format retry: {last_error}")


def repair_diagnostics(run_dir: Path, attempt: int) -> dict | None:
    """Authorise a repair attempt from the immediately preceding candidate.

    Attempt 0 needs no authorisation. A later attempt is legal only when the
    preceding candidate recorded a FAIL that the Agent may inspect: either
    development parity failed, or development parity passed while the fixed
    behaviour fixtures failed (the case that used to abort the whole run).
    """

    if attempt == 0:
        return None
    result_path = run_dir / "migration_result.json"
    previous = read_json(result_path) if result_path.is_file() else {}
    if previous.get("attempt") != attempt - 1:
        raise GateError(
            "Candidate attempts must be sequential and the preceding attempt must be recorded; no API request was sent"
        )
    dev_failed = previous.get("dev_status") == "FAIL"
    fixtures_failed = previous.get("dev_status") == "PASS" and previous.get("fixture_status") == "FAIL"
    if not (dev_failed or fixtures_failed):
        raise GateError(
            "A repair requires a recorded FAIL (development parity or behaviour fixtures) "
            "from the immediately preceding candidate"
        )
    reference = previous.get("diagnostics_ref")
    if not reference:
        raise GateError("The preceding FAIL has no recorded aggregate diagnostics")
    diagnostics = read_json(run_dir / reference)
    if diagnostics.get("contains_raw_rows") or diagnostics.get("contains_baseline_answers"):
        raise ContractError("Unsafe development diagnostics cannot be sent to Agent")
    return diagnostics


def _require_output_budget(repository: Path, provider: Provider, stage: str) -> None:
    """Refuse to send a large generation request with a ceiling that truncates it."""

    config = getattr(provider, "config", None)
    if config is None:
        return
    settings_path = repository / "config" / "provider_config.json"
    settings = read_json(settings_path) if settings_path.is_file() else {}
    minimum = settings.get("min_candidate_output_tokens")
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum <= 0:
        raise ContractError("config/provider_config.json must declare min_candidate_output_tokens")
    if config.max_output_tokens < minimum:
        raise ContractError(
            f"{stage} requires LLM_MAX_OUTPUT_TOKENS >= {minimum}, but the configured ceiling is "
            f"{config.max_output_tokens}; a smaller ceiling truncates the tool payload mid-JSON"
        )


def generate_candidate(repository: Path, run_dir: Path, run_id: str, attempt: int) -> dict:
    capability = _require_capability(run_dir)
    inventory_path = run_dir / "model_inventory.json"
    require_approval(run_dir, run_id, "Gate_A", inventory_path)
    if attempt < 0 or attempt > 2 or candidate_dir(run_dir, attempt).exists():
        raise ContractError("Candidate attempt is outside 0..2 or already exists; no API request was sent")
    if attempt > 0 and not candidate_dir(run_dir, attempt - 1).is_dir():
        raise ContractError("Candidate attempts must be sequential; no API request was sent")
    provider = _provider(repository, run_dir, run_id, f"candidate-{attempt}")
    _require_output_budget(repository, provider, f"Candidate stage {attempt}")
    contract_path = "config/candidate_contract.json"
    model = read_json(run_dir / "reference" / "model.json")
    inventory = read_json(inventory_path)
    allowed = {"legacy/credit_v1.R", contract_path, "config/candidate_schema.json"}

    def dispatch(name, arguments):
        if name == "read_asset":
            result = _read_repository_asset(repository, arguments["path"], allowed)
            _audit(run_dir, run_id, f"candidate-{attempt}", "ASSET_READ", path=arguments["path"], sha256=result["sha256"])
            return result
        if name == "submit_candidate":
            payload = CandidatePayload.model_validate(arguments)
            ast.parse(payload.code)
            return {"status": "VALID", "execution": "REQUIRES_GATE_B"}
        raise ContractError(f"Tool is not available in candidate stage: {name}")

    diagnostics = repair_diagnostics(run_dir, attempt)
    prompt = (
        "Migrate MDL_CREDIT_V1 from R to standalone Python without retraining. Read the R code and candidate contract using tools. "
        "The only paths accepted by read_asset are, exactly, with no prefix or suffix added: "
        + ", ".join(sorted(allowed))
        + ". "
        "Use the exact exported coefficients, medians, feature order and 0.35 threshold supplied below. "
        "Submit exactly one complete candidate with submit_candidate; do not use Markdown. "
        f"Approved inventory (human Gate A): {json.dumps(inventory, ensure_ascii=False)}. "
        f"Model artifact: {json.dumps(model, ensure_ascii=False)}. "
        f"Candidate response Schema: {read_json(repository / 'config' / 'candidate_schema.json')}. "
        + (f"Previous aggregate development diagnostics only: {json.dumps(diagnostics, ensure_ascii=False)}" if diagnostics else "This is the initial candidate.")
    )
    messages = [{"role": "system", "content": "You are a constrained R-to-Python migration Agent. You cannot run tests or access any dataset rows, baseline predictions, Holdout data, or test source."}, {"role": "user", "content": prompt}]
    response, tool_submissions = _run_stage(provider, run_dir, run_id, f"candidate-{attempt}", messages, [READ_ASSET_TOOL, SUBMIT_CANDIDATE_TOOL], dispatch)
    if len(tool_submissions) != 1:
        raise ContractError("Agent must submit exactly one candidate through submit_candidate")
    submission = tool_submissions[0]
    candidate = CandidatePayload.model_validate(submission["payload"])
    generation_mode = "REAL_API" if isinstance(provider, Provider) and isinstance(provider.transport, UrllibTransport) else "TEST_DOUBLE"
    evidence = {
        "capability_check_sha256": sha256_file(run_dir / "provider" / "capability_check.json"),
        "capability_request_ids": capability.get("request_ids", []),
        "generation_request_id": submission["request_id"],
        "generation_request_event_id": submission["request_event_id"],
        "model": provider.config.model if isinstance(provider, Provider) else "TEST_DOUBLE",
        "protocol": provider.config.protocol if isinstance(provider, Provider) else "TEST_DOUBLE",
        "chat_completions_url": provider.config.chat_completions_url if isinstance(provider, Provider) else "TEST_DOUBLE",
        "request_log": "provider/request_log.jsonl",
        "agent_audit_log": "agent_audit_log.jsonl",
    }
    metadata = save_candidate(run_dir, run_id, candidate.code, attempt, evidence, generation_mode=generation_mode)
    _audit(run_dir, run_id, f"candidate-{attempt}", "CANDIDATE_SAVED", candidate_sha256=metadata["candidate_sha256"], request_id=submission["request_id"], request_event_id=submission["request_event_id"])
    return metadata
