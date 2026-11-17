import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_ui_copy", ROOT / "scripts" / "check_ui_copy.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def test_ui_copy_has_no_ai_style_phrases(capsys):
    assert check.main([]) == 0, capsys.readouterr().out


def test_ui_copy_has_no_ai_words_or_icons():
    # Soft rule overall, but the app's own copy currently needs none of these words.
    for path in check.UI_FILES:
        for line, s in check.ui_strings(path):
            if check.CODE_LIKE.match(s):
                continue
            errors, warnings = check.scan_text(s)
            assert not errors and not warnings, f"{path.name}:{line}: {s!r}"


def test_checker_catches_problems():
    errors, warnings = check.scan_text("Certainly! Leverage our AI model ✨")
    assert len(errors) >= 3 and {"AI", "model"} <= set(warnings)


def test_docstrings_ignored(tmp_path):
    f = tmp_path / "x.py"
    f.write_text('"""Uses an AI model internally."""\nLABEL = "Start research"\n', encoding="utf-8")
    assert [s for _, s in check.ui_strings(f)] == ["Start research"]
