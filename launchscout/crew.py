"""Assembles the four-stage sequential crew for one research run."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from crewai import Crew, Process, Task

from . import agents, tasks
from .evidence import collect_review_evidence, render_evidence
from .models import OwnBusinessScan, ResearchInputs
from .own_business import render_own_block, scan_own_business
from .tools import COUNTRY_CODES, RunContext, make_file_writer, make_scrape_tool, make_search_tool

log = logging.getLogger("launchscout.crew")

# Internal role -> stage number shown in the UI
STAGE_BY_ROLE = {
    "Market Researcher": 1,
    "Review Analyst": 2,
    "Strategy Analyst": 3,
    "Report Writer": 4,
}


@dataclass
class BuiltCrew:
    crew: Crew
    market: Task
    feedback: Task
    strategy: Task
    report: Task


def build_crew(inp: ResearchInputs, ctx: RunContext, run_dir: Path) -> BuiltCrew:
    search = make_search_tool(ctx, country=inp.country)
    scrape = make_scrape_tool(ctx)
    writer_tool = make_file_writer(run_dir)

    a1 = agents.market_researcher([search, scrape])
    a2 = agents.review_analyst([search, scrape])
    a3 = agents.strategy_analyst()
    a4 = agents.report_writer([writer_tool])

    t1 = tasks.market_scan_task(a1, inp, ctx)
    t2 = tasks.feedback_task(a2, inp, ctx, t1)
    t3 = tasks.strategy_task(a3, inp, t1, t2)
    t4 = tasks.report_task(a4, inp, run_dir, t1, t2, t3)

    # Once Stage 1 is accepted, collect review evidence in Python and hand it to Stage 2.
    base_feedback_description = t2.description
    base_strategy_description, base_report_description = t3.description, t4.description
    gl = COUNTRY_CODES.get(inp.country.strip().lower(), "")

    def after_market(market: dict) -> None:
        items = collect_review_evidence(ctx, market, inp.city, gl=gl)
        ctx.results["evidence"] = items
        names = [c["name"] for c in market["competitors"]]
        t2.description = base_feedback_description + "\n\n" + render_evidence(items, names)
        if inp.own_business:
            # The requester's own business, researched separately (after the competitor list is final).
            ctx.emit("own_start", inp.own_business)
            start = max([s["id"] for s in market.get("sources", [])] + [e["id"] for e in items] or [0]) + 1
            try:
                own = scan_own_business(ctx, inp, start, market, items, gl=gl)
            except Exception:  # never fail the competitor report because of this step
                log.exception("own business scan failed")
                own = OwnBusinessScan(name=inp.own_business,
                                      note=f"{inp.own_business} could not be researched in this run.").model_dump()
            ctx.results["own"] = own
            block = render_own_block(own, market)
            t3.description = base_strategy_description + "\n\n" + block
            t4.description = base_report_description + "\n\n" + block
            ctx.emit("own_done", inp.own_business)

    ctx.after_market = after_market

    crew = Crew(
        agents=[a1, a2, a3, a4],
        tasks=[t1, t2, t3, t4],
        process=Process.sequential,
        memory=False,
        verbose=False,
        tracing=False,
    )
    return BuiltCrew(crew, t1, t2, t3, t4)
