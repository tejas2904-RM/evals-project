import builtins
import re

import pytest

from evalpilot.audit.export_md import render
from evalpilot.audit.export_pdf import PdfUnavailable, latin1, render_pdf
from evalpilot.audit.run import load_audit

AUDITS = "runs/reference/audits"


def reference_audits(root):
    return sorted(p for p in (root / AUDITS).iterdir() if (p / "risk_register.json").is_file())


def headings(markdown: str) -> list[str]:
    return [re.sub(r"\*\*|`", "", line[3:]).strip() for line in markdown.splitlines() if line.startswith("## ")]


def test_reference_audits_include_both_examples_and_the_own_bot(root):
    names = [p.name for p in reference_audits(root)]
    assert any("vulnerable" in n for n in names) and any("fixed" in n for n in names) and any("evalpilot" in n for n in names)


@pytest.mark.parametrize("which", ["vulnerable", "fixed"])
def test_pdf_is_produced_with_the_same_sections_as_audit_md(root, which):
    path = next(p for p in reference_audits(root) if which in p.name)
    loaded = load_audit(path)
    pdf = render_pdf(*loaded, compress=False)
    assert pdf.startswith(b"%PDF") and len(pdf) > 5_000
    text = pdf.decode("latin-1")
    expected = headings(render(*loaded))
    assert {"Risk register", "Guardrail coverage map", "Evidence"} <= set(expected)
    assert [h for h in expected if h not in text] == []
    assert f"AI System Audit: {loaded[0]['target']}".replace("(", "\\(").replace(")", "\\)") in text


def test_compressed_pdf_is_smaller_and_still_valid(root):
    loaded = load_audit(next(p for p in reference_audits(root) if "vulnerable" in p.name))
    small, big = render_pdf(*loaded), render_pdf(*loaded, compress=False)
    assert small.startswith(b"%PDF") and small.rstrip().endswith(b"%%EOF") and len(small) < len(big)


def test_pdf_is_deterministic(root):
    loaded = load_audit(next(p for p in reference_audits(root) if "fixed" in p.name))
    assert render_pdf(*loaded) == render_pdf(*loaded)


def test_latin1_sanitizes_typography():
    assert latin1("κ ≥ 0.6 → ship × 2 … “ok” — fine") == "? >= 0.6 -> ship x 2 ... \"ok\" - fine"


def test_missing_fpdf2_is_a_clear_error(root, monkeypatch):
    real_import = builtins.__import__

    def no_fpdf(name, *args, **kwargs):
        if name == "fpdf" or name.startswith("fpdf."):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_fpdf)
    loaded = load_audit(next(p for p in reference_audits(root) if "fixed" in p.name))
    with pytest.raises(PdfUnavailable, match=r"\[pdf\]"):
        render_pdf(*loaded)
