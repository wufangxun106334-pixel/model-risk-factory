"""Report rendering with mechanical value provenance (SOP V2-07).

The Markdown report contains no hand-typed numbers, including inside tables.
Every number is produced by ``Renderer.path()``, which resolves one JSON path in
``validation_metrics.json`` and records the path next to the rendered text.
``verify_provenance()`` then re-reads the finished Markdown and fails when a
numeric token cannot be traced back to a recorded path.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, ValidationError

from src.common import ContractError, GateError, append_jsonl, read_json, sha256_file, utc_now, write_json
from src.contracts import StrictModel
from src.review import current_decision

NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w.])")
FORBIDDEN_CLAIMS = (
    "regulatory compliant",
    "regulator approved",
    "certified compliant",
    "regulatory approval",
    "independently validated",
    "independent validation",
    "production ready",
    "production-ready",
    "safe for production",
    "合规认证",
    "监管认证",
    "已通过监管",
    "完全公平",
    "无偏差",
)
LOW_SAMPLE_LABEL = "LOW_SAMPLE"


def resolve(metrics: dict, dotted: str):
    current = metrics
    for part in dotted.split("."):
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            if part not in current:
                raise ContractError(f"Report path does not resolve: {dotted}")
            current = current[part]
        else:
            raise ContractError(f"Report path does not resolve: {dotted}")
    return current


class Renderer:
    def __init__(self, metrics: dict):
        self.metrics = metrics
        self.index: list[dict] = []

    def path(self, dotted: str, *, label: str, section: str, pattern: str = "{:.4f}", empty: str = "not assessable") -> str:
        value = resolve(self.metrics, dotted)
        if value is None:
            text = empty
        elif isinstance(value, bool):
            text = "true" if value else "false"
        elif isinstance(value, (int, float)):
            text = pattern.format(value)
        else:
            text = str(value)
        self.index.append({"section": section, "label": label, "json_path": dotted, "text": text, "raw": value})
        return text

    def raw(self, dotted: str, *, label: str, section: str) -> str:
        return self.path(dotted, label=label, section=section, pattern="{}")

    def note(self, dotted: str, *, label: str, section: str, text: str) -> str:
        """Index a non-numeric value (such as a group name) for provenance."""

        self.index.append({"section": section, "label": label, "json_path": dotted, "text": text, "raw": text})
        return text


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def _value(renderer: Renderer, metrics: dict, dotted: str, *, label: str, section: str, pattern: str = "{:.4f}") -> str:
    return renderer.path(dotted, label=label, section=section, pattern=pattern, empty="—")


def performance_table(renderer: Renderer) -> str:
    rows = []
    for dataset in ("dev", "holdout", "shifted"):
        base = f"performance.{dataset}"
        rows.append([
            dataset,
            _value(renderer, None, f"{base}.rows", label=f"{dataset} rows", section="performance", pattern="{}"),
            _value(renderer, None, f"{base}.positive_rows", label=f"{dataset} positives", section="performance", pattern="{}"),
            _value(renderer, None, f"{base}.negative_rows", label=f"{dataset} negatives", section="performance", pattern="{}"),
            _value(renderer, None, f"{base}.roc_auc.value", label=f"{dataset} ROC-AUC", section="performance"),
            _value(renderer, None, f"{base}.brier_score.value", label=f"{dataset} Brier", section="performance"),
            renderer.raw(f"{base}.roc_auc.status", label=f"{dataset} ROC-AUC status", section="performance"),
        ])
    return _table(["dataset", "rows", "positives", "negatives", "ROC-AUC", "Brier", "AUC status"], rows)


def calibration_table(renderer: Renderer) -> str:
    rows = []
    for index in range(10):
        base = f"performance.holdout.calibration.value.{index}"
        rows.append([
            _value(renderer, None, f"{base}.decile", label=f"decile row {index} label", section="calibration", pattern="{}"),
            _value(renderer, None, f"{base}.rows", label=f"decile row {index} rows", section="calibration", pattern="{}"),
            _value(renderer, None, f"{base}.mean_probability", label=f"decile row {index} mean probability", section="calibration"),
            _value(renderer, None, f"{base}.observed_default_rate", label=f"decile row {index} observed rate", section="calibration"),
            _value(renderer, None, f"{base}.absolute_gap", label=f"decile row {index} gap", section="calibration"),
        ])
    return _table(["decile", "rows", "mean predicted", "observed default rate", "absolute gap"], rows)


def confusion_table(renderer: Renderer) -> str:
    base = "performance.holdout.confusion_matrix.value"
    rows = [
        [
            "predicted default",
            _value(renderer, None, f"{base}.true_positive", label="holdout true positives", section="confusion", pattern="{}"),
            _value(renderer, None, f"{base}.false_positive", label="holdout false positives", section="confusion", pattern="{}"),
        ],
        [
            "predicted no default",
            _value(renderer, None, f"{base}.false_negative", label="holdout false negatives", section="confusion", pattern="{}"),
            _value(renderer, None, f"{base}.true_negative", label="holdout true negatives", section="confusion", pattern="{}"),
        ],
    ]
    return _table(["", "actual default", "actual no default"], rows)


def stability_table(renderer: Renderer) -> str:
    rows = []
    for name in renderer.metrics["stability"]["features"]:
        rows.append([
            name,
            _value(renderer, None, f"stability.features.{name}.value", label=f"{name} PSI", section="stability"),
            renderer.raw(f"stability.features.{name}.state", label=f"{name} PSI state", section="stability"),
        ])
    rows.append([
        "predicted probability",
        _value(renderer, None, "stability.prediction.value", label="prediction PSI", section="stability"),
        renderer.raw("stability.prediction.state", label="prediction PSI state", section="stability"),
    ])
    return _table(["signal", "PSI", "state"], rows)


def fairness_table(renderer: Renderer) -> str:
    metrics = renderer.metrics
    rows = []
    for attribute, payload in metrics["fairness"]["attributes"].items():
        for group in payload.get("groups", {}):
            base = f"fairness.attributes.{attribute}.groups.{group}"
            renderer.note(f"fairness.attributes.{attribute}.groups", label=f"{attribute} group label", section="fairness", text=group)
            rows.append([
                attribute,
                group,
                _value(renderer, None, f"{base}.rows", label=f"{attribute} {group} rows", section="fairness", pattern="{}"),
                _value(renderer, None, f"{base}.positive_rows", label=f"{attribute} {group} positives", section="fairness", pattern="{}"),
                _value(renderer, None, f"{base}.tpr.value", label=f"{attribute} {group} TPR", section="fairness"),
                renderer.raw(f"{base}.tpr.status", label=f"{attribute} {group} TPR status", section="fairness"),
                _value(renderer, None, f"{base}.fpr.value", label=f"{attribute} {group} FPR", section="fairness"),
                renderer.raw(f"{base}.fpr.status", label=f"{attribute} {group} FPR status", section="fairness"),
            ])
    return _table(["attribute", "group", "rows", "positives", "TPR", "TPR status", "FPR", "FPR status"], rows)


def agent_summary_schema() -> dict:
    return AgentInterpretation.model_json_schema()


class SummaryClaims(StrictModel):
    """Closed-enum statements that must equal the facts derived from the metrics."""

    parity: Literal["MATCH", "MISMATCH"]
    stability: Literal["STABLE", "ATTENTION", "REVALIDATION_REQUIRED", "NOT_ASSESSABLE"]
    fairness: Literal["AUDIT_SIGNAL_ONLY"]
    cross_time_backtest: Literal["UNAVAILABLE"]
    degraded_checks: list[Literal["PARITY", "STABILITY", "FAIRNESS_LOW_SAMPLE", "PERFORMANCE_NOT_ASSESSABLE"]]


class AgentInterpretation(StrictModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    status_claims: SummaryClaims
    focus: Literal["PARITY", "PERFORMANCE", "STABILITY", "FAIRNESS"]


class RecordedInterpretation(AgentInterpretation):
    schema_version: Literal["2"]
    run_id: str
    generated_at: str
    model: str
    request_id: str
    request_event_id: str
    audit_log: str
    aggregate_input_sha256: str


REVIEW_FOCUS = {
    "PARITY": "Review row-level probability, classification and behaviour agreement before interpreting other results.",
    "PERFORMANCE": "Review discrimination and calibration together, including the observed rate and predicted probability by decile.",
    "STABILITY": "Review the feature and prediction PSI states against the configured attention and revalidation thresholds.",
    "FAIRNESS": "Review the reported TPR and FPR by group together with sample-size limits and the comparison to each reference group.",
}


# --- Deterministic facts and status claims (V3 gap 2) ------------------------
#
# The Agent used to write free prose that nothing compared with the metrics, so a
# summary could state the opposite of ``parity.status`` or of the PSI state and
# still pass Gate C. The key conclusions are now (a) rendered from the metrics by
# a trusted template that no model can influence, and (b) additionally required
# from the model as closed-enum claims that must equal the facts derived here.

STABILITY_CLAIMS = {
    "OK": "STABLE",
    "REVIEW_HIGHLIGHTED": "ATTENTION",
    "REVALIDATION_REQUIRED": "REVALIDATION_REQUIRED",
    "NOT_ASSESSABLE": "NOT_ASSESSABLE",
}
DEGRADED_PARITY = "PARITY"
DEGRADED_STABILITY = "STABILITY"
DEGRADED_FAIRNESS = "FAIRNESS_LOW_SAMPLE"
DEGRADED_PERFORMANCE = "PERFORMANCE_NOT_ASSESSABLE"


def derive_facts(metrics: dict) -> dict:
    """Derive the checkable facts the summary has to agree with.

    Nothing here reads the Agent text; every value comes from
    ``validation_metrics.json``.
    """

    parity = metrics.get("parity") or {}
    per_dataset = [parity.get(name) or {} for name in ("dev", "holdout")]
    parity_match = bool(per_dataset) and all(entry.get("status") == "PASS" for entry in per_dataset) and all(
        int(entry.get("classification_mismatch_count") or 0) == 0
        and int(entry.get("behaviour_mismatch_count") or 0) == 0
        and bool(entry.get("id_sets_match", True))
        for entry in per_dataset
    )
    stability_status = (metrics.get("stability") or {}).get("status")
    stability_claim = STABILITY_CLAIMS.get(str(stability_status), "NOT_ASSESSABLE")
    fairness = metrics.get("fairness") or {}
    low_sample = sorted(
        f"{attribute}:{group}"
        for attribute, payload in (fairness.get("attributes") or {}).items()
        for group, entry in ((payload or {}).get("groups") or {}).items()
        if (entry or {}).get("sample_status") == LOW_SAMPLE_LABEL
    )
    holdout = (metrics.get("performance") or {}).get("holdout") or {}
    not_assessable = [
        name for name in ("roc_auc", "brier_score") if (holdout.get(name) or {}).get("status") not in (None, "OK")
    ]
    degraded: list[str] = []
    if not parity_match:
        degraded.append(DEGRADED_PARITY)
    if stability_claim != "STABLE":
        degraded.append(DEGRADED_STABILITY)
    if low_sample or fairness.get("status") not in (None, "OK"):
        degraded.append(DEGRADED_FAIRNESS)
    if not_assessable:
        degraded.append(DEGRADED_PERFORMANCE)
    return {
        "parity": "MATCH" if parity_match else "MISMATCH",
        "parity_status": parity.get("status"),
        "stability": stability_claim,
        "stability_status": stability_status,
        "fairness": "AUDIT_SIGNAL_ONLY",
        "fairness_status": fairness.get("status"),
        "cross_time_backtest": "UNAVAILABLE",
        "degraded_checks": degraded,
        "fairness_low_sample_groups": low_sample,
        "performance_not_assessable": not_assessable,
    }


# Phrases that state the opposite of the derived fact. They are only consulted
# when the claim is *not* the true one, and they are deliberately narrow: a
# sentence about discrimination is not a statement about PSI drift.
CONTRADICTING_PHRASES: dict[tuple[str, str], tuple[str, ...]] = {
    ("parity", "MATCH"): (
        "parity fails",
        "parity failed",
        "parity check failed",
        "does not reproduce",
        "does not match the reference",
        "classification mismatches are present",
        "classification differences are present",
        "predictions differ",
        "probabilities differ",
    ),
    ("parity", "MISMATCH"): (
        "parity passes",
        "parity matches",
        "no classification differences",
        "no classification mismatches",
        "identical predictions",
        "exact match",
        "perfect match",
        "reproduces the reference probabilities",
    ),
    ("stability", "STABLE"): (
        "drift exceeds",
        "psi exceeds",
        "revalidation is required",
        "requires revalidation",
        "drift batch is unstable",
    ),
    ("stability", "ATTENTION"): (
        "no drift was detected",
        "no drift is present",
        "psi remains low",
        "within the attention band",
        "no attention is required",
        "no revalidation is required",
        "below the attention threshold",
    ),
    ("stability", "REVALIDATION_REQUIRED"): (
        "no drift was detected",
        "no drift is present",
        "psi remains low",
        "within the attention band",
        "no attention is required",
        "no revalidation is required",
        "below the attention threshold",
        "below the review threshold",
        "stability is fine",
    ),
    ("stability", "NOT_ASSESSABLE"): (
        "no drift was detected",
        "no drift is present",
        "psi remains low",
        "within the attention band",
        "no revalidation is required",
    ),
}
# These are never acceptable, whatever the metrics say: fairness is an audit
# signal, never a proof.
ALWAYS_CONTRASTING_PHRASES = (
    "the model is fair",
    "fairness is proven",
    "proven fair",
    "groups are treated equally",
    "all groups are comparable",
    "no group is disadvantaged",
    "the model is unbiased",
)


def _summary_text(summary: dict) -> str:
    return " ".join(
        str(item)
        for item in [
            summary.get("headline", ""),
            *(summary.get("results") or []),
            *(summary.get("limitations") or []),
            *(summary.get("evidence_gaps") or []),
        ]
    )


def claim_problems(claims, facts: dict) -> list[str]:
    """Compare the Agent's closed-enum claims with the derived facts."""

    try:
        parsed = SummaryClaims.model_validate(claims)
    except ValidationError as error:
        return [f"status_claims are invalid: {str(error)[:200]}"]
    problems: list[str] = []
    for field in ("parity", "stability", "fairness", "cross_time_backtest"):
        got, want = getattr(parsed, field), facts[field]
        if got != want:
            problems.append(f"status_claims.{field}={got!r} contradicts validation_metrics.json ({want!r})")
    if sorted(parsed.degraded_checks) != sorted(facts["degraded_checks"]):
        problems.append(
            f"status_claims.degraded_checks={sorted(set(parsed.degraded_checks))!r} contradicts "
            f"validation_metrics.json ({sorted(facts['degraded_checks'])!r})"
        )
    return problems


def check_interpretation(interpretation: AgentInterpretation, metrics: dict) -> None:
    problems = claim_problems(interpretation.status_claims.model_dump(), derive_facts(metrics))
    if problems:
        raise ContractError("Summary contradicts the metrics: " + "; ".join(problems[:4]))


def contradiction_problems(summary: dict, facts: dict) -> list[str]:
    lowered = _summary_text(summary).lower()
    problems: list[str] = []
    for field in ("parity", "stability"):
        for phrase in CONTRADICTING_PHRASES.get((field, facts[field]), ()):
            if phrase in lowered:
                problems.append(
                    f"report text says {phrase!r}, but validation_metrics.json records "
                    f"{field}={facts[field]!r} ({facts[field + '_status']!r})"
                )
    for phrase in ALWAYS_CONTRASTING_PHRASES:
        if phrase in lowered:
            problems.append(f"report text says {phrase!r}; fairness results are audit signals, never a proof")
    return problems


def check_summary(summary: dict, metrics: dict, *, require_claims: bool = False) -> None:
    """Reject a summary that is unsafe, restates numbers, or contradicts the facts.

    ``require_claims`` is used on the generation path, so a new run cannot produce
    a summary without the structured claims. Historical summaries (schema 1) stay
    readable, but the phrase-level contradiction check still applies to them.
    """

    facts = derive_facts(metrics)
    check_wording(_summary_text(summary))
    restated = NUMBER.findall(_summary_text(summary))
    if restated:
        raise ContractError(
            f"Summary must not restate numbers ({restated[:5]}); every figure is rendered from a metrics path"
        )
    claims = summary.get("status_claims")
    if claims is None:
        if require_claims:
            raise ContractError(
                "Summary is missing status_claims; parity, stability, fairness and back-test status must be "
                "stated as closed-enum claims that match validation_metrics.json"
            )
    else:
        problems = claim_problems(claims, facts)
        if problems:
            raise ContractError("Summary contradicts the metrics: " + "; ".join(problems[:4]))
    problems = contradiction_problems(summary, facts)
    if problems:
        raise ContractError("Summary contradicts the metrics: " + "; ".join(problems[:4]))


def _negated(prefix: str) -> bool:
    """True when the words just before a claim say it does *not* hold.

    A disclaimer such as "no independent validation, regulatory approval or
    production readiness is claimed" is the correct wording, so the phrase list
    must not fire on it.
    """

    words = re.split(r"[^\w']+", prefix.strip())
    recent = [word for word in words if word][-4:]
    negations = {"no", "not", "never", "without", "cannot", "can't", "neither", "nothing", "none", "nor", "未", "不", "无", "没有", "并非"}
    return any(word.lower() in negations for word in recent)


NEGATED_SUFFIXES = (
    "is missing",
    "are missing",
    "remains missing",
    "is unavailable",
    "are unavailable",
    "is absent",
    "not established",
    "not claimed",
    "not inferred",
)
SUFFIX_WINDOW = 120


def _negated_after(suffix: str) -> bool:
    """True when the same clause reports the claim as missing or not claimed.

    Two things count: one of the explicit "is missing / not established" markers, or
    any negation particle inside the same clause. The second rule matters because a
    correct disclaimer often puts the negation after the noun ("regulatory approval
    was not given"), and refusing that wording burns the single retry on a sentence
    that is actually right. The clause ends at the first sentence terminator, so a
    later sentence about missing evidence cannot excuse an overclaim.
    """

    clause = re.split(r"[.!?\n]", suffix.lower(), maxsplit=1)[0]
    if any(marker in clause for marker in NEGATED_SUFFIXES):
        return True
    return bool(re.search(r"(?:\bno\b|\bnot\b|\bnever\b|\bwithout\b|n't\b|未|不|无)", clause))


def check_wording(text: str) -> None:
    lowered = text.lower()
    for claim in FORBIDDEN_CLAIMS:
        needle = claim.lower()
        start = 0
        while True:
            index = lowered.find(needle, start)
            if index < 0:
                break
            prefix = lowered[max(0, index - 60) : index]
            suffix = lowered[index + len(needle) : index + len(needle) + SUFFIX_WINDOW]
            if not _negated(prefix) and not _negated_after(suffix):
                raise ContractError(
                    f"Forbidden compliance claim in report text: {claim}"
                    " (stating the absence of approval is fine; asserting it is not)"
                )
            start = index + len(needle)


def desensitized_summary(metrics: dict) -> dict:
    """Aggregate numbers only: no rows, no client ids, no Holdout inputs."""

    def strip(entry):
        if isinstance(entry, dict):
            if "value" in entry:
                return {"value": entry["value"], "status": entry["status"]}
            return {key: strip(value) for key, value in entry.items() if key not in {"reference_share", "comparison_share", "edges"}}
        if isinstance(entry, list):
            return [strip(item) for item in entry]
        return entry

    return {
        "parity": {
            name: {
                "status": metrics["parity"][name]["status"],
                "max_abs_diff": metrics["parity"][name]["max_abs_diff"],
                "mean_abs_diff": metrics["parity"][name]["mean_abs_diff"],
                "classification_mismatch_count": metrics["parity"][name]["classification_mismatch_count"],
            }
            for name in ("dev", "holdout")
        },
        "performance": {name: strip(metrics["performance"][name]) for name in ("dev", "holdout", "shifted")},
        "stability": strip(metrics["stability"]),
        "fairness": strip(metrics["fairness"]),
        "rules": metrics["rules"],
        "threshold": metrics["threshold"],
        "dataset_rows": {name: entry["rows"] for name, entry in metrics["datasets"].items()},
        # The checkable facts the claims must equal. Sending them keeps the task
        # deterministic instead of asking the model to infer a direction.
        "derived_facts": derive_facts(metrics),
    }


def _render_markdown(metrics: dict, run_id: str, agent_summary: dict | None, inventories: dict) -> tuple[str, str, list[dict]]:
    if metrics.get("run_id") != run_id:
        raise ContractError("validation_metrics.json belongs to another run")
    renderer = Renderer(metrics)

    performance = performance_table(renderer)
    calibration = calibration_table(renderer)
    confusion = confusion_table(renderer)
    stability = stability_table(renderer)
    fairness = fairness_table(renderer)

    lines: list[str] = []
    lines.append("# Model validation report — MDL_CREDIT_V1")
    lines.append("")
    lines.append("Generated by `python -m src.cli report` from `validation_metrics.json`. "
                 "Every number in this report is rendered through a recorded JSON path; "
                 "`report/values_index.csv` lists the path for each one.")
    lines.append("")
    lines.append(f"Run: `{run_id}`")
    lines.append("")
    lines.append("**Approval state.** This file is never edited after generation. Publication "
                 "requires a Gate C approval of `report/review_manifest.json`; that approval is "
                 "recorded in `review_log.json` and mirrored in `report/approval.json`, which is "
                 "created only by `python -m src.cli approve-report` after Gate C passes.")
    lines.append("")

    lines.append("## Artifact under validation")
    for model_id, artifact in sorted(inventories.items()):
        lines.append(f"- {model_id}: Gate A status `{artifact}`")
    lines.append(f"- Frozen candidate SHA256: `{renderer.raw('candidate_sha256', label='candidate hash', section='artifact')}`")
    lines.append(f"- Decision threshold: {renderer.path('threshold', label='threshold', section='artifact')}")
    lines.append("")

    lines.append("## Key conclusions (rendered from validation_metrics.json)")
    lines.append("")
    lines.append(
        "Generated by the trusted renderer from the metrics file, never from Agent text: these "
        "statements always match the recorded status, including after a re-render at Gate C."
    )
    lines.append("")
    lines.append(
        "- Row-level probability and classification parity: "
        f"`{renderer.raw('parity.status', label='parity status', section='conclusions')}` "
        f"(dev `{renderer.raw('parity.dev.status', label='parity dev status', section='conclusions')}`, "
        f"holdout `{renderer.raw('parity.holdout.status', label='parity holdout status', section='conclusions')}`)."
    )
    lines.append(
        "- Stability against the weighted drift batch: "
        f"`{renderer.raw('stability.status', label='stability status', section='conclusions')}`; a flagged batch "
        "only raises a revalidation task and is not a bank action."
    )
    lines.append(
        "- Fairness on the Holdout: "
        f"`{renderer.raw('fairness.status', label='fairness status', section='conclusions')}` — an audit signal "
        "only; groups below the minimum sample size are labelled `LOW_SAMPLE` and their rates are not assessable."
    )
    lines.append(
        "- Cross-time back-test: `UNAVAILABLE` from this dataset and kept on the missing-evidence list."
    )
    lines.append("")

    lines.append("## Row-level equivalence (parity)")
    lines.append("")
    for dataset in ("dev", "holdout"):
        section = f"parity.{dataset}"
        lines.append(
            f"- {dataset}: status `{renderer.raw(section + '.status', label=dataset + ' parity status', section='parity')}`"
            f", rows {renderer.raw(section + '.rows', label=dataset + ' parity rows', section='parity')}"
            f", max absolute difference {renderer.path(section + '.max_abs_diff', label=dataset + ' max abs diff', section='parity', pattern='{:.3e}')}"
            f", mean absolute difference {renderer.path(section + '.mean_abs_diff', label=dataset + ' mean abs diff', section='parity', pattern='{:.3e}')}"
            f", classification mismatches {renderer.raw(section + '.classification_mismatch_count', label=dataset + ' classification mismatches', section='parity')}"
            f", behaviour mismatches {renderer.raw(section + '.behaviour_mismatch_count', label=dataset + ' behaviour mismatches', section='parity')}"
            f", limits {renderer.path(section + '.limits.max_abs_diff', label=dataset + ' max abs diff limit', section='parity', pattern='{:.0e}')}"
            f" / {renderer.path(section + '.limits.mean_abs_diff', label=dataset + ' mean abs diff limit', section='parity', pattern='{:.0e}')}."
        )
    lines.append("")

    lines.append("## Performance and calibration")
    lines.append("")
    lines.append(performance)
    lines.append("")
    for dataset in ("dev", "holdout", "shifted"):
        lines.append(
            f"- {dataset}: ROC-AUC {renderer.path(f'performance.{dataset}.roc_auc.value', label=dataset + ' ROC-AUC', section='performance')}"
            f" (`{renderer.raw(f'performance.{dataset}.roc_auc.status', label=dataset + ' ROC-AUC status', section='performance')}`)"
            f", Brier {renderer.path(f'performance.{dataset}.brier_score.value', label=dataset + ' Brier', section='performance')}"
            f" (`{renderer.raw(f'performance.{dataset}.brier_score.status', label=dataset + ' Brier status', section='performance')}`)."
        )
    lines.append("")
    lines.append("Holdout confusion matrix at the decision threshold:")
    lines.append("")
    lines.append(confusion)
    lines.append("")
    lines.append("Holdout decile calibration (equal-frequency groups on predicted probability):")
    lines.append("")
    lines.append(calibration)
    lines.append("")

    lines.append("## Stability: dev reference vs weighted drift batch (scenario A)")
    lines.append("")
    lines.append(f"Scenario `{renderer.raw('stability.scenario', label='scenario', section='stability')}` "
                 f"uses `{renderer.raw('stability.reference', label='PSI reference', section='stability')}` as the reference distribution.")
    lines.append("")
    lines.append(stability)
    lines.append("")
    lines.append(
        f"PSI uses {renderer.raw('rules.psi_bins', label='PSI bins', section='stability')} bins from reference quantiles "
        f"and a pseudocount of {renderer.path('rules.psi_pseudocount', label='PSI pseudocount', section='stability')}; "
        f"the aggregate state is `{renderer.raw('stability.status', label='stability state', section='stability')}`. "
        f"Attention is flagged at {renderer.path('rules.psi_attention', label='PSI attention', section='stability')} and "
        f"review at {renderer.path('rules.psi_review', label='PSI review', section='stability')}; these are project demo rules, "
        "not a regulatory standard."
    )
    lines.append("")

    lines.append("## Fairness audit on the Holdout")
    lines.append("")
    lines.append(
        f"Reference groups come from `train.csv`: age_band "
        f"`{renderer.raw('fairness.reference_groups.age_band', label='age reference group', section='fairness')}`, "
        f"sex `{renderer.raw('fairness.reference_groups.sex', label='sex reference group', section='fairness')}`. "
        f"Groups with fewer than {renderer.raw('rules.min_group_rows', label='min group rows', section='fairness')} labelled rows are marked "
        f"`{LOW_SAMPLE_LABEL}`, and a rate needs at least {renderer.raw('rules.min_class_rows', label='min class rows', section='fairness')} rows in that class."
    )
    lines.append("")
    lines.append(fairness)
    lines.append("")
    for attribute in ("age_band", "sex"):
        differences = metrics["fairness"]["attributes"].get(attribute, {}).get("differences", {})
        for group in differences:
            lines.append(
                f"- {attribute} `{group}`: TPR difference "
                f"{renderer.path(f'fairness.attributes.{attribute}.differences.{group}.tpr.value', label=f'{attribute} {group} TPR diff', section='fairness')} "
                f"(`{renderer.raw(f'fairness.attributes.{attribute}.differences.{group}.tpr.status', label=f'{attribute} {group} TPR diff status', section='fairness')}`), "
                f"FPR difference "
                f"{renderer.path(f'fairness.attributes.{attribute}.differences.{group}.fpr.value', label=f'{attribute} {group} FPR diff', section='fairness')} "
                f"(`{renderer.raw(f'fairness.attributes.{attribute}.differences.{group}.fpr.status', label=f'{attribute} {group} FPR diff status', section='fairness')}`)."
            )
    lines.append("")

    lines.append("## Agent interpretation (desensitised aggregates only)")
    lines.append("")
    if agent_summary is None:
        lines.append("No agent summary has been recorded for this run.")
    elif agent_summary.get("schema_version") == "2" or "data_kind" in metrics:
        summary = RecordedInterpretation.model_validate(agent_summary)
        if summary.run_id != run_id:
            raise ContractError("Agent summary belongs to another run")
        check_interpretation(summary, metrics)
        lines.append("The Agent selected a review focus from aggregate metrics. The report renders the guidance from a fixed template.")
        lines.append("")
        lines.append(REVIEW_FOCUS[summary.focus])
    else:
        # Rejects forbidden claims, restated numbers, and any statement that is the
        # opposite of the recorded parity direction, PSI state or fairness scope.
        check_summary(agent_summary, metrics)
        lines.append("The Agent received aggregate metrics only: no data rows, no client identifiers and no Holdout inputs.")
        lines.append("")
        lines.append(agent_summary["headline"])
        lines.append("")
        for item in agent_summary["results"]:
            check_wording(item)
            lines.append(f"- {item}")
        lines.append("")
        lines.append("Limitations stated by the Agent:")
        lines.append("")
        for item in agent_summary["limitations"]:
            check_wording(item)
            lines.append(f"- {item}")
        lines.append("")
        lines.append("Evidence the Agent flagged as missing:")
        lines.append("")
        for item in agent_summary["evidence_gaps"]:
            check_wording(item)
            lines.append(f"- {item}")
    lines.append("")

    lines.append("## What these numbers do and do not show")
    lines.append("")
    if metrics.get("data_kind") == "synthetic":
        lines.append("- Holdout and the weighted drift batch use synthetic data and labels. The hold-out is same-period; the drift batch changes the sample composition. These are workflow checks, not a back-test or evidence of real-world performance.")
    else:
        lines.append("- The Holdout result is a same-period random hold-out from the same UCI extract: sample-out validation, not a back-test.")
        lines.append("- The weighted drift batch keeps real labels but changes the sample composition: a sensitivity analysis of stability, not a forecast of future performance.")
    lines.append("- A cross-time back-test is not available from this dataset and stays listed as missing evidence.")
    lines.append("- Fairness results describe error rates of a default-prediction model for the audited groups; they are audit signals, not proof that the model is fair, and they do not transfer to other populations.")
    lines.append("- The legacy model documents are simulated assets; no claim of regulatory approval, independent validation or production suitability is made.")
    lines.append("")

    lines.append("## Value provenance index")
    lines.append("")
    lines.append("Every number above resolves to a path in `validation_metrics.json`; `report/values_index.csv` lists each one.")
    lines.append("")

    tables_text = "\n\n".join([
        "# Validation metrics tables",
        "## Performance", performance,
        "## Calibration (holdout)", calibration,
        "## Confusion matrix (holdout)", confusion,
        "## Stability (dev vs scenario A)", stability,
        "## Fairness (holdout)", fairness,
    ]) + "\n"
    return "\n".join(lines), tables_text, renderer.index


def render_report(run_dir: Path, run_id: str, *, agent_summary: dict | None, inventories: dict) -> dict:
    metrics = read_json(run_dir / "validation_metrics.json")
    report_text, tables_text, index = _render_markdown(metrics, run_id, agent_summary, inventories)
    report_dir = run_dir / "report"
    summary_sha = sha256_file(report_dir / "agent_summary.json") if agent_summary is not None else None
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "validation_report.md"
    report_path.write_text(report_text, encoding="utf-8")

    index_path = report_dir / "values_index.csv"
    index_path.write_text(_render_index(index), encoding="utf-8")

    tables_path = report_dir / "validation_tables.md"
    tables_path.write_text(tables_text, encoding="utf-8")

    unresolved = verify_provenance(report_text, index)
    manifest = {
        "schema_version": "1",
        "run_id": run_id,
        "generated_at": utc_now(),
        "report": "report/validation_report.md",
        "report_sha256": sha256_file(report_path),
        "metrics": "validation_metrics.json",
        "metrics_sha256": sha256_file(run_dir / "validation_metrics.json"),
        "values_index": "report/values_index.csv",
        "values_index_sha256": sha256_file(index_path),
        "tables": "report/validation_tables.md",
        "tables_sha256": sha256_file(tables_path),
        "value_count": len(index),
        "unresolved_numbers": unresolved,
        "agent_summary": "report/agent_summary.json" if agent_summary is not None else None,
        "agent_summary_sha256": summary_sha,
        "inventory_gate_a": inventories,
    }
    write_json(report_dir / "review_manifest.json", manifest)
    return {"report": str(report_path), "manifest": str(report_dir / "review_manifest.json"), "unresolved_numbers": unresolved, "value_count": len(index)}


def _render_index(index: list[dict]) -> str:
    rows = ["section,label,json_path,text"]
    for entry in index:
        text = str(entry["text"]).replace(",", ";")
        rows.append(f"{entry['section']},{entry['label']},{entry['json_path']},{text}")
    return "\n".join(rows) + "\n"


TABLE_HEADERS = (
    ("dataset", "rows", "positives", "negatives", "ROC-AUC", "Brier", "AUC status"),
    ("decile", "rows", "mean predicted", "observed default rate", "absolute gap"),
    ("", "actual default", "actual no default"),
    ("signal", "PSI", "state"),
    ("attribute", "group", "rows", "positives", "TPR", "TPR status", "FPR", "FPR status"),
)


DELIMITER_CELL = re.compile(r"^:?-+:?$")


BLOCKQUOTE_MARKER = re.compile(r"^ {0,3}> ?")
LIST_MARKER = re.compile(r"^ {0,3}(?:[-+*]|\d{1,9}[.)])(?: +|$)")
ATX_HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|$)")
CODE_FENCE = re.compile(r"^ {0,3}(?:`{3,}|~{3,})")
THEMATIC_BREAK = re.compile(r"^ {0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$")


def _split_cells(content: str) -> list[str]:
    """Split one table line into cells the way GFM does.

    A pipe preceded by a backslash is part of the cell (and renders as ``|``), the
    leading and trailing pipes are optional, and a line without any pipe is a
    single cell.
    """

    stripped = content.strip()
    parts: list[str] = []
    current: list[str] = []
    previous = ""
    for character in stripped:
        if character == "|" and previous != "\\":
            parts.append("".join(current))
            current = []
        else:
            current.append(character)
        previous = character
    parts.append("".join(current))
    if stripped.startswith("|"):
        parts = parts[1:]
    if len(stripped) > 1 and stripped.endswith("|") and stripped[-2] != "\\" and parts:
        parts = parts[:-1]
    elif stripped == "|":
        parts = []
    return [part.replace("\\|", "|").strip() for part in parts]


def _line_variants(line: str) -> tuple[str, str]:
    """Return the line without block-quote markers, and without any container marker.

    The cell check must see at least every table a GFM renderer would show; a
    table inside a block quote or list item is still rendered, so hiding a second
    copy there must not make it invisible. Seeing a superset only ever makes the
    check stricter (an extra copy is reported as a duplicate), so a line that a
    renderer could read either as a list item or as table text is tried both ways.
    """

    content = line.expandtabs(4)
    quoted_only: str | None = None
    while True:
        quoted = BLOCKQUOTE_MARKER.match(content)
        if quoted:
            content = content[quoted.end():]
            continue
        if quoted_only is None:
            quoted_only = content.strip()
        if THEMATIC_BREAK.match(content):
            return quoted_only, content.strip()
        listed = LIST_MARKER.match(content)
        if listed:
            content = content[listed.end():]
            continue
        return quoted_only, content.strip()


def _ends_table_body(content: str) -> bool:
    """True when a line certainly closes a GFM table body.

    GFM keeps every following line as a table row until a blank line or the start
    of another block. Only the starts that cannot themselves be rows are treated as
    terminators here; anything else is kept as a row, so a forged row can never be
    dropped by the parser while a renderer still shows it.
    """

    return (
        content == ""
        or bool(ATX_HEADING.match(content))
        or bool(CODE_FENCE.match(content))
        or bool(THEMATIC_BREAK.match(content))
    )


def _delimiter_row(content: str) -> list[str] | None:
    if "|" not in content:
        return None
    cells = _split_cells(content)
    if cells and all(DELIMITER_CELL.match(cell) for cell in cells):
        return cells
    return None


def _table_header(header_line: tuple[str, str], delimiter_line: tuple[str, str]) -> list[str] | None:
    """The header cells when the two lines open a table under any reading."""

    for header_content in dict.fromkeys(header_line):
        if header_content == "" or _ends_table_body(header_content):
            continue
        header = _split_cells(header_content)
        for delimiter_content in dict.fromkeys(delimiter_line):
            delimiter = _delimiter_row(delimiter_content)
            if delimiter is not None and len(delimiter) == len(header):
                return header
    return None


def parse_markdown_tables(text: str) -> list[dict]:
    """Return every table as a GitHub Flavored Markdown renderer would show it.

    * A table starts at a header line followed by a delimiter row with the same
      number of cells; outer pipes are optional and ``\\|`` does not split cells.
    * The body runs until a blank line or another block start. A body row with
      fewer cells than the header is padded with empty cells, and excess cells are
      dropped, exactly as GFM renders them; a row is never discarded for having the
      "wrong" width.
    * Tables nested in block quotes or list items are reported as well.
    """

    variants = [_line_variants(line) for line in text.splitlines()]
    contents = [stripped for _quoted, stripped in variants]
    tables: list[dict] = []
    index = 0
    while index < len(contents) - 1:
        header = _table_header(variants[index], variants[index + 1])
        if header is None:
            index += 1
            continue
        width = len(header)
        rows: list[list[str]] = []
        cursor = index + 2
        while cursor < len(contents) and not _ends_table_body(contents[cursor]):
            cells = _split_cells(contents[cursor])
            rows.append((cells + [""] * width)[:width])
            cursor += 1
        tables.append({"header": header, "rows": rows})
        index = cursor
    return tables


def expected_tables(metrics: dict) -> list[dict]:
    """Rebuild every report table from the metrics JSON with the trusted renderer."""

    renderer = Renderer(metrics)
    rendered = [
        performance_table(renderer),
        calibration_table(renderer),
        confusion_table(renderer),
        stability_table(renderer),
        fairness_table(renderer),
    ]
    return parse_markdown_tables("\n\n".join(rendered))


ROW_KEY_COLUMNS = {"attribute": 2}


def row_key_width(header: list[str]) -> int:
    """How many leading cells identify a row (the fairness table needs two)."""

    return ROW_KEY_COLUMNS.get(header[0], 1) if header else 1


def row_key(row: list[str], width: int) -> tuple:
    return tuple(cell for cell in row[:width])


def format_row_key(key: tuple) -> str:
    return "/".join(key)


def verify_report_cells(run_dir: Path, metrics: dict | None = None) -> list[str]:
    """Compare each table cell in the report with a fresh render of the metrics.

    Table identity is the full header signature and row identity is the row label,
    and both must be unique: otherwise a "wrong row first, correct row last" copy
    would pass because a dict comprehension keeps only the last occurrence.
    """

    report_path = run_dir / "report" / "validation_report.md"
    if not report_path.is_file():
        return ["report missing"]
    metrics = metrics if metrics is not None else (read_json(run_dir / "validation_metrics.json") if (run_dir / "validation_metrics.json").is_file() else None)
    if metrics is None:
        return ["validation_metrics.json missing"]
    try:
        rendered = expected_tables(metrics)
    except (ContractError, KeyError, IndexError, TypeError, ValueError) as error:
        return [f"report tables cannot be re-rendered from the metrics: {error}"]

    problems: list[str] = []
    expected_by_header: dict[tuple, dict] = {}
    for table in rendered:
        key = tuple(table["header"])
        if key in expected_by_header:
            problems.append(f"renderer produced the table {key[0]!r} twice")
            continue
        width = row_key_width(table["header"])
        labels = [row_key(row, width) for row in table["rows"]]
        duplicates = sorted({format_row_key(label) for label in labels if labels.count(label) > 1})
        if duplicates:
            problems.append(f"renderer produced duplicate row labels in table {key[0]!r}: {duplicates}")
        expected_by_header[key] = table
    if problems:
        return problems

    occurrences: dict[tuple, list[dict]] = {}
    for table in parse_markdown_tables(report_path.read_text(encoding="utf-8")):
        key = tuple(table["header"])
        if key in expected_by_header:
            occurrences.setdefault(key, []).append(table)
        else:
            problems.append(f"unexpected table with header {key!r}")

    for key, expected_table in expected_by_header.items():
        label = key[0] if key else str(key)
        found = occurrences.get(key, [])
        if not found:
            problems.append(f"table {label!r}: not found in the report")
            continue
        if len(found) > 1:
            problems.append(f"table {label!r}: appears {len(found)} times, must appear exactly once")
            continue
        table = found[0]
        width = row_key_width(expected_table["header"])
        expected_labels = [row_key(row, width) for row in expected_table["rows"]]
        actual_labels = [row_key(row, width) for row in table["rows"]]
        duplicates = sorted({format_row_key(row_label) for row_label in actual_labels if actual_labels.count(row_label) > 1})
        if duplicates:
            problems.append(f"table {label!r}: duplicate row labels {duplicates} (each row must appear exactly once)")
            continue
        expected_rows = dict(zip(expected_labels, expected_table["rows"]))
        actual_rows = dict(zip(actual_labels, table["rows"]))
        for row_label, row in expected_rows.items():
            shown = format_row_key(row_label)
            found_row = actual_rows.get(row_label)
            if found_row is None:
                problems.append(f"table {label!r}: row {shown!r} missing")
                continue
            if len(found_row) != len(row):
                problems.append(f"table {label!r} row {shown!r}: {len(found_row)} cells, expected {len(row)}")
                continue
            for index, (want, got) in enumerate(zip(row, found_row)):
                if want != got:
                    column = expected_table["header"][index] if index < len(expected_table["header"]) else str(index)
                    problems.append(f"table {label!r} row {shown!r} column {column!r}: report has {got!r}, metrics render {want!r}")
        for row_label in actual_rows:
            if row_label not in expected_rows:
                problems.append(f"table {label!r}: unexpected row {format_row_key(row_label)!r}")
    return problems


def require_report_cells(run_dir: Path) -> None:
    problems = verify_report_cells(run_dir)
    if problems:
        raise ContractError("Report cells do not match validation_metrics.json: " + "; ".join(problems[:5]))


def text_matches_value(value, text: str) -> bool:
    """True when ``text`` is one of the renderer's faithful renderings of ``value``.

    Accepted forms are exactly the ones ``Renderer.path`` can emit: the canonical
    fixed/scientific/17-significant-digit renderings, the plain integer form, the
    empty marker, and a key of the object the path resolves to (used for group
    labels).
    """

    if value is None:
        return text in {"—", "not assessable", ""}
    if isinstance(value, bool):
        return text == ("true" if value else "false")
    if isinstance(value, int):
        return text == str(value)
    if isinstance(value, float):
        if text in {"—", "not assessable"}:
            return False
        return text in {f"{value:.4f}", f"{value:.3e}", f"{value:.0e}", f"{value:.17g}", str(value)}
    if isinstance(value, dict):
        return text in value
    if isinstance(value, list):
        return text in {str(item) for item in value}
    return text == str(value)


def index_mismatches(run_dir: Path, metrics: dict | None = None) -> list[str]:
    """Re-resolve every values_index.csv row against the metrics JSON.

    This is the check a reviewer performs by hand: read the path, read the
    recorded text, and confirm the JSON really holds that value at that
    precision. Duplicate paths are allowed only when they repeat the same text.
    """

    index_path = run_dir / "report" / "values_index.csv"
    if not index_path.is_file():
        return ["values index missing"]
    metrics = metrics if metrics is not None else read_json(run_dir / "validation_metrics.json")
    problems: list[str] = []
    seen: dict[str, set[str]] = {}
    with index_path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return ["values index has no rows"]
    for row in rows:
        path = (row.get("json_path") or "").strip()
        text = row.get("text") or ""
        if not path:
            problems.append("values index row without a json_path")
            continue
        try:
            value = resolve(metrics, path)
        except (ContractError, KeyError, IndexError, ValueError, TypeError):
            problems.append(f"{path}: path does not resolve in validation_metrics.json")
            continue
        if not text_matches_value(value, text):
            problems.append(f"{path}: index text {text!r} does not match the metrics value {value!r}")
        # Repeated paths are fine when they repeat the same rendering; a container
        # value may also contribute several distinct keys (group labels). Anything
        # else is a contradiction.
        previous = seen.setdefault(path, set())
        if previous and text not in previous and not isinstance(value, (dict, list)):
            problems.append(f"{path}: contradictory index rows {sorted(previous)!r} and {text!r}")
        previous.add(text)
    return problems


def index_not_in_report(report_text: str, run_dir: Path) -> list[str]:
    """Every indexed rendering must actually appear in the report body."""

    index_path = run_dir / "report" / "values_index.csv"
    if not index_path.is_file():
        return ["values index missing"]
    missing = []
    with index_path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            text = row.get("text") or ""
            if text and text not in report_text:
                missing.append(f"{row.get('json_path')}: {text!r} is not in the report")
    return missing


def verify_provenance(report_text: str, index: list[dict]) -> list[str]:
    """Return numeric tokens in the Markdown that no recorded path produced."""

    known = set()
    for entry in index:
        known.update(NUMBER.findall(str(entry["text"])))
    return sorted({token for token in NUMBER.findall(report_text) if token not in known})


BOUND_REPORT_FILES = (
    ("report", "report/validation_report.md", "report_sha256"),
    ("metrics", "validation_metrics.json", "metrics_sha256"),
    ("values index", "report/values_index.csv", "values_index_sha256"),
    ("tables", "report/validation_tables.md", "tables_sha256"),
)


def _matches_rendered_markdown(actual: str, rendered: str) -> bool:
    """Accept equivalent pipe framing on the generated table lines only."""

    actual_lines, rendered_lines = actual.split("\n"), rendered.split("\n")
    if len(actual_lines) != len(rendered_lines):
        return False
    for line, expected in zip(actual_lines, rendered_lines):
        if line == expected:
            continue
        if not expected.startswith("|") or line.expandtabs(4).startswith("    "):
            return False
        if _split_cells(line) != _split_cells(expected):
            return False
    return True


def report_content_problems(run_dir: Path, run_id: str) -> tuple[list[str], dict | None]:
    """Every check that must hold before a report may be reviewed or published.

    Deliberately excludes the Gate C decision itself so the approval path can use
    it without being circular.
    """

    manifest_path = run_dir / "report" / "review_manifest.json"
    report_path = run_dir / "report" / "validation_report.md"
    if not manifest_path.is_file() or not report_path.is_file():
        return ["report not generated"], None
    manifest = read_json(manifest_path)
    reasons: list[str] = []
    if manifest.get("run_id") != run_id:
        reasons.append("review manifest run_id mismatch")
    if not manifest.get("value_count"):
        reasons.append("review manifest records no rendered values")
    bound = list(BOUND_REPORT_FILES)
    summary = manifest.get("agent_summary")
    if summary == "report/agent_summary.json":
        bound.append(("agent summary", summary, "agent_summary_sha256"))
    elif summary is not None:
        reasons.append("review manifest has an unexpected agent summary path")
    for label, relative, key in bound:
        path = run_dir / relative
        recorded = manifest.get(key)
        if not path.is_file():
            reasons.append(f"{label} missing")
            continue
        if not isinstance(recorded, str) or not recorded:
            reasons.append(f"{label} is not bound in the manifest")
            continue
        if sha256_file(path) != recorded:
            reasons.append(f"{label} changed after the report was rendered")
    if manifest.get("unresolved_numbers"):
        reasons.append("report contains numbers without a metrics path")
    reasons.extend(f"report cell mismatch: {problem}" for problem in verify_report_cells(run_dir))
    index_path = run_dir / "report" / "values_index.csv"
    metrics_path = run_dir / "validation_metrics.json"
    report_text = report_path.read_text(encoding="utf-8")
    if index_path.is_file() and metrics_path.is_file():
        reasons.extend(index_mismatches(run_dir))
        reasons.extend(index_not_in_report(report_text, run_dir))
    if reasons:
        return reasons, manifest

    # The document is generated, so compare the whole output. Recognised table
    # cells alone cannot account for markup or figures added elsewhere.
    try:
        rendered, tables, index = _render_markdown(
            read_json(metrics_path), run_id, read_json(run_dir / summary) if summary else None,
            manifest["inventory_gate_a"],
        )
    except (AttributeError, KeyError, IndexError, TypeError, ValueError) as error:
        return [f"report cannot be re-rendered from its inputs: {error}"], manifest
    if not _matches_rendered_markdown(report_text, rendered):
        reasons.append("report Markdown differs from the generated report")
    if not _matches_rendered_markdown((run_dir / "report" / "validation_tables.md").read_text(encoding="utf-8"), tables):
        reasons.append("validation tables Markdown differs from the generated tables")
    if manifest["value_count"] != len(index) or index_path.read_text(encoding="utf-8") != _render_index(index):
        reasons.append("values index differs from the generated index")
    return reasons, manifest


def _pre_approval(run_dir: Path, run_id: str) -> tuple[list[str], str, dict | None]:
    reasons, manifest = report_content_problems(run_dir, run_id)
    if manifest is None:
        return reasons, "NOT_REVIEWED", None
    decision = current_decision(run_dir, run_id, "Gate_C", run_dir / "report" / "review_manifest.json")
    if decision != "APPROVED":
        reasons.append(f"Gate_C={decision}")
    return reasons, decision, manifest


def report_status(run_dir: Path, run_id: str) -> dict:
    reasons, decision, manifest = _pre_approval(run_dir, run_id)
    approval_path = run_dir / "report" / "approval.json"
    if manifest is not None:
        if not approval_path.is_file():
            reasons.append("approval record not written")
        else:
            approval = read_json(approval_path)
            if approval.get("report_sha256") != manifest.get("report_sha256") or approval.get("metrics_sha256") != manifest.get("metrics_sha256"):
                reasons.append("approval does not cover the current report and metrics")
    return {"status": "APPROVED" if not reasons else "DRAFT", "reasons": reasons, "gate_c": decision}


def write_approval(run_dir: Path, run_id: str) -> dict:
    reasons, _decision, _manifest = _pre_approval(run_dir, run_id)
    if reasons:
        raise GateError("Report cannot be marked APPROVED: " + "; ".join(reasons))
    manifest = read_json(run_dir / "report" / "review_manifest.json")
    reviews = read_json(run_dir / "review_log.json")["reviews"]
    gate_c = [entry for entry in reviews if entry["gate"] == "Gate_C" and entry["decision"] == "APPROVED"][-1]
    approval = {
        "schema_version": "1",
        "run_id": run_id,
        "status": "APPROVED",
        "report_sha256": manifest["report_sha256"],
        "metrics_sha256": manifest["metrics_sha256"],
        "review_manifest_sha256": sha256_file(run_dir / "report" / "review_manifest.json"),
        "reviewer": gate_c["reviewer"],
        "reviewed_at": gate_c["timestamp"],
        "approved_at": utc_now(),
    }
    write_json(run_dir / "report" / "approval.json", approval)
    append_jsonl(run_dir / "report" / "report_audit.jsonl", {"schema_version": "1", "run_id": run_id, "event": "REPORT_APPROVED", "report_sha256": approval["report_sha256"], "timestamp": approval["approved_at"]})
    return approval
