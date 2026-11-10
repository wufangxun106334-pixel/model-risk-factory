"""V3 gap 2 regression: the Agent summary cannot contradict the metrics.

Before this fix the only checks on ``report/agent_summary.json`` were a compliance
phrase list and a "no bare numbers" rule, so a summary could assert that parity
passed while ``validation_metrics.json`` recorded a mismatch, or that the drift
batch was stable while the PSI state required revalidation, and Gate C would still
approve the report (README "已知工具缺陷" item 7).

The gate now has two independent parts:

* a trusted-template "Key conclusions" block rendered from the metrics only;
* closed-enum ``status_claims`` that must equal :func:`src.report.derive_facts`,
  plus a narrow phrase check for the opposite direction.

Both are exercised here through the normal generation entry
(``src.agent.summarize_validation``) and the normal approval entry
(``approve --gate Gate_C`` / ``approve-report`` / ``report-status``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent import summarize_validation
from src.common import ContractError, GateError, read_json, write_json
from src.provider import ProviderResponse
from src.report import (
    agent_summary_schema,
    check_summary,
    derive_facts,
    render_report,
    report_status,
    write_approval,
)
from src.review import artifact_digest, record_review

from v2_metrics import metrics_fixture

RUN_ID = "v3-gap-summary"

CONSISTENT_TEXT = {
    "headline": "The ported scorecard reproduces the reference probabilities on both scored splits.",
    "results": ["Row-level parity passes on development and hold-out with no classification differences."],
    "limitations": ["The weighted drift batch is a sensitivity analysis of sample composition, not a forecast."],
    "evidence_gaps": ["A cross-time back-test is unavailable for this extract and is still missing."],
}
CLEAN_CLAIMS = {
    "parity": "MATCH",
    "stability": "ATTENTION",
    "fairness": "AUDIT_SIGNAL_ONLY",
    "cross_time_backtest": "UNAVAILABLE",
    "degraded_checks": ["STABILITY"],
}
STABLE_CLAIMS = {**CLEAN_CLAIMS, "stability": "STABLE", "degraded_checks": []}


# --- fixtures ---------------------------------------------------------------


def metrics(run_id: str = RUN_ID, *, degraded: bool = False) -> dict:
    body = metrics_fixture(run_id)
    if degraded:
        body["parity"]["dev"] = {**body["parity"]["dev"], "status": "FAIL", "classification_mismatch_count": 3}
        body["parity"]["status"] = "FAIL"
        body["stability"]["status"] = "REVALIDATION_REQUIRED"
    return body


def make_run(tmp_path: Path, *, degraded: bool = False, summary: dict | None = None) -> Path:
    run = tmp_path / "run"
    write_json(run / "run_manifest.json", {"run_id": RUN_ID})
    write_json(run / "context_manifest.json", {"run_id": RUN_ID, "assets": []})
    write_json(run / "review_log.json", {"schema_version": "1", "run_id": RUN_ID, "reviews": []})
    write_json(run / "validation_metrics.json", metrics(degraded=degraded))
    if summary is not None:
        write_json(run / "report" / "agent_summary.json", {"schema_version": "1", "run_id": RUN_ID, **summary})
    return run


def model_answer(claims: dict | None = None, **overrides) -> dict:
    """Exactly what the gateway is asked to return: the schema fields only."""

    body = {"focus": "STABILITY", **overrides}
    if claims is not None:
        body["status_claims"] = claims
    return body


def stored_summary(claims: dict | None = None, **overrides) -> dict:
    """A summary file as ``summarize_validation`` writes it (answer plus metadata)."""

    return {
        "schema_version": "1",
        "run_id": RUN_ID,
        "request_id": "req-summary",
        "request_event_id": "event-summary",
        "model": "test-model",
        **CONSISTENT_TEXT,
        **({"status_claims": claims} if claims is not None else {}),
        **overrides,
    }


class FixedProvider:
    """One provider response per call; records every message list it receives."""

    def __init__(self, bodies: list[dict], model: str = "test-model"):
        from types import SimpleNamespace

        self.bodies = bodies
        self.calls: list[dict] = []
        self.config = SimpleNamespace(model=model, protocol="test", max_output_tokens=1_000_000)

    def generate(self, messages, tools=None):
        self.calls.append({"messages": list(messages), "tools": tools})
        index = min(len(self.calls) - 1, len(self.bodies) - 1)
        return ProviderResponse(json.dumps(self.bodies[index]), (), "stop", f"req-{len(self.calls)}", f"event-{len(self.calls)}")


def generate(run: Path, bodies: list[dict], monkeypatch) -> FixedProvider:
    provider = FixedProvider(bodies)
    monkeypatch.setattr("src.agent._provider", lambda *args: provider)
    summarize_validation(Path(__file__).resolve().parents[1], run, RUN_ID)
    return provider


def approve_report(run: Path) -> dict:
    rendered = render_report(run, RUN_ID, agent_summary=read_json(run / "report" / "agent_summary.json"), inventories={"MDL_CREDIT_V1": "APPROVED"})
    manifest = run / "report" / "review_manifest.json"
    record_review(run, RUN_ID, "Gate_C", manifest, artifact_digest(manifest, "Gate_C"), "APPROVED", "unit-test", "delegated review of the rendered report")
    return {"rendered": rendered, "approval": write_approval(run, RUN_ID), "status": report_status(run, RUN_ID)}


# --- 1. the correct conclusion is accepted end to end -----------------------


def test_a_correct_summary_passes_generation_and_gate_c(tmp_path, monkeypatch):
    run = make_run(tmp_path)
    provider = generate(run, [model_answer(CLEAN_CLAIMS)], monkeypatch)
    assert len(provider.calls) == 1

    stored = read_json(run / "report" / "agent_summary.json")
    assert stored["status_claims"]["parity"] == "MATCH"
    assert stored["model"] == "test-model"
    assert stored["schema_version"] == "2"
    assert stored["focus"] == "STABILITY"

    result = approve_report(run)
    assert result["status"]["status"] == "APPROVED"
    assert result["approval"]["status"] == "APPROVED"
    assert "Review the feature and prediction PSI states" in Path(result["rendered"]["report"]).read_text()


def test_the_report_states_the_true_status_without_asking_the_model(tmp_path):
    run = make_run(tmp_path, summary=stored_summary(CLEAN_CLAIMS))
    rendered = render_report(run, RUN_ID, agent_summary=read_json(run / "report" / "agent_summary.json"), inventories={})
    text = Path(rendered["report"]).read_text()
    assert "## Key conclusions (rendered from validation_metrics.json)" in text
    section = text.split("## Key conclusions", 1)[1].split("## Row-level equivalence", 1)[0]
    assert "`PASS`" in section  # parity status, rendered from parity.status
    assert "`REVIEW_HIGHLIGHTED`" in section  # stability status, rendered from stability.status
    assert "`AUDIT_SIGNAL_ONLY`" not in section and "`OK`" in section  # fairness status


def test_derived_facts_track_the_metrics(tmp_path):
    facts = derive_facts(metrics(degraded=True))
    assert facts["parity"] == "MISMATCH"
    assert facts["stability"] == "REVALIDATION_REQUIRED"
    assert facts["degraded_checks"] == ["PARITY", "STABILITY"]
    assert facts["cross_time_backtest"] == "UNAVAILABLE"


def test_the_generation_schema_requires_the_claims():
    schema = agent_summary_schema()
    assert "status_claims" in schema["required"]
    assert set(schema["properties"]) == {"status_claims", "focus"}
    assert sorted(schema["$defs"]["SummaryClaims"]["required"]) == [
        "cross_time_backtest",
        "degraded_checks",
        "fairness",
        "parity",
        "stability",
    ]


# --- 2. the reversed direction is refused -----------------------------------


def test_a_reversed_parity_claim_is_refused_after_the_single_retry(tmp_path, monkeypatch):
    run = make_run(tmp_path, degraded=True)
    reversed_claims = {**STABLE_CLAIMS, "parity": "MATCH"}  # metrics say MISMATCH
    provider = FixedProvider([model_answer(reversed_claims)])
    monkeypatch.setattr("src.agent._provider", lambda *args: provider)

    with pytest.raises(ContractError) as error:
        summarize_validation(Path(__file__).resolve().parents[1], run, RUN_ID)
    assert "contradicts" in str(error.value)
    assert not (run / "report" / "agent_summary.json").exists()

    # The retry limit is unchanged: exactly one format retry, both refusals audited.
    audit = [json.loads(line) for line in (run / "agent_audit_log.jsonl").read_text().splitlines()]
    rejected = [event for event in audit if event["event"] == "OUTPUT_REJECTED"]
    assert [event["attempt"] for event in rejected] == [0, 1]
    assert all("contradicts" in event["reason"] for event in rejected)
    assert len(provider.calls) == 2


def test_the_retry_recovers_when_the_second_answer_matches_the_metrics(tmp_path, monkeypatch):
    run = make_run(tmp_path)
    wrong = {**CLEAN_CLAIMS, "parity": "MISMATCH"}  # metrics say MATCH
    provider = FixedProvider([model_answer(wrong), model_answer(CLEAN_CLAIMS)])
    monkeypatch.setattr("src.agent._provider", lambda *args: provider)

    summarize_validation(Path(__file__).resolve().parents[1], run, RUN_ID)
    assert len(provider.calls) == 2
    stored = read_json(run / "report" / "agent_summary.json")
    assert stored["status_claims"]["parity"] == "MATCH"
    audit = [json.loads(line) for line in (run / "agent_audit_log.jsonl").read_text().splitlines()]
    assert [event["event"] for event in audit if event["event"].startswith(("OUTPUT_REJECTED", "SUMMARY_ACCEPTED"))] == [
        "OUTPUT_REJECTED",
        "SUMMARY_ACCEPTED",
    ]


def test_reversed_prose_is_refused_even_with_correct_claims(tmp_path, monkeypatch):
    run = make_run(tmp_path, degraded=True)
    body = model_answer(
        {**CLEAN_CLAIMS, "parity": "MISMATCH", "stability": "STABLE", "degraded_checks": ["PARITY"]},
        results=["Row-level parity passes on both splits with no classification differences."],
    )
    with pytest.raises(ContractError) as error:
        check_summary(body, read_json(run / "validation_metrics.json"), require_claims=True)
    assert "contradicts" in str(error.value)


# --- 3. missing evidence is refused -----------------------------------------


def test_a_summary_without_status_claims_is_refused(tmp_path):
    run = make_run(tmp_path)
    body = model_answer(None)
    with pytest.raises(ContractError) as error:
        check_summary(body, read_json(run / "validation_metrics.json"), require_claims=True)
    assert "missing status_claims" in str(error.value)


def test_a_missing_degraded_check_is_refused(tmp_path):
    run = make_run(tmp_path, degraded=True)
    incomplete = {**CLEAN_CLAIMS, "parity": "MISMATCH", "stability": "REVALIDATION_REQUIRED", "degraded_checks": ["PARITY"]}
    with pytest.raises(ContractError) as error:
        check_summary(model_answer(incomplete), read_json(run / "validation_metrics.json"), require_claims=True)
    assert "degraded_checks" in str(error.value)


def test_an_unsupported_claim_value_is_refused(tmp_path):
    run = make_run(tmp_path)
    with pytest.raises(ContractError):
        check_summary(model_answer({**CLEAN_CLAIMS, "fairness": "FAIR"}), read_json(run / "validation_metrics.json"), require_claims=True)


@pytest.mark.parametrize(
    "prose",
    [
        "The two implementations returned different classifications.",
        "The model is production-ready, but cross-time evidence is not yet available.",
        "The model is fair and unbiased across groups.",
    ],
)
def test_free_text_is_refused_even_if_the_structured_claims_are_correct(tmp_path, monkeypatch, prose):
    run = make_run(tmp_path)
    provider = FixedProvider([model_answer(CLEAN_CLAIMS, results=[prose])])
    monkeypatch.setattr("src.agent._provider", lambda *args: provider)
    with pytest.raises(ContractError, match="Extra inputs"):
        summarize_validation(Path(__file__).resolve().parents[1], run, RUN_ID)
    assert not (run / "report" / "agent_summary.json").exists()


def test_a_new_report_will_not_approve_a_legacy_free_text_summary(tmp_path):
    run = make_run(tmp_path, summary=stored_summary(CLEAN_CLAIMS))
    write_json(run / "validation_metrics.json", {**metrics(), "data_kind": "synthetic"})
    with pytest.raises(ValueError, match="validation error"):
        render_report(run, RUN_ID, agent_summary=read_json(run / "report" / "agent_summary.json"), inventories={})
    assert report_status(run, RUN_ID)["status"] == "DRAFT"


@pytest.mark.parametrize("kind,source", [("synthetic", "use synthetic data and labels"), ("uci", "same UCI extract")])
def test_report_describes_its_dataset_from_the_metrics(tmp_path, kind, source):
    run = make_run(tmp_path)
    write_json(run / "validation_metrics.json", {**metrics(), "data_kind": kind})
    path = Path(render_report(run, RUN_ID, agent_summary=None, inventories={})["report"])
    assert source in path.read_text()
    if kind == "synthetic":
        assert "UCI" not in path.read_text()


# --- 5. historical summaries stay readable but cannot contradict -----------


def test_a_legacy_summary_without_claims_is_still_rendered(tmp_path):
    run = make_run(tmp_path, summary=stored_summary(None))
    rendered = render_report(run, RUN_ID, agent_summary=read_json(run / "report" / "agent_summary.json"), inventories={})
    assert Path(rendered["report"]).is_file()


def test_a_legacy_summary_that_contradicts_the_metrics_blocks_gate_c(tmp_path):
    contradictory = stored_summary(None, results=["Row-level parity passes with no classification differences."])
    run = make_run(tmp_path, degraded=True, summary=contradictory)
    with pytest.raises(ContractError) as error:
        render_report(run, RUN_ID, agent_summary=read_json(run / "report" / "agent_summary.json"), inventories={})
    assert "contradicts the metrics" in str(error.value)

    # Gate C approval is bound to the rendered report, so a hand-edited summary
    # can never turn a report that was rendered without it into APPROVED.
    run2 = make_run(tmp_path / "second", degraded=True)
    render_report(run2, RUN_ID, agent_summary=None, inventories={})
    write_json(run2 / "report" / "agent_summary.json", contradictory)
    status = report_status(run2, RUN_ID)
    assert status["status"] == "DRAFT"
    # The rendered report does not bind the stray file, so it stays out of the
    # approved artifact and gate C cannot be satisfied.
    manifest = read_json(run2 / "report" / "review_manifest.json")
    assert manifest["agent_summary"] is None
    assert any("Gate_C" in reason for reason in status["reasons"])
    with pytest.raises(GateError):
        write_approval(run2, RUN_ID)


# Historical wording is checked for read-only replay compatibility.

@pytest.mark.parametrize(
    "disclaimer",
    [
        "Regulatory approval was not given for this scorecard.",
        "This evidence is never an independent validation for the regulator.",
        "Production readiness is not claimed anywhere in this run.",
    ],
)
def test_a_negation_after_the_claim_is_not_an_overclaim(disclaimer):
    assert check_summary(
        {
            "headline": "The ported scorecard reproduces the reference probabilities.",
            "status_claims": CLEAN_CLAIMS,
            "results": ["Row-level parity passes with no classification differences."],
            "limitations": [disclaimer],
            "evidence_gaps": ["A cross-time back-test is unavailable for this extract."],
        },
        metrics(),
        require_claims=True,
    ) is None
