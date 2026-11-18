"""Assembles the final report from the checked stage outputs.

Sections 1, 2 and Sources are always built here from the validated data, so every citation points
to a real source. Sections 3 and 5 use the writer's text when it is present and well-formed (with
its citations renumbered), otherwise they are rebuilt from the Strategy output. Section 4 always
comes from the Strategy output. The report therefore always has all six sections.

When the requester named their own business and it was researched, a "How You Compare" section is
added after the complaints (sections are renumbered) and the plan becomes a "30-Day Growth Plan".
Older runs without that data keep the original layout.
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
COMPARE_KEY = "## How You Compare"
# Heading titles, matched with or without their number, -> the key used by split_sections.
_TITLES = [
    ("Key Competitors", HEADINGS[0]),
    ("What Customers Complain About", HEADINGS[1]),
    ("How You Compare", COMPARE_KEY),
    ("Market Gap", HEADINGS[2]),
    ("Recommended Positioning", HEADINGS[3]),
    ("30-Day (?:Launch|Growth) Plan", HEADINGS[4]),
    ("Sources", HEADINGS[5]),
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


def report_headings(with_compare: bool) -> list[str]:
    if not with_compare:
        return list(HEADINGS)
    return ["## 1. Key Competitors", "## 2. What Customers Complain About", "## 3. How You Compare",
            "## 4. Market Gap", "## 5. Recommended Positioning", "## 6. 30-Day Growth Plan", "## Sources"]


def _heading_re(title: str) -> str:
    return rf"^##\s*(?:\d+\.\s*)?{title}\s*$"


def split_sections(markdown: str) -> dict[str, str]:
    """Return {heading: body} for the known headings found in a writer's Markdown.

    Headings match by title whatever their number ("## 6. 30-Day Growth Plan" is returned under
    "## 5. 30-Day Launch Plan"), so both report layouts parse the same way."""
    out: dict[str, str] = {}
    if not markdown:
        return out
    positions = []
    for title, key in _TITLES:
        m = re.search(_heading_re(title), markdown, re.M | re.I)
        if m:
            positions.append((m.start(), m.end(), key))
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
                 cites: Citations, growth: bool = False) -> str:
    text = writer.get("## 5. 30-Day Launch Plan", "").strip()
    if len(set(WEEK_RE.findall(text))) == 4:
        return cites.remap_text(text)
    channels = sorted({ch for c in market.get("competitors", []) for ch in c.get("channels") or []})
    ch = ", ".join(channels[:3]) or "local delivery apps and social media"
    price = strategy.get("recommended_price") or "the recommended price"
    if growth:
        return "\n".join([
            f"- Week 1: Update the Google listing for {inp.own_business} (photos, hours, price range) and ask "
            "recent customers for a review.",
            f"- Week 2: Post regularly on {ch}; show prices and new stock.",
            f"- Week 3: Test one offer at {price} for {inp.target.lower()} in {inp.city}; track enquiries.",
            "- Week 4: Compare rating, review count and enquiries with week 1; keep what worked.",
        ])
    return "\n".join([
        f"- Week 1: Set up ordering and listings on {ch}; prepare a short menu and pricing at {price}.",
        f"- Week 2: Run a small trial with {inp.target.lower()} in two {inp.city} neighbourhoods; collect feedback.",
        "- Week 3: Fix the issues raised in trial feedback; test one introductory offer against the full price.",
        "- Week 4: Review orders, repeat rate and cost per order; decide which channel to expand.",
    ])


# ------------------------------------------------------------------------------------- how you compare


def _ids_in(text: str) -> list[int]:
    return [int(n) for m in CITE_RE.finditer(text) for n in re.split(r"\s*,\s*", m.group(1))]


def _first_point(items: list, limited_ok: bool = False) -> str:
    for p in items or []:
        text = p["text"] if isinstance(p, dict) else str(p)
        if limited_ok or not text.lower().startswith(LIMITED):
            return text.rstrip(".")
    return ""


def _rating_text(r: dict | None) -> tuple[str, str]:
    if not r or r.get("rating") is None:
        return "Not found", "—"
    return f"{r['rating']}", (f"{r['reviews']:,}" if r.get("reviews") else "—")


def _channel_names(channels) -> set[str]:
    out = set()
    for ch in channels or []:
        low = (ch["name"] if isinstance(ch, dict) else str(ch)).lower()
        for key in ("instagram", "facebook", "whatsapp", "justdial", "website", "google", "swiggy", "zomato",
                    "amazon", "flipkart", "meesho", "youtube", "indiamart"):
            if key in low:
                out.add(key)
    return out


def _names_competitor(text: str, names: list[str]) -> bool:
    low = text.lower()
    return any(n.lower() in low or all(w in low for w in re.findall(r"[a-z0-9]{4,}", n.lower())[:2])
               for n in names)


def _keep_cited(points: list[str], cites: Citations, names: list[str] | None = None) -> list[str]:
    """Strategy points with at least one citation that resolves (and, if names given, naming a competitor)."""
    kept = []
    for p in points or []:
        p = str(p).strip()
        if not p or not any(i in cites.sources for i in _ids_in(p)):
            continue
        if names is not None and not _names_competitor(p, names):
            continue
        kept.append(cites.remap_text(p).rstrip())
    return kept


def _fallback_points(own: dict, market: dict, inp: ResearchInputs) -> tuple[list[str], list[str], list[str]]:
    """Ahead / behind / actions built only from the collected figures, each with stage source ids."""
    ahead, behind, actions = [], [], []
    ratings = own.get("competitor_ratings") or {}
    own_r, own_n = own.get("rating"), own.get("reviews") or 0
    own_ids = "".join(f"[{i}]" for i in own.get("rating_source_ids") or [])
    most_reviews = None
    for c in market.get("competitors", []):
        r = ratings.get(c["name"])
        if not r or r.get("rating") is None:
            continue
        ids = "".join(f"[{i}]" for i in r.get("source_ids") or [])
        if own_r is not None:
            if own_r > r["rating"]:
                ahead.append(f"Higher Google rating than {c['name']} ({own_r} against {r['rating']}) {own_ids}{ids}")
            elif own_r < r["rating"]:
                behind.append(f"{c['name']} has a higher Google rating ({r['rating']} against {own_r}) {ids}{own_ids}")
        if (r.get("reviews") or 0) > max(own_n * 2, 10) and (most_reviews is None
                                                           or r["reviews"] > most_reviews[1]["reviews"]):
            most_reviews = (c, r, ids)
    if most_reviews:
        c, r, ids = most_reviews
        behind.append(f"{c['name']} has {r['reviews']:,} Google reviews against {own_n or 'none found'} for "
                      f"{own['name']} {ids}{own_ids}")
        actions.append(f"Ask satisfied customers for Google reviews: {c['name']} has {r['reviews']:,} reviews "
                       f"{ids}")
    mine = _channel_names(own.get("channels"))
    for c in market.get("competitors", []):
        missing = sorted(_channel_names(c.get("channels")) - mine - {"google", "website"})
        if missing and own.get("found"):
            ids = "".join(f"[{i}]" for i in c.get("source_ids", [])[:1])
            behind.append(f"{c['name']} sells through {missing[0].title()}, where no page for {own['name']} "
                          f"was found {ids}")
            actions.append(f"Open a {missing[0].title()} page; {c['name']} already uses it {ids}")
            break
    if not own.get("found"):
        c = next(iter(market.get("competitors", [])), None)
        ids = "".join(f"[{i}]" for i in (c or {}).get("source_ids", [])[:1])
        actions.append(f"Create or claim a Google Business listing for {own['name']} in {inp.city}, so it appears "
                       f"next to competitors such as {c['name'] if c else 'local rivals'} {ids}".rstrip())
    for p in (own.get("praises") or [])[:1]:
        ids = "".join(f"[{i}]" for i in p.get("source_ids", []))
        actions.append(f"Lean on what customers already praise ({p['text'].rstrip('.').lower()}) in posts and "
                       f"on the listing {ids}")
    if (own.get("price") or "Not listed").lower().startswith("not listed"):
        priced = next((c for c in market.get("competitors", [])
                       if not (c.get("price") or "").lower().startswith("not listed")), None)
        if priced:
            ids = "".join(f"[{i}]" for i in priced.get("source_ids", [])[:1])
            actions.append(f"Publish a price range online; {priced['name']} shows {priced['price']} {ids}")
    return ahead, behind, actions[:5]


def section_compare(inp: ResearchInputs, own: dict, market: dict, feedback: dict, strategy: dict,
                    cites: Citations, price_ok: dict[str, bool], notes: list[str]) -> str:
    name = own.get("name") or inp.own_business
    rows = ["| Business | Rating | Reviews | Price | Channels | Top strength | Top weakness | Sources |",
            "|---|---|---|---|---|---|---|---|"]
    # Your row first.
    rating, reviews = _rating_text(own)
    # Only the sources behind the cells shown: rating, price, one per channel, top praise and complaint.
    own_ids = list(own.get("rating_source_ids") or []) + list(own.get("price_source_ids") or [])
    own_ids += [ch["source_ids"][0] for ch in own.get("channels") or [] if ch.get("source_ids")]
    for group in ("praises", "complaints"):
        own_ids += ((own.get(group) or [{}])[0]).get("source_ids", [])
    channels = ", ".join(ch["name"] for ch in own.get("channels") or []) or "None found"
    strength = _first_point(own.get("praises")) or "—"
    weakness = _first_point(own.get("complaints")) or ("No complaints in public reviews"
                                                         if own.get("praises") else "—")
    price = own.get("price") or "Not listed"
    rows.append(f"| **{_cell(name)} (you)** | {rating} | {reviews} | {_cell(price)} | {_cell(channels)} | "
                f"{_cell(strength)} | {_cell(weakness)} | {cites.cite(own_ids) or '—'} |")
    fb = {i["competitor"]: i for i in feedback.get("items", [])}
    ratings = own.get("competitor_ratings") or {}
    for c in market.get("competitors", []):
        r = ratings.get(c["name"]) or {}
        rating, reviews = _rating_text(r)
        item = fb.get(c["name"]) or {}
        has_reviews = bool(item.get("source_ids"))
        strength = (_first_point(item.get("praises")) if has_reviews else "") or c.get("strength")
        weakness = (_first_point(item.get("complaints")) if has_reviews else "") or c.get("weakness")
        ids = list(c.get("source_ids", [])) + list(r.get("source_ids", [])) + (item.get("source_ids") or [])
        price = _cell(c.get("price"))
        if price.lower() != "not listed" and price_ok.get(c["name"]) is False:
            price = f"{price} {UNVERIFIED_MARK}"
        rows.append(f"| {_cell(c['name'])} | {rating} | {reviews} | {price} | "
                    f"{_cell(', '.join(c.get('channels') or []))} | {_cell(strength).rstrip('.')} | "
                    f"{_cell(weakness).rstrip('.')} | "
                    f"{cites.cite(ids) or '—'} |")
    parts = []
    if own.get("note"):
        parts.append(own["note"])
    parts.append("\n".join(rows))

    names = [c["name"] for c in market.get("competitors", [])]
    ahead = _keep_cited(strategy.get("you_ahead"), cites)
    behind = _keep_cited(strategy.get("competitors_ahead"), cites, names)
    actions = _keep_cited(strategy.get("actions"), cites)
    fa, fbh, fac = _fallback_points(own, market, inp)
    if not ahead and fa:
        ahead = [cites.remap_text(p) for p in fa]
        notes.append("how you compare: 'ahead' points rebuilt from ratings")
    if not behind and fbh:
        behind = [cites.remap_text(p) for p in fbh]
        notes.append("how you compare: 'competitors ahead' points rebuilt from ratings and channels")
    if len(actions) < 3:
        extra = [cites.remap_text(p) for p in fac if p]
        actions = (actions + [a for a in extra if a not in actions])[:5]
        notes.append("how you compare: actions topped up from the collected figures")

    def block(title: str, items: list[str], empty: str) -> str:
        body = "\n".join(f"- {i.rstrip('.') if not i.rstrip().endswith(']') else i}" for i in items) or empty
        return f"**{title}**\n\n{body}"

    parts.append(block("Where you're ahead", ahead, "Not enough public data to show where you lead."))
    parts.append(block("Where competitors are ahead", behind,
                       "Not enough public data to show where competitors lead."))
    parts.append(block("What to fix / what to lean on", actions[:5], "No actions could be drawn from the data."))
    return "\n\n".join(parts)


# ------------------------------------------------------------------------------------- assemble


def assemble(inp: ResearchInputs, market: dict, feedback: dict | None, strategy: dict | None,
             writer_markdown: str | None, price_ok: dict[str, bool] | None = None,
             today: date | None = None, own: dict | None = None) -> tuple[str, list[str]]:
    """Build the final Markdown. Returns (markdown, notes) where notes list any fallbacks used.

    `own` is the own-business scan; when given (and the input names a business) the report gets the
    "How You Compare" section and a growth plan."""
    feedback = feedback or {"items": [], "common_complaints": [], "sources": []}
    strategy = strategy or {}
    price_ok = price_ok or {}
    today = today or date.today()
    notes: list[str] = []

    sources = {s["id"]: {"title": s["title"], "url": str(s["url"])} for s in market.get("sources", [])}
    for s in feedback.get("sources", []):
        sources.setdefault(s["id"], {"title": s["title"], "url": str(s["url"])})
    with_compare = bool(own) and bool(inp.own_business)
    if with_compare:
        for s in own.get("sources", []):
            sources.setdefault(s["id"], {"title": s["title"], "url": str(s["url"])})
    cites = Citations(sources)
    headings = report_headings(with_compare)

    writer = split_sections(writer_markdown or "")
    for h in ("## 3. Market Gap", "## 5. 30-Day Launch Plan"):
        if h not in writer:
            notes.append(f"writer section missing, rebuilt: {h}")

    s1 = section_competitors(market, cites, price_ok)
    s2 = section_complaints(feedback, cites)
    compare = (section_compare(inp, own, market, feedback, strategy, cites, price_ok, notes)
               if with_compare else None)
    s3 = section_gap(writer, strategy, cites)
    s4 = section_positioning(strategy, writer, cites)
    s5 = section_plan(writer, inp, strategy, market, cites, growth=with_compare)
    if s5 != writer.get("## 5. 30-Day Launch Plan", "").strip() and "## 5. 30-Day Launch Plan" in writer:
        notes.append("writer launch plan incomplete, rebuilt")
    src = cites.render() or ["No sources could be confirmed for this run."]

    if with_compare:
        header_note = f"  \n_Your business: {inp.own_business} (compared in How You Compare, not counted as a competitor)_"
    elif inp.own_business:
        header_note = f"  \n_Your business: {inp.own_business} (left out of the competitor list)_"
    else:
        header_note = ""
    body = [s1, s2] + ([compare] if with_compare else []) + [s3, s4, s5]
    sections = []
    for h, text in zip(headings[:-1], body, strict=True):
        sections += ["", h, text]
    md = "\n".join([
        f"# Competitor Report: {inp.idea_title}, {inp.city}",
        f"_Prepared {today:%d %b %Y} · Target customer: {inp.target}_" + header_note,
        *sections,
        "", headings[-1], "  \n".join(src),
        "", "---",
        f"_Based on publicly available information collected on {today:%d %b %Y}. "
        "Verify prices before making decisions._",
        "",
    ])
    return md, notes


# ------------------------------------------------------------------------------------- checks


def check_structure(markdown: str, min_competitors: int = 3) -> dict:
    """Structure check used by tests, checks.json and the benchmark."""
    # Matched by title, so the layout with "How You Compare" (renumbered, growth plan) passes too.
    missing = [key for title, key in _TITLES
               if key != COMPARE_KEY and not re.search(_heading_re(title), markdown, re.M)]
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
