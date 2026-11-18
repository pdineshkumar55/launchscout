"""Structured outputs for stages 1-3.

Stage tasks use the lenient *Draft* models as `output_pydantic`, so a short list does not
crash the conversion. A task guardrail then validates the draft against the strict models
below and sends specific feedback to the stage if it falls short.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


class Source(BaseModel):
    id: int
    title: str
    url: HttpUrl


class Competitor(BaseModel):
    name: str
    offering: str = Field(default="", description="what they sell, in a few words")
    price: str = Field(description='e.g. "Rs 180 per meal" or "Not listed"')
    price_value: float | None = Field(
        default=None, description="numeric price in local currency per comparable unit, if known"
    )
    channels: list[str]
    offers: str | None = None
    strength: str
    weakness: str
    location_type: Literal["Local", "Online/regional"]
    source_ids: list[int] = Field(min_length=1)


class MarketScan(BaseModel):
    competitors: list[Competitor] = Field(min_length=3, max_length=5)
    sources: list[Source]

    @field_validator("sources")
    @classmethod
    def _unique_source_ids(cls, v: list[Source]) -> list[Source]:
        ids = [s.id for s in v]
        if len(ids) != len(set(ids)):
            raise ValueError("source ids must be unique")
        return v


class CompetitorFeedback(BaseModel):
    competitor: str
    praises: list[str]
    complaints: list[str]
    source_ids: list[int]


class FeedbackScan(BaseModel):
    items: list[CompetitorFeedback]
    common_complaints: list[str] = Field(
        description="complaints shared by 2+ competitors, naming them"
    )
    sources: list[Source]


class Strategy(BaseModel):
    matrix_notes: str
    market_gap: str = Field(description="one or two sentences")
    positioning_line: str = Field(description="one-line offer with price")
    recommended_price: str
    price_rationale: str
    # Filled only when the requester named their own business (empty for older runs).
    you_ahead: list[str] = Field(default_factory=list, description="where the own business is ahead, cited")
    competitors_ahead: list[str] = Field(default_factory=list,
                                         description="where a named competitor is ahead, cited")
    actions: list[str] = Field(default_factory=list, description="3-5 actions: what to fix or lean on, cited")


class OwnBusinessScan(BaseModel):
    """What public sources say about the requester's own business. Stored in raw.json as "own"."""

    name: str
    found: bool = False
    note: str = ""                       # e.g. "No public listing or reviews found for X in Y."
    listing_name: str = ""               # name as shown on the listing that matched
    rating: float | None = None
    reviews: int | None = None
    rating_source_ids: list[int] = []
    price: str = "Not listed"
    price_source_ids: list[int] = []
    channels: list[dict] = []            # [{"name": "Instagram", "source_ids": [n]}]
    praises: list[dict] = []             # [{"text": str, "source_ids": [n]}]
    complaints: list[dict] = []
    sources: list[dict] = []             # [{"id", "title", "url"}], ids after the market/evidence ids
    competitor_ratings: dict[str, dict] = {}  # name -> {"rating", "reviews", "source_ids"}


class ResearchInputs(BaseModel):
    idea: str = Field(min_length=3, max_length=200)
    city: str = Field(min_length=2, max_length=100)
    target: str = Field(default="General consumers", max_length=200)
    known_competitors: str = Field(default="", max_length=300)
    country: str = Field(default="India", max_length=60)
    currency: str = Field(default="Rs", max_length=10)
    own_business: str = Field(default="", max_length=100, description="the user's own business: never a competitor")

    @field_validator("idea", "city", "target", "known_competitors", "country", "currency", "own_business",
                     mode="before")
    @classmethod
    def _strip(cls, v):
        return " ".join(str(v or "").split())

    @property
    def idea_title(self) -> str:
        return self.idea[:1].upper() + self.idea[1:]

    @property
    def competitor_list(self) -> list[str]:
        return [c.strip() for c in self.known_competitors.split(",") if c.strip()]


# Lenient drafts used as task output_pydantic -------------------------------------------


class SourceDraft(BaseModel):
    id: int
    title: str
    url: str


class CompetitorDraft(BaseModel):
    name: str
    offering: str = ""
    price: str
    price_value: float | None = None
    channels: list[str] = []
    offers: str | None = None
    strength: str = ""
    weakness: str = ""
    location_type: str = "Local"
    source_ids: list[int] = []


class MarketScanDraft(BaseModel):
    competitors: list[CompetitorDraft]
    sources: list[SourceDraft]


class FeedbackScanDraft(BaseModel):
    items: list[CompetitorFeedback]
    common_complaints: list[str] = []
    sources: list[SourceDraft]
