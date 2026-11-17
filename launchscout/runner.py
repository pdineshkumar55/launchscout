"""Runs one research job in a background thread and streams progress events to the UI.

Streamlit reruns its script on every interaction, so the app keeps a ResearchRun object in
st.session_state and polls `drain()` / `poll()` about once a second.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .config import settings
from .crew import build_crew
from .events import ProgressEvent, stage_done, stage_start, tool_event
from .models import ResearchInputs
from .pipeline import FinalReport, finalize, new_run_dir, save_run
from .tools import RunContext
from .usage import estimate_cost, log_run, release_run_slot

log = logging.getLogger("launchscout.runner")

# Run states
RUNNING, DONE, PARTIAL, FAILED = "running", "done", "partial", "failed"


@dataclass
class ResearchRun:
    inp: ResearchInputs
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    status: str = RUNNING
    stage: int = 1                       # stage currently running
    stage_state: dict[int, str] = field(default_factory=lambda: {1: "running", 2: "waiting",
                                                                 3: "waiting", 4: "waiting"})
    events: list[ProgressEvent] = field(default_factory=list)
    final: FinalReport | None = None
    error_kind: str = ""                 # "timeout" | "error" | "search" (UI picks the neutral message)
    started: float = field(default_factory=time.time)
    finished: float | None = None
    run_dir: Path | None = None

    _queue: queue.Queue = field(default_factory=queue.Queue, repr=False)
    _ctx: RunContext | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)

    # ------------------------------------------------------------------ public (UI thread)

    def start(self) -> None:
        """Start the background thread. The caller must already hold a run slot (usage.acquire_run_slot)."""
        self.run_dir = new_run_dir(self.inp)
        self._push(stage_start(1))
        self._thread = threading.Thread(target=self._work, name=f"run-{self.run_id}", daemon=True)
        self._thread.start()

    @property
    def elapsed(self) -> float:
        return (self.finished or time.time()) - self.started

    @property
    def is_running(self) -> bool:
        return self.status == RUNNING

    def drain(self) -> list[ProgressEvent]:
        """Move queued events into self.events; returns the new ones."""
        new = []
        while True:
            try:
                new.append(self._queue.get_nowait())
            except queue.Empty:
                break
        self.events.extend(new)
        return new

    def poll(self) -> None:
        """Called by the UI each tick: applies the timeout guard."""
        if self.is_running and self.elapsed > settings.run_timeout_seconds:
            self._on_timeout()

    # ------------------------------------------------------------------ internals (worker thread)

    def _push(self, ev: ProgressEvent) -> None:
        self._queue.put(ev)

    def _mark_done(self, stage: int, data: dict | None) -> None:
        with self._lock:
            if self.stage_state.get(stage) == "done":
                return
            self.stage_state[stage] = "done"
            self._push(stage_done(stage, data))
            if stage < 4:
                self.stage = stage + 1
                self.stage_state[stage + 1] = "running"
                self._push(stage_start(stage + 1))

    def _on_tool(self, kind: str, detail: str) -> None:
        self._push(tool_event(self.stage, kind, detail))

    def _work(self) -> None:
        ctx = RunContext(run_id=self.run_id, on_event=self._on_tool)
        self._ctx = ctx
        outcome, error_type, result = "failed", "", None
        try:
            built = build_crew(self.inp, ctx, self.run_dir)

            # Stage 1 is "done" as soon as its guardrail accepts it (review evidence for Stage 2 is
            # collected right after), so wrap the hook to move the progress display on first.
            collect_evidence = ctx.after_market

            def after_market(market: dict) -> None:
                self._mark_done(1, market)
                collect_evidence(market)
            ctx.after_market = after_market

            outputs = {1: lambda: ctx.results.get("market"), 2: lambda: ctx.results.get("feedback"),
                       3: lambda: _pyd(built.strategy), 4: lambda: None}

            tasks_done = {"n": 0}

            def on_task_done(_output) -> None:
                # The n-th finished task is stage n. Stage 1 may already be marked done by the
                # hook above; _mark_done ignores repeats.
                tasks_done["n"] += 1
                stage = min(tasks_done["n"], 4)
                self._mark_done(stage, outputs[stage]())
            built.crew.task_callback = on_task_done

            result = built.crew.kickoff()
            if not self.is_running:      # timed out meanwhile; partial report already delivered
                return
            self._finish(built, ctx, writer=built.report.output.raw if built.report.output else None)
            outcome = "ok"
        except Exception as exc:
            error_type = type(exc).__name__
            log.error("run %s failed: %s\n%s", self.run_id, error_type, traceback.format_exc())
            if self.is_running:
                outcome = self._fail(ctx, "search" if ctx.search_unavailable else "error")
        finally:
            if self.status == PARTIAL:
                outcome = "timeout_partial" if self.error_kind == "timeout" else "partial"
            self._log(result, ctx, outcome, error_type)
            release_run_slot()

    def _finish(self, built, ctx: RunContext, writer: str | None) -> None:
        self._push(ProgressEvent(4, "info", "Checking sources"))
        raw = self._raw(ctx, strategy=_pyd(built.strategy), writer=writer)
        save_run(self.run_dir, raw, ctx.seen_text)
        final = finalize(self.inp, raw["market"], raw["feedback"], raw["strategy"], writer,
                         ctx.seen_text, self.run_dir)
        with self._lock:
            if self.status == RUNNING:
                self.final = final
                self.stage_state[4] = "done"
                self.status = DONE
                self.finished = time.time()
                self._push(ProgressEvent(0, "done", "Report ready"))

    def _fail(self, ctx: RunContext, kind: str) -> str:
        """Keep partial findings if Stage 1 finished; otherwise mark the run failed."""
        with self._lock:
            if self.status != RUNNING:
                return "failed"
            self.error_kind = kind
            self.finished = time.time()
            if ctx.results.get("market"):
                raw = self._raw(ctx, strategy=None, writer=None)
                save_run(self.run_dir, raw, ctx.seen_text)
                self.final = finalize(self.inp, raw["market"], raw["feedback"], None, None,
                                      ctx.seen_text, self.run_dir, check_links=False)
                self.status = PARTIAL
                self._push(ProgressEvent(0, "error", "Run stopped early. Partial report saved."))
                return "partial"
            self.status = FAILED
            self._push(ProgressEvent(0, "error", "Run stopped."))
            return "failed"

    def _on_timeout(self) -> None:
        ctx = self._ctx
        if ctx is None:
            return
        ctx.cancelled = True  # tools stop searching/reading; the stage wraps up on its own
        log.warning("run %s hit the %ss time limit", self.run_id, settings.run_timeout_seconds)
        self._fail(ctx, "timeout")

    def _raw(self, ctx: RunContext, strategy: dict | None, writer: str | None) -> dict:
        return {
            "inputs": self.inp.model_dump(),
            "market": ctx.results.get("market") or {"competitors": [], "sources": []},
            "feedback": ctx.results.get("feedback"),
            "strategy": strategy,
            "report_markdown": writer,
            "evidence": ctx.results.get("evidence", []),
            "searches": ctx.searches,
            "fetches": ctx.fetches,
            "seen_urls": sorted(ctx.seen_urls),
        }

    def _log(self, result, ctx: RunContext, outcome: str, error_type: str) -> None:
        usage = getattr(result, "token_usage", None)
        p_tok = (usage.prompt_tokens if usage else 0) + sum(u["prompt"] for u in ctx.llm_usage)
        c_tok = (usage.completion_tokens if usage else 0) + sum(u["completion"] for u in ctx.llm_usage)
        calls = (usage.successful_requests if usage else 0) + len(ctx.llm_usage)
        record = {
            "run_id": self.run_id,
            "input_chars": sum(len(v) for v in self.inp.model_dump().values() if isinstance(v, str)),
            "duration_s": round(self.elapsed, 1),
            "model_calls": calls,
            "prompt_tokens": p_tok,
            "completion_tokens": c_tok,
            "cost_usd": estimate_cost(p_tok, c_tok),
            "searches": len(ctx.searches),
            "page_reads": len(ctx.fetches),
            "competitors": len((ctx.results.get("market") or {}).get("competitors", [])),
            "outcome": outcome,
            "error_type": error_type,
        }
        log_run(record)
        log.info("run %s: %s", self.run_id, record)


def _pyd(task) -> dict | None:
    out = getattr(task, "output", None)
    if out is None:
        return None
    return out.pydantic.model_dump(mode="json") if out.pydantic is not None else None
