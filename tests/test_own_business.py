"""The requester's own business: matching, the separate scan, the comparison section and the UI.

All data is synthetic (made-up shops and URLs); no network access and no model calls.
"""

import copy
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from launchscout.events import OWN_STAGE, stage_done, stage_order
from launchscout.models import ResearchInputs
from launchscout.own_business import city_in, not_found_note, render_own_block, scan_own_business
from launchscout.report import assemble, check_structure, split_sections
from launchscout.tools import RunContext
from launchscout.validation import is_own_business

OWN = "Sri Example Silks"
CITY = "Testcity"
MAPS_HERE = "https://www.google.com/maps/place/?q=place_id:HERE"
MAPS_ELSEWHERE = "https://www.google.com/maps/place/?q=place_id:ELSEWHERE"
INSTA = "https://www.instagram.com/sri_example_silks/"
JD = "https://www.justdial.com/Testcity/Sri-Example-Silks"
EVIDENCE = [{"id": 7, "competitor": "Ragi Box", "title": "Ragi Box on Google", "url": "https://maps.google.com/?cid=7",
             "text": "Google rating 4.5 from 300 reviews"}]
SEARCHES = {
    f"{OWN} {CITY}".lower(): {
        "listing": None,
        "places": [
            {"title": "Sri Example Silk Sarees", "url": MAPS_HERE, "maps_url": MAPS_HERE, "rating": 4.2,
             "reviews": 40, "price": None, "type": "Saree store", "address": "12 Main Rd, Testcity 600001"},
            # Same name, different town: must be ignored.
            {"title": OWN, "url": MAPS_ELSEWHERE, "maps_url": MAPS_ELSEWHERE, "rating": 4.9, "reviews": 900,
             "price": None, "type": "Saree store", "address": "Othertown 600002"},
        ],
        "organic": [{"title": "Sri Example Silks (@sri_example_silks) • Testcity", "link": INSTA,
                     "snippet": "Silk sarees from Rs 4,500. Testcity."}],
    },
    f"{OWN} {CITY} reviews".lower(): {
        "listing": None, "places": [],
        "organic": [{"title": "Sri Example Silks in Testcity - JustDial", "link": JD,
                     "snippet": "Rated 4.1 from 25 reviews. Good collection of Kanchipuram sarees. "
                                "Billing is slow on weekends."}],
    },
}


def make_ctx(searches: dict) -> RunContext:
    ctx = RunContext(use_cache=False)
    for q, data in searches.items():  # pre-filled: run_search returns the memo, no network
        ctx.raw_searches[q] = data
        ctx._search_memo[q] = "results"
    for q in (f"{OWN} {CITY}", f"{OWN} {CITY} reviews", f"{OWN} {CITY} instagram justdial"):
        ctx._search_memo.setdefault(q.lower(), "No results")
    return ctx


def fake_summary(calls: list):
    def summarize(name, items, usage=None):
        calls.append(items)
        by_title = {i["title"]: i["id"] for i in items}
        jd, insta = by_title["Sri Example Silks in Testcity - JustDial"], by_title[
            "Sri Example Silks (@sri_example_silks) • Testcity"]
        return {
            "praises": [{"text": "Good collection of Kanchipuram sarees", "source_ids": [jd]},
                        {"text": "Very friendly owners", "source_ids": [jd]},          # not in the source
                        {"text": "Silk sarees from Rs 4,500", "source_ids": [insta]}],  # not a review
            "complaints": [{"text": "Billing is slow on weekends", "source_ids": [jd]}],
            "price": {"text": "Rs 4,500 per saree", "source_ids": [insta]},
        }
    return summarize


@pytest.fixture
def own_scan(market) -> dict:
    ctx = make_ctx(SEARCHES)
    inp = ResearchInputs(idea="silk saree shop", city=CITY, own_business=OWN)
    return scan_own_business(ctx, inp, 10, market, EVIDENCE, summarizer=fake_summary([]))


# ------------------------------------------------------------------------------ matching


@pytest.mark.parametrize("name,expected", [
    ("Sri Example Silk Sarees", True),
    ("Example Silks", True),
    ("SRI EXAMPLE SILKS & Sarees", True),
    ("Example Bakery", False),
    ("ST Silks", False),
])
def test_loose_name_match(name, expected):
    assert is_own_business(name, OWN) is expected


@pytest.mark.parametrize("text,city,expected", [
    ("9, Main Rd, Udumalaipettai, Tamil Nadu 642203", "Udumalpet", True),   # local spelling
    ("12 Main Rd, Testcity", "Testcity", True),
    ("Othertown 600002", "Testcity", False),
    ("", "Testcity", False),
])
def test_city_in(text, city, expected):
    assert city_in(text, city) is expected


# ------------------------------------------------------------------------------ scan


def test_scan_collects_grounded_facts(own_scan):
    s = own_scan
    assert s["found"] and s["note"] == ""
    assert (s["rating"], s["reviews"]) == (4.2, 40)                       # the Testcity listing
    assert all(src["url"] != MAPS_ELSEWHERE for src in s["sources"])     # same-name shop elsewhere ignored
    assert [c["name"] for c in s["channels"]] == ["Walk-in shop (Google listing)", "Instagram", "JustDial"]
    assert [p["text"] for p in s["praises"]] == ["Good collection of Kanchipuram sarees"]
    assert [p["text"] for p in s["complaints"]] == ["Billing is slow on weekends"]
    assert s["price"] == "Rs 4,500 per saree"
    assert min(src["id"] for src in s["sources"]) >= 7 and s["competitor_ratings"]["Ragi Box"]["rating"] == 4.5


def test_scan_skips_redirects_and_merges_url_variants(market, monkeypatch):
    from types import SimpleNamespace
    read = []
    monkeypatch.setattr("launchscout.own_business.make_scrape_tool",
                        lambda ctx: SimpleNamespace(_run=lambda website_url: read.append(website_url)))
    searches = copy.deepcopy(SEARCHES)
    searches[f"{OWN} {CITY}".lower()]["organic"] += [
        {"title": "Sri Example Silks • Testcity", "link": "https://www.google.com/goto?url=CAESabc",
         "snippet": "Sri Example Silks, Testcity."},
        {"title": "Sri Example Silks | Testcity", "link": "https://sriexamplesilks.com/", "snippet": "Testcity"},
        {"title": "Sri Example Silks | Testcity", "link": "http://www.sriexamplesilks.com/", "snippet": "Testcity"},
    ]
    ctx = make_ctx(searches)
    ctx.seen_text["https://sriexamplesilks.com"] = "Sri Example Silks. Handloom sarees."
    inp = ResearchInputs(idea="silk saree shop", city=CITY, own_business=OWN)
    s = scan_own_business(ctx, inp, 10, market, [], summarizer=lambda *a, **k: {})
    urls = [src["url"] for src in s["sources"]]
    assert not any("goto" in u for u in urls)
    assert sum("sriexamplesilks.com" in u for u in urls) == 1
    own_site = next(c for c in s["channels"] if c["name"] == "Own website")
    assert len(own_site["source_ids"]) == 1 and read == ["https://sriexamplesilks.com/"]


def test_price_and_praise_cleaned(market):
    def summarize(name, items, usage=None):
        by_title = {i["title"]: i["id"] for i in items}
        insta = by_title["Sri Example Silks (@sri_example_silks) • Testcity"]
        jd = by_title["Sri Example Silks in Testcity - JustDial"]
        return {"praises": [{"text": "Good collection of Kanchipuram sarees ❤️😍", "source_ids": [jd]}],
                "complaints": [], "price": {"text": "4,500/-free shipping", "source_ids": [insta]}}
    inp = ResearchInputs(idea="silk saree shop", city=CITY, own_business=OWN)
    s = scan_own_business(make_ctx(SEARCHES), inp, 10, market, [], summarizer=summarize)
    assert s["price"] == "Rs 4,500 (as posted on Instagram)"
    assert s["praises"][0]["text"] == "Good collection of Kanchipuram sarees"


def test_scan_drops_price_not_in_source(market):
    def summarize(name, items, usage=None):
        return {"praises": [], "complaints": [], "price": {"text": "Rs 9,999 per saree",
                                                          "source_ids": [items[0]["id"]]}}
    inp = ResearchInputs(idea="silk saree shop", city=CITY, own_business=OWN)
    s = scan_own_business(make_ctx(SEARCHES), inp, 10, market, [], summarizer=summarize)
    assert s["price"] == "Not listed" and s["price_source_ids"] == []


def test_scan_not_found_says_so_and_invents_nothing(market):
    calls = []
    inp = ResearchInputs(idea="silk saree shop", city=CITY, own_business=OWN)
    s = scan_own_business(make_ctx({}), inp, 10, market, [], summarizer=fake_summary(calls))
    assert not s["found"] and s["note"] == not_found_note(OWN, CITY)
    assert s["note"] == "No public listing or reviews found for Sri Example Silks in Testcity."
    assert s["rating"] is None and s["praises"] == [] and s["channels"] == [] and s["price"] == "Not listed"
    assert calls == []  # no model call without sources


def test_scan_has_its_own_search_allowance(market):
    ctx = make_ctx(SEARCHES)
    before = (ctx.max_searches, ctx.max_fetches)
    inp = ResearchInputs(idea="silk saree shop", city=CITY, own_business=OWN)
    scan_own_business(ctx, inp, 10, market, [], summarizer=lambda *a, **k: {})
    assert (ctx.max_searches, ctx.max_fetches) == (before[0] + 3, before[1] + 2)


def test_own_block_for_prompts(own_scan, market):
    block = render_own_block(own_scan, market)
    assert block.startswith("<own_business>") and "Google rating: 4.2 from 40 reviews" in block
    assert "Competitor rating: Ragi Box 4.5 from 300 reviews [7]" in block


# ------------------------------------------------------------------------------ report


def _strategy(strategy: dict, scan: dict) -> dict:
    ids = {s["url"]: s["id"] for s in scan["sources"]}
    s = copy.deepcopy(strategy)
    s["you_ahead"] = [f"More Kanchipuram sarees on display than Ragi Box [{ids[JD]}]", "Uncited claim"]
    s["competitors_ahead"] = [f"Ragi Box has a higher Google rating (4.5 against 4.2) [7][{ids[MAPS_HERE]}]",
                              "Someone is ahead [1]"]
    s["actions"] = [f"Ask recent customers for Google reviews [{ids[MAPS_HERE]}]",
                    f"Post new stock on Instagram every week [{ids[INSTA]}]",
                    f"Add a second billing counter for weekends [{ids[JD]}]"]
    return s


def test_compare_section_layout_and_citations(own_scan, market, feedback, strategy, writer_md):
    inp = ResearchInputs(idea="silk saree shop", city=CITY, own_business=OWN)
    md, _ = assemble(inp, market, feedback, _strategy(strategy, own_scan), writer_md,
                     today=date(2026, 11, 18), own=own_scan)
    order = ["## 1. Key Competitors", "## 2. What Customers Complain About", "## 3. How You Compare",
             "## 4. Market Gap", "## 5. Recommended Positioning", "## 6. 30-Day Growth Plan", "## Sources"]
    assert [md.index(h) for h in order] == sorted(md.index(h) for h in order)
    s = check_structure(md)
    assert s["sections_ok"] and s["citations_ok"] and s["competitors"] == 3, s
    compare = split_sections(md)["## How You Compare"]
    assert "| **Sri Example Silks (you)** | 4.2 | 40 | Rs 4,500 per saree |" in compare
    assert "| Ragi Box | 4.5 | 300 |" in compare
    assert "**Where you're ahead**" in compare and "**What to fix / what to lean on**" in compare
    assert "Uncited claim" not in md and "Someone is ahead" not in md
    assert "Ask recent customers for Google reviews" in compare
    assert "compared in How You Compare" in md


def test_compare_when_business_not_found(market, feedback, strategy, writer_md):
    inp = ResearchInputs(idea="silk saree shop", city=CITY, own_business=OWN)
    scan = scan_own_business(make_ctx({}), inp, 10, market, [], summarizer=lambda *a, **k: {})
    md, notes = assemble(inp, market, feedback, strategy, writer_md, today=date(2026, 11, 18), own=scan)
    compare = split_sections(md)["## How You Compare"]
    assert compare.startswith("No public listing or reviews found for Sri Example Silks in Testcity.")
    assert "| **Sri Example Silks (you)** | Not found |" in compare
    assert "Create or claim a Google Business listing" in compare
    assert check_structure(md)["citations_ok"]


def test_old_runs_keep_original_layout(inp, market, feedback, strategy, writer_md):
    # No own-business data (older run or field left empty): no comparison, launch plan as before.
    for i in (inp, ResearchInputs(idea="silk saree shop", city=CITY, own_business=OWN)):
        md, _ = assemble(i, market, feedback, strategy, writer_md, today=date(2026, 11, 18), own=None)
        assert "How You Compare" not in md and "## 5. 30-Day Launch Plan" in md


def test_growth_plan_from_writer_is_used(own_scan, market, feedback, strategy):
    writer = ("## 6. 30-Day Growth Plan\n- Week 1: Ask for reviews [1].\n- Week 2: Post stock.\n"
              "- Week 3: Test an offer.\n- Week 4: Review results.\n")
    inp = ResearchInputs(idea="silk saree shop", city=CITY, own_business=OWN)
    md, _ = assemble(inp, market, feedback, strategy, writer, today=date(2026, 11, 18), own=own_scan)
    assert "- Week 1: Ask for reviews [1]." in split_sections(md)["## 5. 30-Day Launch Plan"]


# ------------------------------------------------------------------------------ stage 1 prompt and retry


def test_stage1_prompt_only_changes_when_business_named():
    from launchscout import tasks
    captured = {}
    orig = tasks.Task
    tasks.Task = lambda **kw: captured.setdefault("t", kw)
    try:
        tasks.market_scan_task(None, ResearchInputs(idea="silk saree shop", city=CITY), RunContext())
        plain = captured.pop("t")["description"]
        tasks.market_scan_task(None, ResearchInputs(idea="silk saree shop", city=CITY, own_business=OWN),
                               RunContext())
        named = captured.pop("t")["description"]
    finally:
        tasks.Task = orig
    assert "does not count" not in plain and "shops near" not in plain
    assert f"{OWN} is the requester's own business. It does not count towards the 3 to 5" in named
    assert f'"<core keyword> shops near {CITY}"' in named


def test_retry_names_removed_own_business(ctx, market, monkeypatch):
    from types import SimpleNamespace

    from launchscout.validation import market_scan_guardrail
    monkeypatch.setattr("launchscout.relevance.check_relevance",
                        lambda idea, target, comps, ev, **k: {c["name"]: {"comparable": True} for c in comps})
    guard = market_scan_guardrail(ctx, own_business="Ragi Box", city=CITY)
    ok, msg = guard(SimpleNamespace(pydantic=None, raw=json.dumps(market)))
    assert not ok and "Ragi Box is the requester's own business and was removed; it does not count" in msg


# ------------------------------------------------------------------------------ progress and UI


def test_stage_order_and_messages():
    assert stage_order(False) == [1, 2, 3, 4] and stage_order(True) == [1, OWN_STAGE, 2, 3, 4]
    assert stage_done(OWN_STAGE, {"found": True, "rating": 4.2, "reviews": 40}).text == \
        "Your business scan complete: rated 4.2 from 40 reviews"
    assert stage_done(OWN_STAGE, {"found": False}).text == "Your business scan complete: no public listing found"


def _saved_run(root: Path, own: dict | None, md: str) -> Path:
    d = root / "silk-saree-shop-testcity_20261118_120000"
    d.mkdir(parents=True)
    raw = {"inputs": {"idea": "silk saree shop", "city": CITY, "own_business": OWN},
           "market": {"competitors": [], "sources": []}, "feedback": None}
    if own is not None:
        raw["own"] = own
    (d / "raw.json").write_text(json.dumps(raw), encoding="utf-8")
    (d / "report.md").write_text(md, encoding="utf-8")
    (d / "checks.json").write_text("{}", encoding="utf-8")
    return d


@pytest.mark.parametrize("with_own", [True, False])
def test_app_opens_runs_with_and_without_own_data(tmp_path, monkeypatch, own_scan, with_own):
    from streamlit.testing.v1 import AppTest

    from launchscout import config
    from ui import copy as c
    monkeypatch.setattr(config, "settings", replace(config.settings, access_code=""))
    d = _saved_run(tmp_path, own_scan if with_own else None, "# Competitor Report: x\n\n## 1. Key Competitors\n")
    at = AppTest.from_file(str(Path(__file__).resolve().parent.parent / "app.py"), default_timeout=30)
    at.session_state["view_dir"] = str(d)
    at.run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert (c.OWN_CARD_HEADER.format(name=OWN) in text) is with_own
