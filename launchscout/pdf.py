"""Markdown report -> PDF (A4) via HTML and xhtml2pdf (pure Python, works on Windows and Linux).

Fonts: no font files are committed (licences). The first available regular+bold pair that has the
rupee sign is used: PDF_FONT/PDF_FONT_BOLD from .env, DejaVu Sans (installed in the Docker image via
fonts-dejavu-core), Noto Sans, then Windows Arial. If none is found, the built-in Helvetica is used
and "₹" is written as "Rs". Characters the chosen font cannot draw (e.g. emoji in a source title)
are removed so the PDF never shows empty boxes.
"""

from __future__ import annotations

import html
import io
import logging
import os
import re
from functools import lru_cache
from pathlib import Path

import markdown as md_lib

from .events import short_url

log = logging.getLogger("launchscout.pdf")

FONT_CANDIDATES = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf", "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf"),
]
RUPEE = "\u20b9"


@lru_cache(maxsize=1)
def pick_font() -> tuple[str, str, frozenset[int]] | None:
    """Return (regular_path, bold_path, supported_codepoints) or None for the built-in font."""
    from reportlab.pdfbase.ttfonts import TTFontFile

    env = (os.getenv("PDF_FONT", ""), os.getenv("PDF_FONT_BOLD", "") or os.getenv("PDF_FONT", ""))
    for regular, bold in ([env] if env[0] else []) + FONT_CANDIDATES:
        if not (Path(regular).is_file() and Path(bold).is_file()):
            continue
        try:
            cmap = TTFontFile(regular).charToGlyph
        except Exception as exc:  # unreadable font file: try the next one
            log.info("font %s skipped: %s", regular, exc)
            continue
        if ord(RUPEE) in cmap:
            return regular, bold, frozenset(cmap)
    log.warning("no font with the rupee sign found; PDF will use Helvetica and 'Rs'")
    return None


def _clean_text(text: str, supported: frozenset[int] | None) -> str:
    if supported is None:
        text = text.replace(RUPEE, "Rs ")
        return "".join(ch for ch in text if ord(ch) < 256 or ch in "—–‘’“”•…·")
    return "".join(ch for ch in text if ch in "\n\t " or ord(ch) in supported)


def _short_link_text(html_text: str, limit: int = 70) -> str:
    """Long URLs overflow the page as one unbreakable word. Show a short form; the link keeps the
    full address: <a href="https://www.justdial.com/Chennai/...">justdial.com/Chennai/…</a>"""
    def repl(m: re.Match) -> str:
        return f"{m.group(1)}{html.escape(short_url(html.unescape(m.group(2)), limit))}</a>"
    return re.sub(r"(<a [^>]*>)(https?://[^<]+)</a>", repl, html_text)


CSS = """
@page {{
  size: a4 portrait;
  margin: 2.1cm 1.6cm 1.8cm 1.6cm;
  @frame header_frame {{ -pdf-frame-content: header_content; left: 1.6cm; right: 1.6cm; top: 0.9cm; height: 0.8cm; }}
  @frame footer_frame {{ -pdf-frame-content: footer_content; left: 1.6cm; right: 1.6cm; bottom: 0.7cm; height: 0.8cm; }}
}}
{font_faces}
body {{ font-family: {family}; font-size: 9.5pt; line-height: 1.4; color: #1f2328; }}
h1 {{ font-size: 17pt; margin: 0 0 4pt 0; color: #0b3d91; }}
h2 {{ font-size: 12.5pt; margin: 14pt 0 5pt 0; padding-bottom: 2pt; border-bottom: 0.6pt solid #c9d1d9; color: #0b3d91; }}
p {{ margin: 0 0 6pt 0; }}
ul {{ margin: 0 0 6pt 0; }}
li {{ margin: 0 0 2pt 0; }}
blockquote {{ margin: 4pt 0 8pt 0; padding: 6pt 8pt; background-color: #eef4ff; border-left: 2pt solid #1f6feb; font-size: 10.5pt; }}
table {{ width: 100%; margin: 4pt 0 8pt 0; -pdf-keep-in-frame-mode: shrink; }}
th {{ background-color: #eef1f5; font-weight: bold; font-size: 8.5pt; padding: 3pt; border: 0.5pt solid #9aa4ae; text-align: left; }}
td {{ font-size: 8.5pt; padding: 3pt; border: 0.5pt solid #9aa4ae; vertical-align: top; }}
a {{ color: #0b57d0; text-decoration: none; }}
em {{ color: #57606a; }}
hr {{ color: #c9d1d9; }}
.sources p {{ font-size: 8pt; margin: 0 0 3pt 0; }}
#header_content {{ font-size: 8pt; color: #57606a; border-bottom: 0.5pt solid #d0d7de; }}
#footer_content {{ font-size: 8pt; color: #57606a; text-align: center; }}
"""


def _font_css(font: tuple[str, str, frozenset[int]] | None) -> tuple[str, str]:
    if font is None:
        return "", "Helvetica"
    regular, bold, _ = font
    r, b = Path(regular).as_posix(), Path(bold).as_posix()
    faces = (f'@font-face {{ font-family: ReportFont; src: url("{r}"); }}\n'
             f'@font-face {{ font-family: ReportFont; font-weight: bold; src: url("{b}"); }}')
    return faces, "ReportFont"


def markdown_to_html(markdown_text: str, title: str = "Competitor Report") -> str:
    font = pick_font()
    supported = font[2] if font else None
    text = _clean_text(markdown_text, supported)
    text = re.sub(r"(?<![<(\"])\b(https?://[^\s<>|]+)", r"<\1>", text)  # bare URLs -> links
    body = md_lib.markdown(text, extensions=["tables", "sane_lists"])
    # Put the Sources list in its own block so it can use a smaller size.
    body = body.replace("<h2>Sources</h2>", '<h2>Sources</h2><div class="sources">', 1)
    if '<div class="sources">' in body:
        body = re.sub(r"(<hr\s*/?>)", r"</div>\1", body, count=1) if "<hr" in body else body + "</div>"
    body = _short_link_text(body)
    faces, family = _font_css(font)
    css = CSS.format(font_faces=faces, family=family)
    header = html.escape(title)
    return f"""<html><head><meta charset="utf-8"><style>{css}</style></head><body>
<div id="header_content">{header}</div>
<div id="footer_content">LaunchScout · Page <pdf:pagenumber> of <pdf:pagecount></div>
{body}
</body></html>"""


def markdown_to_pdf(markdown_text: str, out_path: Path | None = None) -> bytes:
    """Render the report to PDF bytes; also write them to out_path if given."""
    from xhtml2pdf import pisa
    from xhtml2pdf.config.resources import ResourceAccessPolicy

    html_doc = markdown_to_html(markdown_text)
    font = pick_font()
    # Local reads: the working directory plus the chosen font's folder only. No network fetches:
    # report text comes from the web, so it must not be able to make the renderer call out.
    roots = tuple({Path(font[0]).parent, Path(font[1]).parent}) if font else ()
    policy = ResourceAccessPolicy(allow_remote=False, base_dir=Path.cwd(), extra_roots=roots)
    buf = io.BytesIO()
    status = pisa.CreatePDF(html_doc, dest=buf, encoding="utf-8", resource_policy=policy)
    if status.err:
        raise RuntimeError(f"PDF rendering failed with {status.err} error(s)")
    data = buf.getvalue()
    if out_path is not None:
        Path(out_path).write_bytes(data)
    return data
