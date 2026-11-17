"""Daily usage totals from logs/runs.jsonl.

Usage: python scripts/usage_report.py [--days 14]
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "logs" / "runs.jsonl"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=14)
    args = p.parse_args()
    if not LOG.exists():
        print("No runs logged yet.")
        return 0
    days: dict[str, dict] = defaultdict(lambda: {"runs": 0, "cost": 0.0, "failed": 0, "duration": 0.0,
                                                 "searches": 0})
    for line in LOG.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        d = days[r.get("ts", "")[:10]]
        d["runs"] += 1
        d["cost"] += r.get("cost_usd", 0) or 0
        d["duration"] += r.get("duration_s", 0) or 0
        d["searches"] += r.get("searches", 0) or 0
        d["failed"] += r.get("outcome") not in ("ok",)
    print(f"{'Day':<12}{'Runs':>6}{'Cost USD':>10}{'Avg s':>8}{'Searches':>10}{'Not ok':>8}{'Fail %':>8}")
    for day in sorted(days)[-args.days:]:
        d = days[day]
        print(f"{day:<12}{d['runs']:>6}{d['cost']:>10.4f}{d['duration'] / d['runs']:>8.0f}{d['searches']:>10}"
              f"{d['failed']:>8}{100 * d['failed'] / d['runs']:>7.0f}%")
    tot_runs = sum(d["runs"] for d in days.values())
    tot_cost = sum(d["cost"] for d in days.values())
    print(f"Total: {tot_runs} runs, ${tot_cost:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
