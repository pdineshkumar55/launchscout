import requests

from launchscout import checks
from launchscout.checks import check_url, grade_prices, price_numbers, run_checks
from launchscout.report import assemble


def test_price_numbers():
    assert price_numbers("Rs 3,600 per month") == ["3600"]
    assert price_numbers("Rs 200–400 per meal") == ["200", "400"]
    assert price_numbers("Rs 99.50 for 1 box") == ["99.5"]
    assert price_numbers("Not listed") == []


def test_grade_prices(market, seen_text):
    graded = grade_prices(market, seen_text)
    assert graded["Ragi Box"]["status"] == "verified"
    assert graded["Green Tiffin Co"]["status"] == "unverified"
    assert graded["Millet Kitchen"]["status"] == "not_listed"


def test_price_match_is_whole_number(market):
    market["competitors"] = market["competitors"][:1]
    graded = grade_prices(market, {"https://ragibox.example/menu": "Call 1800 123 456"})
    assert graded["Ragi Box"]["status"] == "unverified"  # "180" inside "1800" does not count


class FakeResp:
    def __init__(self, code):
        self.status_code = code

    def close(self):
        pass


def test_check_url_statuses(monkeypatch):
    monkeypatch.setattr(requests, "head", lambda *a, **k: FakeResp(200))
    assert check_url("https://a.example")["status"] == "ok"
    monkeypatch.setattr(requests, "head", lambda *a, **k: FakeResp(404))
    assert check_url("https://a.example")["status"] == "broken"
    monkeypatch.setattr(requests, "head", lambda *a, **k: FakeResp(403))
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResp(403))
    assert check_url("https://a.example")["status"] == "blocked"


def test_timeout_counts_only_on_platforms(monkeypatch):
    def slow(*a, **k):
        raise requests.Timeout()
    monkeypatch.setattr(requests, "head", slow)
    assert check_url("https://www.zomato.com/x")["counts_as_reachable"] is True
    assert check_url("https://ragibox.example/")["counts_as_reachable"] is False


def test_run_checks_summary(inp, market, feedback, strategy, writer_md, seen_text, monkeypatch):
    monkeypatch.setattr(checks, "check_sources", lambda urls: [{"url": u, "status": "ok", "code": 200} for u in urls])
    prices = grade_prices(market, seen_text)
    md, _ = assemble(inp, market, feedback, strategy, writer_md)
    result = run_checks(md, market, prices)
    assert result["structure"]["sections_ok"] and result["structure"]["citations_ok"]
    assert result["sources"]["reachable_pct"] == 100.0 and result["sources"]["total"] >= 4
    assert result["prices"]["with_price"] == 2 and result["prices"]["verified"] == 1


def test_finalize_writes_files(tmp_path, inp, market, feedback, strategy, writer_md, seen_text, monkeypatch):
    from launchscout.pipeline import finalize
    monkeypatch.setattr(checks, "check_sources", lambda urls: [])
    final = finalize(inp, market, feedback, strategy, writer_md, seen_text, tmp_path, check_links=False)
    assert (tmp_path / "report.md").read_text(encoding="utf-8") == final.markdown
    assert (tmp_path / "checks.json").exists()
    assert "(price not confirmed on source)" in final.markdown  # Green Tiffin's Rs 3,600 not on its page
