"""PDF audit report (audit.pdf), laid out from the same Markdown as audit.md so the sections match.

Needs the optional `pdf` extra (fpdf2: pure Python, no system libraries).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from evalpilot.audit.export_md import render
from evalpilot.audit.models import CoverageCell, Risk, Verdict
from evalpilot.audit.redact import redact

# Core PDF fonts are latin-1 only.
LATIN1 = str.maketrans({
    "\u2026": "...", "\u2265": ">=", "\u2264": "<=", "\u2192": "->", "\u2190": "<-", "\u00d7": "x",
    "\u2013": "-", "\u2014": "-", "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2022": "*", "\u20b9": "Rs ", "\u00a0": " ", "\u2212": "-", "\u2713": "yes", "\u2717": "no",
})
INLINE = re.compile(r"\*\*|`")
TABLE_SPLIT = re.compile(r"(?<!\\)\|")


class PdfUnavailable(RuntimeError):
    pass


def latin1(text: str) -> str:
    return text.translate(LATIN1).encode("latin-1", "replace").decode("latin-1")


def plain(text: str) -> str:
    return latin1(INLINE.sub("", text).replace("\\|", "|"))


def _cells(line: str) -> list[str]:
    return [plain(c.strip()) for c in TABLE_SPLIT.split(line.strip().strip("|"))]


def _widths(rows: list[list[str]]) -> tuple[float, ...]:
    n = len(rows[0])
    return tuple(min(max(len(r[i]) if i < len(r) else 0 for r in rows), 70) + 6 for i in range(n))


def _date(intake: dict[str, Any]) -> datetime:
    stamp = intake.get("finished") or intake.get("started")
    try:
        return datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return datetime(2026, 1, 1, tzinfo=timezone.utc)


def markdown_to_pdf(markdown: str, *, title: str, created: datetime, compress: bool = True) -> bytes:
    try:
        from fpdf import FPDF
        from fpdf.fonts import FontFace
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise PdfUnavailable("PDF export needs fpdf2: pip install -e .[pdf]") from exc

    pdf = FPDF(orientation="landscape", format="A4")
    pdf.set_compression(compress)
    pdf.set_title(latin1(title))
    pdf.set_creator("EvalPilot")
    pdf.set_creation_date(created)
    pdf.set_auto_page_break(True, margin=12)
    pdf.set_margins(12, 12, 12)
    pdf.add_page()
    heading_style = FontFace(emphasis="BOLD", fill_color=(235, 238, 242))

    def text(body: str, size: float = 9, style: str = "", indent: float = 0, family: str = "Helvetica") -> None:
        pdf.set_font(family, style, size)
        pdf.set_x(pdf.l_margin + indent)
        pdf.multi_cell(pdf.epw - indent, size * 0.5, body, new_x="LMARGIN", new_y="NEXT")

    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(latin1(lines[i].strip()))
                i += 1
            pdf.set_fill_color(246, 248, 250)
            pdf.set_font("Courier", "", 7.5)
            pdf.set_x(pdf.l_margin + 6)
            pdf.multi_cell(pdf.epw - 6, 3.6, "\n".join(block) or " ", fill=True, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)
        elif stripped.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not re.fullmatch(r"\|(\s*-+\s*\|)+", lines[i].strip()):
                    rows.append(_cells(lines[i]))
                i += 1
            i -= 1
            pdf.set_font("Helvetica", "", 7)
            with pdf.table(col_widths=_widths(rows), text_align="LEFT", line_height=3.6,
                           headings_style=heading_style, padding=1) as table:
                for row in rows:
                    r = table.row()
                    for cell in row:
                        r.cell(cell)
            pdf.ln(2)
        elif stripped.startswith("### "):
            pdf.ln(1)
            text(plain(stripped[4:]), 10, "B")
        elif stripped.startswith("## "):
            pdf.ln(3)
            heading = plain(stripped[3:])
            pdf.start_section(heading)
            text(heading, 13, "B")
        elif stripped.startswith("# "):
            heading = plain(stripped[2:])
            pdf.start_section(heading)
            text(heading, 17, "B")
            pdf.ln(1)
        elif stripped.startswith("- "):
            text("- " + plain(stripped[2:]), 9, indent=4 if line.startswith("  ") else 0)
        elif stripped:
            text(plain(stripped), 9)
        else:
            pdf.ln(1.5)
        i += 1
    return bytes(pdf.output())


def render_pdf(
    intake: dict[str, Any],
    risks: list[Risk],
    coverage: list[CoverageCell],
    verdict: Verdict,
    flaws: list[dict[str, Any]] | None = None,
    *,
    compress: bool = True,
) -> bytes:
    markdown = redact(render(intake, risks, coverage, verdict, flaws))
    title = f"AI System Audit: {intake.get('target', '?')}"
    return markdown_to_pdf(markdown, title=title, created=_date(intake), compress=compress)
