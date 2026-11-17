from launchscout.sanitize import sanitize


def test_ai_style_phrases_replaced():
    text, report = sanitize("Founders can leverage this robust, seamless plan to delve into the market.")
    low = text.lower()
    for word in ("leverage", "robust", "seamless", "delve"):
        assert word not in low
    assert "use this strong, smooth plan" in text
    assert report["style_phrases_replaced"] >= 4


def test_verb_forms_stay_grammatical():
    text, _ = sanitize("The team delved into reviews while leveraging delivery apps.")
    assert "looked at reviews" in text and "using delivery apps" in text


def test_self_reference_sentence_removed():
    text, report = sanitize("Prices start at Rs 180. As an AI, I cannot visit shops. Demand is high.")
    assert "As an AI" not in text
    assert "Prices start at Rs 180." in text and "Demand is high." in text
    assert report["self_reference_sentences_removed"] == 1


def test_first_person_rewritten():
    text, report = sanitize("We found three competitors. Our research shows a gap. I recommend Rs 160.")
    assert "We found" not in text and "Our research" not in text and "I recommend" not in text
    assert "The research found" in text and "The research shows" in text
    assert report["first_person_rewritten"] == 3


def test_chatty_openers_removed():
    text, report = sanitize("Certainly! Here's the plan.\nWeek 1: list on Swiggy.")
    assert "Certainly" not in text and "Here's" not in text
    assert "Week 1: list on Swiggy." in text


def test_watch_words_flagged_not_removed():
    # Soft rule: genuine uses stay; they are only reported.
    text, report = sanitize("An AI tutoring centre needs a clear business model.")
    assert text == "An AI tutoring centre needs a clear business model."
    assert "AI" in report["watch_words"]


def test_markdown_line_breaks_kept():
    md = "[1] A — https://a.example  \n[2] B — https://b.example"
    text, _ = sanitize(md)
    assert text == md


def test_clean_text_unchanged():
    md = "## 3. Market Gap\nNo evening millet option exists in Testcity [1]."
    text, report = sanitize(md)
    assert text == md
    assert not any(v for k, v in report.items() if k != "watch_words")
