"""Post-run steps shared by the CLI and the web app: assemble, sanitize, check, save.

`finalize()` works from plain data (no CrewAI objects), so a finished run can be re-assembled
offline from its saved folder (raw.json + seen_text.json) without any API cost.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from slugify import slugify

from .checks import grade_prices, run_checks
from .config import settings
from .models import ResearchInputs
from .report import assemble
from .sanitize import sanitize

log = logging.getLogger("launchscout.pipeline")


@dataclass
class FinalReport:
    markdown: str
    checks: dict
    notes: list[str]
    run_dir: Path


def finalize(inp: ResearchInputs, market: dict, feedback: dict | None, strategy: dict | None,
             writer_markdown: str | None, seen_text: dict[str, str], run_dir: Path,
             check_links: bool = True, own: dict | None = None) -> FinalReport:
    prices = grade_prices(market, seen_text)
    price_ok = {name: p["status"] != "unverified" for name, p in prices.items()}
    markdown, notes = assemble(inp, market, feedback, strategy, writer_markdown, price_ok, own=own)
    markdown, cleaning = sanitize(markdown)
    checks = run_checks(markdown, market, prices, check_links=check_links)
    checks["sanitizer"] = cleaning
    checks["assembly_notes"] = notes

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.md").write_text(markdown, encoding="utf-8")
    (run_dir / "checks.json").write_text(json.dumps(checks, indent=2, ensure_ascii=False), encoding="utf-8")
    write_pdf(markdown, run_dir)
    return FinalReport(markdown, checks, notes, run_dir)


def write_pdf(markdown: str, run_dir: Path) -> Path | None:
    """Create report.pdf next to report.md. A PDF failure never fails the run (Markdown is still there)."""
    try:
        from .pdf import markdown_to_pdf
        path = run_dir / "report.pdf"
        markdown_to_pdf(markdown, path)
        return path
    except Exception as exc:
        log.error("PDF export failed for %s: %s", run_dir.name, exc)
        return None


def refinalize(run_dir: Path, check_links: bool = True) -> FinalReport:
    """Re-assemble a saved run from raw.json + seen_text.json (no API calls except link checks)."""
    raw = json.loads((run_dir / "raw.json").read_text(encoding="utf-8"))
    seen_path = run_dir / "seen_text.json"
    seen = json.loads(seen_path.read_text(encoding="utf-8")) if seen_path.exists() else {}
    inp = ResearchInputs(**raw["inputs"])
    return finalize(inp, raw["market"], raw.get("feedback"), raw.get("strategy"),
                    raw.get("report_markdown"), seen, run_dir, check_links=check_links, own=raw.get("own"))


def new_run_dir(inp: ResearchInputs) -> Path:
    slug = slugify(f"{inp.idea}-{inp.city}")[:60] or "report"
    run_dir = settings.outputs_dir / f"{slug}_{datetime.now():%Y%m%d_%H%M%S}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def save_run(run_dir: Path, raw: dict, seen_text: dict[str, str]) -> None:
    (run_dir / "raw.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
    (run_dir / "seen_text.json").write_text(json.dumps(seen_text, ensure_ascii=False), encoding="utf-8")


@dataclass
class SavedRun:
    run_dir: Path
    inputs: dict
    created: datetime
    markdown: str
    market: dict
    sources: list[dict]
    own: dict | None = None  # the requester's own business scan; None for older runs or when not asked

    @property
    def label(self) -> str:
        idea = self.inputs.get("idea", "Report")
        return f"{idea[:1].upper() + idea[1:]}, {self.inputs.get('city', '')}"


def load_run(run_dir: Path) -> SavedRun | None:
    try:
        markdown = (run_dir / "report.md").read_text(encoding="utf-8")
        raw = json.loads((run_dir / "raw.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    market = raw.get("market") or {}
    sources = list(market.get("sources", [])) + list((raw.get("feedback") or {}).get("sources", []))
    own = raw.get("own") if isinstance(raw.get("own"), dict) else None
    if own:
        sources += list(own.get("sources", []))
    created = datetime.fromtimestamp((run_dir / "report.md").stat().st_mtime)
    return SavedRun(run_dir, raw.get("inputs", {}), created, markdown, market, sources, own)


def list_runs(root: Path | None = None, limit: int = 30) -> list[SavedRun]:
    """Finished runs (folders with report.md), newest first."""
    root = root or settings.outputs_dir
    if not root.exists():
        return []
    # checks.json marks a run finished by the current pipeline (older dev runs are skipped).
    dirs = sorted((d for d in root.iterdir() if (d / "report.md").exists() and (d / "checks.json").exists()),
                  key=lambda d: (d / "report.md").stat().st_mtime, reverse=True)
    runs = [load_run(d) for d in dirs[:limit]]
    return [r for r in runs if r is not None]


def print_checks(checks: dict) -> None:
    s, src, pr = checks["structure"], checks["sources"], checks["prices"]
    print(f"Structure:   sections {'OK' if s['sections_ok'] else 'MISSING ' + str(s['missing_sections'])}"
          f" | competitors {s['competitors']} | citations {'OK' if s['citations_ok'] else s}")
    print(f"Sources:     {src['total']} cited | ok {src['ok']} | blocked {src['blocked']} | "
          f"timeout {src.get('timeout', 0)} | broken {src['broken']}"
          f" | reachable {src['reachable_pct']}%")
    print(f"Prices:      {pr['verified']}/{pr['with_price']} verified ({pr['verified_pct']}%)")
    cl = checks.get("sanitizer", {})
    changed = {k: v for k, v in cl.items() if v and k != "watch_words"}
    print(f"Sanitizer:   {changed or 'no changes'}" + (f" | watch words: {cl['watch_words']}" if cl.get("watch_words") else ""))
    if checks.get("assembly_notes"):
        print(f"Assembly:    {checks['assembly_notes']}")
