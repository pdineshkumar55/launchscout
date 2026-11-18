"""Runner tests with a fake crew: no network, no model calls."""

import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

from launchscout import runner as runner_mod
from launchscout.runner import DONE, FAILED, PARTIAL, ResearchRun


class FakeCrew:
    def __init__(self, ctx, market, feedback, delay=0.0, fail=False):
        self.ctx, self.market, self.feedback, self.delay, self.fail = ctx, market, feedback, delay, fail
        self.task_callback = None

    def kickoff(self):
        self.ctx.on_event("search", "millet meals Testcity")
        self.ctx.results["market"] = self.market
        self.ctx.after_market(self.market)            # Stage 1 accepted
        self.task_callback(None)
        if self.fail:
            raise RuntimeError("boom")
        time.sleep(self.delay)
        self.ctx.on_event("read", "https://www.zomato.com/testcity/ragi-box/reviews")
        self.ctx.results["feedback"] = self.feedback
        self.task_callback(None)                      # Stage 2
        self.task_callback(None)                      # Stage 3
        self.task_callback(None)                      # Stage 4
        usage = SimpleNamespace(prompt_tokens=1000, completion_tokens=100, successful_requests=8)
        return SimpleNamespace(raw="", token_usage=usage)


@pytest.fixture
def fake_env(tmp_path, monkeypatch, market, feedback, strategy, writer_md):
    s = replace(runner_mod.settings, outputs_dir=tmp_path / "out", logs_dir=tmp_path / "logs",
                run_timeout_seconds=60)
    monkeypatch.setattr(runner_mod, "settings", s)
    monkeypatch.setattr("launchscout.pipeline.settings", s)
    monkeypatch.setattr("launchscout.usage.settings", s)
    monkeypatch.setattr("launchscout.checks.check_sources", lambda urls: [])
    opts = {"delay": 0.0, "fail": False}

    def fake_build(inp, ctx, run_dir):
        ctx.after_market = lambda m: ctx.results.setdefault("evidence", [])
        crew = FakeCrew(ctx, market, feedback, **opts)
        out = lambda d: SimpleNamespace(output=SimpleNamespace(pydantic=None, raw=d))  # noqa: E731
        strat = SimpleNamespace(output=SimpleNamespace(pydantic=SimpleNamespace(model_dump=lambda mode=None: strategy)))
        return SimpleNamespace(crew=crew, market=out(""), feedback=out(""), strategy=strat,
                               report=SimpleNamespace(output=SimpleNamespace(raw=writer_md)))
    monkeypatch.setattr(runner_mod, "build_crew", fake_build)
    return opts


def wait(run, seconds=10):
    end = time.time() + seconds
    while run.is_running and time.time() < end:
        run.poll()
        time.sleep(0.05)
    run.drain()


def test_full_run_events_and_report(fake_env, inp):
    run = ResearchRun(inp)
    run.start()
    wait(run)
    assert run.status == DONE
    texts = [e.text for e in run.events]
    assert texts[0] == "Stage 1 · Market scan started"
    assert "Searching: millet meals Testcity" in texts
    assert "Stage 1 complete: 3 competitors found" in texts
    assert "Stage 2 complete: reviews found for 2 of 3 competitors" in texts
    assert texts[-1] == "Report ready"
    assert run.stage_state == {1: "done", 2: "done", 3: "done", 4: "done"}
    assert (run.run_dir / "report.md").exists() and (run.run_dir / "raw.json").exists()
    # the read happened while stage 2 was running
    read = next(e for e in run.events if e.kind == "read")
    assert read.stage == 2


def test_run_logged_without_user_text(fake_env, inp, tmp_path):
    run = ResearchRun(inp)
    run.start()
    wait(run)
    log = (tmp_path / "logs" / "runs.jsonl").read_text(encoding="utf-8")
    assert '"outcome": "ok"' in log and "millet" not in log


def test_failure_after_stage1_gives_partial_report(fake_env, inp):
    fake_env["fail"] = True
    run = ResearchRun(inp)
    run.start()
    wait(run)
    assert run.status == PARTIAL and run.final is not None
    assert "## 1. Key Competitors" in run.final.markdown


def test_timeout_keeps_partial(fake_env, inp, monkeypatch):
    fake_env["delay"] = 1.0
    run = ResearchRun(inp)
    run.start()
    time.sleep(0.3)
    run.started -= 1000          # pretend the time limit passed
    run.poll()
    assert run.status == PARTIAL and run.error_kind == "timeout"
    assert run._ctx.cancelled
    time.sleep(1.2)              # crew finishes later; must not overwrite the partial result
    assert run.status == PARTIAL


def test_failure_before_stage1_is_failed(fake_env, inp, monkeypatch):
    def broken_build(*a):
        raise RuntimeError("no crew")
    monkeypatch.setattr(runner_mod, "build_crew", broken_build)
    run = ResearchRun(inp)
    run.start()
    wait(run)
    assert run.status == FAILED and run.final is None


def test_own_business_stage_runs_between_stage1_and_2(fake_env, monkeypatch):
    from launchscout.models import ResearchInputs
    from launchscout.pipeline import load_run
    inner = runner_mod.build_crew

    def build(inp, ctx, run_dir):
        built = inner(inp, ctx, run_dir)

        def after_market(m):
            ctx.results["own"] = {"name": inp.own_business, "found": False,
                                  "note": f"No public listing or reviews found for {inp.own_business} in Testcity."}
            ctx.emit("own_start", inp.own_business)
            ctx.emit("own_done", inp.own_business)
        ctx.after_market = after_market
        return built
    monkeypatch.setattr(runner_mod, "build_crew", build)
    run = ResearchRun(ResearchInputs(idea="silk saree shop", city="Testcity", own_business="Sri Example Silks"))
    assert list(run.stage_state) == [1, 5, 2, 3, 4]
    run.start()
    wait(run)
    assert run.status == DONE
    assert run.stage_state == {1: "done", 5: "done", 2: "done", 3: "done", 4: "done"}
    texts = [e.text for e in run.events]
    i1 = texts.index("Stage 1 complete: 3 competitors found")
    i_own = texts.index("Your business scan started")
    i_done = texts.index("Your business scan complete: no public listing found")
    assert i1 < i_own < i_done < texts.index("Stage 2 · Customer feedback started")
    saved = load_run(run.run_dir)
    assert saved.own["found"] is False and "## 3. How You Compare" in saved.markdown
