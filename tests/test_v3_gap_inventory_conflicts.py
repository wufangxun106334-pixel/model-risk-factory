"""V3 gap 1 regression: inventory conflicts are decided from the frozen expectations.

Before this fix ``build_inventory`` only counted ``len(conflicts) >= min_conflicts``.
The seed-46 v2 evidence contains the defect this file pins down: the MDL_CREDIT_V2
artifact recorded a ``decision_threshold`` entry whose own text says the code value
and the documented value agree (0.3 / 0.3) — agreement counted as a conflict — and
the run still passed Gate A.

The frozen authority is ``config/inventory_expectations.json`` plus the allowlisted
source files, so every case below is decided without asking a model.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.common import ContractError, read_json, sha256_file, write_json
from src.inventory import build_inventory, inventory_path, load_inventory
from src.provider import ProviderResponse, ToolCall

REPOSITORY = Path(__file__).resolve().parents[1]
RUN_ID = "v3-gap-threshold"

V1 = "MDL_CREDIT_V1"
V2 = "MDL_CREDIT_V2"
TREE = "MDL_CREDIT_TREE"

FEATURES = {
    V1: ["delay_1", "log_limit", "util_1", "log_pay_1"],
    V2: ["delay_1", "delay_2", "delay_3", "log_limit", "util_1", "util_mean_6", "log_pay_1"],
    TREE: ["delay_1", "delay_2", "delay_3", "delay_4", "delay_5", "delay_6", "limit_bal", "util_1"],
}
THRESHOLDS = {V1: (0.35, 0.5), V2: (0.3, 0.3), TREE: (0.5, 0.5)}
CODE = {V1: "legacy/credit_v1.R", V2: "legacy/credit_v2.R", TREE: "legacy/credit_tree.R"}
NOTE = {V1: "legacy/notes/credit_v1.md", V2: "legacy/notes/credit_v2.md", TREE: "legacy/notes/credit_tree.md"}


def make_run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    write_json(run / "run_manifest.json", {"run_id": RUN_ID})
    write_json(run / "context_manifest.json", {"run_id": RUN_ID, "assets": []})
    write_json(run / "provider" / "capability_check.json", {"status": "PASS", "request_ids": ["capability-fixture"]})
    return run


def source(path: str, line: int, excerpt: str) -> dict:
    return {
        "path": path,
        "sha256": sha256_file(REPOSITORY / path),
        "line_start": line,
        "line_end": line,
        "excerpt": excerpt,
    }


def sources(model_id: str) -> list[dict]:
    codes = {V1: (3, 'MODEL_ID <- "MDL_CREDIT_V1"'), V2: (6, 'MODEL_ID <- "MDL_CREDIT_V2"'), TREE: (6, 'MODEL_ID <- "MDL_CREDIT_TREE"')}
    notes = {V1: (9, "Decision threshold: 0.50"), V2: (9, "Decision threshold: 0.30"), TREE: (9, "Decision threshold: 0.50")}
    line, excerpt = codes[model_id]
    note_line, note_excerpt = notes[model_id]
    return [source(CODE[model_id], line, excerpt), source(NOTE[model_id], note_line, note_excerpt)]


CONFIRMED_FIELDS = {
    V1: ["decision_threshold"],
    V2: ["input_validity_limits"],
    TREE: ["repayment_history", "tree_controls"],
}


def payload(model_id: str, conflicts: list[dict], **overrides) -> dict:
    code, documented = THRESHOLDS[model_id]
    body = {
        "model_id": model_id,
        "model_type": "logistic regression" if model_id != TREE else "decision tree",
        "owner": "Unknown",
        "training_date": "Unknown",
        "feature_order": FEATURES[model_id],
        "code_threshold": code,
        "documented_threshold": documented,
        "unknowns": ["owner", "training_date"],
        "conflicts": conflicts,
        "sources": sources(model_id),
    }
    body.update(overrides)
    return body


def build(run: Path, model_id: str, conflicts: list[dict], **overrides) -> dict:
    return build_inventory(RUN_ID, payload(model_id, conflicts, **overrides), REPOSITORY, inventory_path(run, model_id))


@pytest.mark.parametrize("field", ["decision_threshold", "decision cutoff", "refresh_schedule"])
def test_an_unconfirmed_finding_is_rejected(tmp_path, field):
    run = make_run(tmp_path)
    with pytest.raises(ContractError, match="frozen findings"):
        build(run, V2, [{"field": field}])
    assert not inventory_path(run, V2).exists()


@pytest.mark.parametrize("model_id", [V1, V2, TREE])
def test_confirmed_findings_are_bound_to_both_exact_sources(tmp_path, model_id):
    run = make_run(tmp_path)
    inventory = build(run, model_id, [{"field": field} for field in CONFIRMED_FIELDS[model_id]])
    assert [finding["field"] for finding in inventory["conflicts"]] == CONFIRMED_FIELDS[model_id]
    assert (inventory["code_threshold"], inventory["documented_threshold"]) == THRESHOLDS[model_id]
    for finding in inventory["conflicts"]:
        assert {source["path"] for source in finding["sources"]} == {CODE[model_id], NOTE[model_id]}
        for source in finding["sources"]:
            path = REPOSITORY / source["path"]
            assert source["sha256"] == sha256_file(path)
            assert source["excerpt"] in path.read_text().splitlines()[source["line_start"] - 1]


@pytest.mark.parametrize("fields", [[], ["input_validity_limits", "input_validity_limits"]])
def test_required_findings_cannot_be_omitted_or_duplicated(tmp_path, fields):
    with pytest.raises(ContractError):
        build(make_run(tmp_path), V2, [{"field": field} for field in fields])


def test_invented_conflict_text_cannot_enter_the_inventory(tmp_path):
    with pytest.raises(ValueError, match="Extra inputs"):
        build(make_run(tmp_path), V2, [{"field": "input_validity_limits", "detail": "invented text"}])


@pytest.mark.parametrize("threshold", [0.5, float("nan")])
def test_thresholds_still_match_the_source_contract(tmp_path, threshold):
    with pytest.raises(ContractError, match="threshold pair"):
        build(make_run(tmp_path), V2, [{"field": "input_validity_limits"}], code_threshold=threshold)


@pytest.mark.parametrize("field", ["owner", "training_date"])
def test_unknown_fields_stay_unknown(tmp_path, field):
    run = make_run(tmp_path)
    conflicts = [{"field": "input_validity_limits"}]
    with pytest.raises(ContractError, match="must not be invented"):
        build(run, V2, conflicts, **{field: "A. Reviewer"})
    with pytest.raises(ContractError, match="must be listed"):
        build(run, V2, conflicts, unknowns=["owner"])


def test_legacy_inventory_artifacts_can_still_be_read(tmp_path):
    path = inventory_path(make_run(tmp_path), V2)
    legacy = payload(V2, [{"kind": "legacy finding", "code": "legacy source text"}])
    write_json(path, {"schema_version": "1", "run_id": RUN_ID, "review_status": "APPROVED", **legacy})
    assert load_inventory(path, RUN_ID)["conflicts"] == legacy["conflicts"]


class SpuriousProvider:
    """Alternates a validate_inventory tool call with the final (invalid) payload."""

    def __init__(self, body: dict):
        self.body = body
        self.calls: list[dict] = []

    def generate(self, messages, tools=None):
        self.calls.append({"messages": list(messages), "tools": tools})
        index = len(self.calls)
        if index % 2 == 1:
            call = ToolCall("call-validate", "validate_inventory", json.dumps({"payload": self.body}))
            return ProviderResponse(None, (call,), "tool_calls", f"req-{index}", f"event-{index}")
        return ProviderResponse(json.dumps(self.body), (), "stop", f"req-{index}", f"event-{index}")


def test_the_agent_entry_point_refuses_the_conflict_and_keeps_the_reason(tmp_path, monkeypatch):
    from src.agent import extract_inventory

    run = make_run(tmp_path)
    body = payload(
        V2,
        [{"field": "decision cutoff"}],
    )
    provider = SpuriousProvider(body)
    monkeypatch.setattr("src.agent._provider", lambda *args: provider)
    monkeypatch.setattr("src.agent.verify_context", lambda *args: True)
    with pytest.raises(ContractError) as error:
        extract_inventory(REPOSITORY, run, RUN_ID, V2)
    assert "failed after one format retry" in str(error.value)
    assert not inventory_path(run, V2).exists()

    audit = [json.loads(line) for line in (run / "agent_audit_log.jsonl").read_text().splitlines()]
    rejected = [event for event in audit if event["event"] == "OUTPUT_REJECTED"]
    assert [event["format_attempt"] for event in rejected] == [0, 1]
    assert all("frozen findings" in event["reason"] for event in rejected)
    tool_failures = [event for event in audit if event["event"] == "TOOL_CALL" and event["status"] == "FAIL"]
    assert tool_failures and "frozen findings" in tool_failures[0]["reason"]
    # Two format attempts, each a tool call plus a final answer: the existing
    # eight-request ceiling and one-retry limit are unchanged.
    assert len(provider.calls) <= 8
