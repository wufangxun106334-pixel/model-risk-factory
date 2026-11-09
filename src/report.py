"""Report rendering with mechanical value provenance (SOP V2-07).

The Markdown report contains no hand-typed numbers, including inside tables.
Every number is produced by ``Renderer.path()``, which resolves one JSON path in
``validation_metrics.json`` and records the path next to the rendered text.
``verify_provenance()`` then re-reads the finished Markdown and fails when a
numeric token cannot be traced back to a recorded path.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from src.common import ContractError, GateError, append_jsonl, read_json, sha256_file, utc_now, write_json
from src.review import current_decision

NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w.])")
FORBIDDEN_CLAIMS = (
    "regulatory compliant",
    "regulator approved",
    "certified compliant",
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
            renderer.note(f"fairness.attributes.{attribute}.groups.{group}", label=f"{attribute} group label", section="fairness", text=group)
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
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["headline", "results", "limitations", "evidence_gaps"],
        "properties": {
            "headline": {"type": "string"},
            "results": {"type": "array", "items": {"type": "string"}},
            "limitations": {"type": "array", "items": {"type": "string"}},
            "evidence_gaps": {"type": "array", "items": {"type": "string"}},
        },
    }


class AgentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headline: str = Field(min_length=1, max_length=400)
    results: list[str] = Field(min_length=1, max_length=8)
    limitations: list[str] = Field(min_length=1, max_length=8)
    evidence_gaps: list[str] = Field(min_length=1, max_length=8)


def check_wording(text: str) -> None:
    lowered = text.lower()
    for claim in FORBIDDEN_CLAIMS:
        if claim.lower() in lowered:
            raise ContractError(f"Forbidden compliance claim in report text: {claim}")


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
    }


def render_report(run_dir: Path, run_id: str, *, agent_summary: dict | None, inventories: dict) -> dict:
    metrics = read_json(run_dir / "validation_metrics.json")
    if metrics.get("run_id") != run_id:
        raise ContractError("validation_metrics.json belongs to another run")
    renderer = Renderer(metrics)
    report_dir = run_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)

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
    for model_id, artifact in inventories.items():
        lines.append(f"- {model_id}: Gate A status `{artifact}`")
    lines.append(f"- Frozen candidate SHA256: `{renderer.raw('candidate_sha256', label='candidate hash', section='artifact')}`")
    lines.append(f"- Decision threshold: {renderer.path('threshold', label='threshold', section='artifact')}")
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
    else:
        summary_text = " ".join([agent_summary.get("headline", "")] + agent_summary.get("results", []) + agent_summary.get("limitations", []) + agent_summary.get("evidence_gaps", []))
        check_wording(summary_text)
        restated = NUMBER.findall(summary_text)
        if restated:
            raise ContractError(f"Agent summary restates numbers without a metrics path: {restated[:5]}; regenerate it")
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

    report_path = report_dir / "validation_report.md"
    report_text = "\n".join(lines)
    report_path.write_text(report_text, encoding="utf-8")

    index_path = report_dir / "values_index.csv"
    rows = ["section,label,json_path,text"]
    for entry in renderer.index:
        text = str(entry["text"]).replace(",", ";")
        rows.append(f"{entry['section']},{entry['label']},{entry['json_path']},{text}")
    index_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    tables_path = report_dir / "validation_tables.md"
    tables_path.write_text("\n\n".join([
        "# Validation metrics tables",
        "## Performance", performance,
        "## Calibration (holdout)", calibration,
        "## Confusion matrix (holdout)", confusion,
        "## Stability (dev vs scenario A)", stability,
        "## Fairness (holdout)", fairness,
    ]) + "\n", encoding="utf-8")

    unresolved = verify_provenance(report_text, renderer.index)
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
        "value_count": len(renderer.index),
        "unresolved_numbers": unresolved,
        "agent_summary": "report/agent_summary.json" if (report_dir / "agent_summary.json").is_file() else None,
        "agent_summary_sha256": sha256_file(report_dir / "agent_summary.json") if (report_dir / "agent_summary.json").is_file() else None,
        "inventory_gate_a": inventories,
    }
    write_json(report_dir / "review_manifest.json", manifest)
    return {"report": str(report_path), "manifest": str(report_dir / "review_manifest.json"), "unresolved_numbers": unresolved, "value_count": len(renderer.index)}


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


def _pre_approval(run_dir: Path, run_id: str) -> tuple[list[str], str, dict | None]:
    manifest_path = run_dir / "report" / "review_manifest.json"
    report_path = run_dir / "report" / "validation_report.md"
    if not manifest_path.is_file() or not report_path.is_file():
        return ["report not generated"], "NOT_REVIEWED", None
    manifest = read_json(manifest_path)
    reasons: list[str] = []
    if manifest.get("run_id") != run_id:
        reasons.append("review manifest run_id mismatch")
    if not manifest.get("value_count"):
        reasons.append("review manifest records no rendered values")
    bound = list(BOUND_REPORT_FILES)
    if manifest.get("agent_summary"):
        bound.append(("agent summary", manifest["agent_summary"], "agent_summary_sha256"))
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
    decision = current_decision(run_dir, run_id, "Gate_C", manifest_path)
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
