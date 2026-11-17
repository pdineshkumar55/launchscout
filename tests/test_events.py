import re

from launchscout.events import STAGE_NAMES, short_url, stage_done, stage_start, tool_event

AI_WORDS = re.compile(r"\b(AI|LLM|model|agent|crew|thought|prompt|token|GPT|OpenAI)\b", re.I)


def test_search_and_read_messages():
    assert tool_event(1, "search", "millet meal delivery Coimbatore").text == "Searching: millet meal delivery Coimbatore"
    ev = tool_event(2, "read", "https://www.zomato.com/coimbatore/millet-life-1-peelamedu/reviews")
    assert ev.text == "Reading: zomato.com/coimbatore/millet-life-1-peelamedu/reviews"
    assert ev.stage == 2 and ev.kind == "read"


def test_short_url_truncates():
    s = short_url("https://example.com/" + "a" * 200)
    assert len(s) <= 60 and s.endswith("…")


def test_stage_messages():
    assert stage_start(1).text == "Stage 1 · Market scan started"
    assert stage_done(1, {"competitors": [{}, {}, {}, {}]}).text == "Stage 1 complete: 4 competitors found"
    assert stage_done(1, {"competitors": [{}]}).text.endswith("1 competitor found")
    fb = {"items": [{"source_ids": [5]}, {"source_ids": []}, {"source_ids": [6]}]}
    assert stage_done(2, fb).text == "Stage 2 complete: reviews found for 2 of 3 competitors"
    assert stage_done(3, {"market_gap": "x"}).text == "Stage 3 complete: gap identified"
    assert stage_done(4, None).text == "Stage 4 complete: report ready"


def test_no_ai_words_in_any_message():
    messages = [stage_start(n).text for n in STAGE_NAMES] + [stage_done(n, {}).text for n in STAGE_NAMES]
    messages += [tool_event(1, "search", "q").text, tool_event(1, "read", "https://a.example/b").text]
    for m in messages:
        assert not AI_WORDS.search(m), m
