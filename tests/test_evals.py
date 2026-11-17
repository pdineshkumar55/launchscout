from evals.judge import quote_in_report
from evals.run_bench import TARGETS, load_cases, public_inputs, summarize


def test_cases_file():
    cases = load_cases()
    assert len(cases) == 3
    assert {c["name"] for c in cases} == {"millet-coimbatore", "pet-grooming-chennai", "silk-saree-udumalpet"}
    public = load_cases(include_private=False)
    assert not any(c.get("own_business") for c in public)  # private values live in evals/private.yaml


def test_quote_check():
    report = "## 3. Market Gap\nNo one offers **evening** millet meals in Testcity [1].\n| Ragi Box | Rs 180 | x |"
    assert quote_in_report("No one offers evening millet meals in Testcity [1].", report)
    assert quote_in_report("Ragi Box | Rs 180", report)
    assert not quote_in_report("Customers are frustrated with late delivery.", report)
    assert not quote_in_report("", report)


def _r(**kw):
    base = dict(structure_pass=True, competitors=4, sources_total=10, sources_reachable=9, prices_total=4,
                prices_verified=3, duration_s=100.0, cost_usd=0.01, judge={"average": 4.25}, judge_cost_usd=0.001)
    return base | kw


def test_summary_pools_sources_and_prices():
    s = summarize([_r(), _r(sources_total=10, sources_reachable=10, prices_total=1, prices_verified=1,
                        structure_pass=False, judge={"average": 3.75})])
    assert s["structure_pct"] == 50.0
    assert s["reachable_pct"] == 95.0          # 19 of 20 sources, pooled
    assert s["prices_verified_pct"] == 80.0    # 4 of 5 prices, pooled
    assert s["judge_avg"] == 4.0
    assert set(TARGETS) <= set(s)


def test_public_inputs_blank_private_fields():
    assert public_inputs({"idea": "x", "own_business": "My Shop"})["own_business"] == ""
    assert public_inputs({"idea": "x"}) == {"idea": "x"}
