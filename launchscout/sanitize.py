"""Cleans report text so it reads like a market research analyst wrote it.

- Sentences where the text talks about itself as an AI / language model, or about its own
  instructions, are removed.
- AI-style phrasing ("leverage", "delve into", "seamless"...) is replaced with plain words.
- First-person research voice ("I found", "our research") is rewritten to neutral third person.
- Words like "AI", "model" or "agent" are only reported as warnings: they are allowed when the
  content genuinely needs them (e.g. "business model", or an idea that is itself about AI).
"""

from __future__ import annotations

import re

# Sentences containing these are removed: the text describing itself or its process.
SELF_REFERENCE = re.compile(
    r"\b(as an ai|as a language model|i am an ai|i'm an ai|this instruction|my instructions|"
    r"the (search|scrape|scraping|file writer) tool|i (used|ran) (a |the )?tool|"
    r"based on my training|knowledge cutoff)\b",
    re.I,
)

# Plain replacements for AI-style phrasing (case-insensitive, whole words).
REPLACEMENTS: list[tuple[str, str]] = [
    (r"\bin today's fast-paced world,?\s*", ""),
    (r"\bcomprehensive insights\b", "findings"),
    (r"\bpowerful insights\b", "findings"),
    (r"\b(delved|dived|dove) into\b", "looked at"),
    (r"\b(delving|diving) into\b", "looking at"),
    (r"\b(delves|dives) into\b", "looks at"),
    (r"\b(delve|dive) into\b", "look at"),
    (r"\bdelved\b", "looked"),
    (r"\bdelv(e|es|ing)\b", "look"),
    (r"\bleverag(e|es|ed|ing)\b", "us\\1"),
    (r"\bharness(es|ed|ing)?\b", "use"),
    (r"\bunlock(s|ed|ing)?\b", "open\\1"),
    (r"\bunleash(es|ed|ing)?\b", "release"),
    (r"\bsupercharg(e|es|ed|ing)\b", "improv\\1"),
    (r"\bempower(s|ed|ing)?\b", "help\\1"),
    (r"\belevat(e|es|ed|ing)\b", "rais\\1"),
    (r"\bseamless(ly)?\b", "smooth\\1"),
    (r"\beffortless(ly)?\b", "easy"),
    (r"\bcutting-edge\b", "modern"),
    (r"\brobust\b", "strong"),
    (r"\bgame-changer\b", "major change"),
    (r"\brevolutioniz(e|es|ed|ing)\b", "chang\\1"),
    (r"\bjourney\b", "process"),
]

# Chatty openers/closers at the start of a line or sentence: removed with their sentence.
CHATTY = re.compile(
    r"(^|(?<=[.!?]\s))(certainly!?|great question|here's|here is|let's|i hope this helps|"
    r"feel free to)[^.!?\n]*[.!?]?\s*",
    re.I | re.M,
)

FIRST_PERSON = [
    (r"\b(i|we) (found|identified|observed|noticed)\b", "the research \\2"),
    (r"\b(my|our) (research|analysis|findings|searches)\b", "the \\2"),
    (r"\bi (searched|looked|checked)\b", "searches \\1"),
    (r"\bwe (searched|looked|checked)\b", "searches \\1"),
    (r"\bi (recommend|suggest)\b", "the report \\1s"),
    (r"\bwe (recommend|suggest)\b", "the report \\1s"),
]

# Reported but not changed (soft rule): allowed when genuinely needed.
WATCH_WORDS = re.compile(
    r"\b(AI|A\.I\.|artificial intelligence|LLM|language model|GPT|OpenAI|Claude|Gemini|CrewAI|"
    r"agents?|chatbot|prompts?|tokens?|generated|generative)\b"
)


def _match_case(src: str, repl: str) -> str:
    return repl[:1].upper() + repl[1:] if src[:1].isupper() and repl else repl


def _sub(pattern: str, repl: str, text: str) -> tuple[str, int]:
    rx = re.compile(pattern, re.I)
    count = 0

    def f(m: re.Match) -> str:
        nonlocal count
        count += 1
        return _match_case(m.group(0), m.expand(repl))

    return rx.sub(f, text), count


def _drop_self_reference(text: str) -> tuple[str, int]:
    dropped = 0
    out_lines = []
    for line in text.split("\n"):
        if not SELF_REFERENCE.search(line):
            out_lines.append(line)
            continue
        parts = re.split(r"(?<=[.!?])\s+", line)
        keep = [p for p in parts if not SELF_REFERENCE.search(p)]
        dropped += len(parts) - len(keep)
        if keep:
            out_lines.append(" ".join(keep))
    return "\n".join(out_lines), dropped


def sanitize(markdown: str) -> tuple[str, dict]:
    """Return (clean_markdown, report) where report lists what was changed or flagged."""
    text, n_self = _drop_self_reference(markdown)
    text, n_chatty = CHATTY.subn("", text)
    n_style = 0
    for pat, rep in REPLACEMENTS:
        text, c = _sub(pat, rep, text)
        n_style += c
    n_first = 0
    for pat, rep in FIRST_PERSON:
        text, c = _sub(pat, rep, text)
        n_first += c
    text = re.sub(r"[ \t]{2,}(?=\S)", " ", text)  # tidy double spaces left by removals (keeps "  \n")
    watch = sorted({m.group(0) for m in WATCH_WORDS.finditer(text)})
    return text, {
        "self_reference_sentences_removed": n_self,
        "chatty_phrases_removed": n_chatty,
        "style_phrases_replaced": n_style,
        "first_person_rewritten": n_first,
        "watch_words": watch,
    }
