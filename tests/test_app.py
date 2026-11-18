"""Headless app tests with Streamlit's AppTest (no browser, no research run)."""

from dataclasses import replace
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from launchscout import config
from ui import copy as c

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture
def no_code(monkeypatch):
    """Tests must not depend on the developer's .env (which may set ACCESS_CODE)."""
    monkeypatch.setattr(config, "settings", replace(config.settings, access_code=""))


def app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    return at


def test_first_render(no_code):
    at = app()
    assert not at.exception
    assert c.APP_TITLE in at.title[0].value
    labels = [t.label for t in at.text_input]
    assert c.IDEA_LABEL in labels and c.CITY_LABEL in labels
    assert any(b.label == c.START_BUTTON for b in at.button)
    assert any(c.HOW_HEADER == h.value for h in at.subheader)


def test_missing_city_shows_message(no_code):
    at = app()
    at.text_input(key="f_idea").input("Healthy millet meal boxes")
    next(b for b in at.button if b.label == c.START_BUTTON).click()
    at.run()
    assert not at.exception
    assert any(c.ERR_CITY in w.value for w in at.warning)


def test_sample_button_fills_form(no_code):
    at = app()
    next(b for b in at.button if b.label == c.SAMPLE_BUTTON).click()
    at.run()
    assert at.text_input(key="f_idea").value == "Healthy millet meal boxes"
    assert at.text_input(key="f_city").value == "Coimbatore"


def test_access_code_gate(monkeypatch):
    monkeypatch.setattr(config, "settings", replace(config.settings, access_code="letmein1"))
    at = app()
    assert [t.label for t in at.text_input] == [c.ACCESS_LABEL]
    at.text_input[0].input("wrong")
    at.button[0].click()
    at.run()
    assert any(c.ACCESS_WRONG in e.value for e in at.error)
    at.text_input[0].input("letmein1")
    at.button[0].click()
    at.run()
    assert c.IDEA_LABEL in [t.label for t in at.text_input]


def test_own_business_field_shown(no_code):
    at = app()
    field = next(t for t in at.text_input if t.label == c.OWN_BUSINESS_LABEL)
    assert field.placeholder == c.OWN_BUSINESS_PLACEHOLDER
    assert "not listed as one" in field.placeholder
