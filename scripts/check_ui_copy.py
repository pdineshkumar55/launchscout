"""Checks user-visible text for AI-style phrasing and AI-reference words.

Scans string literals in app.py and ui/ (via ast), plus any extra files given on the command line
(e.g. a generated report.md).

- AI-style phrases ("leverage", "delve", "Certainly!") are ERRORS: exit code 1.
- AI-reference words ("AI", "model", "agent"...) are WARNINGS only, because they are allowed when
  the text genuinely needs them. Use --strict to make them errors too.

Usage: python scripts/check_ui_copy.py [--strict] [extra files...]
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI_FILES = [ROOT / "app.py", *sorted((ROOT / "ui").glob("*.py"))]

AI_STYLE = [
    r"\bunlock\w*", r"\bunleash\w*", r"\bseamless\w*", r"\beffortless\w*", r"\belevat\w*", r"\bsupercharg\w*",
    r"\bempower\w*", r"\bharness\w*", r"\bleverag\w*", r"\bdive into\b", r"\bdelv\w*", r"\bgame[- ]changer\b",
    r"\brevolutioni[sz]\w*", r"\bcutting[- ]edge\b", r"\brobust\b", r"\bcomprehensive insights\b",
    r"\bpowerful insights\b", r"\bin today's fast-paced world\b", r"\bjourney\b", r"\bcertainly!",
    r"\bgreat question\b", r"\bhere's\b", r"\blet's\b", r"\bi hope this helps\b", r"\bfeel free to\b",
]
AI_WORDS = [
    r"\bAI\b", r"\bA\.I\.", r"\bartificial intelligence\b", r"\bLLM\b", r"\blanguage model\b", r"\bmodels?\b",
    r"\bGPT\b", r"\bOpenAI\b", r"\bClaude\b", r"\bGemini\b", r"\bCrewAI\b", r"\bcrew\b", r"\bagents?\b",
    r"\bbot\b", r"\bassistant\b", r"\bprompts?\b", r"\btokens?\b", r"\bgenerated\b", r"\bgenerative\b",
    r"\bautonomous\b", r"\bmachine learning\b", r"\bintelligent\b", r"\bmagic\b",
]
AI_ICONS = ["🤖", "🧠", "✨", "🪄"]

STYLE_RE = re.compile("|".join(AI_STYLE), re.I)
WORDS_RE = re.compile("|".join(AI_WORDS), re.I)


def ui_strings(path: Path) -> list[tuple[int, str]]:
    """String literals in a Python file, skipping docstrings, f-string internals and log/format keys."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                docstrings.add(id(body[0].value))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            if node.value.strip():
                out.append((node.lineno, node.value))
    return out


def scan_text(text: str) -> tuple[list[str], list[str]]:
    errors = [m.group(0) for m in STYLE_RE.finditer(text)] + [i for i in AI_ICONS if i in text]
    warnings = [m.group(0) for m in WORDS_RE.finditer(text)]
    return errors, warnings


# Literals that are code, not copy (module paths, logger names, widget keys, etc.).
CODE_LIKE = re.compile(r"^(launchscout[.\w]*|[a-z_]+(\.[a-z_]+)+|f_\w+|[a-z_-]+|%\(.*|text/\w+|application/\w+)$")


def main(argv: list[str]) -> int:
    strict = "--strict" in argv
    extra = [Path(a) for a in argv if not a.startswith("--")]
    n_err = n_warn = 0
    for path in UI_FILES:
        for line, s in ui_strings(path):
            if CODE_LIKE.match(s):
                continue
            errors, warnings = scan_text(s)
            for e in errors:
                print(f"ERROR   {path.relative_to(ROOT)}:{line}: AI-style phrase '{e}' in: {s[:70]!r}")
                n_err += 1
            for w in warnings:
                print(f"{'ERROR  ' if strict else 'WARNING'} {path.relative_to(ROOT)}:{line}: word '{w}' in: {s[:70]!r}")
                n_warn += 1
    for path in extra:
        text = path.read_text(encoding="utf-8")
        for no, line in enumerate(text.splitlines(), start=1):
            errors, warnings = scan_text(line)
            for e in errors:
                print(f"ERROR   {path}:{no}: AI-style phrase '{e}'")
                n_err += 1
            for w in warnings:
                print(f"{'ERROR  ' if strict else 'WARNING'} {path}:{no}: word '{w}'")
                n_warn += 1
    print(f"check_ui_copy: {n_err} error(s), {n_warn} warning(s)")
    return 1 if n_err or (strict and n_warn) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
