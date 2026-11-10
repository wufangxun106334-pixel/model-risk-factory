"""Altair charts for the Streamlit demo.

Palette: the validated reference palette of the dataviz method. Datasets use
categorical slots 1-3 in fixed order (dev, holdout, shifted), which pass the
all-pairs CVD and normal-vision checks in light and dark mode. Aqua is below 3:1
on the light surface, so every chart ships with a data table (relief rule) and
datasets also differ by point shape. PSI states use the reserved status colors
and always carry a text label.
"""

from __future__ import annotations

import altair as alt
import pandas as pd

LIGHT = {
    "series": ["#2a78d6", "#eb6834", "#1baf7a"],
    "text": "#0b0b0b", "muted": "#52514e", "grid": "#e4e3df", "reference": "#8a8984",
    "sequential": ["#cde2fb", "#1c5cab"],
}
DARK = {
    "series": ["#3987e5", "#d95926", "#199e70"],
    "text": "#f0efec", "muted": "#c3c2b7", "grid": "#3a3a38", "reference": "#8a8984",
    "sequential": ["#184f95", "#86b6ef"],
}
STATUS = {"OK": "#0ca30c", "REVIEW_HIGHLIGHTED": "#fab219", "REVALIDATION_REQUIRED": "#d03b3b"}
STATUS_LABEL = {"OK": "✓ OK", "REVIEW_HIGHLIGHTED": "! review highlighted", "REVALIDATION_REQUIRED": "✕ revalidation required"}
DATASET_ORDER = ["dev", "holdout", "shifted"]
SHAPES = ["circle", "square", "triangle-up"]

# Parity plots every client (Holdout 1,199 rows, dev 6,000); values are local, so lift the 5,000-row cap.
alt.data_transformers.disable_max_rows()


def palette(dark: bool) -> dict:
    return DARK if dark else LIGHT


def _style(chart: alt.Chart, colors: dict) -> alt.Chart:
    return (
        chart.configure_view(strokeWidth=0)
        .configure_axis(gridColor=colors["grid"], domainColor=colors["grid"], tickColor=colors["grid"],
                        labelColor=colors["muted"], titleColor=colors["muted"], labelFontSize=12, titleFontSize=12)
        .configure_legend(labelColor=colors["text"], titleColor=colors["muted"], orient="top", labelFontSize=12)
        .configure_text(color=colors["text"])
    )


def parity_scatter(frame: pd.DataFrame, dark: bool = False) -> alt.Chart:
    """One series: each client's R probability against the Python probability; the diagonal is exact parity."""

    colors = palette(dark)
    data = frame.dropna(subset=["probability_r", "probability_python"])[["client_id", "probability_r", "probability_python", "abs_diff"]]
    diagonal = alt.Chart(pd.DataFrame({"x": [0.0, 1.0], "y": [0.0, 1.0]})).mark_line(
        color=colors["reference"], strokeDash=[4, 4], strokeWidth=1).encode(x="x:Q", y="y:Q")
    points = alt.Chart(data).mark_circle(size=36, opacity=0.55, color=colors["series"][0]).encode(
        x=alt.X("probability_r:Q", title="R baseline probability", scale=alt.Scale(domain=[0, 1])),
        y=alt.Y("probability_python:Q", title="Python candidate probability", scale=alt.Scale(domain=[0, 1])),
        tooltip=[alt.Tooltip("client_id:N", title="client"),
                 alt.Tooltip("probability_r:Q", title="R", format=".6f"),
                 alt.Tooltip("probability_python:Q", title="Python", format=".6f"),
                 alt.Tooltip("abs_diff:Q", title="|diff|", format=".2e")],
    )
    return _style(alt.layer(diagonal, points).properties(height=380), colors)


def calibration_chart(frame: pd.DataFrame, dark: bool = False) -> alt.Chart:
    colors = palette(dark)
    data = frame.dropna(subset=["mean_probability", "observed_default_rate"])
    present = [name for name in DATASET_ORDER if name in set(data["dataset"])]
    # Colour follows the dataset, never its position among the present series.
    color = alt.Color("dataset:N", title=None, scale=alt.Scale(domain=DATASET_ORDER, range=colors["series"]),
                      legend=alt.Legend(values=present))
    shape = alt.Shape("dataset:N", title=None, scale=alt.Scale(domain=DATASET_ORDER, range=SHAPES), legend=None)
    upper = float(max(data["mean_probability"].max(), data["observed_default_rate"].max(), 0.1)) * 1.05
    diagonal = alt.Chart(pd.DataFrame({"x": [0.0, upper], "y": [0.0, upper]})).mark_line(
        color=colors["reference"], strokeDash=[4, 4], strokeWidth=1).encode(x="x:Q", y="y:Q")
    base = alt.Chart(data).encode(
        x=alt.X("mean_probability:Q", title="Mean predicted probability (decile)", scale=alt.Scale(domain=[0, upper])),
        y=alt.Y("observed_default_rate:Q", title="Observed default rate", scale=alt.Scale(domain=[0, upper])),
        color=color,
    )
    lines = base.mark_line(strokeWidth=2).encode(detail="dataset:N", order="decile:Q")
    hover = alt.selection_point(on="pointerover", fields=["dataset", "decile"], nearest=True, empty=False)
    points = base.mark_point(size=70, filled=True).encode(
        shape=shape,
        size=alt.condition(hover, alt.value(140), alt.value(70)),
        tooltip=[alt.Tooltip("dataset:N"), alt.Tooltip("decile:Q"), alt.Tooltip("rows:Q"),
                 alt.Tooltip("mean_probability:Q", title="predicted", format=".3f"),
                 alt.Tooltip("observed_default_rate:Q", title="observed", format=".3f")],
    ).add_params(hover)
    return _style(alt.layer(diagonal, lines, points).properties(height=360), colors)


def psi_chart(frame: pd.DataFrame, thresholds: dict, dark: bool = False) -> alt.Chart:
    colors = palette(dark)
    data = frame.copy()
    data["state_label"] = data["state"].map(STATUS_LABEL).fillna(data["state"].astype(str))
    data["label"] = data.apply(lambda row: f"{row['psi']:.3f}  {row['state_label']}" if pd.notna(row["psi"]) else str(row["state_label"]), axis=1)
    upper = max(float(data["psi"].max() or 0), thresholds["review"]) * 1.35
    states = list(STATUS)
    y = alt.Y("name:N", title=None, sort=None)
    bars = alt.Chart(data).mark_bar(cornerRadiusEnd=4, height=18).encode(
        x=alt.X("psi:Q", title="Population Stability Index (dev → shifted scenario A)", scale=alt.Scale(domain=[0, upper])),
        y=y,
        color=alt.Color("state:N", title="state", scale=alt.Scale(domain=states, range=[STATUS[name] for name in states]),
                        legend=alt.Legend(labelExpr="{'OK':'✓ OK','REVIEW_HIGHLIGHTED':'! review highlighted','REVALIDATION_REQUIRED':'✕ revalidation required'}[datum.label]")),
        tooltip=[alt.Tooltip("name:N"), alt.Tooltip("psi:Q", format=".4f"), alt.Tooltip("state_label:N", title="state")],
    )
    labels = alt.Chart(data).mark_text(align="left", dx=6, fontSize=12, color=colors["text"]).encode(x="psi:Q", y=y, text="label:N")
    rules = pd.DataFrame({"x": [thresholds["attention"], thresholds["review"]],
                          "text": [f"attention {thresholds['attention']}", f"revalidation {thresholds['review']}"]})
    rule = alt.Chart(rules).mark_rule(color=colors["reference"], strokeDash=[4, 4]).encode(x="x:Q")
    rule_text = alt.Chart(rules).mark_text(align="left", dx=4, dy=-6, fontSize=11, color=colors["muted"]).encode(
        x="x:Q", y=alt.value(0), text="text:N")
    height = max(120, 34 * len(data))
    return _style(alt.layer(rule, bars, labels, rule_text).properties(height=height), colors)


def fairness_chart(frame: pd.DataFrame, dark: bool = False) -> alt.Chart:
    """Dot plot of TPR and FPR per group; one small multiple per audit attribute."""

    colors = palette(dark)
    data = frame.dropna(subset=["value"]).copy()
    data["group_label"] = data.apply(lambda row: f"{row['group']} (ref)" if row["reference"] else str(row["group"]), axis=1)
    color = alt.Color("rate:N", title=None, scale=alt.Scale(domain=["TPR", "FPR"], range=colors["series"][:2]))
    shape = alt.Shape("rate:N", title=None, scale=alt.Scale(domain=["TPR", "FPR"], range=["circle", "square"]), legend=None)
    base = alt.Chart(data).encode(
        x=alt.X("value:Q", title="Rate on Holdout", scale=alt.Scale(domain=[0, 1])),
        y=alt.Y("group_label:N", title=None),
    )
    link = base.mark_rule(color=colors["grid"], strokeWidth=2).encode(detail="group_label:N")
    dots = base.mark_point(size=90, filled=True).encode(
        color=color, shape=shape,
        tooltip=[alt.Tooltip("attribute:N"), alt.Tooltip("group:N"), alt.Tooltip("rate:N"),
                 alt.Tooltip("value:Q", format=".3f"), alt.Tooltip("rows:Q"), alt.Tooltip("sample_status:N", title="sample")],
    )
    return _style(
        alt.layer(link, dots, data=data).properties(height=150).facet(
            row=alt.Row("attribute:N", title=None, header=alt.Header(labelColor=colors["text"], labelFontSize=12))
        ).resolve_scale(y="independent"),
        colors,
    )


def confusion_chart(frame: pd.DataFrame, dark: bool = False) -> alt.Chart:
    colors = palette(dark)
    total = float(frame["count"].sum() or 1)
    data = frame.assign(share=frame["count"] / total)
    data["label"] = data.apply(lambda row: f"{int(row['count']):,}  ({row['share']:.0%})", axis=1)
    base = alt.Chart(data).encode(
        x=alt.X("predicted:N", title=None, sort=["predicted default", "predicted no default"], axis=alt.Axis(orient="top", labelAngle=0)),
        y=alt.Y("actual:N", title=None, sort=["default (1)", "no default (0)"]),
    )
    cells = base.mark_rect(cornerRadius=4, stroke=colors["grid"], strokeWidth=2).encode(
        color=alt.Color("count:Q", legend=None, scale=alt.Scale(range=colors["sequential"])),
        tooltip=[alt.Tooltip("cell:N"), alt.Tooltip("count:Q", format=","), alt.Tooltip("share:Q", format=".1%")],
    )
    midpoint = float(data["count"].max()) / 2
    text = base.mark_text(fontSize=14, fontWeight="bold").encode(
        text="label:N",
        color=alt.condition(alt.datum.count > midpoint, alt.value("#ffffff" if not dark else "#0b0b0b"), alt.value(colors["text"])),
    )
    return _style(alt.layer(cells, text).properties(height=200), colors)
