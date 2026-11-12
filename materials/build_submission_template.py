#!/usr/bin/env python3
"""Fill the official EXL x UCD submission template for Challenge 04.

Input : docs/EXL_UCD_Hackathon_Project_Submission_Template - Copy.pptx (left untouched)
Output: materials/EXL_UCD_Submission_Challenge04.pptx

Text is replaced inside the template's own text boxes, keeping the template's
fonts and colours (the first run of each box is the format source). Every
number carries its origin, using the same labels as materials/solution_deck.md:
HIST-UCI (seed 46 formal run, historical), SYN-SEED47 (synthetic drill),
CLIENT-CONTEXT (challenge brief), PENDING.

Build tool only: python-pptx is not in requirements.txt.
Run: .venv/bin/python materials/build_submission_template.py
"""

from __future__ import annotations

import copy
from pathlib import Path

from pptx import Presentation
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "docs" / "EXL_UCD_Hackathon_Project_Submission_Template - Copy.pptx"
OUTPUT = ROOT / "materials" / "EXL_UCD_Submission_Challenge04.pptx"
SCREENS = ROOT / "docs" / "v3" / "ui_screens"
ARCHITECTURE = ROOT / "materials" / "architecture.png"


def shape(slide, shape_id: int):
    for item in slide.shapes:
        if item.shape_id == shape_id:
            return item
    raise KeyError(f"shape {shape_id} not found")


def set_text(slide, shape_id: int, lines, size: float | None = None, bold_first: bool = False) -> None:
    """Replace a text box's content, one paragraph per line, keeping the template's run format."""

    frame = shape(slide, shape_id).text_frame
    frame.word_wrap = True
    paragraphs = frame.paragraphs
    template_p = paragraphs[0]._p
    template_r = template_p.find("{http://schemas.openxmlformats.org/drawingml/2006/main}r")
    body = template_p.getparent()
    for paragraph in paragraphs:
        body.remove(paragraph._p)
    for index, line in enumerate([lines] if isinstance(lines, str) else lines):
        new_p = copy.deepcopy(template_p)
        for child in list(new_p):
            if child.tag.endswith("}r") or child.tag.endswith("}br") or child.tag.endswith("}fld"):
                new_p.remove(child)
        run = copy.deepcopy(template_r) if template_r is not None else None
        end = new_p.find("{http://schemas.openxmlformats.org/drawingml/2006/main}endParaRPr")
        if run is not None:
            if end is not None:
                end.addprevious(run)
            else:
                new_p.append(run)
        body.append(new_p)
    for index, (paragraph, line) in enumerate(zip(frame.paragraphs, [lines] if isinstance(lines, str) else lines)):
        if not paragraph.runs:
            paragraph.add_run()
        paragraph.runs[0].text = line
        if size is not None:
            paragraph.runs[0].font.size = Pt(size)
        if bold_first and index == 0:
            paragraph.runs[0].font.bold = True


def add_text(slide, left, top, width, height, text: str, like_id: int, size: float) -> None:
    """New text box copying the run format of an existing box (used for the link values on slide 6)."""

    reference = shape(slide, like_id)
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    box.text_frame._txBody.getparent().replace(box.text_frame._txBody, copy.deepcopy(reference.text_frame._txBody))
    set_text(slide, box.shape_id, text, size=size)


def picture_in(slide, path: Path, frame_id: int, placeholder_id: int | None = None, pad: float = 0.08) -> None:
    """Fit a picture inside a template frame, keeping its aspect ratio, and drop the placeholder text."""

    frame = shape(slide, frame_id)
    if placeholder_id is not None:
        element = shape(slide, placeholder_id)._element
        element.getparent().remove(element)
    picture = slide.shapes.add_picture(str(path), frame.left, frame.top)
    pad_emu = Inches(pad)
    max_w, max_h = frame.width - 2 * pad_emu, frame.height - 2 * pad_emu
    scale = min(max_w / picture.width, max_h / picture.height)
    picture.width, picture.height = int(picture.width * scale), int(picture.height * scale)
    picture.left = Emu(frame.left + (frame.width - picture.width) // 2)
    picture.top = Emu(frame.top + (frame.height - picture.height) // 2)


def build() -> Path:
    deck = Presentation(str(TEMPLATE))
    s1, s2, s3, s4, s5, s6 = deck.slides

    # ---- Slide 1: team details (team name and leader e-mail stay for the team to fill)
    set_text(s1, 2, ["Model Risk Factory"])
    set_text(s1, 6, "Document, migrate and validate legacy credit models, with a human at every gate.", size=11)
    set_text(s1, 35, "fangxunwu (25208508)")
    set_text(s1, 37, "fangxunwu (25208508), kaiwenyao (25202665)", size=10)
    set_text(s1, 41, "04 · Agentic model risk factory", size=10)

    # ---- Slide 2: problem and USP
    set_text(s2, 10, [
        "A Tier-1 UK bank runs ~250 credit, fraud and pricing models in SAS, R and Python. "
        "Under PRA SS1/23 each needs current documentation and independent validation, yet documents drift "
        "from code and one validation takes 8–12 weeks (CLIENT-CONTEXT, challenge brief).",
        "Who it affects: model owners, model-risk validators and the reviewers who sign off. "
        "Tracks: GenAI & Agents · Predictive Analytics · Responsible AI.",
        "Our prototype: 3 team-built legacy R models on the public UCI credit-default data.",
    ], size=11)
    set_text(s2, 25, "Evidence-bound, not just generated: every inventory fact carries file path, line range, excerpt and SHA-256; Unknowns stay Unknown.", size=10)
    set_text(s2, 29, "Agent drafts, humans approve: Gates A/B/C bind the exact artifact hash; any code or config change invalidates old approvals.", size=10)
    set_text(s2, 33, "Migration proven, not retrained: record-by-record R vs Python parity on a single-use Holdout, plus an auto-built validation report.", size=10)

    # ---- Slide 3: idea, features, flow
    set_text(s3, 10, "An Agent documents a legacy model estate from code and stale notes, rebuilds one R model in Python with a parity proof, "
                     "and auto-generates a performance, stability and fairness report; model-risk reviewers approve each step in a Streamlit UI.", size=11)
    features = [
        (14, 15, "Inventory with gaps", "Threshold conflicts and Unknowns kept, each with source + hash"),
        (18, 19, "R → Python migration", "Reuses R coefficients; parity checked row by row in Docker"),
        (22, 23, "Validation report", "AUC/Brier, calibration, PSI drift and TPR/FPR fairness audit"),
        (26, 27, "Human gates + evidence", "Gate A/B/C hash-bound approvals; sealed evidence ZIP export"),
    ]
    for title_id, body_id, title, body in features:
        set_text(s3, title_id, title, size=12)
        set_text(s3, body_id, body, size=9)
    set_text(s3, 30, [
        "Discover → Document (Agent inventory) → Gate A → Redevelop (Agent Python candidate) → Gate B → "
        "Run in locked Docker + parity → Freeze → single-use Holdout → Validate (performance · stability · fairness) → "
        "Gate C report → Monitor (PSI drift triggers re-validation)",
    ], size=11)

    # ---- Slide 4: architecture, tech, cost, RAI
    picture_in(s4, ARCHITECTURE, 9, 10)
    set_text(s4, 13, "Python, R (glm/rpart), Streamlit, Docker, pytest, Pydantic, pandas/NumPy; LLM deepseek-v4.1-flash:1017 via gateway; runs locally, no cloud.", size=8.5)
    set_text(s4, 16, "Laptop + Docker; only cost is LLM API tokens (not separately metered).", size=8.5)
    set_text(s4, 19, [
        "•  Public UCI data (CC BY 4.0); demographics audit-only",
        "•  No raw rows or Holdout sent to the LLM; keys local",
        "•  Fairness gaps reported as signals, small groups flagged",
        "•  Prototype only: no production or regulatory claim",
        "•  No-network, read-only container; hash-bound gates",
    ], size=8)

    # ---- Slide 5: screenshots and measured figures (no invented percentages)
    for frame_id, text_id, name in ((9, 10, "01_inventory.png"), (11, 12, "03_migration.png"), (13, 14, "04_validation_report.png")):
        picture_in(s5, SCREENS / name, frame_id, text_id, pad=0.06)
    set_text(s5, 17, "2.2e-16", size=20)
    set_text(s5, 18, "Max |R − Python| probability gap on the formal 1,199-row UCI Holdout (seed 47), 0 class mismatches", size=8.5)
    set_text(s5, 20, "3.5 min", size=20)
    set_text(s5, 21, "Full Agent pipeline, synthetic drill (SYN-SEED47); manual baseline PENDING, so no % saved is claimed", size=8.5)
    set_text(s5, 23, "0.699", size=20)
    set_text(s5, 24, "Holdout ROC-AUC, formal seed 47 run (small sample, wide CI); 13/14 checks pass, release BLOCKED", size=8.5)

    # ---- Slide 6: links, AI tools, roadmap
    values = [
        (2.50, "github.com/wufangxun106334-pixel/model-risk-factory (private; judge access pending)"),
        (3.22, "materials/demo_video.mp4 (1:51, synthetic replay); share link pending"),
        (3.94, "Local Streamlit app (streamlit run app.py); not deployed publicly"),
        (4.66, "Claude Code, Kimi Code CLI; product LLM deepseek-v4.1-flash:1017; UCI data"),
    ]
    for top, text in values:
        add_text(s6, 3.45, top - 0.06, 2.45, 0.34, text, like_id=10, size=7.5)
    set_text(s6, 19, [
        "Done: formal seed-47 run with human Gate A/B/C. Next: fix the chain-checker defect, SAS inputs, a batch queue for ~250 models, MLflow/Azure ML evidence sink.",
        "Constraints: 2005 Taiwan public data, not a UK portfolio; prototype only.",
    ], size=8)
    set_text(s6, 26, "EXL Hackathon | [Team name] | Challenge 04", size=None)

    deck.save(str(OUTPUT))
    return OUTPUT


if __name__ == "__main__":
    print(build())
