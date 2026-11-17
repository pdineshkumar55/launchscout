from datetime import date

import pdfplumber
import pytest

from launchscout import pdf as pdf_mod
from launchscout.pdf import markdown_to_html, markdown_to_pdf
from launchscout.report import HEADINGS, assemble


@pytest.fixture
def report_md(inp, market, feedback, strategy, writer_md):
    md, _ = assemble(inp, market, feedback, strategy, writer_md, today=date(2026, 11, 17))
    long_url = "https://www.justdial.com/Testcity/" + "Very-Long-Business-Name-Near-Landmark-" * 4 + "reviews"
    return md.replace("₹", "₹") + f"\n[9] Long link — {long_url}\n" + "\nPrice check: ₹1,099 per session 🐶\n"


def _read(path):
    with pdfplumber.open(path) as doc:
        text = "\n".join(p.extract_text() or "" for p in doc.pages)
        over = [w for p in doc.pages for w in p.extract_words() if w["x1"] > p.width - 30]
        links = [link["uri"] for p in doc.pages for link in p.hyperlinks]
        return doc.pages, text, over, links


def test_pdf_created_and_complete(tmp_path, report_md):
    out = tmp_path / "report.pdf"
    data = markdown_to_pdf(report_md, out)
    assert out.exists() and data[:5] == b"%PDF-" and len(data) > 5000
    pages, text, over, links = _read(out)
    assert abs(pages[0].width - 595.3) < 1 and abs(pages[0].height - 841.9) < 1  # A4
    for h in HEADINGS:
        assert h.lstrip("# ") in text, h
    assert "Competitor Report" in text and "Page 1 of" in text
    assert not over, f"text past the right margin: {[w['text'] for w in over][:3]}"
    assert any("Very-Long-Business-Name" in u for u in links)  # full URL kept behind short text


def test_rupee_rendered_when_font_available(tmp_path, report_md):
    if pdf_mod.pick_font() is None:
        pytest.skip("no font with the rupee sign on this machine")
    _, text, _, _ = _read_pdf(tmp_path, report_md)
    assert "₹1,099" in text
    assert "🐶" not in text  # unsupported glyphs are removed, not drawn as boxes


def test_fallback_without_font(tmp_path, report_md, monkeypatch):
    monkeypatch.setattr(pdf_mod, "pick_font", lambda: None)
    _, text, _, _ = _read_pdf(tmp_path, report_md)
    assert "Rs 1,099" in text and "₹" not in text


def test_remote_resources_never_fetched(monkeypatch, tmp_path):
    import requests
    calls = []
    monkeypatch.setattr(requests, "get", lambda *a, **k: calls.append(a) or None)
    md = '# Competitor Report: X, Y\n\n<img src="http://169.254.169.254/latest/meta-data">\n\n## Sources\n'
    markdown_to_pdf(md, tmp_path / "r.pdf")
    assert not calls


def test_html_has_header_footer_and_short_links():
    html = markdown_to_html("# T\n\n## Sources\n[1] A — https://www.example.com/" + "x" * 150 + "\n")
    assert 'id="header_content"' in html and "<pdf:pagenumber>" in html
    assert 'href="https://www.example.com/' + "x" * 150 in html
    assert ">example.com/xxx" in html and "…</a>" in html


def _read_pdf(tmp_path, md):
    out = tmp_path / "r.pdf"
    markdown_to_pdf(md, out)
    return _read(out)
