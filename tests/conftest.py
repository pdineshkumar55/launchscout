"""Shared fixtures. All data is synthetic (made-up businesses and URLs); no network access."""

from __future__ import annotations

import copy

import pytest

from launchscout.models import ResearchInputs
from launchscout.tools import RunContext

MARKET = {
    "competitors": [
        {"name": "Ragi Box", "offering": "millet lunch boxes, delivery", "price": "Rs 180 per meal",
         "price_value": 180, "channels": ["Swiggy", "Own website"], "offers": "10% off first order",
         "strength": "Daily changing menu.", "weakness": "Delivery only till 2 pm.",
         "location_type": "Local", "source_ids": [1, 2]},
        {"name": "Green Tiffin Co", "offering": "tiffin subscription", "price": "Rs 3,600 per month",
         "price_value": 3600, "channels": ["WhatsApp"], "offers": None,
         "strength": "Monthly plans.", "weakness": "No weekend service.",
         "location_type": "Local", "source_ids": [3]},
        {"name": "Millet Kitchen", "offering": "millet thali restaurant", "price": "Not listed",
         "price_value": None, "channels": ["Zomato"], "offers": "Prices only on Zomato.",
         "strength": "Large portions.", "weakness": "Limited seating.",
         "location_type": "Online/regional", "source_ids": [4]},
    ],
    "sources": [
        {"id": 1, "title": "Ragi Box", "url": "https://ragibox.example/menu"},
        {"id": 2, "title": "Ragi Box on Swiggy", "url": "https://www.swiggy.com/city/testcity/ragi-box"},
        {"id": 3, "title": "Green Tiffin Co", "url": "https://greentiffin.example/"},
        {"id": 4, "title": "Millet Kitchen on Zomato", "url": "https://www.zomato.com/testcity/millet-kitchen"},
    ],
}

FEEDBACK = {
    "items": [
        {"competitor": "Ragi Box", "praises": ["Fresh food and good taste"],
         "complaints": ["Late delivery at lunch time"], "source_ids": [5]},
        {"competitor": "Green Tiffin Co", "praises": [], "complaints": ["Limited public reviews found"],
         "source_ids": []},
        {"competitor": "Millet Kitchen", "praises": ["Large portions"],
         "complaints": ["Late delivery on weekends", "Small seating area"], "source_ids": [6]},
    ],
    "common_complaints": ["Late delivery (Ragi Box, Millet Kitchen)"],
    "sources": [
        {"id": 5, "title": "Ragi Box reviews", "url": "https://www.zomato.com/testcity/ragi-box/reviews"},
        {"id": 6, "title": "Millet Kitchen on JustDial", "url": "https://www.justdial.com/Testcity/Millet-Kitchen"},
    ],
}

STRATEGY = {
    "matrix_notes": "Ragi Box leads on delivery; Green Tiffin Co on subscriptions.",
    "market_gap": "No one offers evening millet meals for office workers in Testcity.",
    "positioning_line": "Evening millet meal boxes delivered by 8 pm, Rs 160 per meal",
    "recommended_price": "Rs 160 per meal",
    "price_rationale": "Below Ragi Box at Rs 180 per meal [1] and well under Green Tiffin Co's monthly plan.",
}

WRITER = """# Competitor Report: Millet meal boxes, Testcity
## 1. Key Competitors
| garbled | table |
## 2. What Customers Complain About
- wrong citations [99]
## 3. Market Gap
Office workers in Testcity have no evening millet option; current players stop delivery by 2 pm [1].
## 4. Recommended Positioning
> "something"
## 5. 30-Day Launch Plan
- Week 1: List on Swiggy and set up a WhatsApp order line [2].
- Week 2: Trial with two office parks.
- Week 3: Test a Rs 150 intro price.
- Week 4: Review repeat orders and expand.
## Sources
[1] Something — https://ragibox.example/menu
"""

SEEN_TEXT = {
    "https://ragibox.example/menu": "Ragi Box menu. Millet lunch box Rs 180. Order by 11 am.",
    "https://www.swiggy.com/city/testcity/ragi-box": "Ragi Box. Healthy food. Rs 180 for one.",
    "https://greentiffin.example": "Green Tiffin Co. Monthly tiffin plans. Call for prices.",
    "https://www.zomato.com/testcity/millet-kitchen": "Millet Kitchen. Thali. Rated 4.1.",
    "https://www.zomato.com/testcity/ragi-box/reviews": (
        "Ragi Box reviews Testcity. Rated 4.0. Fresh food and good taste. Delivery was late at lunch time."),
    "https://www.justdial.com/Testcity/Millet-Kitchen": (
        "Millet Kitchen Testcity. Rated 3.8 from 40 reviews. Large portions. Late delivery on weekends."),
}


@pytest.fixture
def inp() -> ResearchInputs:
    return ResearchInputs(idea="millet meal boxes", city="Testcity", target="office workers")


@pytest.fixture
def market() -> dict:
    return copy.deepcopy(MARKET)


@pytest.fixture
def feedback() -> dict:
    return copy.deepcopy(FEEDBACK)


@pytest.fixture
def strategy() -> dict:
    return copy.deepcopy(STRATEGY)


@pytest.fixture
def writer_md() -> str:
    return WRITER


@pytest.fixture
def seen_text() -> dict:
    return dict(SEEN_TEXT)


@pytest.fixture
def ctx() -> RunContext:
    c = RunContext(use_cache=False)
    for url, text in SEEN_TEXT.items():
        c.record(url, text)
    return c
