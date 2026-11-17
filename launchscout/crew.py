"""Assembles the four-stage sequential crew for one research run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from crewai import Crew, Process, Task

from . import agents, tasks
from .evidence import collect_review_evidence, render_evidence
from .models import ResearchInputs
from .tools import COUNTRY_CODES, RunContext, make_file_writer, make_scrape_tool, make_search_tool

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
    gl = COUNTRY_CODES.get(inp.country.strip().lower(), "")

    def after_market(market: dict) -> None:
        items = collect_review_evidence(ctx, market, inp.city, gl=gl)
        ctx.results["evidence"] = items
        names = [c["name"] for c in market["competitors"]]
        t2.description = base_feedback_description + "\n\n" + render_evidence(items, names)

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
