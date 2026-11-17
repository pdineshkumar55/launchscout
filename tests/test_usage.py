import json
from dataclasses import replace

import pytest

from launchscout import usage


@pytest.fixture
def tmp_settings(tmp_path, monkeypatch):
    s = replace(usage.settings, data_dir=tmp_path / "data", logs_dir=tmp_path / "logs", daily_run_cap=2)
    monkeypatch.setattr(usage, "settings", s)
    return s


def test_daily_cap(tmp_settings):
    assert usage.reserve_daily_run() and usage.reserve_daily_run()
    assert not usage.reserve_daily_run()
    assert usage.runs_today() == 2
    usage.release_daily_run()
    assert usage.reserve_daily_run()


def test_run_log_drops_unknown_fields(tmp_settings):
    usage.log_run({"run_id": "abc", "outcome": "ok", "cost_usd": 0.01, "idea": "secret idea text"})
    line = (tmp_settings.logs_dir / "runs.jsonl").read_text(encoding="utf-8").strip()
    rec = json.loads(line)
    assert rec["run_id"] == "abc" and "idea" not in rec and "ts" in rec


def test_mask_pii():
    masked = usage.mask_pii("Call +91 98765 43210 or mail owner@shop.in")
    assert "[phone]" in masked and "[email]" in masked and "98765" not in masked


def test_cost_estimate():
    assert usage.estimate_cost(1_000_000, 1_000_000) == 0.75
