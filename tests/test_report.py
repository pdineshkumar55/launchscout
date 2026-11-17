import re
from datetime import date

from launchscout.report import HEADINGS, UNVERIFIED_MARK, assemble, check_structure, split_sections

TODAY = date(2026, 11, 17)


def build(inp, market, feedback, strategy, writer, price_ok=None):
    md, notes = assemble(inp, market, feedback, strategy, writer, price_ok, today=TODAY)
    return md, notes


def test_all_six_sections_in_order(inp, market, feedback, strategy, writer_md):
    md, _ = build(inp, market, feedback, strategy, writer_md)
    positions = [md.index(h) for h in HEADINGS]
    assert positions == sorted(positions)
    assert md.startswith("# Competitor Report: Millet meal boxes, Testcity")
    assert "Verify prices before making decisions" in md


def test_citations_consistent(inp, market, feedback, strategy, writer_md):
    md, _ = build(inp, market, feedback, strategy, writer_md)
    s = check_structure(md)
    assert s["sections_ok"] and s["citations_ok"], s
    assert s["competitors"] == 3


def test_sources_numbered_sequentially_from_one(inp, market, feedback, strategy, writer_md):
    md, _ = build(inp, market, feedback, strategy, writer_md)
    nums = [int(n) for n in re.findall(r"^\[(\d+)\]", md.partition("## Sources")[2], re.M)]
    assert nums == list(range(1, len(nums) + 1))


def test_writer_unknown_citation_dropped(inp, market, feedback, strategy, writer_md):
    md, _ = build(inp, market, feedback, strategy, writer_md)
    assert "[99]" not in md


def test_duplicate_url_gets_one_number(inp, market, feedback, strategy):
    feedback["sources"].append({"id": 7, "title": "Same page", "url": market["sources"][0]["url"]})
    feedback["items"][0]["source_ids"] = [7]
    md, _ = build(inp, market, feedback, strategy, "")
    urls = re.findall(r"— (\S+)$", md.partition("## Sources")[2], re.M)
    assert len(urls) == len(set(urls))
    assert check_structure(md)["citations_ok"]


def test_fallback_when_writer_missing(inp, market, feedback, strategy):
    md, notes = build(inp, market, feedback, strategy, None)
    assert check_structure(md)["sections_ok"]
    plan = split_sections(md)["## 5. 30-Day Launch Plan"]
    assert all(f"Week {n}" in plan for n in range(1, 5))
    assert strategy["market_gap"] in md
    assert any("rebuilt" in n for n in notes)


def test_fallback_when_writer_plan_incomplete(inp, market, feedback, strategy, writer_md):
    broken = writer_md.replace("- Week 3: Test a Rs 150 intro price.\n", "")
    md, notes = build(inp, market, feedback, strategy, broken)
    plan = split_sections(md)["## 5. 30-Day Launch Plan"]
    assert all(f"Week {n}" in plan for n in range(1, 5))
    assert "writer launch plan incomplete, rebuilt" in notes


def test_gap_prefers_strategy(inp, market, feedback, strategy, writer_md):
    md, _ = build(inp, market, feedback, strategy, writer_md)
    gap = split_sections(md)["## 3. Market Gap"]
    assert gap == strategy["market_gap"]


def test_gap_falls_back_to_writer_and_renumbers(inp, market, feedback, strategy, writer_md):
    strategy["market_gap"] = ""
    md, _ = build(inp, market, feedback, strategy, writer_md)
    gap = split_sections(md)["## 3. Market Gap"]
    assert "evening millet option" in gap
    assert re.search(r"\[\d+\]", gap)


def test_positioning_from_strategy(inp, market, feedback, strategy, writer_md):
    md, _ = build(inp, market, feedback, strategy, writer_md)
    pos = split_sections(md)["## 4. Recommended Positioning"]
    assert '> "Evening millet meal boxes delivered by 8 pm, Rs 160 per meal"' in pos
    assert pos.count("Why this price:") == 1


def test_unverified_price_marked(inp, market, feedback, strategy):
    md, _ = build(inp, market, feedback, strategy, "", price_ok={"Ragi Box": True, "Green Tiffin Co": False})
    table = split_sections(md)["## 1. Key Competitors"]
    tiffin = next(line for line in table.splitlines() if "Green Tiffin" in line)
    ragi = next(line for line in table.splitlines() if "Ragi Box" in line)
    assert UNVERIFIED_MARK in tiffin and UNVERIFIED_MARK not in ragi
    kitchen = next(line for line in table.splitlines() if "Millet Kitchen" in line)
    assert "Not listed" in kitchen and UNVERIFIED_MARK not in kitchen


def test_complaints_section_content(inp, market, feedback, strategy):
    md, _ = build(inp, market, feedback, strategy, "")
    s2 = split_sections(md)["## 2. What Customers Complain About"]
    assert s2.splitlines()[0].startswith("- Late delivery (Ragi Box, Millet Kitchen)")
    assert "Small seating area (Millet Kitchen)" in s2
    assert "Limited public reviews found for: Green Tiffin Co." in s2
    assert "**What customers praise:**\n\n- " in s2


def test_no_complaints_message(inp, market, feedback, strategy):
    for item in feedback["items"]:
        item["complaints"] = []
    feedback["common_complaints"] = []
    md, _ = build(inp, market, feedback, strategy, "")
    assert "No complaints were found" in md
    assert check_structure(md)["citations_ok"]


def test_online_regional_labelled(inp, market, feedback, strategy):
    md, _ = build(inp, market, feedback, strategy, "")
    assert "Millet Kitchen (online/regional)" in md


def test_pipe_in_cell_does_not_break_table(inp, market, feedback, strategy):
    market["competitors"][0]["strength"] = "Fast | cheap"
    md, _ = build(inp, market, feedback, strategy, "")
    row = next(line for line in md.splitlines() if line.startswith("| Ragi Box"))
    assert row.count("|") == 7


def test_check_structure_detects_problems():
    s = check_structure("## 1. Key Competitors\nSee [3].\n## Sources\n[1] A — https://a.example\n")
    assert not s["sections_ok"]
    assert s["unresolved_citations"] == [3] and s["unused_sources"] == [1]


def test_own_business_noted_in_header(market, feedback, strategy):
    from launchscout.models import ResearchInputs
    inp = ResearchInputs(idea="silk saree shop", city="Udumalpet", own_business="Sri Example Silks")
    md, _ = build(inp, market, feedback, strategy, "")
    assert "_Your business: Sri Example Silks (left out of the competitor list)_" in md
    assert check_structure(md)["sections_ok"]


def test_writer_backup_path_is_relative(tmp_path, monkeypatch):
    # CrewAI strips a leading "/" from output_file; an absolute path broke runs in the container.
    from pathlib import Path

    from launchscout.tasks import backup_output_path
    monkeypatch.chdir(tmp_path)
    inside = backup_output_path(tmp_path / "outputs" / "run1" / "report_writer.md")
    assert inside == "outputs/run1/report_writer.md" and not Path(inside).is_absolute()
    outside = backup_output_path(tmp_path.parent / "elsewhere" / "report_writer.md")
    assert outside is None
