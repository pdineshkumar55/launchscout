"""One complete research run, synchronously (used by the CLI and the benchmark).

The web app uses runner.ResearchRun instead, which wraps the same steps in a background thread
with live progress and a timeout.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from .crew import build_crew
from .models import ResearchInputs
from .pipeline import FinalReport, finalize, new_run_dir, save_run
from .tools import RunContext
from .usage import estimate_cost


@dataclass
class RunResult:
    final: FinalReport
    raw: dict
    duration_s: float
    prompt_tokens: int
    completion_tokens: int
    model_calls: int
    searches: int
    page_reads: int

    @property
    def cost_usd(self) -> float:
        return estimate_cost(self.prompt_tokens, self.completion_tokens)


def run_research(inp: ResearchInputs, on_event: Callable[[str, str], None] | None = None,
                 use_cache: bool = True, check_links: bool = True) -> RunResult:
    run_dir = new_run_dir(inp)
    ctx = RunContext(run_id=run_dir.name, use_cache=use_cache, on_event=on_event)
    built = build_crew(inp, ctx, run_dir)

    start = time.time()
    result = built.crew.kickoff()
    duration = time.time() - start

    strategy_out = built.strategy.output
    raw = {
        "inputs": inp.model_dump(),
        "market": ctx.results.get("market") or {"competitors": [], "sources": []},
        "feedback": ctx.results.get("feedback"),
        "strategy": strategy_out.pydantic.model_dump(mode="json") if strategy_out and strategy_out.pydantic else None,
        "report_markdown": built.report.output.raw if built.report.output else None,
        "evidence": ctx.results.get("evidence", []),
        "own": ctx.results.get("own"),
        "searches": ctx.searches,
        "fetches": ctx.fetches,
        "seen_urls": sorted(ctx.seen_urls),
    }
    save_run(run_dir, raw, ctx.seen_text)
    final = finalize(inp, raw["market"], raw["feedback"], raw["strategy"], raw["report_markdown"],
                     ctx.seen_text, run_dir, check_links=check_links, own=raw["own"])

    usage = result.token_usage
    return RunResult(
        final=final, raw=raw, duration_s=round(duration, 1),
        prompt_tokens=usage.prompt_tokens + sum(u["prompt"] for u in ctx.llm_usage),
        completion_tokens=usage.completion_tokens + sum(u["completion"] for u in ctx.llm_usage),
        model_calls=usage.successful_requests + len(ctx.llm_usage),
        searches=len(ctx.searches), page_reads=len(ctx.fetches),
    )
