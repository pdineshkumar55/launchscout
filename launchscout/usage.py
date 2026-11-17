"""Usage caps and run logging.

- Daily run cap: a small SQLite counter shared by every visitor (atomic reserve/release).
- Concurrent run cap: process-wide semaphore so the VPS is never overloaded.
- Run log: one JSON line per run in logs/runs.jsonl. No raw user content is written; anything
  free-text that must be logged goes through mask_pii() first.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import date, datetime, timezone
from pathlib import Path

from .config import settings

_db_lock = threading.Lock()
_run_slots = threading.BoundedSemaphore(settings.max_concurrent_runs)

# gpt-4o-mini list prices (USD per token); other models are logged at the same rate as an estimate.
PRICE_IN = 0.15e-6
PRICE_OUT = 0.60e-6


def _db_path() -> Path:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings.data_dir / "usage.sqlite3"


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(_db_path(), timeout=10)
    con.execute("CREATE TABLE IF NOT EXISTS daily_runs (day TEXT PRIMARY KEY, count INTEGER NOT NULL)")
    return con


def runs_today() -> int:
    with _db_lock, _connect() as con:
        row = con.execute("SELECT count FROM daily_runs WHERE day = ?", (date.today().isoformat(),)).fetchone()
        return row[0] if row else 0


def reserve_daily_run() -> bool:
    """Count one run against today's cap. False if the cap is already reached."""
    day = date.today().isoformat()
    with _db_lock, _connect() as con:
        row = con.execute("SELECT count FROM daily_runs WHERE day = ?", (day,)).fetchone()
        count = row[0] if row else 0
        if count >= settings.daily_run_cap:
            return False
        con.execute("INSERT INTO daily_runs(day, count) VALUES(?, 1) "
                    "ON CONFLICT(day) DO UPDATE SET count = count + 1", (day,))
        return True


def release_daily_run() -> None:
    """Give a reserved run back (e.g. the run was refused before it started)."""
    day = date.today().isoformat()
    with _db_lock, _connect() as con:
        con.execute("UPDATE daily_runs SET count = MAX(count - 1, 0) WHERE day = ?", (day,))


def acquire_run_slot() -> bool:
    return _run_slots.acquire(blocking=False)


def release_run_slot() -> None:
    try:
        _run_slots.release()
    except ValueError:
        pass


_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d\s-]{8,}\d)(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def mask_pii(text: str) -> str:
    return _PHONE.sub("[phone]", _EMAIL.sub("[email]", text or ""))


def estimate_cost(prompt_tokens: int, completion_tokens: int) -> float:
    return round(prompt_tokens * PRICE_IN + completion_tokens * PRICE_OUT, 5)


def log_run(record: dict) -> None:
    """Append one run record to logs/runs.jsonl (terminal/log file only, never the UI)."""
    allowed = {"run_id", "input_chars", "duration_s", "model_calls", "prompt_tokens", "completion_tokens",
               "cost_usd", "searches", "page_reads", "retries", "competitors", "outcome", "error_type",
               "search_provider_fallbacks"}
    clean = {k: v for k, v in record.items() if k in allowed}
    clean["ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    with _db_lock, (settings.logs_dir / "runs.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(clean) + "\n")
