import json
from types import SimpleNamespace

import pytest

from launchscout import validation
from launchscout.validation import (
    clean_market_scan,
    feedback_guardrail,
    is_own_site,
    market_scan_guardrail,
    name_was_seen,
    statement_grounded,
    strict_name_match,
    strip_boilerplate,
)


def out(data: dict):
    return SimpleNamespace(pydantic=None, raw=json.dumps(data))


@pytest.fixture(autouse=True)
def no_relevance_call(monkeypatch):
    """Relevance check calls OpenAI; default to 'everything comparable' in tests."""
    monkeypatch.setattr("launchscout.relevance.check_relevance",
                        lambda idea, target, comps, ev, **k: {c["name"]: {"comparable": True} for c in comps})


# ------------------------------------------------------------------------------ name matching

@pytest.mark.parametrize("name,text,expected", [
    ("Revival Foods", "Revival Restaurant and Banquets Gangtok", False),
    ("Revival Foods", "Revival Foods Coimbatore reviews", True),
    ("Mummy's Cloud Kitchen", "https://mummyscloudkitchen.in/x", True),
    ("Zero Cals", "Zero cals - Google", True),
    ("Zero Cals", "zero chill with their naming", False),
    ("Ragi Box", "Ragi Boxing Club Testcity", False),
    ("Ragi Box", "https://ragiboxingclub.example", False),
    ("Ragi Box", "Ragi Box's lunch menu", True),
])
def test_strict_name_match(name, text, expected):
    assert strict_name_match(name, text) is expected


def test_name_seen_via_url_only(ctx):
    ctx.record("https://mummyscloudkitchen.example/diet", "Healthy diet meals")
    assert name_was_seen(ctx, "Mummy's Cloud Kitchen")
    assert not name_was_seen(ctx, "Unheard Of Bistro")


# ------------------------------------------------------------------------------ market scan

def test_clean_market_scan_drops_unseen_source(ctx, market):
    from launchscout.models import MarketScanDraft
    market["sources"][2]["url"] = "https://invented-site.example/"
    data, problems = clean_market_scan(MarketScanDraft.model_validate(market), ctx)
    names = [c["name"] for c in data["competitors"]]
    assert "Green Tiffin Co" not in names and len(names) == 2
    assert any("invented-site" in p for p in problems)


def test_market_guardrail_retries_then_accepts(ctx, market):
    market["sources"][2]["url"] = "https://invented-site.example/"
    guard = market_scan_guardrail(ctx)
    ok, msg = guard(out(market))
    assert not ok and "working source URL" in msg
    ok, payload = guard(out(market))  # second attempt: accept what is confirmed
    assert ok and len(json.loads(payload)["competitors"]) == 2


def test_market_guardrail_hook_runs_once_accepted(ctx, market):
    seen = []
    ctx.after_market = seen.append
    ok, _ = market_scan_guardrail(ctx)(out(market))
    assert ok and len(seen) == 1 and ctx.results["market"]["competitors"]


def test_relevance_drop_triggers_retry(ctx, market, monkeypatch):
    monkeypatch.setattr("launchscout.relevance.check_relevance", lambda *a, **k: {
        "Ragi Box": {"comparable": True}, "Green Tiffin Co": {"comparable": True},
        "Millet Kitchen": {"comparable": False, "reason": "sells flour"}})
    guard = market_scan_guardrail(ctx, "millet meal boxes", "office workers")
    ok, msg = guard(out(market))
    assert not ok and "Millet Kitchen" in msg
    ok, payload = guard(out(market))  # final attempt keeps it but says why
    kept = {c["name"]: c for c in json.loads(payload)["competitors"]}
    assert ok and kept["Millet Kitchen"]["weakness"].startswith("Not a direct substitute")


def test_relevance_check_failure_does_not_block(ctx, market, monkeypatch):
    monkeypatch.setattr("launchscout.relevance.check_relevance", lambda *a, **k: {})
    ok, _ = market_scan_guardrail(ctx, "millet meal boxes", "office workers")(out(market))
    assert ok


# ------------------------------------------------------------------------------ feedback

def test_own_site_detection(ctx, market):
    ctx.results["market"] = market
    assert is_own_site(ctx, "Ragi Box", "https://ragibox.example/menu")
    assert not is_own_site(ctx, "Ragi Box", "https://www.zomato.com/testcity/ragi-box/reviews")


def test_feedback_guardrail_rejects_homepage_citations(ctx, market, feedback):
    ctx.results["market"] = market
    feedback["items"][0]["source_ids"] = [1]   # Ragi Box's own site
    feedback["items"][2]["source_ids"] = [1]   # another competitor's page
    guard = feedback_guardrail(ctx)
    ok, msg = guard(out(feedback))
    assert not ok and "own homepage" in msg
    ok, payload = guard(out(feedback))
    items = {i["competitor"]: i for i in json.loads(payload)["items"]}
    assert items["Ragi Box"]["complaints"] == ["Limited public reviews found"]


def test_feedback_guardrail_keeps_grounded_and_drops_invented(ctx, market, feedback):
    ctx.results["market"] = market
    feedback["items"][0]["complaints"].append("Rude staff and wrong orders")  # not in the source
    ok, payload = feedback_guardrail(ctx)(out(feedback))
    items = {i["competitor"]: i for i in json.loads(payload)["items"]}
    assert ok
    assert items["Ragi Box"]["complaints"] == ["Late delivery at lunch time"]
    assert items["Millet Kitchen"]["praises"] == ["Large portions"]


def test_feedback_common_complaints_need_two_supported(ctx, market, feedback):
    ctx.results["market"] = market
    feedback["common_complaints"].append("High prices (Ragi Box, Green Tiffin Co)")
    ok, payload = feedback_guardrail(ctx)(out(feedback))
    assert json.loads(payload)["common_complaints"] == ["Late delivery (Ragi Box, Millet Kitchen)"]


def test_feedback_source_ids_continue_after_market(ctx, market, feedback):
    ctx.results["market"] = market
    feedback["sources"] = [dict(s, id=s["id"] + 95) for s in feedback["sources"]]  # 100, 101
    for item in feedback["items"]:
        item["source_ids"] = [i + 95 for i in item["source_ids"]]
    ok, payload = feedback_guardrail(ctx)(out(feedback))
    ids = sorted(s["id"] for s in json.loads(payload)["sources"])
    assert ok and ids == [5, 6]


# ------------------------------------------------------------------------------ grounding

def test_statement_grounding_needs_two_specific_words():
    src = strip_boilerplate("Reviews of X; see all unbiased reviews of X Testcity for delivery and dining on Zomato.")
    assert not statement_grounded("Limited delivery options", "X", src)
    good = "Rated 4.0. The staff are courteous and prompt."
    assert statement_grounded("Staff are courteous and prompt", "X", good)


def test_boilerplate_removed():
    assert "unbiased" not in strip_boilerplate("Reviews of A; see all unbiased reviews of A for delivery and dining on Zomato.")


def test_platform_list():
    assert validation.is_platform("https://www.justdial.com/x")
    assert not validation.is_platform("https://ragibox.example/")


def test_platform_matching_is_by_domain():
    assert validation.is_platform("https://x.com/somebrand")
    assert not validation.is_platform("https://www.netflix.com/")  # used to match "x.com"
    assert validation.is_platform("https://maps.google.co.in/place")
    assert validation.is_platform("https://www.tripadvisor.in/Restaurant_Review")
    assert not validation.is_platform("https://googlefoods.example/")


def test_own_social_page_is_own_site(ctx, market):
    ctx.results["market"] = market
    assert is_own_site(ctx, "Ragi Box", "https://www.facebook.com/RagiBox.in/videos/123")
    assert not is_own_site(ctx, "Ragi Box", "https://www.facebook.com/groups/testcityfoodies/posts/9")


def test_other_branch_label_added(ctx, market, feedback):
    ctx.results["market"] = market
    ctx.results["evidence"] = [{"id": 6, "competitor": "Millet Kitchen", "title": "x",
                                "url": "https://www.justdial.com/Testcity/Millet-Kitchen",
                                "text": "[other location] Rated 3.8"}]
    ok, payload = feedback_guardrail(ctx)(out(feedback))
    items = {i["competitor"]: i for i in json.loads(payload)["items"]}
    assert all(p.endswith("(other branch)") for p in items["Millet Kitchen"]["praises"])
    assert not any("other branch" in c for c in items["Ragi Box"]["complaints"])


def test_other_competitors_site_removed_from_citations(ctx):
    from launchscout.models import MarketScanDraft
    ctx.record("https://www.petgroomers.example/", "Pet Groomers Chennai grooming")
    ctx.record("https://happypetschennai.example/", "Happy Pets Grooming Studio Chennai")
    draft = MarketScanDraft.model_validate({
        "competitors": [
            {"name": "Pet Groomers", "price": "Not listed", "source_ids": [1, 2]},
            {"name": "Happy Pets Grooming Studio", "price": "Not listed", "source_ids": [1, 2]},
        ],
        "sources": [{"id": 1, "title": "a", "url": "https://www.petgroomers.example/"},
                    {"id": 2, "title": "b", "url": "https://happypetschennai.example/"}],
    })
    data, _ = clean_market_scan(draft, ctx)
    ids = {c["name"]: c["source_ids"] for c in data["competitors"]}
    assert ids == {"Pet Groomers": [1], "Happy Pets Grooming Studio": [2]}


@pytest.mark.parametrize("raw,clean", [
    ("Good service and quality products (id: 4)", "Good service and quality products"),
    ("Nice collection (ids: 7, 9)", "Nice collection"),
    ("Friendly staff [source 12]", "Friendly staff"),
    ("Open since 1998 (est. 1998)", "Open since 1998 (est. 1998)"),
])
def test_strip_id_markers(raw, clean):
    from launchscout.validation import strip_id_markers
    assert strip_id_markers(raw) == clean


def test_dead_site_replaced_by_listing(ctx):
    from launchscout.models import MarketScanDraft
    ctx.record("https://www.oldshop.example/", "Old Shop Silks")
    ctx.dead_urls.add("https://www.oldshop.example")
    ctx.record("https://www.google.com/maps/place/?q=place_id:X1", "Old Shop Silks. Google listing: rating 4.5")
    draft = MarketScanDraft.model_validate({
        "competitors": [{"name": "Old Shop Silks", "price": "Not listed", "source_ids": [1]}],
        "sources": [{"id": 1, "title": "Old Shop", "url": "https://www.oldshop.example/"}],
    })
    data, problems = clean_market_scan(draft, ctx)
    assert [s["url"] for s in data["sources"]] == ["https://www.google.com/maps/place/?q=place_id:X1"]
    assert any("no longer exists" in p for p in problems)


def test_dead_site_without_listing_dropped(ctx):
    from launchscout.models import MarketScanDraft
    ctx.record("https://www.gone.example/", "Gone Traders")
    ctx.dead_urls.add("https://www.gone.example")
    draft = MarketScanDraft.model_validate({
        "competitors": [{"name": "Gone Traders", "price": "Not listed", "source_ids": [1]}],
        "sources": [{"id": 1, "title": "Gone", "url": "https://www.gone.example/"}],
    })
    data, _ = clean_market_scan(draft, ctx)
    assert data["competitors"] == []


@pytest.mark.parametrize("name,own,expected", [
    ("Sri Example Silks", "Sri Example Silks", True),
    ("Example Silks", "Sri Example Silks", True),
    ("SRI EXAMPLE SILKS & Sarees", "Sri Example Silks", True),
    ("ST Silks", "Sri Example Silks", False),
    ("Velmayil Silks", "Sri Example Silks", False),
    ("Anything", "", False),
])
def test_is_own_business(name, own, expected):
    from launchscout.validation import is_own_business
    assert is_own_business(name, own) is expected


def test_own_business_removed_from_market_scan(ctx, market):
    guard = market_scan_guardrail(ctx, own_business="Ragi Box")
    ok, msg = guard(out(market))
    assert not ok and "at least 3" in msg  # only 2 left: retry asked
    ok, payload = guard(out(market))
    names = [c["name"] for c in json.loads(payload)["competitors"]]
    assert ok and "Ragi Box" not in names


def test_short_list_filled_from_listings(ctx, market):
    ctx.raw_searches["silk saree shop testcity"] = {"organic": [], "listing": None, "places": [
        {"title": "Sri Own Silks", "url": "https://www.google.com/maps/place/?q=place_id:OWN", "rating": 4.9,
         "reviews": 50, "price": None, "type": "Saree store", "address": "Testcity"},
        {"title": "Ragi Box", "url": "https://www.google.com/maps/place/?q=place_id:DUP", "rating": 4.0,
         "reviews": 9, "price": None, "type": "x", "address": "Testcity"},
        {"title": "Lakshmi Silks", "url": "https://www.google.com/maps/place/?q=place_id:L1", "rating": 4.5,
         "reviews": 320, "price": None, "type": "Saree store", "address": "Testcity"},
    ]}
    market["competitors"] = market["competitors"][:2]
    guard = market_scan_guardrail(ctx, own_business="Sri Own Silks", city="Testcity")
    guard(out(market))                      # first attempt: retry requested
    ok, payload = guard(out(market))        # final attempt: topped up from listings
    data = json.loads(payload)
    names = [c["name"] for c in data["competitors"]]
    assert ok and names == ["Ragi Box", "Green Tiffin Co", "Lakshmi Silks"]
    added = data["competitors"][2]
    assert added["strength"] == "Rated 4.5 from 320 Google reviews." and added["price"] == "Not listed"
    assert any(s["url"].endswith("place_id:L1") for s in data["sources"])


def test_listing_fill_uses_maps_link_when_website_dead(ctx, market):
    ctx.dead_urls.add("https://oldsite.example")
    ctx.raw_searches["saree shop testcity"] = {"organic": [], "listing": None, "places": [
        {"title": "Old Site Silks", "url": "https://oldsite.example/", "rating": 4.2, "reviews": 80,
         "maps_url": "https://www.google.com/maps/place/?q=place_id:OS1", "price": None, "type": "", "address": ""}]}
    data = {"competitors": market["competitors"][:2], "sources": market["sources"]}
    from launchscout.validation import fill_from_listings
    assert fill_from_listings(ctx, data, "Testcity") == ["Old Site Silks"]
    assert data["sources"][-1]["url"].endswith("place_id:OS1")
