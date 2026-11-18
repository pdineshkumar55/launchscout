"""Rendering helpers for the Streamlit app. All visible text comes from ui/copy.py."""

from __future__ import annotations

import json
import re
from pathlib import Path

import streamlit as st

from launchscout.events import OWN_STAGE, stage_label, stage_order
from launchscout.pipeline import SavedRun

from . import copy as c

STATUS_TEXT = {"waiting": f":gray[{c.STATUS_WAITING}]", "running": f":blue[**{c.STATUS_RUNNING}…**]",
               "done": f":green[{c.STATUS_DONE}]"}
STATUS_ICON = {"waiting": "○", "running": "◐", "done": "✅"}


def how_it_works() -> None:
    st.subheader(c.HOW_HEADER)
    for i, (icon, title, text) in enumerate(c.HOW_STEPS, start=1):
        st.markdown(f"{icon} **Stage {i} · {title}**  \n{text}")


def stage_cards(stage_state: dict[int, str]) -> None:
    # The "Your business scan" card appears only when the run has that stage.
    for n in stage_order(OWN_STAGE in stage_state):
        state = stage_state.get(n, "waiting")
        with st.container(border=True):
            left, right = st.columns([3, 1])
            left.markdown(f"{STATUS_ICON[state]} **{stage_label(n)}**")
            right.markdown(STATUS_TEXT[state])


def activity_log(lines: list[str], height: int = 260) -> None:
    st.caption(c.LOG_HEADER)
    with st.container(height=height, border=True):
        if not lines:
            st.caption(c.LOG_EMPTY)
        for line in reversed(lines[-40:]):  # newest first: the box does not auto-scroll
            st.text(line)


def elapsed_text(seconds: float) -> str:
    s = int(seconds)
    return c.ELAPSED.format(minutes=s // 60, seconds=s % 60)


def file_stem(run: SavedRun) -> str:
    return "competitor-report_" + run.run_dir.name.rsplit("_", 2)[0]


def _price_check_label(status: str | None) -> str:
    return {"verified": c.PRICE_CONFIRMED, "unverified": c.PRICE_NOT_CONFIRMED}.get(status or "", c.PRICE_NOT_LISTED)


def own_business_card(run: SavedRun) -> None:
    """Highlighted card for the requester's own business, shown above the competitor rows."""
    own = run.own
    if not own:
        return
    url_by_id = {s["id"]: str(s["url"]) for s in own.get("sources", [])}

    def links(ids) -> str:
        return " ".join(f"[{c.OWN_SOURCE_LINK}]({url_by_id[i]})" for i in dict.fromkeys(ids or []) if i in url_by_id)

    with st.container(border=True):
        st.markdown(f"**{c.OWN_CARD_HEADER.format(name=own.get('name', ''))}**")
        if not own.get("found"):
            st.info(own.get("note") or c.OWN_NOT_FOUND)
            return
        m1, m2, m3 = st.columns(3)
        m1.metric(c.OWN_RATING, own["rating"] if own.get("rating") is not None else c.OWN_NONE)
        m2.metric(c.OWN_REVIEWS, f"{own['reviews']:,}" if own.get("reviews") else c.OWN_NONE)
        m3.metric(c.COL_PRICE, own.get("price") or c.PRICE_NOT_LISTED)
        channels = ", ".join(ch["name"] for ch in own.get("channels") or []) or c.OWN_NONE
        lines = [f"**{c.COL_CHANNELS}:** {channels}"]
        for key, label in (("praises", c.OWN_PRAISE), ("complaints", c.OWN_COMPLAINTS)):
            pts = own.get(key) or []
            if pts:
                lines.append(f"**{label}:** " + "; ".join(f"{p['text']} {links(p.get('source_ids'))}" for p in pts))
        all_ids = [s["id"] for s in own.get("sources", []) if s["id"] in set(
            (own.get("rating_source_ids") or []) + (own.get("price_source_ids") or [])
            + [ch["source_ids"][0] for ch in own.get("channels") or [] if ch.get("source_ids")])]
        if all_ids:
            lines.append(f"**{c.COL_SOURCE}:** {links(all_ids)}")
        if own.get("note"):
            lines.append(f"_{own['note']}_")
        st.markdown("  \n".join(lines))


def competitors_table(run: SavedRun) -> None:
    own_business_card(run)
    checks = _load_checks(run.run_dir)
    price_details = (checks.get("prices") or {}).get("details", {})
    url_by_id = {s["id"]: str(s["url"]) for s in run.market.get("sources", [])}
    rows = []
    for comp in run.market.get("competitors", []):
        first = next((url_by_id[i] for i in comp.get("source_ids", []) if i in url_by_id), None)
        rows.append({
            c.COL_COMPETITOR: comp.get("name", ""),
            c.COL_PRICE: comp.get("price", ""),
            c.COL_PRICE_CHECK: _price_check_label((price_details.get(comp.get("name", "")) or {}).get("status")),
            c.COL_CHANNELS: ", ".join(comp.get("channels") or []),
            c.COL_TYPE: comp.get("location_type", ""),
            c.COL_SOURCE: first,
        })
    st.dataframe(rows, hide_index=True, use_container_width=True,
                 column_config={c.COL_SOURCE: st.column_config.LinkColumn(c.COL_SOURCE)})


def sources_list(run: SavedRun) -> None:
    part = run.markdown.partition("## Sources")[2].split("\n---", 1)[0]
    entries = re.findall(r"^\[(\d+)\] (.*?) — (https?://\S+)", part, re.M)
    if not entries:
        st.info(c.SOURCES_EMPTY)
        return
    st.caption(c.SOURCES_CAPTION)
    st.markdown("\n".join(f"{n}. [{title}]({url})" for n, title, url in entries))


def downloads(run: SavedRun) -> None:
    stem = file_stem(run)
    st.caption(c.DOWNLOAD_HELP)
    st.download_button(c.DOWNLOAD_MD, data=run.markdown.encode("utf-8"), file_name=f"{stem}.md",
                       mime="text/markdown", key=f"md-{run.run_dir.name}")
    pdf = pdf_bytes(run)
    if pdf:
        st.download_button(c.DOWNLOAD_PDF, data=pdf, file_name=f"{stem}.pdf", mime="application/pdf",
                           key=f"pdf-{run.run_dir.name}")
    else:
        st.caption(c.PDF_UNAVAILABLE)


def pdf_bytes(run: SavedRun) -> bytes | None:
    """Return the run's PDF, creating it on first request. None if it cannot be made."""
    path = run.run_dir / "report.pdf"
    if path.exists():
        return path.read_bytes()
    try:
        from launchscout.pdf import markdown_to_pdf
    except ImportError:
        return None
    try:
        markdown_to_pdf(run.markdown, path)
        return path.read_bytes()
    except Exception:  # never surface a stack trace
        return None


def results(run: SavedRun, note: str | None = None) -> None:
    st.subheader(c.RESULTS_HEADER.format(label=run.label))
    if note:
        st.info(note)
    t_report, t_comp, t_src, t_dl = st.tabs([c.TAB_REPORT, c.TAB_COMPETITORS, c.TAB_SOURCES, c.TAB_DOWNLOADS])
    with t_report:
        body = re.sub(r"^# .*\n", "", run.markdown, count=1)  # title already shown above
        st.markdown(body)
    with t_comp:
        competitors_table(run)
    with t_src:
        sources_list(run)
    with t_dl:
        downloads(run)


def _load_checks(run_dir: Path) -> dict:
    try:
        return json.loads((run_dir / "checks.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
