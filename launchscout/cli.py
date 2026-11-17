"""Command-line run: python -m launchscout.cli --idea "..." --city "..."

Developer tool. Prints progress and usage to the terminal and saves outputs/<slug>_<time>/.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import settings
from .models import ResearchInputs
from .pipeline import print_checks, refinalize


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "LiteLLM", "litellm", "urllib3", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run a competitor research report from the terminal.")
    p.add_argument("--rebuild", metavar="RUN_DIR",
                   help="re-assemble a saved run folder (no search or model cost)")
    p.add_argument("--no-link-check", action="store_true")
    p.add_argument("--idea")
    p.add_argument("--city")
    p.add_argument("--target", default="General consumers")
    p.add_argument("--competitors", default="")
    p.add_argument("--own-business", default="", help="your own business; never listed as a competitor")
    p.add_argument("--country", default="India")
    p.add_argument("--currency", default="Rs")
    p.add_argument("--no-cache", action="store_true")
    args = p.parse_args(argv)
    setup_logging()

    if args.rebuild:
        final = refinalize(Path(args.rebuild), check_links=not args.no_link_check)
        print(final.markdown)
        print("=== Checks (terminal only) ===")
        print_checks(final.checks)
        return 0
    if not (args.idea and args.city):
        p.error("--idea and --city are required (or use --rebuild RUN_DIR)")
    if missing := settings.missing_keys():
        print(f"Missing keys in .env: {', '.join(missing)}")
        return 2

    from .research import run_research  # heavy import (CrewAI) only when actually running

    inp = ResearchInputs(idea=args.idea, city=args.city, target=args.target,
                         known_competitors=args.competitors, country=args.country, currency=args.currency,
                         own_business=args.own_business)
    r = run_research(inp, on_event=lambda kind, text: print(f"  [{kind}] {text}", flush=True),
                     use_cache=not args.no_cache, check_links=not args.no_link_check)

    print("\n=== Run summary (terminal only) ===")
    print(f"Folder:      {r.final.run_dir}")
    print(f"Duration:    {r.duration_s:.0f}s")
    print(f"Searches:    {r.searches}   Page reads: {r.page_reads}")
    print(f"Competitors: {len(r.raw['market'].get('competitors', []))}")
    print(f"Tokens:      prompt={r.prompt_tokens} completion={r.completion_tokens} requests={r.model_calls}")
    print(f"Est. cost:   ${r.cost_usd:.4f} (gpt-4o-mini pricing)")
    print_checks(r.final.checks)
    return 0


if __name__ == "__main__":
    sys.exit(main())
