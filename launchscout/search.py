"""Web search with two providers and automatic fallback.

Order: SerpApi (returns Google review excerpts) -> Serper.dev. When a provider reports that its
quota is used up or its key is rejected, it is skipped for the rest of the process.

Both providers' raw responses are converted to one normalized shape:
    {"organic":  [{"title", "link", "snippet"}],
     "places":   [{"title", "url", "rating", "reviews", "price", "type", "address"}],
     "listing":  {"title", "url", "website", "rating", "reviews", "price", "type", "address",
                  "description", "excerpts": [str]} | None}
The cache stores raw responses tagged with their provider and is keyed by query only, so a query
already searched is never paid for twice, whichever provider answered it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time

import requests

from .config import settings

log = logging.getLogger("launchscout.search")

SERPAPI_URL = "https://serpapi.com/search.json"
SERPER_URL = "https://google.serper.dev/search"
SEARCH_TIMEOUT = 30

_disabled: set[str] = set()  # providers out of quota or with a rejected key (process lifetime)
_disabled_lock = threading.Lock()


class ProviderUnavailable(Exception):
    """Quota used up or key rejected: skip this provider from now on."""


def providers() -> list[str]:
    order = []
    if settings.serpapi_api_key:
        order.append("serpapi")
    if settings.serper_api_key:
        order.append("serper")
    return [p for p in order if p not in _disabled]


def _disable(provider: str, reason: str) -> None:
    with _disabled_lock:
        if provider not in _disabled:
            _disabled.add(provider)
            log.warning("search provider %s disabled: %s", provider, reason)


def cache_path(query: str, gl: str, hl: str, num: int):
    key = json.dumps([query.lower().strip(), gl, hl, num])
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    d = settings.cache_dir / "search"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{h}.json"


# ----------------------------------------------------------------------------------- providers


def _serpapi(query: str, gl: str, hl: str, num: int) -> dict:
    params = {"engine": "google", "q": query, "gl": gl, "hl": hl, "num": num,
              "api_key": settings.serpapi_api_key}
    params = {k: v for k, v in params.items() if v not in ("", None)}
    # SerpApi can take 20-30 s on uncached queries.
    resp = requests.get(SERPAPI_URL, params=params, timeout=SEARCH_TIMEOUT)
    if resp.status_code in (401, 403, 429):
        raise ProviderUnavailable(f"HTTP {resp.status_code}")
    data = resp.json()
    err = (data.get("error") or "").lower()
    if err and "hasn't returned any results" not in err:
        if any(k in err for k in ("run out", "searches", "plan", "invalid api key", "limit")):
            raise ProviderUnavailable(err[:120])
        raise requests.RequestException(err[:200])
    resp.raise_for_status()
    return data


def _serper(query: str, gl: str, hl: str, num: int) -> dict:
    payload = {"q": query, "num": num}
    if gl:
        payload["gl"] = gl
    if hl:
        payload["hl"] = hl
    resp = requests.post(SERPER_URL, json=payload, timeout=SEARCH_TIMEOUT,
                         headers={"X-API-KEY": settings.serper_api_key, "Content-Type": "application/json"})
    if resp.status_code in (400, 401, 403, 429):
        msg = resp.text[:120]
        if resp.status_code != 400 or "credit" in msg.lower():
            raise ProviderUnavailable(f"HTTP {resp.status_code} {msg}")
    resp.raise_for_status()
    return resp.json()


_CALLERS = {"serpapi": _serpapi, "serper": _serper}


def search(query: str, gl: str = "in", hl: str = "en", num: int = 10, use_cache: bool = True) -> dict | None:
    """Return a normalized result dict, or None if every provider failed."""
    cpath = cache_path(query, gl, hl, num)
    if use_cache and cpath.exists():
        raw = json.loads(cpath.read_text(encoding="utf-8"))
        return normalize(raw.get("_provider", "serpapi"), raw)

    order = providers()
    for n, provider in enumerate(order):
        has_next = n + 1 < len(order)
        # With a fallback available, give each provider one try: SerpApi sometimes hangs on a
        # specific query, and retrying it just wastes the run's time.
        for attempt in range(1 if has_next else 2):
            try:
                raw = _CALLERS[provider](query, gl, hl, num)
                raw["_provider"] = provider
                if use_cache:
                    cpath.write_text(json.dumps(raw), encoding="utf-8")
                log.info("search via %s: %s", provider, query)
                return normalize(provider, raw)
            except ProviderUnavailable as exc:
                _disable(provider, str(exc))
                break  # next provider
            except (requests.RequestException, ValueError) as exc:
                log.warning("%s search failed (attempt %s): %s", provider, attempt + 1, exc)
                if not has_next:
                    time.sleep(1 + attempt)
    return None


# ----------------------------------------------------------------------------------- normalize


def maps_url_from_place_id(place_id: str) -> str:
    return f"https://www.google.com/maps/place/?q=place_id:{place_id}" if place_id else ""


def maps_url_from_cid(cid: str | int) -> str:
    return f"https://maps.google.com/?cid={cid}" if cid else ""


def normalize(provider: str, raw: dict) -> dict:
    return _norm_serper(raw) if provider == "serper" else _norm_serpapi(raw)


def _norm_serpapi(d: dict) -> dict:
    organic = [{"title": r.get("title", ""), "link": r.get("link", ""), "snippet": r.get("snippet", "")}
               for r in d.get("organic_results", []) if r.get("link")]
    local = d.get("local_results")
    raw_places = local.get("places", []) if isinstance(local, dict) else (local or [])
    places = []
    for p in raw_places:
        maps = maps_url_from_place_id(p.get("place_id", ""))
        url = (p.get("links") or {}).get("website") or p.get("website") or maps
        if url:
            places.append({"title": p.get("title", ""), "url": url, "maps_url": maps, "rating": p.get("rating"),
                           "reviews": p.get("reviews"), "price": p.get("price"), "type": p.get("type"),
                           "address": p.get("address")})
    kg = d.get("knowledge_graph") or {}
    listing = None
    if kg.get("title"):
        excerpts = [(r.get("summary") or r.get("snippet") or "").strip() for r in kg.get("user_reviews") or []]
        listing = {"title": kg.get("title", ""), "url": maps_url_from_place_id(kg.get("place_id", "")),
                   "website": kg.get("website"), "rating": kg.get("rating"), "reviews": kg.get("review_count"),
                   "price": kg.get("price"), "type": kg.get("type"), "address": kg.get("address"),
                   "description": kg.get("description"), "excerpts": [e for e in excerpts if e][:5]}
    return {"organic": organic, "places": places, "listing": listing}


def _norm_serper(d: dict) -> dict:
    organic = [{"title": r.get("title", ""), "link": r.get("link", ""), "snippet": r.get("snippet", "")}
               for r in d.get("organic", []) if r.get("link")]
    places = []
    for p in d.get("places", []):
        maps = maps_url_from_cid(p.get("cid", ""))
        url = p.get("website") or maps
        if url:
            places.append({"title": p.get("title", ""), "url": url, "maps_url": maps, "rating": p.get("rating"),
                           "reviews": p.get("ratingCount"), "price": p.get("priceLevel"),
                           "type": p.get("category"), "address": p.get("address")})
    kg = d.get("knowledgeGraph") or {}
    listing = None
    if kg.get("title"):
        attrs = kg.get("attributes") or {}
        listing = {"title": kg.get("title", ""), "url": maps_url_from_cid(kg.get("cid", "")),
                   "website": kg.get("website"), "rating": kg.get("rating"), "reviews": kg.get("ratingCount"),
                   "price": attrs.get("Price"), "type": kg.get("type"), "address": attrs.get("Address"),
                   "description": kg.get("description"), "excerpts": []}
    return {"organic": organic, "places": places, "listing": listing}
