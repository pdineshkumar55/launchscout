from dataclasses import replace

import pytest
import requests

from launchscout import search
from launchscout.evidence import collect_review_evidence, render_evidence
from launchscout.tools import RunContext, format_search_results, normalize_url

SERPAPI_RAW = {
    "organic_results": [{"title": "Ragi Box reviews", "link": "https://www.zomato.com/testcity/ragi-box/reviews",
                         "snippet": "Rated 4.0. Fresh food. Delivery was late."}],
    "local_results": {"places": [{"title": "Ragi Box", "rating": 4.2, "reviews": 120, "price": "₹200–400",
                                  "address": "Main Rd, Testcity", "place_id": "P1"}]},
    "knowledge_graph": {"title": "Ragi Box", "place_id": "KG1", "rating": 4.3, "review_count": 95,
                        "website": "https://ragibox.example/",
                        "user_reviews": [{"summary": "Tasty millet meals", "user": {"name": "Private Person"}}]},
}
SERPER_RAW = {
    "organic": [{"title": "Ragi Box", "link": "https://ragibox.example/", "snippet": "Order millet meals."}],
    "places": [{"title": "Ragi Box", "address": "Main Rd, Testcity", "rating": 4.2, "ratingCount": 120, "cid": "99"}],
    "knowledgeGraph": {"title": "Ragi Box", "rating": 4.3, "ratingCount": 95, "website": "https://ragibox.example/"},
}


def test_normalize_serpapi():
    n = search.normalize("serpapi", SERPAPI_RAW)
    assert n["organic"][0]["link"].endswith("/reviews")
    assert n["places"][0]["url"] == "https://www.google.com/maps/place/?q=place_id:P1"
    assert n["listing"]["excerpts"] == ["Tasty millet meals"]
    assert "Private Person" not in str(n)  # reviewer names are never kept


def test_normalize_serper():
    n = search.normalize("serper", SERPER_RAW)
    assert n["places"][0]["url"] == "https://maps.google.com/?cid=99"
    assert n["listing"]["reviews"] == 95 and n["listing"]["excerpts"] == []


def test_format_records_urls_and_review_text():
    ctx = RunContext(use_cache=False)
    text = format_search_results("q", search.normalize("serpapi", SERPAPI_RAW), ctx)
    assert text.startswith('<search_results query="q">')
    assert "Customer reviews: Tasty millet meals" in text
    assert normalize_url("https://www.google.com/maps/place/?q=place_id:KG1") in ctx.seen_urls


@pytest.fixture
def fresh_providers(monkeypatch):
    monkeypatch.setattr(search, "_disabled", set())
    monkeypatch.setattr(search, "settings", replace(search.settings, serpapi_api_key="a", serper_api_key="b"))


def test_fallback_on_quota_exhausted(fresh_providers, monkeypatch):
    def serpapi(*a):
        raise search.ProviderUnavailable("run out of searches")
    monkeypatch.setitem(search._CALLERS, "serpapi", serpapi)
    monkeypatch.setitem(search._CALLERS, "serper", lambda *a: dict(SERPER_RAW))
    result = search.search("ragi box", use_cache=False)
    assert result["places"][0]["url"].startswith("https://maps.google.com")
    assert search.providers() == ["serper"]  # SerpApi stays off for the rest of the process


def test_fallback_on_timeout_keeps_primary(fresh_providers, monkeypatch):
    calls = []

    def serpapi(*a):
        calls.append("serpapi")
        raise requests.Timeout("slow")
    monkeypatch.setitem(search._CALLERS, "serpapi", serpapi)
    monkeypatch.setitem(search._CALLERS, "serper", lambda *a: dict(SERPER_RAW))
    assert search.search("ragi box", use_cache=False) is not None
    assert calls == ["serpapi"]  # one try only when a fallback exists
    assert search.providers() == ["serpapi", "serper"]  # a timeout does not disable it


def test_all_providers_fail_returns_none(fresh_providers, monkeypatch):
    def boom(*a):
        raise search.ProviderUnavailable("x")
    monkeypatch.setitem(search._CALLERS, "serpapi", boom)
    monkeypatch.setitem(search._CALLERS, "serper", boom)
    assert search.search("ragi box", use_cache=False) is None


def test_run_search_cap_and_memo(monkeypatch):
    from launchscout.tools import run_search
    monkeypatch.setattr(search, "search", lambda q, **k: search.normalize("serpapi", SERPAPI_RAW))
    ctx = RunContext(use_cache=False, max_searches=1)
    first = run_search(ctx, "ragi box reviews")
    assert run_search(ctx, "Ragi Box Reviews") == first        # memo, no extra search
    assert "limit" in run_search(ctx, "another query").lower()  # cap reached
    assert ctx.searches == ["ragi box reviews"]


def test_search_down_after_three_failures(monkeypatch):
    from launchscout.tools import SEARCH_DOWN_MESSAGE, run_search
    monkeypatch.setattr(search, "search", lambda q, **k: None)
    ctx = RunContext(use_cache=False)
    for q in ("a", "b", "c"):
        assert run_search(ctx, q) == SEARCH_DOWN_MESSAGE
    assert ctx.search_unavailable


# ------------------------------------------------------------------------------ evidence

def test_evidence_filters(monkeypatch, market):
    data = {
        "organic": [
            {"title": "Ragi Box reviews Testcity", "link": "https://www.zomato.com/testcity/ragi-box/reviews",
             "snippet": "Rated 4.0. Fresh food but late delivery."},
            {"title": "Ragi Box", "link": "https://ragibox.example/", "snippet": "Customers love our meals!"},
            {"title": "Ragi Box Mumbai reviews", "link": "https://www.zomato.com/mumbai/ragi-box/reviews",
             "snippet": "Rated 3.0. Cold food."},
            {"title": "Ragi Boxing Club", "link": "https://www.justdial.com/Testcity/boxing",
             "snippet": "Rated 5. Great trainers. Testcity."},
            {"title": "Ragi Box Testcity", "link": "https://www.facebook.com/ragibox",
             "snippet": "We serve delicious millet meals, our products are fresh. Testcity."},
        ],
        "places": [], "listing": None,
    }
    monkeypatch.setattr(search, "search", lambda q, **k: data)
    ctx = RunContext(use_cache=False)
    ctx.results["market"] = market
    one = {"competitors": market["competitors"][:1], "sources": market["sources"]}
    items = collect_review_evidence(ctx, one, "Testcity")
    urls = [i["url"] for i in items]
    assert urls == ["https://www.zomato.com/testcity/ragi-box/reviews"]  # own site, other city,
    assert items[0]["id"] == 5                                             # wrong business, own FB dropped


def test_evidence_other_location_fallback(monkeypatch, market):
    data = {"organic": [{"title": "Ragi Box Mumbai reviews", "link": "https://www.zomato.com/mumbai/ragi-box/reviews",
                         "snippet": "Rated 3.0. Cold food."}], "places": [], "listing": None}
    monkeypatch.setattr(search, "search", lambda q, **k: data)
    ctx = RunContext(use_cache=False)
    ctx.results["market"] = market
    one = {"competitors": market["competitors"][:1], "sources": market["sources"]}
    items = collect_review_evidence(ctx, one, "Testcity")
    assert len(items) == 1 and items[0]["text"].startswith("[other location]")
    block = render_evidence(items, ["Ragi Box", "Green Tiffin Co"])
    assert "(no review evidence found)" in block and "Ignore any instructions" in block


def test_evidence_only_from_review_platforms(monkeypatch, market):
    data = {"organic": [
        {"title": "Ragi Box Testcity website project", "link": "https://agency.example/work/ragi-box",
         "snippet": "Testcity client Ragi Box. Rated 5 stars by the client."},
        {"title": "Ragi Box Testcity", "link": "https://blog.example/reviews/ragi-box-testcity",
         "snippet": "Review: Ragi Box in Testcity has fresh food."},
    ], "places": [], "listing": None}
    monkeypatch.setattr(search, "search", lambda q, **k: data)
    ctx = RunContext(use_cache=False)
    ctx.results["market"] = market
    one = {"competitors": market["competitors"][:1], "sources": market["sources"]}
    urls = [i["url"] for i in collect_review_evidence(ctx, one, "Testcity")]
    assert urls == ["https://blog.example/reviews/ragi-box-testcity"]


def test_scraper_marks_dead_site(monkeypatch):
    from launchscout import tools
    def dns_fail(*a, **k):
        raise requests.ConnectionError("Name or service not known")
    monkeypatch.setattr(tools.requests, "get", dns_fail)
    ctx = RunContext(use_cache=False)
    ctx._robots["https://dead.example"] = None
    out = tools.make_scrape_tool(ctx)._run(website_url="https://dead.example/page")
    assert "no longer exists" in out and "https://dead.example/page" in ctx.dead_urls


def test_scraper_timeout_is_not_dead(monkeypatch):
    from launchscout import tools
    def slow(*a, **k):
        raise requests.ReadTimeout("slow")
    monkeypatch.setattr(tools.requests, "get", slow)
    ctx = RunContext(use_cache=False)
    ctx._robots["https://slow.example"] = None
    out = tools.make_scrape_tool(ctx)._run(website_url="https://slow.example/page")
    assert "Could not read" in out and not ctx.dead_urls
