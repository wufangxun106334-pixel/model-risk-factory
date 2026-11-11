#!/usr/bin/env python3
"""Build the judge-facing deck from ``materials/solution_deck.md``.

Outputs, next to this file:
  solution_deck.pptx  -- editable deck (python-pptx, 16:9, one slide per "## Slide N")
  solution_deck.pdf   -- print-ready copy rendered by headless Chrome

The Markdown file is the single source of truth: edit it, then re-run
``.venv/bin/python materials/build_deck.py``. Neither output is hand-edited, so the
two copies can never drift apart.

Tooling note: ``python-pptx`` is a build-time tool only. It is deliberately *not*
listed in ``requirements.txt``; the project's locked runtime dependencies are
unchanged.
"""

from __future__ import annotations

import html
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

MATERIALS = Path(__file__).resolve().parent
REPOSITORY = MATERIALS.parent
SOURCE = MATERIALS / "solution_deck.md"
PPTX = MATERIALS / "solution_deck.pptx"
PDF = MATERIALS / "solution_deck.pdf"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

INK = RGBColor(0x14, 0x2B, 0x33)
ACCENT = RGBColor(0x0E, 0x6E, 0x6E)
MUTED = RGBColor(0x5A, 0x6B, 0x72)
RULE = RGBColor(0xD5, 0xDE, 0xE2)

SLIDE_WIDTH = Inches(13.333)
SLIDE_HEIGHT = Inches(7.5)


@dataclass
class Slide:
    number: int
    title: str
    subtitle: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)
    images: list[Path] = field(default_factory=list)
    source: str = ""

    @property
    def image_height_in(self) -> float:
        """Image band height: taller when the slide carries few bullets."""

        if not self.images:
            return 0.0
        return 3.5 if len(self.bullets) <= 3 else 2.6


def _aspect(path: Path) -> float:
    """Width / height of a PNG, read from its IHDR chunk (no imaging dependency)."""

    header = path.read_bytes()[:24]
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit(f"only PNG images are supported: {path}")
    width = int.from_bytes(header[16:20], "big")
    height = int.from_bytes(header[20:24], "big")
    return width / height


def plain(text: str) -> str:
    """Drop Markdown emphasis but keep the words (both outputs use the same text)."""

    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"\1", text)
    return text.strip()


def parse(markdown: str) -> list[Slide]:
    slides: list[Slide] = []
    current: Slide | None = None
    for raw in markdown.splitlines():
        line = raw.rstrip()
        if line.startswith("## Slide "):
            header = line[len("## Slide ") :]
            number_text, _, title = header.partition("—")
            current = Slide(number=int(number_text.strip()), title=title.strip())
            slides.append(current)
            continue
        if current is None or not line.strip() or line.strip() == "<!--":
            continue
        if line.strip().startswith("<!--"):
            continue
        if line.startswith("- "):
            current.bullets.append(plain(line[2:]))
        elif line.startswith("IMAGE:"):
            path = REPOSITORY / line[len("IMAGE:") :].strip()
            if not path.is_file():
                raise SystemExit(f"missing image: {path}")
            current.images.append(path)
        elif line.startswith("SOURCE:"):
            current.source = plain(line[len("SOURCE:") :])
        else:
            current.subtitle.append(plain(line))
    if not slides:
        raise SystemExit("no slides parsed")
    return slides


def build_pptx(slides: list[Slide]) -> None:
    presentation = Presentation()
    presentation.slide_width = SLIDE_WIDTH
    presentation.slide_height = SLIDE_HEIGHT
    blank = presentation.slide_layouts[6]

    for slide in slides:
        page = presentation.slides.add_slide(blank)
        left = Inches(0.62)
        width = SLIDE_WIDTH - Inches(1.24)

        title = page.shapes.add_textbox(left, Inches(0.42), width, Inches(1.05))
        frame = title.text_frame
        frame.word_wrap = True
        run = frame.paragraphs[0].add_run()
        run.text = slide.title
        run.font.size = Pt(30)
        run.font.bold = True
        run.font.color.rgb = INK
        run.font.name = "Helvetica Neue"

        rule = page.shapes.add_shape(1, left, Inches(1.46), Inches(1.5), Inches(0.05))
        rule.fill.solid()
        rule.fill.fore_color.rgb = ACCENT
        rule.line.fill.background()

        cursor = Inches(1.66)
        if slide.subtitle:
            box = page.shapes.add_textbox(left, cursor, width, Inches(0.8))
            text_frame = box.text_frame
            text_frame.word_wrap = True
            for index, line in enumerate(slide.subtitle):
                paragraph = text_frame.paragraphs[0] if index == 0 else text_frame.add_paragraph()
                run = paragraph.add_run()
                run.text = line
                run.font.size = Pt(16)
                run.font.color.rgb = ACCENT
                run.font.name = "Helvetica Neue"
            cursor += Inches(0.35) + Inches(0.32) * len(slide.subtitle)

        bullet_points = 13 if slide.images else 15
        bullets_height = SLIDE_HEIGHT - cursor - Inches(0.78)
        if slide.images:
            # Estimate where the bullets end (Helvetica averages ~0.5 em per character),
            # then fit the image band between that and the footer so nothing overlaps.
            chars_per_line = max(1, int(width / Emu(int(Pt(bullet_points)) * 0.5)))
            lines = sum(-(-len("•  " + bullet) // chars_per_line) for bullet in slide.bullets)
            text_height = Emu(int(Pt(bullet_points) * 1.2 * lines + Pt(9) * len(slide.bullets)))
            available = SLIDE_HEIGHT - Inches(0.78) - (cursor + text_height) - Inches(0.2)
            image_height = Emu(min(int(Inches(slide.image_height_in)), int(available)))
            if image_height < Inches(1.5):
                raise SystemExit(f"slide {slide.number}: too much text to fit its image")
            bullets_height = text_height
        else:
            image_height = Emu(0)
        if slide.bullets:
            box = page.shapes.add_textbox(left, cursor, width, bullets_height)
            frame = box.text_frame
            frame.word_wrap = True
            for index, bullet in enumerate(slide.bullets):
                paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
                paragraph.space_after = Pt(9)
                run = paragraph.add_run()
                run.text = "•  " + bullet
                run.font.size = Pt(bullet_points)
                run.font.color.rgb = INK
                run.font.name = "Helvetica Neue"

        if slide.images:
            gap = Inches(0.22)
            share = int((width - gap * (len(slide.images) - 1)) / len(slide.images))
            top = SLIDE_HEIGHT - Inches(0.78) - image_height
            bottom = SLIDE_HEIGHT - Inches(0.78)
            for index, image in enumerate(slide.images):
                # Fit inside the band, keep the aspect ratio, centre in its share.
                height = int(image_height)
                picture_width = int(height * _aspect(image))
                if picture_width > share:
                    picture_width = share
                    height = int(share / _aspect(image))
                x = left + (share + gap) * index + (share - picture_width) // 2
                page.shapes.add_picture(str(image), x, bottom - height, width=Emu(picture_width), height=Emu(height))

        if slide.source:
            box = page.shapes.add_textbox(left, SLIDE_HEIGHT - Inches(0.62), width, Inches(0.5))
            frame = box.text_frame
            frame.word_wrap = True
            run = frame.paragraphs[0].add_run()
            run.text = slide.source
            run.font.size = Pt(9)
            run.font.italic = True
            run.font.color.rgb = MUTED
            run.font.name = "Helvetica Neue"

        number = page.shapes.add_textbox(SLIDE_WIDTH - Inches(1.05), Inches(0.32), Inches(0.6), Inches(0.3))
        run = number.text_frame.paragraphs[0].add_run()
        run.text = f"{slide.number}/{len(slides)}"
        run.font.size = Pt(10)
        run.font.color.rgb = MUTED
        number.text_frame.paragraphs[0].alignment = PP_ALIGN.RIGHT

    presentation.save(PPTX)


def render_html(slides: list[Slide]) -> str:
    blocks = []
    for slide in slides:
        bullets = "".join(f"<li>{html.escape(bullet)}</li>" for bullet in slide.bullets)
        subtitle = "".join(f"<p class=sub>{html.escape(line)}</p>" for line in slide.subtitle)
        images = "".join(
            f'<figure><img src="{image.as_uri()}" style="max-height:{slide.image_height_in}in"></figure>'
            for image in slide.images
        )
        blocks.append(
            f'<section class="slide"><div class="num">{slide.number}/{len(slides)}</div>'
            f"<h1>{html.escape(slide.title)}</h1>{subtitle}"
            f'<ul class="bullets">{bullets}</ul>'
            f'<div class="images">{images}</div>'
            f'<p class="source">{html.escape(slide.source)}</p></section>'
        )
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Model Risk Factory — solution deck</title>
<style>
  @page {{ size: 13.333in 7.5in; margin: 0; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; color: #{INK}; }}
  .slide {{ width: 13.333in; height: 7.5in; padding: 0.5in 0.62in 0.62in; position: relative;
            page-break-after: always; overflow: hidden; display: flex; flex-direction: column; }}
  .slide:last-child {{ page-break-after: auto; }}
  h1 {{ font-size: 26pt; margin: 0 0 6pt; color: #{INK}; }}
  .num {{ position: absolute; top: 0.3in; right: 0.62in; font-size: 9pt; color: #{MUTED}; }}
  h1::after {{ content: ""; display: block; width: 1.5in; height: 3pt; background: #{ACCENT}; margin-top: 6pt; }}
  .sub {{ font-size: 12pt; color: #{ACCENT}; margin: 2pt 0; }}
  ul.bullets {{ margin: 10pt 0 0; padding-left: 16pt; }}
  ul.bullets li {{ font-size: 11pt; line-height: 1.38; margin-bottom: 6pt; }}
  .images {{ display: flex; gap: 0.2in; margin-top: auto; padding-bottom: 0.45in; }}
  .images figure {{ margin: 0; flex: 1; display: flex; justify-content: center; align-items: flex-end; }}
  .images img {{ max-width: 100%; width: auto; border: 1px solid #{RULE}; }}
  .source {{ position: absolute; bottom: 0.42in; left: 0.62in; right: 0.62in;
             font-size: 7.5pt; font-style: italic; color: #{MUTED}; margin: 0; }}
</style></head><body>{''.join(blocks)}</body></html>"""


def build_pdf(slides: list[Slide]) -> None:
    if not CHROME.is_file():
        print(f"warning: {CHROME} not found; skipped PDF", file=sys.stderr)
        return
    document = render_html(slides)
    with tempfile.TemporaryDirectory() as temporary:
        page = Path(temporary) / "deck.html"
        page.write_text(document, encoding="utf-8")
        subprocess.run(
            [
                str(CHROME),
                "--headless",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--print-to-pdf={PDF}",
                page.as_uri(),
            ],
            check=True,
            capture_output=True,
        )


def main() -> int:
    slides = parse(SOURCE.read_text(encoding="utf-8"))
    if len(slides) > 10:
        raise SystemExit(f"the official limit is 10 slides, the source has {len(slides)}")
    if "--html" in sys.argv:
        target = Path(sys.argv[sys.argv.index("--html") + 1])
        target.write_text(render_html(slides), encoding="utf-8")
        print(f"html -> {target} ({target.stat().st_size} bytes)")
        return 0
    build_pptx(slides)
    build_pdf(slides)
    print(f"{len(slides)} slides -> {PPTX.name} ({PPTX.stat().st_size} bytes)")
    if PDF.is_file():
        print(f"pdf -> {PDF.name} ({PDF.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
