"""Progress events shown in the app's live log.

Only neutral, factual lines reach the UI: what is being searched or read, and what each stage
found. Model reasoning text is never forwarded.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

STAGE_NAMES = {
    1: "Market scan",
    2: "Customer feedback",
    3: "Gap & positioning",
    4: "Report",
    5: "Your business scan",  # shown only when the requester names their own business
}
OWN_STAGE = 5


def stage_order(has_own: bool) -> list[int]:
    """Display and run order of the stages: the own-business scan runs between stages 1 and 2."""
    return [1, OWN_STAGE, 2, 3, 4] if has_own else [1, 2, 3, 4]


def stage_label(stage: int) -> str:
    return STAGE_NAMES[stage] if stage == OWN_STAGE else f"Stage {stage} · {STAGE_NAMES[stage]}"


@dataclass
class ProgressEvent:
    stage: int          # 1-4, or 0 for run-level events
    kind: str           # search | read | stage_start | stage_done | info | done | error
    text: str
    ts: float = field(default_factory=time.time)


def short_url(url: str, limit: int = 60) -> str:
    """'https://www.zomato.com/coimbatore/millet-life/reviews' -> 'zomato.com/coimbatore/millet-life/…'"""
    p = urlparse(url)
    host = p.netloc.lower().removeprefix("www.")
    path = p.path.rstrip("/")
    text = host + path
    if len(text) > limit:
        text = text[: limit - 1].rstrip("/") + "…"
    return text


def tool_event(stage: int, kind: str, detail: str) -> ProgressEvent:
    if kind == "search":
        return ProgressEvent(stage, "search", f"Searching: {detail.strip()[:90]}")
    if kind == "read":
        return ProgressEvent(stage, "read", f"Reading: {short_url(detail)}")
    return ProgressEvent(stage, "info", detail)


def stage_start(stage: int) -> ProgressEvent:
    return ProgressEvent(stage, "stage_start", f"{stage_label(stage)} started")


def stage_done(stage: int, data: dict | None) -> ProgressEvent:
    data = data or {}
    if stage == 1:
        n = len(data.get("competitors", []))
        fact = f"{n} competitor{'s' if n != 1 else ''} found"
    elif stage == 2:
        items = data.get("items", [])
        with_reviews = sum(1 for i in items if i.get("source_ids"))
        fact = f"reviews found for {with_reviews} of {len(items)} competitors"
    elif stage == OWN_STAGE:
        if not data.get("found"):
            fact = "no public listing found"
        elif data.get("rating") is not None:
            fact = f"rated {data['rating']}" + (f" from {data['reviews']} reviews" if data.get("reviews") else "")
        else:
            fact = "listing found, no rating"
    elif stage == 3:
        fact = "gap identified" if data.get("market_gap") else "comparison done"
    else:
        fact = "report ready"
    return ProgressEvent(stage, "stage_done", (f"{STAGE_NAMES[stage]} complete: {fact}" if stage == OWN_STAGE else f"Stage {stage} complete: {fact}"))
