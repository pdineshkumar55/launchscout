"""Automatic trust checks for a finished run (developer-facing: terminal + checks.json, not the UI).

- Price grounding: a competitor's price is "verified" when one of its numbers appears in the text
  fetched for one of its cited sources (search snippet or page text).
- Source reachability: each cited URL is requested (HEAD, then GET). Results are "ok" (< 400),
  "blocked" (401/403/429: the page exists but refuses automated requests, common on Zomato/Swiggy)
  or "broken" (404/410/5xx/connection error).
- Structure: all six sections, >= 3 competitors, every [n] citation listed in Sources.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

import requests

from .report import check_structure
from .tools import USER_AGENT, normalize_url
from .validation import is_platform

NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def price_numbers(price: str) -> list[str]:
    """Numbers in a price string worth matching (>= 10, commas removed)."""
    nums = []
    for raw in NUM_RE.findall(price or ""):
        n = raw.replace(",", "")
        try:
            if float(n) >= 10:
                nums.append(n.rstrip("0").rstrip(".") if "." in n else n)
        except ValueError:
            continue
    return nums


def _number_in_text(n: str, text: str) -> bool:
    plain = text.replace(",", "")
    return re.search(rf"(?<![\d.]){re.escape(n)}(?:\.0+)?(?![\d])", plain) is not None


def grade_prices(market: dict, seen_text: dict[str, str]) -> dict[str, dict]:
    """Return {competitor: {"price", "status": verified|unverified|not_listed, "numbers"}}."""
    url_by_id = {s["id"]: str(s["url"]) for s in market.get("sources", [])}
    out = {}
    for c in market.get("competitors", []):
        price = c.get("price") or ""
        nums = price_numbers(price)
        if price.strip().lower().startswith("not listed") or not nums:
            out[c["name"]] = {"price": price, "status": "not_listed", "numbers": nums}
            continue
        texts = [seen_text.get(normalize_url(url_by_id[i]), "") for i in c.get("source_ids", []) if i in url_by_id]
        ok = any(_number_in_text(n, t) for n in nums for t in texts)
        out[c["name"]] = {"price": price, "status": "verified" if ok else "unverified", "numbers": nums}
    return out


def check_url(url: str, timeout: int = 12) -> dict:
    headers = {"User-Agent": USER_AGENT}
    try:
        r = requests.head(url, headers=headers, timeout=timeout, allow_redirects=True)
        if r.status_code in (405, 403, 400) or r.status_code >= 500:
            r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True, stream=True)
            r.close()
        code = r.status_code
    except requests.Timeout:
        # Listing platforms (e.g. Zomato) stall automated clients on purpose; the URL came from
        # search results, so on those domains a timeout is not evidence of a dead link.
        return {"url": url, "status": "timeout", "code": None,
                "counts_as_reachable": is_platform(url)}
    except requests.RequestException as exc:
        return {"url": url, "status": "broken", "code": None, "error": type(exc).__name__}
    if code < 400:
        status = "ok"
    elif code in (401, 403, 429, 999):
        status = "blocked"
    else:
        status = "broken"
    return {"url": url, "status": status, "code": code}


def check_sources(urls: list[str]) -> list[dict]:
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(check_url, urls))


def run_checks(markdown: str, market: dict, prices: dict[str, dict], check_links: bool = True) -> dict:
    structure = check_structure(markdown)
    source_urls = re.findall(r"^\[\d+\] .*? — (https?://\S+)", markdown.partition("## Sources")[2], re.M)
    links = check_sources(source_urls) if check_links else []
    n = len(links) or 1

    def reachable(x: dict) -> bool:
        return x["status"] in ("ok", "blocked") or (x["status"] == "timeout" and x.get("counts_as_reachable"))

    priced = [p for p in prices.values() if p["status"] != "not_listed"]
    return {
        "structure": structure,
        "sources": {
            "total": len(links),
            "ok": sum(1 for x in links if x["status"] == "ok"),
            "blocked": sum(1 for x in links if x["status"] == "blocked"),
            "timeout": sum(1 for x in links if x["status"] == "timeout"),
            "broken": sum(1 for x in links if x["status"] == "broken"),
            "reachable_pct": round(100 * sum(1 for x in links if reachable(x)) / n, 1),
            "details": links,
        },
        "prices": {
            "with_price": len(priced),
            "verified": sum(1 for p in priced if p["status"] == "verified"),
            "verified_pct": round(100 * sum(1 for p in priced if p["status"] == "verified") / (len(priced) or 1), 1),
            "details": prices,
        },
    }
