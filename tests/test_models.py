import pytest
from pydantic import ValidationError

from launchscout.models import Competitor, MarketScan, ResearchInputs, Source


def test_market_scan_accepts_three_to_five(market):
    scan = MarketScan.model_validate(market)
    assert len(scan.competitors) == 3


def test_market_scan_rejects_fewer_than_three(market):
    market["competitors"] = market["competitors"][:2]
    with pytest.raises(ValidationError):
        MarketScan.model_validate(market)


def test_market_scan_rejects_more_than_five(market):
    market["competitors"] = market["competitors"] * 2
    with pytest.raises(ValidationError):
        MarketScan.model_validate(market)


def test_competitor_needs_a_source(market):
    c = dict(market["competitors"][0], source_ids=[])
    with pytest.raises(ValidationError):
        Competitor.model_validate(c)


def test_source_url_must_be_valid():
    with pytest.raises(ValidationError):
        Source(id=1, title="x", url="not a url")
    assert str(Source(id=1, title="x", url="https://example.com/a").url).startswith("https://")


def test_duplicate_source_ids_rejected(market):
    market["sources"].append(dict(market["sources"][0]))
    with pytest.raises(ValidationError):
        MarketScan.model_validate(market)


def test_location_type_is_restricted(market):
    c = dict(market["competitors"][0], location_type="Somewhere")
    with pytest.raises(ValidationError):
        Competitor.model_validate(c)


def test_research_inputs_cleanup_and_limits():
    inp = ResearchInputs(idea="  millet   meal boxes ", city=" Coimbatore ", known_competitors="A, B ,, C")
    assert inp.idea == "millet meal boxes"
    assert inp.idea_title == "Millet meal boxes"
    assert inp.competitor_list == ["A", "B", "C"]
    assert inp.country == "India" and inp.currency == "Rs"
    with pytest.raises(ValidationError):
        ResearchInputs(idea="x" * 201, city="Chennai")
    with pytest.raises(ValidationError):
        ResearchInputs(idea="ok idea", city="")
