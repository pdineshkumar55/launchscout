"""Benchmark: run every case in evals/cases.yaml, judge the reports, write evals/report.md.

    python -m evals.run_bench                 # run all cases, judge, write report
    python -m evals.run_bench --only millet-coimbatore
    python -m evals.run_bench --rejudge       # re-judge and rewrite the report from saved results (no runs)
    python -m evals.run_bench --save-samples  # also copy each case's report to docs/samples/<case>/

Search responses cached during development are reused when the same query repeats (saves search
credits); the research stages, checks and judging always run fresh.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path

import yaml

from launchscout.cli import setup_logging
from launchscout.config import settings
from launchscout.models import ResearchInputs
from launchscout.pipeline import load_run
from launchscout.usage import estimate_cost

from .judge import CRITERIA, judge_report

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
RESULTS = ROOT / "results.json"
REPORT = ROOT / "report.md"
TARGETS = {"structure_pct": 100.0, "reachable_pct": 90.0, "prices_verified_pct": 70.0, "judge_avg": 4.0}
SAMPLE_FILES = ("report.md", "report.pdf", "checks.json", "raw.json")


def load_private() -> dict:
    """Git-ignored per-case values (e.g. the developer's own shop). Empty if the file is absent."""
    path = ROOT / "private.yaml"
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}


def load_cases(include_private: bool = True) -> list[dict]:
    cases = yaml.safe_load((ROOT / "cases.yaml").read_text(encoding="utf-8"))
    if include_private:
        private = load_private()
        cases = [c | private.get(c["name"], {}) for c in cases]
    return cases


def public_inputs(inputs: dict) -> dict:
    """Inputs as stored in public files: private values blanked."""
    return inputs | {"own_business": ""} if inputs.get("own_business") else inputs


def case_inputs(case: dict) -> ResearchInputs:
    return ResearchInputs(idea=case["idea"], city=case["city"], target=case.get("target", "General consumers"),
                          known_competitors=case.get("competitors", ""), own_business=case.get("own_business", ""))


def metrics(checks: dict) -> dict:
    s, src, pr = checks["structure"], checks["sources"], checks["prices"]
    return {
        "sections_ok": s["sections_ok"], "citations_ok": s["citations_ok"],
        "competitors": s["competitors"], "enough_competitors": s["enough_competitors"],
        "structure_pass": s["sections_ok"] and s["citations_ok"] and s["enough_competitors"],
        "sources_total": src["total"], "sources_reachable": round(src["reachable_pct"] * src["total"] / 100),
        "reachable_pct": src["reachable_pct"], "sources_broken": src["broken"],
        "prices_total": pr["with_price"], "prices_verified": pr["verified"], "prices_verified_pct": pr["verified_pct"],
    }


def run_case(case: dict) -> dict:
    from launchscout.research import run_research  # CrewAI import only when running

    print(f"\n=== {case['name']}: {case['idea']}, {case['city']} ===", flush=True)
    r = run_research(case_inputs(case), on_event=lambda k, t: print(f"  [{k}] {t}", flush=True))
    return {
        "name": case["name"], "inputs": public_inputs(r.raw["inputs"]),
        "run_dir": r.final.run_dir.resolve().relative_to(PROJECT).as_posix(),
        "duration_s": r.duration_s, "cost_usd": r.cost_usd, "model_calls": r.model_calls,
        "searches": r.searches, "page_reads": r.page_reads, **metrics(r.final.checks),
    }


def judge_case(result: dict) -> dict:
    saved = load_run(PROJECT / result["run_dir"])
    j = judge_report(saved.markdown, result["inputs"])
    result["judge"] = j
    result["judge_cost_usd"] = estimate_cost(j["prompt_tokens"], j["completion_tokens"])
    return result


def summarize(results: list[dict]) -> dict:
    n = len(results) or 1
    src_total = sum(r["sources_total"] for r in results) or 1
    price_total = sum(r["prices_total"] for r in results) or 1
    judged = [r["judge"]["average"] for r in results if r.get("judge")]
    return {
        "cases": len(results),
        "structure_pct": round(100 * sum(r["structure_pass"] for r in results) / n, 1),
        "avg_competitors": round(sum(r["competitors"] for r in results) / n, 1),
        "reachable_pct": round(100 * sum(r["sources_reachable"] for r in results) / src_total, 1),
        "prices_verified_pct": round(100 * sum(r["prices_verified"] for r in results) / price_total, 1),
        "judge_avg": round(sum(judged) / len(judged), 2) if judged else 0.0,
        "avg_duration_s": round(sum(r["duration_s"] for r in results) / n, 1),
        "avg_cost_usd": round(sum(r["cost_usd"] for r in results) / n, 4),
        "judge_cost_usd": round(sum(r.get("judge_cost_usd", 0) for r in results), 4),
    }


def write_report(results: list[dict]) -> str:
    s = summarize(results)

    def mark(key: str) -> str:
        return "✅" if s[key] >= TARGETS[key] else "❌"

    lines = [
        "# LaunchScout benchmark", "",
        f"Run on {date.today():%d %b %Y} · {s['cases']} cases · research model `{settings.model_default}` "
        f"(stages 1-2) / `{settings.model_strategy}` (stages 3-4) · judge `{results[0].get('judge', {}).get('model', '-')}`",
        "",
        "## Summary vs targets", "",
        "| Metric | Result | Target | |", "|---|---|---|---|",
        f"| Structure pass (6 sections, ≥3 competitors, citations resolve) | {s['structure_pct']}% | 100% | {mark('structure_pct')} |",
        f"| Sources reachable | {s['reachable_pct']}% | ≥ 90% | {mark('reachable_pct')} |",
        f"| Prices confirmed on their source | {s['prices_verified_pct']}% | ≥ 70% | {mark('prices_verified_pct')} |",
        f"| Judge average (1-5) | {s['judge_avg']} | ≥ 4 | {mark('judge_avg')} |",
        f"| Average competitors | {s['avg_competitors']} | 3-5 | |",
        f"| Average time per run | {s['avg_duration_s']} s | < 480 s | |",
        f"| Average cost per run | ${s['avg_cost_usd']} | | |",
        "",
        "## Per case", "",
        "| Case | Sections | Competitors | Sources reachable | Prices confirmed | Judge | Time | Cost |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        j = r.get("judge", {})
        lines.append(
            f"| {r['inputs']['idea']}, {r['inputs']['city']} | {'✅' if r['sections_ok'] else '❌'} | "
            f"{r['competitors']} | {r['sources_reachable']}/{r['sources_total']} | "
            f"{r['prices_verified']}/{r['prices_total']} | {j.get('average', '-')} | {r['duration_s']:.0f} s | "
            f"${r['cost_usd']:.4f} |")
    lines += ["", "## Judge details", ""]
    for r in results:
        j = r.get("judge")
        if not j:
            continue
        lines += [f"### {r['inputs']['idea']}, {r['inputs']['city']} (average {j['average']})", "",
                  f"{j['summary']}", "", "| Criterion | Score | Quote from the report | Reason |", "|---|---|---|---|"]
        for name in CRITERIA:
            v = j["scores"][name]
            q = v["quote"].replace("|", "/")
            flag = "" if v["quote_found"] else " ⚠️ quote not found in report"
            lines.append(f"| {name} | {v['score']} | “{q}”{flag} | {v['reason'].replace('|', '/')} |")
        lines.append("")
    lines += [
        "## Notes", "",
        "- Sources count as reachable when they answer, or when a listing platform (e.g. Zomato) refuses or "
        "stalls automated requests; a competitor's own site that fails counts as broken. Raw statuses are in each "
        "run's `checks.json`.",
        "- A price is confirmed when its number appears in the text fetched from one of its cited sources. "
        "Prices written as \"Not listed\" are not counted.",
        "- Search responses cached during development are reused for repeated queries; research stages, checks "
        f"and judging ran fresh. Judging cost ${s['judge_cost_usd']} in total.",
        "",
    ]
    text = "\n".join(lines)
    REPORT.write_text(text, encoding="utf-8")
    return text


def save_samples(results: list[dict]) -> None:
    for r in results:
        dest = settings.samples_dir / r["name"]
        dest.mkdir(parents=True, exist_ok=True)
        for f in SAMPLE_FILES:
            src = PROJECT / r["run_dir"] / f
            if src.exists():
                shutil.copy2(src, dest / f)
        print(f"sample saved: {dest}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", help="run just this case name")
    p.add_argument("--rejudge", action="store_true", help="judge saved results again, no research runs")
    p.add_argument("--no-judge", action="store_true")
    p.add_argument("--save-samples", action="store_true")
    args = p.parse_args(argv)
    setup_logging()

    if args.rejudge:
        results = json.loads(RESULTS.read_text(encoding="utf-8"))
    else:
        saved = {r["name"]: r for r in json.loads(RESULTS.read_text(encoding="utf-8"))} if RESULTS.exists() else {}
        for case in load_cases():
            if args.only and case["name"] != args.only:
                continue
            saved[case["name"]] = run_case(case)
            RESULTS.write_text(json.dumps(list(saved.values()), indent=2), encoding="utf-8")
        order = [c["name"] for c in load_cases()]
        results = [saved[n] for n in order if n in saved]

    if not args.no_judge:
        for r in results:
            print(f"judging {r['name']}…", flush=True)
            judge_case(r)
    RESULTS.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(write_report(results))
    if args.save_samples:
        save_samples(results)
    s = summarize(results)
    ok = all(s[k] >= v for k, v in TARGETS.items())
    print("ALL TARGETS MET" if ok else "SOME TARGETS MISSED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
