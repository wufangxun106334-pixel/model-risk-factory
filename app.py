"""Model Risk Factory - Streamlit demo (four pages, SOP section 11).

Run:  .venv/bin/python -m pip install -r requirements-ui.txt
      .venv/bin/streamlit run app.py

The UI is a thin shell over the CLI. It reads run artifacts through
``src.ui_data`` and executes every action with ``python -m src.cli``, so gates,
hash bindings and the command log are identical to the CLI path. The reviewer
field is a self-declared local label, not an authenticated identity.
"""

from __future__ import annotations

import json
import shlex

import pandas as pd
import streamlit as st

from src import ui_charts, ui_data

st.set_page_config(page_title="Model Risk Factory", layout="wide")

PAGES = ["1 · Inventory", "2 · Model detail", "3 · Migration", "4 · Validation report"]
STATUS_ICON = {"APPROVED": "✅", "REJECTED": "⛔", "NOT_REVIEWED": "⏳", "NOT_RUN": "—", "INVALIDATED": "⚠️"}


def is_dark() -> bool:
    try:
        return st.context.theme.type == "dark"
    except AttributeError:
        return False


def table_view(frame: pd.DataFrame, label: str = "Data table") -> None:
    """Every chart has a table view (accessibility relief and exact values)."""

    with st.expander(label):
        st.dataframe(frame, hide_index=True, width="stretch")


def parity_section(stage: str, attempt: int | None = None) -> None:
    summary = ui_data.parity_summary(RUN_DIR, stage, attempt)
    frame = ui_data.parity_frame(RUN_DIR, stage, attempt)
    if summary is None and frame is None:
        st.info(f"No {stage} parity yet." + (" Run the dev tests first." if stage == "dev" else " Runs after freeze + Holdout acceptance."))
        return
    if summary:
        cols = st.columns(5)
        cols[0].metric("Status", f"{'✅' if summary.get('status') == 'PASS' else '⛔'} {summary.get('status')}")
        cols[1].metric("Rows compared", f"{summary.get('n', summary.get('baseline_row_count', '—'))}")
        cols[2].metric("Max |diff|", f"{summary.get('max_abs_diff', float('nan')):.2e}" if isinstance(summary.get("max_abs_diff"), (int, float)) else "—")
        cols[3].metric("Class mismatches", summary.get("classification_mismatch_count", "—"))
        cols[4].metric("Behaviour mismatches", summary.get("behaviour_mismatch_count", "—"))
    if frame is not None:
        st.altair_chart(ui_charts.parity_scatter(frame, is_dark()), width="stretch")
        st.caption("Each point is one client. Points on the dashed diagonal mean R and Python give the same probability.")
        table_view(frame.sort_values("abs_diff", ascending=False).head(200), "Largest differences (top 200)")


def metrics_dashboard(metrics: dict) -> None:
    dark = is_dark()
    performance = pd.DataFrame(ui_data.performance_rows(metrics))
    st.subheader("Performance")
    if not performance.empty:
        cols = st.columns(len(performance))
        for col, row in zip(cols, performance.to_dict("records")):
            auc = row["roc_auc"]
            brier = row["brier_score"]
            col.metric(f"ROC-AUC · {row['dataset']}", f"{auc:.4f}" if auc is not None else row["roc_auc_status"],
                       help=f"{row['rows']} rows, {row['defaults']} defaults")
            col.caption(f"Brier {brier:.4f}" if brier is not None else f"Brier {row['brier_status']}")
        table_view(performance)
    left, right = st.columns([3, 2])
    with left:
        st.markdown("**Calibration (deciles)** — closer to the dashed diagonal is better")
        calibration = pd.DataFrame(ui_data.calibration_rows(metrics))
        if calibration.empty:
            st.info("No calibration table.")
        else:
            st.altair_chart(ui_charts.calibration_chart(calibration, dark), width="stretch")
            table_view(calibration)
    with right:
        st.markdown("**Confusion matrix · Holdout**")
        confusion = pd.DataFrame(ui_data.confusion_rows(metrics, "holdout"))
        if confusion.empty:
            st.info("No Holdout confusion matrix.")
        else:
            st.altair_chart(ui_charts.confusion_chart(confusion, dark), width="stretch")
            st.caption(f"Threshold {metrics.get('threshold')}")
            table_view(confusion)

    st.subheader("Stability (drift)")
    psi = pd.DataFrame(ui_data.psi_rows(metrics))
    if psi.empty:
        st.info("No PSI results.")
    else:
        st.altair_chart(ui_charts.psi_chart(psi, ui_data.psi_thresholds(metrics), dark), width="stretch")
        table_view(psi)

    st.subheader("Fairness (audit only, not model inputs)")
    fairness = pd.DataFrame(ui_data.fairness_rows(metrics))
    if fairness.empty:
        st.info("No fairness results.")
    else:
        st.altair_chart(ui_charts.fairness_chart(fairness, dark), width="stretch")
        low = fairness[fairness["sample_status"] != "OK"]
        if not low.empty:
            st.warning("Small-sample groups: " + ", ".join(sorted(set(low["attribute"] + "=" + low["group"]))))
        table_view(fairness)


def badge(decision: str) -> str:
    return f"{STATUS_ICON.get(decision, '•')} {decision}"


def show_result(result: dict) -> None:
    st.code(" ".join(shlex.quote(part) for part in result["command"]), language="bash")
    (st.success if result["returncode"] == 0 else st.error)(f"exit code {result['returncode']}")
    output = result["stdout"].strip()
    if output:
        try:
            st.json(json.loads(output), expanded=False)
        except ValueError:
            st.code(output[-6000:])
    if result["stderr"].strip():
        st.code(result["stderr"].strip()[-4000:])


def action(label: str, args: list[str], key: str, *, help_text: str | None = None, confirm: str | None = None) -> None:
    """Button that runs one CLI command; ``confirm`` adds a mandatory checkbox."""

    allowed = True
    if confirm:
        allowed = st.checkbox(confirm, key=f"{key}-confirm")
    if st.button(label, key=key, help=help_text, disabled=not allowed):
        with st.spinner(f"Running {args[0]} ..."):
            st.session_state["last_result"] = ui_data.run_cli(args, ROOT)
        st.rerun()


def review_form(gate: str, sha256: str, key: str, *, model: str | None = None, attempt: int | None = None) -> None:
    with st.form(key):
        st.caption(f"Artifact hash under review (full SHA-256): `{sha256}`")
        reviewer = st.text_input("Reviewer", placeholder="your name, or agent-delegated")
        decision = st.radio("Decision", ["APPROVED", "REJECTED"], horizontal=True)
        comment = st.text_area("Comment", placeholder="What you checked: sources, line numbers, hashes, Unknowns, conflicts ...")
        submitted = st.form_submit_button(f"Record {gate} decision")
    if submitted:
        try:
            args = ui_data.approve_args(RUN_ID, gate, sha256, reviewer, comment, decision, model=model, attempt=attempt)
        except ValueError as error:
            st.error(str(error))
            return
        st.session_state["last_result"] = ui_data.run_cli(args, ROOT)
        st.rerun()


# ---------------------------------------------------------------- sidebar
st.sidebar.title("Model Risk Factory")
root_name = st.sidebar.radio("Runs root", ["dev_runs", "runs"], help="dev_runs = synthetic dry runs; runs = formal runs (single-use Holdout)")
ROOT = ui_data.runs_root(root_name)
runs = ui_data.list_runs(ROOT)
run_ids = [row["run_id"] for row in runs]
def progress(run_id: str) -> int:
    """Number of model inventories in a run (0-3): a cheap signal of how far it got."""

    directory = ROOT / run_id
    return int((directory / "model_inventory.json").is_file()) + len(list((directory / "inventories").glob("*.json")))


PROGRESS = {run_id: progress(run_id) for run_id in run_ids}
STATES = {row["run_id"]: row["state"] for row in runs}
# Default to the newest run that has work in it, not an empty run that was just initialised.
default_index = next((index for index, run_id in enumerate(run_ids) if PROGRESS[run_id]), 0) if run_ids else None
RUN_ID = st.sidebar.selectbox(
    "Run", run_ids, index=default_index, placeholder="no runs yet",
    format_func=lambda run_id: f"{run_id} · {PROGRESS[run_id]}/3 inventories · {STATES.get(run_id)}",
)
page = st.sidebar.radio("Page", PAGES)

with st.sidebar.expander("New run"):
    if root_name == "runs":
        # Formal runs must start from a clean commit with the approved UCI ZIP; the UI does not create them.
        st.caption("Formal runs are created from the CLI on a clean commit: `init-run --mode uci`, then `prepare --uci ...`. Use dev_runs for dry runs.")
    elif st.button("init-run (synthetic dry run)"):
        st.session_state["last_result"] = ui_data.run_cli(["init-run", "--mode", "synthetic"], ROOT)
        st.rerun()

st.sidebar.caption("Reviewer names are self-declared labels. Every action runs `python -m src.cli`.")

if "last_result" in st.session_state:
    with st.expander("Last command", expanded=True):
        show_result(st.session_state["last_result"])
        if st.button("Clear"):
            del st.session_state["last_result"]
            st.rerun()

if RUN_ID is None:
    st.info(f"No runs under `{ROOT.name}/`. Create one from the sidebar (New run).")
    st.stop()

RUN_DIR = ROOT / RUN_ID
WITH_WORK = [run_id for run_id in run_ids if PROGRESS[run_id]]
if PROGRESS[RUN_ID] == 0:
    st.warning(
        f"`{RUN_ID}` is an empty run (no model inventories yet). "
        + (f"Runs with results in `{ROOT.name}/`: " + ", ".join(f"`{run_id}`" for run_id in WITH_WORK[:3])
           if WITH_WORK else f"No run in `{ROOT.name}/` has inventories yet; try the other runs root.")
    )
models = ui_data.model_rows(RUN_DIR, RUN_ID)

# ---------------------------------------------------------------- page 1
if page == PAGES[0]:
    st.header("Model inventory")
    st.caption(f"Run `{RUN_ID}` in `{ROOT.name}/`")
    st.dataframe(pd.DataFrame([{
        "model_id": row["model_id"],
        "scope": "migrate to Python" if row["migrated"] else "document only",
        "inventory": "yes" if row["exists"] else "missing",
        "Gate A": badge(row["gate_a"]),
        "sources": row.get("sources"),
        "conflicts": row.get("conflicts"),
        "unknowns": row.get("unknowns"),
    } for row in models]), hide_index=True, width="stretch")
    if any(row["gate_a"] == "INVALIDATED" for row in models):
        st.warning("INVALIDATED: `src/`, `tests/` or `config/` changed since this run was created, so earlier approvals no longer apply. Start a new run.")

    st.subheader("Run history")
    st.dataframe(pd.DataFrame(runs), hide_index=True, width="stretch")

    st.subheader("Pipeline steps")
    cols = st.columns(4)
    steps = [
        ("check-provider", "API smoke test"),
        ("prepare", "Split data"),
        ("baseline", "R baseline"),
        ("reference-parity", "Reference parity"),
        ("fixture-parity", "Fixture parity"),
        ("mutation-check", "Deliberate error"),
        ("docker-boundary", "Container limits"),
        ("failure-drills", "Failure drills"),
    ]
    for index, (command, label) in enumerate(steps):
        with cols[index % 4]:
            args = [command, "--run-id", RUN_ID]
            if command == "prepare":
                args += ["--synthetic"] if root_name == "dev_runs" else []
                if root_name == "runs":
                    st.caption("Formal `prepare --uci` needs the approved ZIP and hash: run it from the CLI.")
                    continue
            action(label, args, key=f"step-{command}")

# ---------------------------------------------------------------- page 2
elif page == PAGES[1]:
    st.header("Model detail and Gate A")
    model_id = st.selectbox("Model", ui_data.MODEL_IDS)
    row = next(item for item in models if item["model_id"] == model_id)
    action(f"Extract inventory for {model_id} (Agent)", ["extract-inventory", "--run-id", RUN_ID, "--model", model_id], key="extract")
    if not row["exists"]:
        st.info("No inventory yet for this model.")
        st.stop()
    inventory = row["inventory"]
    st.markdown(f"**Gate A:** {badge(row['gate_a'])}")
    left, right = st.columns(2)
    with left:
        st.metric("Code threshold", inventory.get("code_threshold"))
        st.metric("Documented threshold", inventory.get("documented_threshold"))
        st.write("**Model type:**", inventory.get("model_type"))
        st.write("**Owner:**", inventory.get("owner"), " · **Training date:**", inventory.get("training_date"))
        st.write("**Feature order:**", ", ".join(inventory.get("feature_order") or []))
    with right:
        st.write("**Conflicts**")
        st.dataframe(pd.DataFrame(inventory.get("conflicts") or []), hide_index=True, width="stretch")
        st.write("**Unknowns**")
        st.dataframe(pd.DataFrame({"unknown": inventory.get("unknowns") or []}), hide_index=True, width="stretch")
    st.write("**Sources** (check line ranges and SHA-256 against the legacy files)")
    st.dataframe(pd.DataFrame(inventory.get("sources") or []), hide_index=True, width="stretch")
    with st.expander("Full inventory JSON (read all of it before approving)"):
        st.json(inventory)
    review_form("Gate_A", row["artifact_sha256"], key=f"gate-a-{model_id}", model=model_id)

# ---------------------------------------------------------------- page 3
elif page == PAGES[2]:
    st.header("Migration of MDL_CREDIT_V1 (R → Python)")
    gate_a = next(item for item in models if item["migrated"])["gate_a"]
    st.markdown(f"Gate A for MDL_CREDIT_V1: {badge(gate_a)}")
    candidates = ui_data.candidate_rows(RUN_DIR, RUN_ID)
    next_attempt = len(candidates)
    if next_attempt <= 2:
        action(f"Generate candidate attempt {next_attempt} (Agent)",
               ["generate-candidate", "--run-id", RUN_ID, "--attempt", str(next_attempt)], key="generate",
               help_text="Initial generation plus at most two repairs")
    else:
        st.info("Repair limit reached (initial + 2 repairs).")
    if not candidates:
        st.stop()
    st.dataframe(pd.DataFrame([{
        "attempt": item["attempt"], "Gate B": badge(item["gate_b"]),
        "candidate_sha256": item["candidate_sha256"], "dev": item["dev_status"],
    } for item in candidates]), hide_index=True, width="stretch")
    attempt = st.selectbox("Attempt", [item["attempt"] for item in candidates], index=len(candidates) - 1)
    chosen = next(item for item in candidates if item["attempt"] == attempt)
    code_tab, diff_tab = st.tabs(["Candidate source", "Diff"])
    with code_tab:
        st.code(chosen["source"].read_text(encoding="utf-8"), language="python")
    with diff_tab:
        st.code(chosen["diff"].read_text(encoding="utf-8") if chosen["diff"].is_file() else "(no diff)", language="diff")
    review_form("Gate_B", chosen["candidate_sha256"], key=f"gate-b-{attempt}", attempt=attempt)

    st.subheader("Execute (Docker, after Gate B)")
    cols = st.columns(4)
    with cols[0]:
        action("Run dev tests", ["run-dev", "--run-id", RUN_ID, "--attempt", str(attempt)], key="run-dev")
    with cols[1]:
        action("Candidate fixtures", ["candidate-fixtures", "--run-id", RUN_ID, "--attempt", str(attempt)], key="fixtures")
    with cols[2]:
        action("Freeze candidate", ["freeze", "--run-id", RUN_ID, "--attempt", str(attempt)], key="freeze")
    with cols[3]:
        action("Holdout acceptance", ["accept", "--run-id", RUN_ID], key="accept",
               confirm="I understand the Holdout is consumed once and cannot be re-run")

    st.subheader("Results: R vs Python parity")
    dev_tab, holdout_tab = st.tabs([f"Dev · attempt {attempt}", "Holdout (frozen candidate)"])
    with dev_tab:
        parity_section("dev", attempt)
    with holdout_tab:
        parity_section("holdout")

# ---------------------------------------------------------------- page 4
else:
    st.header("Validation report and Gate C")
    paths = ui_data.report_paths(RUN_DIR)
    cols = st.columns(4)
    with cols[0]:
        action("Compute metrics", ["validation-metrics", "--run-id", RUN_ID], key="metrics")
    with cols[1]:
        action("Agent summary", ["agent-summary", "--run-id", RUN_ID], key="summary")
    with cols[2]:
        action("Render report", ["report", "--run-id", RUN_ID], key="report")
    with cols[3]:
        action("Report status", ["report-status", "--run-id", RUN_ID], key="report-status")

    metrics = ui_data.load_metrics(RUN_DIR)
    if metrics is None:
        st.info("No validation metrics yet. Freeze the candidate, run Holdout acceptance, then Compute metrics.")
    else:
        st.caption(f"`validation_metrics.json` · model {metrics.get('model_id')} · candidate `{str(metrics.get('candidate_sha256'))[:12]}…` · generated {metrics.get('generated_at')}")
        metrics_dashboard(metrics)

    st.subheader("Report and Gate C")
    gate_c = ui_data.gate_c_state(RUN_DIR, RUN_ID)
    st.markdown(f"**Gate C:** {badge(gate_c['decision'])}")
    if paths["report"].is_file():
        report_tab, tables_tab = st.tabs(["Report", "Tables"])
        with report_tab:
            st.markdown(paths["report"].read_text(encoding="utf-8"))
        with tables_tab:
            if paths["tables"].is_file():
                st.markdown(paths["tables"].read_text(encoding="utf-8"))
    else:
        st.info("No report yet. Compute metrics, then the Agent summary, then render the report.")
    if gate_c["exists"]:
        review_form("Gate_C", gate_c["artifact_sha256"], key="gate-c")
        action("Write approval (approve-report)", ["approve-report", "--run-id", RUN_ID], key="approve-report")

    st.subheader("Export and acceptance")
    cols = st.columns(2)
    with cols[0]:
        action("Export evidence", ["export", "--run-id", RUN_ID], key="export")
    with cols[1]:
        action("Evaluate acceptance", ["acceptance", "--run-id", RUN_ID], key="acceptance")
    approved, records = ui_data.acceptance_records(RUN_DIR)
    if records:
        st.markdown(f"**release_approved (this run):** {approved}. A formal release also needs `release-check` → APPROVED on the release commit.")
        st.dataframe(pd.DataFrame(records), hide_index=True, width="stretch")

    st.subheader("Downloads")
    for path in ui_data.downloads(RUN_DIR, RUN_ID):
        st.download_button(f"Download {path.name}", path.read_bytes(), file_name=path.name, key=f"dl-{path.name}")
