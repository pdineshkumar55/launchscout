"""Private values (evals/private.yaml, git-ignored) must never appear in files that get committed.

On machines without the private file (e.g. CI) there is nothing to check and the test is skipped.
"""

import re
from pathlib import Path

import pytest

from evals.run_bench import load_private

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".venv", "venv", "outputs", ".cache", "logs", "data", "__pycache__", ".git", ".pytest_cache",
             ".ruff_cache", "node_modules"}
SKIP_FILES = {ROOT / "evals" / "private.yaml", ROOT / ".env", ROOT / ".claude" / "settings.local.json"}
GENERIC = {"silks", "silk", "sarees", "saree", "shop", "store", "the", "and"}


def committed_files():
    for path in ROOT.rglob("*"):
        if path.is_file() and path not in SKIP_FILES and not (set(path.relative_to(ROOT).parts) & SKIP_DIRS):
            yield path


def file_text(path: Path) -> str:
    if path.suffix == ".pdf":
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return "\n".join(p.extract_text() or "" for p in pdf.pages)
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


def test_private_values_not_in_public_files():
    values = [v for case in load_private().values() for v in case.values() if isinstance(v, str) and v.strip()]
    if not values:
        pytest.skip("no evals/private.yaml on this machine")
    # Distinctive words of each private value (e.g. a shop's unique name part), whole-word, any case.
    words = {w.lower() for v in values for w in re.findall(r"[A-Za-z]{4,}", v)} - GENERIC
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, sorted(words))) + r")\b", re.I)
    leaks = [str(p.relative_to(ROOT)) for p in committed_files() if pattern.search(file_text(p))]
    assert not leaks, f"private values found in: {leaks}"
