#!/usr/bin/env python3
"""Fill the official EXL x UCD submission template for Challenge 04.

Input : docs/EXL_UCD_Hackathon_Project_Submission_Template - Copy.pptx (left untouched)
Output: materials/EXL_UCD_Submission_Challenge04.pptx (local only, see .gitignore)

Layout rule: no text on any slide is smaller than 16 pt (MIN_PT). Text is replaced
inside the template's own boxes, keeping fonts and colours; boxes are enlarged where
16 pt needs more room. Figures come from the formal seed 47 run
(docs/v3/12_formal_run_seed47.md) unless marked synthetic.

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
MIN_PT = 16
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def shape(slide, shape_id: int):
    for item in slide.shapes:
        if item.shape_id == shape_id:
            return item
    raise KeyError(f"shape {shape_id} not found")


def place(slide, shape_id: int, left=None, top=None, width=None, height=None) -> None:
    item = shape(slide, shape_id)
    if left is not None:
        item.left = Inches(left)
    if top is not None:
        item.top = Inches(top)
    if width is not None:
        item.width = Inches(width)
    if height is not None:
        item.height = Inches(height)


def set_text(slide, shape_id: int, lines, size: float = MIN_PT, bold: bool | None = None) -> None:
    """Replace a box's text, one paragraph per line, keeping the template's first-run format."""

    lines = [lines] if isinstance(lines, str) else list(lines)
    frame = shape(slide, shape_id).text_frame
    frame.word_wrap = True
    template_p = frame.paragraphs[0]._p
    template_r = template_p.find(A + "r")
    body = template_p.getparent()
    for paragraph in list(frame.paragraphs):
        body.remove(paragraph._p)
    for _ in lines:
        new_p = copy.deepcopy(template_p)
        for child in list(new_p):
            if child.tag in (A + "r", A + "br", A + "fld"):
                new_p.remove(child)
        if template_r is not None:
            run = copy.deepcopy(template_r)
            end = new_p.find(A + "endParaRPr")
            (end.addprevious(run) if end is not None else new_p.append(run))
        body.append(new_p)
    for paragraph, line in zip(frame.paragraphs, lines):
        if not paragraph.runs:
            paragraph.add_run()
        paragraph.runs[0].text = line
        paragraph.runs[0].font.size = Pt(max(size, MIN_PT))
        if bold is not None:
            paragraph.runs[0].font.bold = bold


def add_text(slide, left, top, width, height, text: str, like_id: int, size: float = MIN_PT) -> None:
    reference = shape(slide, like_id)
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    box.text_frame._txBody.getparent().replace(box.text_frame._txBody, copy.deepcopy(reference.text_frame._txBody))
    set_text(slide, box.shape_id, text, size=size, bold=False)


def remove(slide, shape_id: int) -> None:
    element = shape(slide, shape_id)._element
    element.getparent().remove(element)


def picture_in(slide, path: Path, frame_id: int, placeholder_id: int | None = None, pad: float = 0.06) -> None:
    frame = shape(slide, frame_id)
    if placeholder_id is not None:
        remove(slide, placeholder_id)
    picture = slide.shapes.add_picture(str(path), frame.left, frame.top)
    pad_emu = Inches(pad)
    scale = min((frame.width - 2 * pad_emu) / picture.width, (frame.height - 2 * pad_emu) / picture.height)
    picture.width, picture.height = int(picture.width * scale), int(picture.height * scale)
    picture.left = Emu(frame.left + (frame.width - picture.width) // 2)
    picture.top = Emu(frame.top + (frame.height - picture.height) // 2)


def enforce_minimum(deck) -> None:
    """Raise every explicit run size below MIN_PT (template labels included) to MIN_PT."""

    for slide in deck.slides:
        for item in slide.shapes:
            if not item.has_text_frame:
                continue
            for paragraph in item.text_frame.paragraphs:
                for run in paragraph.runs:
                    if run.font.size is None or run.font.size < Pt(MIN_PT):
                        run.font.size = Pt(MIN_PT)


def build() -> Path:
    deck = Presentation(str(TEMPLATE))
    s1, s2, s3, s4, s5, s6 = deck.slides

    # ---- Slide 1: team (team name and leader e-mail left for the team to fill)
    set_text(s1, 2, "Model Risk Factory", size=54)
    set_text(s1, 6, "Document, migrate and validate legacy credit models")
    place(s1, 6, width=8.2)
    for value_id in (33, 35, 37, 39, 41):
        place(s1, value_id, left=3.92, width=4.29, height=0.3)
    set_text(s1, 35, "fangxunwu (25208508)")
    set_text(s1, 37, "fangxunwu, kaiwenyao")
    set_text(s1, 41, "04 · Model risk factory")

    # ---- Slide 2: problem and USP
    place(s2, 10, height=3.7)
    set_text(s2, 10, [
        "• ~250 bank models need current documentation and validation (PRA SS1/23).",
        "• One validation takes 8–12 weeks; documents drift from the code.",
        "• Users: model owners, validators and sign-off reviewers.",
        "(Client context from the challenge brief.)",
    ])
    for usp_id, text in ((25, "Every fact traced to file, line and SHA-256"),
                         (29, "Agent drafts; a human approves each gate"),
                         (33, "Migration proven by parity, not retraining")):
        place(s2, usp_id, height=0.75)
        set_text(s2, usp_id, text)

    # ---- Slide 3: idea, features, flow
    place(s3, 10, top=2.26, height=0.6)
    set_text(s3, 10, "An Agent documents legacy R models, ports one to Python with a parity proof "
                     "and writes the validation report. A human approves every gate.")
    for title_id, body_id, title, body in ((14, 15, "Inventory", "Gaps kept, hashed"),
                                           (18, 19, "R → Python", "Row-by-row parity"),
                                           (22, 23, "Validation", "Perf · drift · bias"),
                                           (26, 27, "Human gates", "Hash-bound approvals")):
        set_text(s3, title_id, title, size=18)
        place(s3, body_id, height=0.32)
        set_text(s3, body_id, body)
    place(s3, 11, width=8.0)
    place(s3, 28, width=8.0)
    set_text(s3, 30, "Document → Gate A → Port to Python → Gate B → Docker parity → Holdout → Validate → Gate C → Monitor drift")

    # ---- Slide 4: architecture, tech, cost, RAI
    picture_in(s4, ARCHITECTURE, 9, 10)
    place(s4, 13, top=2.74, height=0.62)
    set_text(s4, 13, ["Python · R · Docker · Streamlit", "LLM: deepseek-v4.1-flash"])
    set_text(s4, 15, "ESTIMATED COST")
    set_text(s4, 16, "Local laptop; LLM tokens only")
    place(s4, 18, top=4.78)
    place(s4, 19, top=5.06, height=0.98)
    set_text(s4, 19, ["• Public data only", "• No raw rows sent to LLM", "• Prototype; not certified"])

    # ---- Slide 5: formal-run screenshots and figures
    for frame_id, text_id, name in ((9, 10, "formal_seed47_01_inventory.png"),
                                    (11, 12, "formal_seed47_03_parity.png"),
                                    (13, 14, "formal_seed47_04_validation.png")):
        picture_in(s5, SCREENS / name, frame_id, text_id)
    metrics = ((17, 18, "2.2e-16", "R vs Python gap, 1,199 rows"),
               (20, 21, "3.5 min", "Agent pipeline (synthetic)"),
               (23, 24, "0.699", "Holdout AUC, seed 47"))
    for number_id, label_id, number, label in metrics:
        number_box, label_box = shape(s5, number_id), shape(s5, label_id)
        number_box.width = Inches(1.6)
        label_box.left = number_box.left + Inches(1.62)
        label_box.width = Inches(1.95)
        label_box.top, label_box.height = number_box.top, Inches(0.72)
        set_text(s5, number_id, number, size=26)
        set_text(s5, label_id, label)

    # ---- Slide 6: links (value under each label), roadmap, release state
    rows = ((10, 11, "github.com/wufangxun106334-pixel/model-risk-factory"),
            (12, 13, "Link pending (1:51 MP4 ready)"),
            (14, 15, "Local Streamlit app; not deployed"),
            (16, 17, "Claude Code, Kimi Code, deepseek-v4.1"))
    for label_id, line_id, value in rows:
        label = shape(s6, label_id)
        label.width = Inches(5.4)
        top = label.top / 914400
        add_text(s6, 0.95, top + 0.28, 5.6, 0.32, value, like_id=label_id)
        place(s6, line_id, top=top + 0.64)
    place(s6, 18, top=5.36)
    place(s6, 19, top=5.64, width=5.6, height=0.66)
    set_text(s6, 19, ["13/14 checks pass; release BLOCKED (D-01)", "Next: SAS inputs, ~250-model queue"])
    for label_id in (22, 25, 28, 31):
        place(s6, label_id, width=1.75)
    for value_id in (23, 26, 29, 32):
        place(s6, value_id, left=9.25, width=3.3, height=0.55)
    set_text(s6, 32, "Leader's UCD email")
    set_text(s6, 25, "SUBJECT")
    set_text(s6, 26, "EXL Hackathon | [Team name] | Challenge 04")

    # Template hyperlinks render blue on the navy card; make them readable.
    from pptx.dml.color import RGBColor
    for link_id in (23, 34):
        for paragraph in shape(s6, link_id).text_frame.paragraphs:
            for run in paragraph.runs:
                if run.hyperlink.address:
                    run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                    run.font.underline = True

    enforce_minimum(deck)
    deck.save(str(OUTPUT))
    return OUTPUT


if __name__ == "__main__":
    print(build())
