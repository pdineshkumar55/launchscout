"""Source-integrity checks used as task guardrails for stages 1 and 2."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from pydantic import ValidationError

from .models import FeedbackScan, FeedbackScanDraft, MarketScan, MarketScanDraft
from .tools import RunContext, normalize_url

log = logging.getLogger("launchscout.validation")

_STOP = {"the", "and", "of", "by", "co", "pvt", "ltd", "private", "limited", "foods", "food", "kitchen", "&"}


def domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def url_was_seen(ctx: RunContext, url: str) -> bool:
    """True if the URL (or another page on the same site) came back from a search or page read."""
    try:
        norm = normalize_url(url)
    except Exception:
        return False
    if norm in ctx.seen_urls:
        return True
    d = domain(norm)
    return bool(d) and any(domain(u) == d for u in ctx.seen_urls)


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def name_in_text(name: str, text: str) -> bool:
    """Loose match: full name, all distinctive words, or the name squashed together (as in a domain)."""
    low = text.lower().replace("’", "'")
    if not low:
        return False
    if name.lower() in low:
        return True
    words = [w for w in re.findall(r"[a-z0-9]+", name.lower()) if w not in _STOP and len(w) > 2]
    if words and all(w in low for w in words):
        return True
    squashed = _compact(name)
    return len(squashed) >= 5 and squashed in _compact(low)


_LEGAL = {"the", "and", "pvt", "ltd", "private", "limited", "co", "llp", "inc"}


def strict_name_match(name: str, text: str) -> bool:
    """Stricter than name_in_text: every word of the name (bar legal suffixes) must appear.

    Used for review evidence, where a loose match picks up a different business that shares one word
    (e.g. "Revival Foods" vs "Revival Restaurant").
    """
    low = text.lower().replace("’", "'")
    squashed = _compact(name)
    # Squashed form only as a whole token (e.g. a domain "mummyscloudkitchen.in"), never as a prefix:
    # "ragibox" must not match "ragiboxingclub".
    tokens = set(re.split(r"[^a-z0-9]+", low.replace("'", "")))
    if len(squashed) >= 5 and (squashed in tokens or squashed + "s" in tokens):
        return True
    words = [w for w in re.findall(r"[a-z0-9]+", name.lower()) if w not in _LEGAL and len(w) > 1]
    # Whole words, allowing plural/possessive ("box" matches "box's", not "boxing").
    return bool(words) and all(re.search(rf"\b{re.escape(w)}(?:s|'s)?\b", low) for w in words)


def name_was_seen(ctx: RunContext, name: str) -> bool:
    """True if the competitor name appears in any collected text or URL."""
    return name_in_text(name, ctx.all_text() + "\n" + "\n".join(ctx.seen_urls))


REVIEW_SIGNAL = re.compile(
    r"review|rating|rated|stars?\b|testimonial|complain|customers? (say|said|love|like)|feedback|"
    r"\b[1-5](\.\d)?\s*/\s*5\b|recommend|disappoint|worst|tasty|delicious|stale",
    re.I,
)


def text_for_url(ctx: RunContext, url: str) -> str:
    try:
        return ctx.seen_text.get(normalize_url(url), "")
    except Exception:
        return ""


# Listing / review platforms: never treated as a competitor's "own website".
PLATFORM_DOMAINS = (
    "swiggy.com", "zomato.com", "justdial.com", "magicpin.in", "instagram.com", "facebook.com",
    "reddit.com", "youtube.com", "eazydiner.com", "dineout.co.in", "quora.com", "mouthshut.com",
    "x.com", "twitter.com", "linkedin.com", "indiamart.com", "sulekha.com", "trustpilot.com",
    "urbancompany.com", "practo.com", "district.in",
)
# Brand families with country domains (google.com, google.co.in, tripadvisor.in, yelp.com...).
PLATFORM_BRANDS = ("google", "tripadvisor", "yelp")
SOCIAL_DOMAINS = ("facebook.com", "instagram.com", "x.com", "twitter.com", "linkedin.com", "youtube.com")


def _domain_is(d: str, base: str) -> bool:
    return d == base or d.endswith("." + base)


def is_platform(url: str) -> bool:
    d = domain(url)
    if any(_domain_is(d, p) for p in PLATFORM_DOMAINS):
        return True
    labels = d.split(".")
    return any(b in labels[:-1] for b in PLATFORM_BRANDS)  # e.g. maps.google.co.in, tripadvisor.in


def is_own_site(ctx: RunContext, competitor: str, url: str) -> bool:
    """True if the URL is the competitor's own website or its own social media page."""
    d = domain(url)
    squashed = _compact(competitor)
    if any(_domain_is(d, s) for s in SOCIAL_DOMAINS):
        # facebook.com/Pawspace.in -> the brand's own page, not customer feedback
        first = _compact(urlparse(url).path.strip("/").split("/")[0]) if urlparse(url).path.strip("/") else ""
        return len(squashed) >= 4 and bool(first) and squashed[:8] in first
    if is_platform(url):
        return False
    squashed = _compact(competitor)
    if len(squashed) >= 4 and squashed[:8] in _compact(d):
        return True
    words = [w for w in re.findall(r"[a-z0-9]+", competitor.lower()) if w not in _STOP and len(w) > 3]
    if any(w in d for w in words):
        return True
    market = ctx.results.get("market", {})
    ids = next((c["source_ids"] for c in market.get("competitors", [])
                if _compact(c["name"]) == squashed), [])
    own = {domain(s["url"]) for s in market.get("sources", []) if s["id"] in ids and not is_platform(s["url"])}
    return d in own


_GENERIC = set("""some many most customers customer people users report reports reported mention mentions mentioned
find finds found express expressed note noted feel feels felt says said like likes liked love loves appreciate
appreciated praise praised complain complaint complaints issue issues with that this they their there have has
been were also very more less about over rather than from into food meal meals service services option options
offered offers offering place overall good great nice well really quite generally often sometimes being""".split())


def statement_grounded(statement: str, competitor: str, source_text: str) -> bool:
    """A praise/complaint is grounded if a specific word from it appears in its cited source text."""
    low = source_text.lower()
    name_words = set(re.findall(r"[a-z0-9]+", competitor.lower()))
    words = [w for w in re.findall(r"[a-z]+", statement.lower())
             if len(w) >= 4 and w not in _GENERIC and w not in name_words]
    if not words:
        return False
    hits = sum(1 for w in set(words) if w[:5] in low)
    return hits >= min(2, len(set(words)))


# Platform template text that looks like review content but says nothing about the business.
BOILERPLATE = re.compile(
    r"(see all unbiased reviews of [^.;]*|for delivery and dining on \w+|based on user generated reviews,? "
    r"ratings[^.;]*|with \d+ photos|order (food )?online[^.;]*|is a popular food destination[^.;]*)",
    re.I,
)
FIRST_PERSON = re.compile(r"\b(our|we|we're|us)\b", re.I)


ID_MARKER = re.compile(
    r"\s*[\(\[]\s*(?:source\s*)?(?:ids?|sources?|evidence)\s*[:#]?\s*\d+(?:\s*(?:,|and)\s*\d+)*\s*[\)\]]",
    re.I,
)


def strip_id_markers(text: str) -> str:
    """'Good service (id: 4)' -> 'Good service'. Citations are added by the report, not the stage."""
    return ID_MARKER.sub("", text).strip()


def strip_boilerplate(text: str) -> str:
    return re.sub(r"\s{2,}", " ", BOILERPLATE.sub("", text or "")).strip(" .;,")


def _parse(output: Any, draft_cls):
    if getattr(output, "pydantic", None) is not None:
        return draft_cls.model_validate(output.pydantic.model_dump())
    raw = getattr(output, "raw", output)
    m = re.search(r"\{.*\}", raw, re.S)
    return draft_cls.model_validate_json(m.group(0) if m else raw)


def _site_belongs_to(name: str, url: str) -> bool:
    """Name-based check (no run context): is this non-platform URL the business's own website?"""
    if is_platform(url):
        return False
    d = _compact(domain(url).rsplit(".", 1)[0])
    squashed = _compact(name)
    words = [w for w in re.findall(r"[a-z0-9]+", name.lower()) if w not in _STOP | _LEGAL and len(w) > 3]
    return (len(squashed) >= 4 and squashed[:8] in d) or (bool(words) and all(w in d for w in words))


def _is_dead(ctx: RunContext, url: str) -> bool:
    try:
        return normalize_url(url) in ctx.dead_urls
    except Exception:
        return False


def _listing_for(ctx: RunContext, name: str) -> str | None:
    """A Google/listing-platform URL from this run whose recorded text names the business."""
    for url, text in ctx.seen_text.items():
        if is_platform(url) and url not in ctx.dead_urls and strict_name_match(name, text.split(".")[0]):
            return ctx.original_urls.get(url, url)
    return None


def clean_market_scan(draft: MarketScanDraft, ctx: RunContext) -> tuple[dict, list[str]]:
    """Drop competitors without a seen source / seen name. Returns (data, problems)."""
    problems: list[str] = []
    good_sources = {}
    for s in draft.sources:
        if _is_dead(ctx, s.url):
            problems.append(f"Source [{s.id}] {s.url} no longer exists.")
        elif urlparse(s.url).scheme in ("http", "https") and url_was_seen(ctx, s.url):
            good_sources[s.id] = s
        else:
            problems.append(f"Source [{s.id}] {s.url} was not returned by any search or page read.")
    next_id = max([s.id for s in draft.sources] or [0]) + 1
    kept = []
    names = [c.name for c in draft.competitors]
    for c in draft.competitors:
        ids = [i for i in c.source_ids if i in good_sources]
        # Drop another competitor's own website from this competitor's citations.
        ids = [i for i in ids if not any(
            other != c.name and _site_belongs_to(other, good_sources[i].url)
            and not _site_belongs_to(c.name, good_sources[i].url) for other in names)]
        if not ids and (listing := _listing_for(ctx, c.name)):
            # Its website is gone or uncited, but a listing for it came up in this run's searches.
            from .models import SourceDraft
            good_sources[next_id] = SourceDraft(id=next_id, title=f"{c.name} listing", url=listing)
            ids = [next_id]
            next_id += 1
        if not ids:
            problems.append(f"{c.name}: no working source URL from your searches.")
            continue
        if not name_was_seen(ctx, c.name):
            problems.append(f"{c.name}: name does not appear in any search result or page.")
            continue
        if c.location_type not in ("Local", "Online/regional"):
            c.location_type = "Online/regional" if "online" in c.location_type.lower() else "Local"
        c.source_ids = ids
        kept.append(c)
    kept = kept[:5]
    used = {i for c in kept for i in c.source_ids}
    data = {
        "competitors": [c.model_dump() for c in kept],
        "sources": [good_sources[i].model_dump() for i in sorted(used)],
    }
    return data, problems


def apply_relevance(ctx: RunContext, data: dict, idea: str, target: str, final_attempt: bool) -> list[str]:
    """Drop competitors that are not substitutes for the idea. Returns problem messages.

    On the final attempt, if fewer than 3 comparable ones remain, the closest non-comparable ones are
    kept to make up the numbers, with the reason added to their weakness.
    """
    from .relevance import check_relevance  # local import: keeps tests free of the OpenAI client

    by_id = {s["id"]: s["url"] for s in data["sources"]}
    evidence = {c["name"]: " ".join(text_for_url(ctx, by_id[i]) for i in c["source_ids"] if i in by_id)
                for c in data["competitors"]}
    verdicts = check_relevance(idea, target, data["competitors"], evidence, usage=ctx.llm_usage)
    if not verdicts:
        return []
    comparable, other = [], []
    for c in data["competitors"]:
        v = verdicts.get(c["name"], {"comparable": True})
        (comparable if v["comparable"] else other).append((c, v.get("reason", "")))
    problems = [f"{c['name']} is not a substitute for the planned product ({why})." for c, why in other]
    keep = [c for c, _ in comparable]
    if len(keep) < 3 and final_attempt:
        for c, why in other[: 3 - len(keep)]:
            note = f"Not a direct substitute: {why.rstrip('.')}."
            c["weakness"] = f"{note} {c.get('weakness', '')}".strip()
            keep.append(c)
    elif len(keep) < 3:
        return problems  # caller asks for a retry
    used = {i for c in keep for i in c["source_ids"]}
    data["competitors"] = keep
    data["sources"] = [s for s in data["sources"] if s["id"] in used]
    if problems:
        log.info("relevance dropped/flagged: %s", problems)
    return []


def is_own_business(name: str, own_business: str) -> bool:
    """True if a competitor name is the requester's own business ("Sri Example Silks" ~ "Example Silks")."""
    if not own_business.strip():
        return False
    a, b = _compact(name), _compact(own_business)
    if a == b or (min(len(a), len(b)) >= 5 and (a in b or b in a)):
        return True
    return strict_name_match(own_business, name) or strict_name_match(name, own_business)


def fill_from_listings(ctx: RunContext, data: dict, city: str, own_business: str = "", needed: int = 3) -> list[str]:
    """Top up a short competitor list with Google Maps listings returned by this run's searches.

    Used only on the final attempt. Each added competitor is described only by what its listing states
    (name, rating, review count, price range), so nothing is invented. Returns the names added.
    """
    have = [c["name"] for c in data["competitors"]]
    next_id = max([s["id"] for s in data["sources"]] or [0]) + 1
    added = []
    for query, results in ctx.raw_searches.items():
        if city.lower() not in query:
            continue
        for pl in results.get("places", []):
            if len(have) >= needed:
                return added
            # Cite the Google Maps listing itself: it holds the rating and works even if the shop's
            # own website is gone.
            name, url = pl.get("title", "").strip(), pl.get("maps_url") or pl.get("url", "")
            if not name or not url or _is_dead(ctx, url):
                continue
            if any(is_own_business(name, h) for h in have) or is_own_business(name, own_business):
                continue
            rating = f"Rated {pl['rating']}" + (f" from {pl['reviews']} Google reviews" if pl.get("reviews") else "")
            data["sources"].append({"id": next_id, "title": f"{name} on Google Maps", "url": url})
            data["competitors"].append({
                "name": name, "offering": pl.get("type") or "", "price":
                    f"{pl['price']} (Google price range)".replace("₹", "Rs ") if pl.get("price") else "Not listed",
                "price_value": None, "channels": ["Shop (Google Maps listing)"], "offers": None,
                "strength": f"{rating}." if pl.get("rating") else "Listed on Google Maps.",
                "weakness": "No website or public price list found in the searches.",
                "location_type": "Local", "source_ids": [next_id],
            })
            have.append(name)
            added.append(name)
            next_id += 1
    return added


def market_scan_guardrail(ctx: RunContext, idea: str = "", target: str = "", own_business: str = "",
                          city: str = "") -> Callable:
    attempts = {"n": 0}

    def guard(output):
        attempts["n"] += 1
        final = attempts["n"] > 1
        try:
            draft = _parse(output, MarketScanDraft)
        except (ValidationError, ValueError) as exc:
            return False, f"Output was not valid JSON for the required format: {exc}"
        if own_business:
            own = [c.name for c in draft.competitors if is_own_business(c.name, own_business)]
            if own:
                log.info("own business removed from competitors: %s", own)
                draft.competitors = [c for c in draft.competitors if c.name not in own]
        data, problems = clean_market_scan(draft, ctx)
        if problems:
            log.info("market scan dropped: %s", problems)
        if idea and data["competitors"]:
            rel_problems = apply_relevance(ctx, data, idea, target, final_attempt=final)
            if rel_problems:
                return False, (
                    "Fewer than 3 listed businesses compete directly with the planned product. "
                    + " ".join(rel_problems) + " Search for businesses selling a comparable product to the "
                    "same customers (for example restaurants, tiffin or meal services for a meal idea) and "
                    "replace these."
                )
        try:
            MarketScan.model_validate(data)
        except ValidationError:
            if not final:
                return False, (
                    "Each competitor needs a working source URL from your searches, and at least 3 "
                    "competitors are required. Problems: " + " ".join(problems[:8]) +
                    " Search again and only list competitors whose page or listing you found."
                    " If fewer than 3 can be confirmed in this city, add the nearest businesses from "
                    "neighbouring towns or the district's main city, or online sellers that deliver here, "
                    'and set their location_type to "Online/regional".'
                    + (" Keep the requester's own business out of the list." if own_business else "")
                )
            if city and len(data["competitors"]) < 3:
                added = fill_from_listings(ctx, data, city, own_business)
                if added:
                    log.info("added from Google Maps listings: %s", added)
            if not data["competitors"]:
                return False, "No competitor could be confirmed from search results."
            if len(data["competitors"]) < 3:
                log.warning("market scan accepted with %d competitors", len(data["competitors"]))
        ctx.results["market"] = data
        if ctx.after_market:
            ctx.after_market(data)
        return True, json.dumps(data)

    return guard


def _valid_review_source(ctx: RunContext, competitor: str, url: str) -> bool:
    """A review source must mention the competitor and contain review-like text.

    This stops a stage from citing a competitor's plain homepage (or another competitor's
    page) as evidence of what customers say.
    """
    if not url_was_seen(ctx, url) or is_own_site(ctx, competitor, url):
        return False
    text = text_for_url(ctx, url)
    mentions = strict_name_match(competitor, text + " " + url)
    return mentions and bool(REVIEW_SIGNAL.search(text + " " + url))


def feedback_guardrail(ctx: RunContext) -> Callable:
    attempts = {"n": 0}

    def guard(output):
        attempts["n"] += 1
        try:
            draft = _parse(output, FeedbackScanDraft)
        except (ValidationError, ValueError) as exc:
            return False, f"Output was not valid JSON for the required format: {exc}"

        # Every id the stage may cite: market-scan sources, the pre-collected review evidence,
        # plus any new sources the stage found itself.
        market_sources = ctx.results.get("market", {}).get("sources", [])
        known = market_sources + [{"id": e["id"], "title": e["title"], "url": e["url"]}
                                  for e in ctx.results.get("evidence", [])]
        url_by_id: dict[int, str] = {s["id"]: s["url"] for s in known}
        title_by_id: dict[int, str] = {s["id"]: s["title"] for s in known}
        by_url = {normalize_url(s["url"]): s["id"] for s in known}
        next_id = max([s["id"] for s in known] or [0]) + 1
        remap: dict[int, int] = {}
        for s in draft.sources:
            key = normalize_url(s.url)
            if key not in by_url:
                by_url[key] = next_id
                url_by_id[next_id], title_by_id[next_id] = s.url, s.title
                next_id += 1
            remap[s.id] = by_url[key]

        other_location_ids = {e["id"] for e in ctx.results.get("evidence", [])
                              if e.get("text", "").startswith("[other location]")}
        unsupported = []
        for item in draft.items:
            item.praises = [strip_id_markers(p) for p in item.praises]
            item.complaints = [strip_id_markers(c) for c in item.complaints]
            ids = sorted({remap.get(i, i) for i in item.source_ids})
            ids = [i for i in ids if i in url_by_id and _valid_review_source(ctx, item.competitor, url_by_id[i])]
            evidence = " ".join(strip_boilerplate(text_for_url(ctx, url_by_id[i])) for i in ids)
            item.praises = [s for s in item.praises if statement_grounded(s, item.competitor, evidence)]
            item.complaints = [s for s in item.complaints if statement_grounded(s, item.competitor, evidence)]
            if not item.praises and not item.complaints:
                ids = []
            if ids and all(i in other_location_ids for i in ids):
                tag = " (other branch)"
                item.praises = [p if "other branch" in p.lower() else p.rstrip(". ") + tag for p in item.praises]
                item.complaints = [c if "other branch" in c.lower() else c.rstrip(". ") + tag
                                   for c in item.complaints]
            item.source_ids = ids
            if not ids:
                unsupported.append(item.competitor)
                item.praises, item.complaints = [], ["Limited public reviews found"]

        if unsupported and attempts["n"] == 1 and len(unsupported) * 2 >= len(draft.items):
            return False, (
                "Praises and complaints must come from review pages or review snippets that mention the "
                "competitor (Google Maps listings, Zomato or Swiggy reviews, JustDial, Reddit, social "
                "comments). A competitor's own homepage or another competitor's page is not customer "
                f"feedback. No usable review source was cited for: {', '.join(unsupported)}. Cite the review "
                "URLs from your search results. If none exist for a competitor, use "
                '"Limited public reviews found".'
            )

        # Common complaints may only name competitors that still have real feedback.
        supported = {i.competitor for i in draft.items if i.source_ids}
        common = [c for c in draft.common_complaints if sum(name_in_text(n, c) for n in supported) >= 2]

        market_ids = {s["id"] for s in market_sources}
        used = {i for it in draft.items for i in it.source_ids}
        new_sources = [{"id": i, "title": title_by_id[i], "url": url_by_id[i]}
                       for i in sorted(used) if i not in market_ids]
        data = {
            "items": [i.model_dump() for i in draft.items],
            "common_complaints": common,
            "sources": new_sources,
        }
        try:
            FeedbackScan.model_validate(data)
        except ValidationError as exc:
            return False, f"Format problem: {exc}"
        if unsupported:
            log.info("feedback without review sources: %s", unsupported)
        ctx.results["feedback"] = data
        return True, json.dumps(data)

    return guard
