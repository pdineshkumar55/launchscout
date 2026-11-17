"""Assembles the final report from the checked stage outputs.

Sections 1, 2 and Sources are always built here from the validated data, so every citation points
to a real source. Sections 3 and 5 use the writer's text when it is present and well-formed (with
its citations renumbered), otherwise they are rebuilt from the Strategy output. Section 4 always
comes from the Strategy output. The report therefore always has all six sections.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .models import ResearchInputs

HEADINGS = [
    "## 1. Key Competitors",
    "## 2. What Customers Complain About",
    "## 3. Market Gap",
    "## 4. Recommended Positioning",
    "## 5. 30-Day Launch Plan",
    "## Sources",
]
UNVERIFIED_MARK = "(price not confirmed on source)"
LIMITED = "limited public reviews found"
CITE_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


@dataclass
class Citations:
    """Maps stage source ids to final report numbers in order of first use."""

    sources: dict[int, dict]  # stage id -> {"title", "url"}
    order: list[int] = field(default_factory=list)  # stage ids in report order
    _by_url: dict[str, int] = field(default_factory=dict)

    def cite(self, ids: list[int]) -> str:
        nums = []
        for i in ids:
            if i not in self.sources:
                continue
            url = self.sources[i]["url"]
            canonical = self._by_url.setdefault(url, i)  # same URL under two ids -> one number
            if canonical not in self.order:
                self.order.append(canonical)
            n = self.order.index(canonical) + 1
            if n not in nums:
                nums.append(n)
        return "".join(f"[{n}]" for n in sorted(nums))

    def remap_text(self, text: str) -> str:
        """Renumber [n] markers written with stage ids; drop markers that match no source."""
        def repl(m: re.Match) -> str:
            ids = [int(x) for x in re.split(r"\s*,\s*", m.group(1))]
            return self.cite(ids)
        return CITE_RE.sub(repl, text)

    def render(self) -> list[str]:
        return [f"[{n}] {self.sources[i]['title']} — {self.sources[i]['url']}"
                for n, i in enumerate(self.order, start=1)]


def _cell(text: str | None) -> str:
    return " ".join(str(text or "").split()).replace("|", "/") or "—"


def split_sections(markdown: str) -> dict[str, str]:
    """Return {heading: body} for the known headings found in a writer's Markdown."""
    out: dict[str, str] = {}
    if not markdown:
        return out
    positions = []
    for h in HEADINGS:
        m = re.search(rf"^{re.escape(h)}\s*$", markdown, re.M | re.I)
        if m:
            positions.append((m.start(), m.end(), h))
    positions.sort()
    for idx, (_, end, h) in enumerate(positions):
        stop = positions[idx + 1][0] if idx + 1 < len(positions) else len(markdown)
        out[h] = markdown[end:stop].strip()
    return out


# ------------------------------------------------------------------------------------- sections


def section_competitors(market: dict, cites: Citations, price_ok: dict[str, bool]) -> str:
    rows = ["| Competitor | Price | Channel | Strength | Weakness | Source |", "|---|---|---|---|---|---|"]
    for c in market.get("competitors", []):
        name = c["name"] + (" (online/regional)" if c.get("location_type") == "Online/regional" else "")
        ref = cites.cite(c.get("source_ids", []))
        price = _cell(c.get("price"))
        if price.lower() != "not listed" and price_ok.get(c["name"]) is False:
            price = f"{price} {UNVERIFIED_MARK}"
        rows.append(f"| {_cell(name)} | {price} | {_cell(', '.join(c.get('channels') or []))} | "
                    f"{_cell(c.get('strength'))} | {_cell(c.get('weakness'))} | {ref or '—'} |")
    return "\n".join(rows)


def section_complaints(feedback: dict, cites: Citations) -> str:
    items = feedback.get("items", [])
    real = [i for i in items if i.get("source_ids")]
    limited = [i["competitor"] for i in items if not i.get("source_ids")]
    ids_for = {i["competitor"]: i["source_ids"] for i in real}

    lines: list[str] = []
    used_complaints: set[str] = set()
    for common in feedback.get("common_complaints", []):
        names = [n for n in ids_for if n.lower() in common.lower()]
        ids = [s for n in names for s in ids_for[n]]
        lines.append(f"- {common.rstrip('.')} {cites.cite(ids)}".rstrip())
    for i in real:
        for comp in i.get("complaints", []):
            if comp.lower().startswith(LIMITED) or comp.lower() in used_complaints:
                continue
            used_complaints.add(comp.lower())
            lines.append(f"- {comp.rstrip('.')} ({i['competitor']}) {cites.cite(i['source_ids'])}")
    if not lines:
        lines.append("- No complaints were found in the public reviews collected for these competitors.")

    praise = []
    for i in real:
        for p in i.get("praises", [])[:2]:
            praise.append(f"- {p.rstrip('.')} ({i['competitor']}) {cites.cite(i['source_ids'])}")
    body = "\n".join(lines)
    if praise:
        # Blank line before the list: strict Markdown (and the PDF) needs it to start a list.
        body += "\n\n**What customers praise:**\n\n" + "\n".join(praise)
    if limited:
        body += f"\n\nLimited public reviews found for: {', '.join(limited)}."
    return body


def section_gap(writer: dict[str, str], strategy: dict, cites: Citations) -> str:
    """The Strategy stage's gap statement is preferred: the writer tends to add general claims about
    customers that the feedback does not support. The writer's text is the fallback."""
    gap = strategy.get("market_gap", "").strip()
    if gap:
        return cites.remap_text(gap)
    text = writer.get("## 3. Market Gap", "").strip()
    if len(text) >= 40:
        return cites.remap_text(text)
    return "Not enough public information to identify a clear gap."


def section_positioning(strategy: dict, writer: dict[str, str], cites: Citations) -> str:
    line = strategy.get("positioning_line", "").strip().strip('"')
    why = strategy.get("price_rationale", "").strip()
    if line:
        return f'> "{line}"\n\nWhy this price: {why}'.rstrip()
    text = writer.get("## 4. Recommended Positioning", "").strip()
    return cites.remap_text(text) if text else "No positioning could be recommended from the data collected."


WEEK_RE = re.compile(r"^\s*[-*]\s*\**week\s*([1-4])\**\s*[:.-]", re.I | re.M)


def section_plan(writer: dict[str, str], inp: ResearchInputs, strategy: dict, market: dict,
                 cites: Citations) -> str:
    text = writer.get("## 5. 30-Day Launch Plan", "").strip()
    if len(set(WEEK_RE.findall(text))) == 4:
        return cites.remap_text(text)
    channels = sorted({ch for c in market.get("competitors", []) for ch in c.get("channels") or []})
    ch = ", ".join(channels[:3]) or "local delivery apps and social media"
    price = strategy.get("recommended_price") or "the recommended price"
    return "\n".join([
        f"- Week 1: Set up ordering and listings on {ch}; prepare a short menu and pricing at {price}.",
        f"- Week 2: Run a small trial with {inp.target.lower()} in two {inp.city} neighbourhoods; collect feedback.",
        "- Week 3: Fix the issues raised in trial feedback; test one introductory offer against the full price.",
        "- Week 4: Review orders, repeat rate and cost per order; decide which channel to expand.",
    ])


# ------------------------------------------------------------------------------------- assemble


def assemble(inp: ResearchInputs, market: dict, feedback: dict | None, strategy: dict | None,
             writer_markdown: str | None, price_ok: dict[str, bool] | None = None,
             today: date | None = None) -> tuple[str, list[str]]:
    """Build the final Markdown. Returns (markdown, notes) where notes list any fallbacks used."""
    feedback = feedback or {"items": [], "common_complaints": [], "sources": []}
    strategy = strategy or {}
    price_ok = price_ok or {}
    today = today or date.today()
    notes: list[str] = []

    sources = {s["id"]: {"title": s["title"], "url": str(s["url"])} for s in market.get("sources", [])}
    for s in feedback.get("sources", []):
        sources.setdefault(s["id"], {"title": s["title"], "url": str(s["url"])})
    cites = Citations(sources)

    writer = split_sections(writer_markdown or "")
    for h in ("## 3. Market Gap", "## 5. 30-Day Launch Plan"):
        if h not in writer:
            notes.append(f"writer section missing, rebuilt: {h}")

    s1 = section_competitors(market, cites, price_ok)
    s2 = section_complaints(feedback, cites)
    s3 = section_gap(writer, strategy, cites)
    s4 = section_positioning(strategy, writer, cites)
    s5 = section_plan(writer, inp, strategy, market, cites)
    if s5 != writer.get("## 5. 30-Day Launch Plan", "").strip() and "## 5. 30-Day Launch Plan" in writer:
        notes.append("writer launch plan incomplete, rebuilt")
    src = cites.render() or ["No sources could be confirmed for this run."]

    md = "\n".join([
        f"# Competitor Report: {inp.idea_title}, {inp.city}",
        f"_Prepared {today:%d %b %Y} · Target customer: {inp.target}_"
        + (f"  \n_Your business: {inp.own_business} (left out of the competitor list)_" if inp.own_business else ""),
        "", HEADINGS[0], s1,
        "", HEADINGS[1], s2,
        "", HEADINGS[2], s3,
        "", HEADINGS[3], s4,
        "", HEADINGS[4], s5,
        "", HEADINGS[5], "  \n".join(src),
        "", "---",
        f"_Based on publicly available information collected on {today:%d %b %Y}. "
        "Verify prices before making decisions._",
        "",
    ])
    return md, notes


# ------------------------------------------------------------------------------------- checks


def check_structure(markdown: str, min_competitors: int = 3) -> dict:
    """Structure check used by tests, checks.json and the benchmark."""
    missing = [h for h in HEADINGS if not re.search(rf"^{re.escape(h)}\s*$", markdown, re.M)]
    body, _, sources_part = markdown.partition("## Sources")
    cited = {int(n) for m in CITE_RE.finditer(body) for n in re.split(r"\s*,\s*", m.group(1))}
    listed = {int(n) for n in re.findall(r"^\[(\d+)\]", sources_part, re.M)}
    table = markdown.split(HEADINGS[0], 1)[-1].split("## 2.", 1)[0]
    competitors = max(0, len([ln for ln in table.splitlines() if ln.startswith("|")]) - 2)
    return {
        "sections_ok": not missing,
        "missing_sections": missing,
        "competitors": competitors,
        "enough_competitors": competitors >= min_competitors,
        "unresolved_citations": sorted(cited - listed),
        "unused_sources": sorted(listed - cited),
        "citations_ok": not (cited - listed) and not (listed - cited),
    }
