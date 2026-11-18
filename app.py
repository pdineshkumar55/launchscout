"""LaunchScout web app (Streamlit). UI only: research logic lives in the launchscout package."""

from __future__ import annotations

import hmac
import logging
from pathlib import Path

import streamlit as st
from pydantic import ValidationError

from launchscout.config import settings
from launchscout.guard import screen
from launchscout.models import ResearchInputs
from launchscout.pipeline import list_runs, load_run
from launchscout.runner import DONE, FAILED, PARTIAL, ResearchRun
from launchscout.usage import (
    acquire_run_slot,
    release_daily_run,
    release_run_slot,
    reserve_daily_run,
)
from ui import components as ui
from ui import copy as c

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
for noisy in ("httpx", "LiteLLM", "litellm", "urllib3", "openai", "root"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

st.set_page_config(page_title=c.APP_TITLE, page_icon=c.PAGE_ICON, layout="wide")

SAMPLE_INPUT = {"idea": "Healthy millet meal boxes", "city": "Coimbatore", "own": "",
                "target": "Office workers and health-conscious families", "competitors": "",
                "country": "India", "currency": "Rs"}
ss = st.session_state
FORM_DEFAULTS = {"f_idea": "", "f_city": "", "f_target": "", "f_competitors": "", "f_own": "",
                 "f_country": "India", "f_currency": "Rs"}
ss.setdefault("runs_started", 0)
for key, value in FORM_DEFAULTS.items():
    ss.setdefault(key, value)


# ------------------------------------------------------------------ access code


def access_gate() -> bool:
    if not settings.access_code or ss.get("access_ok"):
        return True
    st.title(c.APP_TITLE)
    with st.form("access"):
        st.subheader(c.ACCESS_HEADER)
        code = st.text_input(c.ACCESS_LABEL, type="password")
        if st.form_submit_button(c.ACCESS_BUTTON):
            if hmac.compare_digest(code.encode(), settings.access_code.encode()):
                ss.access_ok = True
                st.rerun()
            st.error(c.ACCESS_WRONG)
    return False


# ------------------------------------------------------------------ actions


def load_sample() -> None:
    for k, v in SAMPLE_INPUT.items():
        ss[f"f_{k}"] = v
    samples = list_runs(settings.samples_dir)
    sample = next((r for r in samples if r.inputs.get("idea", "").lower() == SAMPLE_INPUT["idea"].lower()),
                  samples[0] if samples else None)
    ss.view_dir = str(sample.run_dir) if sample else None
    ss.view_note = c.SAMPLE_NOTE if sample else None
    ss.pop("run", None)


def open_past(run_dir: Path, created) -> None:
    ss.view_dir = str(run_dir)
    ss.view_note = c.PAST_NOTE.format(date=f"{created:%d %b %Y}")
    ss.pop("run", None)


def new_research() -> None:
    """Back to an empty form: drop the shown report and clear every input field.

    Runs as a button callback, i.e. before the form widgets are drawn again, so the reset shows at once."""
    ss.pop("run", None)
    ss.view_dir = None
    ss.view_note = None
    for key, value in FORM_DEFAULTS.items():
        ss[key] = value


def start_research() -> None:
    try:
        inp = ResearchInputs(idea=ss.f_idea, city=ss.f_city, target=ss.f_target or "General consumers",
                             known_competitors=ss.f_competitors, country=ss.f_country or "India",
                             currency=ss.f_currency or "Rs", own_business=ss.f_own)
    except ValidationError as exc:
        fields = {e["loc"][0] for e in exc.errors()}
        ss.form_error = c.ERR_IDEA if "idea" in fields else c.ERR_CITY if "city" in fields else c.ERR_FIELD_TOO_LONG
        return
    if ss.get("run") is not None and ss.run.is_running:
        ss.form_error = c.ALREADY_RUNNING
        return
    if ss.runs_started >= settings.max_runs_per_session:
        ss.form_error = c.SESSION_LIMIT
        return
    with st.spinner(c.SCREENING):
        verdict = screen(inp)
    if not verdict.allowed:
        logging.getLogger("launchscout.app").info("request refused: %s", verdict.category)
        ss.form_error = c.REFUSED
        return
    if not reserve_daily_run():
        ss.form_error = c.DAILY_LIMIT
        return
    if not acquire_run_slot():
        release_daily_run()
        ss.form_error = c.BUSY
        return
    run = ResearchRun(inp)
    try:
        run.start()
    except Exception:
        logging.getLogger("launchscout.app").exception("could not start run")
        release_run_slot()
        release_daily_run()
        ss.form_error = c.ERROR_GENERIC
        return
    ss.run = run
    ss.runs_started += 1
    ss.view_dir = None


# ------------------------------------------------------------------ layout pieces


def sidebar() -> None:
    with st.sidebar:
        st.header(c.PAST_HEADER)
        runs = list_runs(limit=15)
        if not runs:
            st.caption(c.PAST_EMPTY)
        for r in runs:
            st.button(f"{r.label}  \n{r.created:%d %b %Y, %H:%M}", key=f"past-{r.run_dir.name}",
                      on_click=open_past, args=(r.run_dir, r.created), use_container_width=True)


def input_form(disabled: bool) -> None:
    st.subheader(c.FORM_HEADER)
    st.text_input(c.IDEA_LABEL, key="f_idea", placeholder=c.IDEA_PLACEHOLDER, max_chars=200, disabled=disabled)
    st.text_input(c.CITY_LABEL, key="f_city", placeholder=c.CITY_PLACEHOLDER, max_chars=100, disabled=disabled)
    st.text_input(c.TARGET_LABEL, key="f_target", placeholder=c.TARGET_PLACEHOLDER, max_chars=200,
                  disabled=disabled)
    st.text_input(c.OWN_BUSINESS_LABEL, key="f_own", placeholder=c.OWN_BUSINESS_PLACEHOLDER,
                  help=c.OWN_BUSINESS_HELP, max_chars=100, disabled=disabled)
    st.text_input(c.COMPETITORS_LABEL, key="f_competitors", help=c.COMPETITORS_HELP, max_chars=300,
                  disabled=disabled)
    with st.expander(c.MORE_OPTIONS):
        st.text_input(c.COUNTRY_LABEL, key="f_country", max_chars=60, disabled=disabled)
        st.text_input(c.CURRENCY_LABEL, key="f_currency", max_chars=10, disabled=disabled)
    b1, b2 = st.columns(2)
    b1.button(c.START_BUTTON, type="primary", on_click=start_research, disabled=disabled,
              use_container_width=True)
    b2.button(c.SAMPLE_BUTTON, on_click=load_sample, disabled=disabled, use_container_width=True)
    st.caption(c.RUN_TIME_NOTE)
    if err := ss.pop("form_error", None):
        st.warning(err)


@st.fragment(run_every=1.0)
def progress_panel() -> None:
    run: ResearchRun = ss.run
    run.poll()
    run.drain()
    st.subheader(c.PROGRESS_HEADER)
    st.caption(ui.elapsed_text(run.elapsed))
    ui.stage_cards(run.stage_state)
    ui.activity_log([e.text for e in run.events])
    if not run.is_running:
        st.rerun(scope="app")  # switch the whole page to the results view


def finished_view(run: ResearchRun) -> None:
    run.drain()
    if run.status == FAILED or run.final is None:
        st.error(c.SEARCH_DOWN if run.error_kind == "search" else c.ERROR_GENERIC)
        st.button(c.NEW_BUTTON, on_click=new_research)
        return
    saved = load_run(run.run_dir)
    if saved is None:
        st.error(c.ERROR_GENERIC)
        return
    note = None
    if run.status == PARTIAL:
        note = c.TIMEOUT_PARTIAL if run.error_kind == "timeout" else c.PARTIAL
    ui.results(saved, note)
    st.button(c.NEW_BUTTON, on_click=new_research)


# ------------------------------------------------------------------ page


def main() -> None:
    if not access_gate():
        return
    sidebar()
    st.title(f"{c.PAGE_ICON} {c.APP_TITLE}")
    st.markdown(f"**{c.TAGLINE}**  \n{c.INTRO}")
    if settings.missing_keys():
        st.error(c.NOT_CONFIGURED)
        return

    run: ResearchRun | None = ss.get("run")
    running = run is not None and run.is_running

    left, right = st.columns([2, 3], gap="large")
    with left:
        input_form(disabled=running)
    with right:
        if running:
            progress_panel()
        elif run is None and not ss.get("view_dir"):
            ui.how_it_works()
        elif run is not None and run.status in (DONE, PARTIAL, FAILED):
            ui.stage_cards(run.stage_state)

    showing_report = False
    if run is not None and not run.is_running:
        st.divider()
        finished_view(run)
        showing_report = True
    elif ss.get("view_dir"):
        saved = load_run(Path(ss.view_dir))
        if saved:
            st.divider()
            ui.results(saved, ss.get("view_note"))
            st.button(c.NEW_BUTTON, on_click=new_research)
            showing_report = True

    if not showing_report:  # reports carry the same note in their own footer
        st.divider()
        st.caption(c.FOOTER)


main()
