from datetime import date

import pytest

from flightwatch import commands
from flightwatch.commands import CommandError, next_release_date, parse_travel_date

from conftest import local

MON_10PM = local(2026, 10, 26, 22)  # Monday


@pytest.mark.parametrize("now,expected", [
    (local(2026, 10, 26, 22), date(2026, 10, 28)),       # Mon night: Tue 00:00 opens Wed
    (local(2026, 10, 27, 0, 10), date(2026, 10, 28)),    # just after midnight: still Wed
    (local(2026, 10, 27, 10), date(2026, 10, 29)),       # Tue morning: next release is Thu
])
def test_next_release_date(now, expected):
    assert next_release_date(now) == expected


@pytest.mark.parametrize("text,expected", [
    ("", date(2026, 10, 28)),
    ("tomorrow", date(2026, 10, 27)),
    ("today", date(2026, 10, 26)),
    ("wed", date(2026, 10, 28)),
    ("Wednesday", date(2026, 10, 28)),
    ("mon", date(2026, 11, 2)),
    ("10/29", date(2026, 10, 29)),
    ("1/5", date(2027, 1, 5)),
    ("2026-11-03", date(2026, 11, 3)),
    ("Nov 3", date(2026, 11, 3)),
])
def test_parse_travel_date(text, expected):
    assert parse_travel_date(text, MON_10PM) == expected


def test_bad_date():
    with pytest.raises(CommandError):
        parse_travel_date("someday", MON_10PM)


def test_alert_arms_and_explains_timing(state):
    reply = commands.handle(state, "/alert", MON_10PM)
    assert "Wed Oct 28" in reply and "12:00 AM Tue Oct 27" in reply
    a = state.runtime["alerts"][0]
    assert a["route"] is None and a["date"] == "2026-10-28"
    assert "Already armed" in commands.handle(state, "/alert wed", MON_10PM)
    commands.handle(state, "/alert orD-iaH fri", MON_10PM)
    assert state.runtime["alerts"][1]["route"] == "ORD-IAH"
    assert "Cancelled 1" in commands.handle(state, "/cancel fri", MON_10PM)
    assert "Cancelled 1" in commands.handle(state, "/cancel all", MON_10PM)


def test_alert_rejects_blackout_and_unknown_route(state):
    assert "blackout" in commands.handle(state, "/alert 11/25", MON_10PM)
    assert "Which route" in commands.handle(state, "/alert MDW-HOU wed", MON_10PM)


def test_pause_resume_times_add_remove(state):
    assert "Paused IAH → ORD" in commands.handle(state, "/pause IAH-ORD", MON_10PM)
    assert state.find_route("IAH-ORD")["notify"] is False
    commands.handle(state, "/resume all", MON_10PM)
    assert all(r["notify"] for r in state.routes())

    assert "6:00 AM–2:00 PM" in commands.handle(state, "/times ORD-IAH 6am-2pm", MON_10PM)
    r = state.find_route("ORD-IAH")
    assert (r["depart_after"], r["depart_before"]) == ("06:00", "14:00")
    commands.handle(state, "/times ORD-IAH after 5:30pm", MON_10PM)
    assert (r["depart_after"], r["depart_before"]) == ("17:30", None)
    commands.handle(state, "/times ORD-IAH any", MON_10PM)
    assert (r["depart_after"], r["depart_before"]) == (None, None)
    assert "before" in commands.handle(state, "/times ORD-IAH 2pm-6am", MON_10PM)

    commands.handle(state, "/add ord-den", MON_10PM)
    assert state.find_route("ORD-DEN")
    commands.handle(state, "/remove ORD-DEN", MON_10PM)
    assert state.find_route("ORD-DEN") is None


def test_digest_and_nightly_settings(state):
    commands.handle(state, "/digest 7:30am", MON_10PM)
    assert state.settings["digest"] == {"enabled": True, "time": "07:30"}
    commands.handle(state, "/digest off", MON_10PM)
    assert state.settings["digest"]["enabled"] is False
    commands.handle(state, "/nightly on", MON_10PM)
    assert state.settings["nightly_alert"] is True


def test_unknown_command_shows_help(state):
    assert "GoWild watcher" in commands.handle(state, "hello", MON_10PM)
    assert "Routes" in commands.handle(state, "/status@MyBot", MON_10PM)
