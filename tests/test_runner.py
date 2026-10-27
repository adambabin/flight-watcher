import json
from datetime import timedelta

from flightwatch import messages
from flightwatch.frontier import FrontierError
from flightwatch.state import State

from conftest import Clock, flight, local, make_app, page


def released_at_midnight(origin, dest, dep, now):
    """Seats for the next day appear at 12:00 AM Central; ORD-IAH 6:05 AM has 2 left."""
    opened = now >= local(dep.year, dep.month, dep.day, 0) - timedelta(days=1)
    num = "1234" if origin == "ORD" else "1235"
    return page([
        flight(num, f"{dep}T06:05:00", f"{dep}T08:42:00", gowild=opened and origin == "ORD", seats=2),
        flight("2401", f"{dep}T17:30:00", f"{dep}T20:05:00"),
    ], out_of_range=not opened)


def test_pick_mode():
    for when, mode in [(local(2026, 10, 26, 23, 50), "night"), (local(2026, 10, 27, 0, 5), "night"),
                       (local(2026, 10, 26, 22, 40), "night"), (local(2026, 10, 26, 22, 5), "tick"),
                       (local(2026, 10, 27, 0, 25), "tick"), (local(2026, 10, 27, 6, 5), "tick")]:
        app, _, _ = make_app(State("/nonexistent"), Clock(when), released_at_midnight)
        assert app.pick_mode() == mode, when


def test_night_watch_catches_release_and_alerts_once(state):
    clock = Clock(local(2026, 10, 26, 23, 50))  # Monday night
    app, fr, bot = make_app(state, clock, released_at_midnight, inbox=["/alert"])
    app.night()

    # Checked Wednesday's flights only, every few minutes, and stopped after 12:30 AM.
    assert {c[2].isoformat() for c in fr.calls} == {"2026-10-28"}
    last = fr.calls[-1][3]
    assert local(2026, 10, 27, 0, 30) <= last < local(2026, 10, 27, 0, 35)
    assert len(fr.calls) <= 2 * 25

    opened = [m for m in bot.sent if m.startswith("🟢")]
    assert len(opened) == 1
    assert "ORD → IAH · Wed Oct 28" in opened[0]
    assert "F9 1234 · 6:05 AM → 8:42 AM · GoWild 2 left · $15.41" in opened[0]
    assert "opened between Mon 11:5" in opened[0] and "and Tue 12:0" in opened[0]
    # IAH-ORD got nothing: one "no seats" note.
    assert any(m.startswith("⚪ IAH → ORD") for m in bot.sent)

    rec = state.flights["2026-10-28|ORD-IAH|F9 1234"]
    gap = (local(2026, 10, 27, 0, 0) - local(2026, 10, 26, 23, 0)).total_seconds()  # sanity on types
    assert rec["opened_prev"] < rec["opened_at"] and gap > 0
    assert state.days["2026-10-28|ORD-IAH"]["window_closed_seen"] is True


def test_paused_direction_gets_no_alert(state):
    clock = Clock(local(2026, 10, 26, 23, 50))
    app, fr, bot = make_app(state, clock, released_at_midnight, inbox=["/pause IAH-ORD", "/nightly on"])
    app.night()
    assert not any("IAH → ORD" in m for m in bot.sent if m[0] in "🟢⚪")
    assert any(m.startswith("🟢 <b>GoWild seats open: ORD → IAH") for m in bot.sent)
    # Paused routes are still tracked.
    assert "2026-10-28|IAH-ORD" in state.days


def test_alert_fires_again_only_after_full_sell_out(state):
    clock = Clock(local(2026, 10, 27, 9, 5))
    seats = {"open": True}

    def respond(o, d, dep, now):
        return page([flight("1234", f"{dep}T06:05:00", f"{dep}T08:42:00", gowild=seats["open"], seats=1)])

    app, fr, bot = make_app(state, clock, respond, inbox=["/alert ORD-IAH wed"])
    app.tick()
    app.tick()
    seats["open"] = False
    app.tick()
    seats["open"] = True
    app.tick()
    assert len([m for m in bot.sent if m.startswith("🟢")]) == 2


def test_morning_digest_sent_once_when_due(state):
    clock = Clock(local(2026, 10, 26, 23, 50))
    app, fr, bot = make_app(state, clock, released_at_midnight)
    app.night()
    bot.sent.clear()

    clock.t = local(2026, 10, 27, 3, 5).astimezone(clock.t.tzinfo)
    app.tick()
    assert bot.sent == []

    clock.t = local(2026, 10, 27, 6, 5).astimezone(clock.t.tzinfo)
    app.tick()
    app.tick()
    assert len(bot.sent) == 1
    d = bot.sent[0]
    assert "GoWild morning report · Tue Oct 27" in d
    assert "<b>ORD → IAH · Wed Oct 28</b> (released last night)" in d
    assert "✅ F9 1234 · 6:05 AM → 8:42 AM · GoWild 2 left · $15.41 · opened Tue 12:0" in d
    assert "▫️ F9 2401 · 5:30 PM → 8:05 PM · no GoWild seats" in d
    assert "GoWild opened between Mon 11:5" in d


def test_digest_respects_pause_and_time_window(state):
    clock = Clock(local(2026, 10, 27, 6, 5))
    app, fr, bot = make_app(state, clock, released_at_midnight,
                            inbox=["/pause IAH-ORD", "/times ORD-IAH after noon"])
    app.tick()
    d = bot.sent[-1]
    assert "Paused: IAH → ORD" in d and "IAH → ORD ·" not in d
    assert "F9 1234" not in d and "1 more outside your after 12:00 PM window" in d


def test_block_warns_once_per_day_and_stops_the_tick(state):
    clock = Clock(local(2026, 10, 27, 9, 5))

    def respond(o, d, dep, now):
        raise FrontierError("HTTP 403 from Frontier", 403, blocked=True)

    app, fr, bot = make_app(state, clock, respond)
    app.tick()
    app.tick()
    assert len(fr.calls) == 2
    assert len([m for m in bot.sent if m.startswith("⚠️")]) == 1


def test_blackout_night_skips_watch(state):
    clock = Clock(local(2026, 11, 23, 23, 50))  # Tue Nov 24 opens Wed Nov 25: both blackout
    app, fr, bot = make_app(state, clock, released_at_midnight)
    app.night()
    # Falls back to one ordinary tick: blackout dates (Nov 24, 25) are never checked.
    assert {c[2].isoformat() for c in fr.calls} == {"2026-11-23", "2026-11-26"}
    assert len(fr.calls) == 4


def test_night_watch_tightens_around_both_midnights(state):
    start = local(2026, 10, 26, 22, 40)
    clock = Clock(start)
    app, fr, bot = make_app(state, clock, released_at_midnight)
    app.night()
    # Minutes after 10:40 PM of each ORD-IAH check, in order.
    mins = [round((c[3] - start).total_seconds() / 60) for c in fr.calls if c[0] == "ORD"]
    gaps = dict(zip(mins, (b - a for a, b in zip(mins, mins[1:]))))
    assert mins[0] == 0 and 110 <= mins[-1] < 115           # 10:40 PM until just past 12:30 AM
    assert all(g <= 4 for g in gaps.values())
    assert max(g for m, g in gaps.items() if 18 <= m <= 30) <= 2   # 10:58-11:10 PM (midnight Eastern)
    assert max(g for m, g in gaps.items() if 78 <= m <= 90) <= 2   # 11:58 PM-12:10 AM
    assert min(g for m, g in gaps.items() if 40 <= m <= 70) == 4   # quieter in between


def test_tick_checks_three_days_out(state):
    clock = Clock(local(2026, 10, 26, 9, 5))
    app, fr, bot = make_app(state, clock, released_at_midnight)
    app.tick()
    assert sorted({c[2].isoformat() for c in fr.calls}) == ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29"]


def _redesigned(origin, dest, dep, now):
    return "<html><div id='new-site'></div></html>"


def test_layout_change_alerts_once_a_day_saves_the_page_and_recovers(state):
    clock = Clock(local(2026, 10, 26, 9, 5))
    app, fr, bot = make_app(state, clock, _redesigned)
    app.tick()
    h = state.runtime["health"]
    assert h["fail_streak"] == 8 and "layout changed" in h["last_error"]
    alerts = [m for m in bot.sent if "Frontier checks are failing" in m]
    assert len(alerts) == 1 and app.health_alerted
    assert state.flights == {}
    with open(state.path + "/debug/last_failure.html", encoding="utf-8") as f:
        assert "new-site" in f.read()
    with open(state.path + "/debug/last_failure.json", encoding="utf-8") as f:
        assert json.load(f)["layout"] is True

    # Still broken an hour later: no second ping the same day, and the run isn't failed again.
    clock.t += timedelta(hours=1)
    app2, _, bot2 = make_app(state, clock, _redesigned)
    app2.tick()
    assert not any("failing" in m for m in bot2.sent) and not app2.health_alerted
    assert "Frontier checks have been failing" in messages.digest(state, app2.local_now().date())

    # Fixed: one all-clear, the streak resets, and a good sample page is kept.
    clock.t += timedelta(hours=1)
    app3, _, bot3 = make_app(state, clock, released_at_midnight)
    app3.tick()
    assert sum("working again" in m for m in bot3.sent) == 1
    assert h["fail_streak"] == 0 and h["notified"] is None and h["last_ok"]
    with open(state.path + "/debug/sample_ok.html", encoding="utf-8") as f:
        assert "FlightData" in f.read()


def test_two_failures_then_success_stays_quiet(state):
    clock = Clock(local(2026, 10, 26, 9, 5))
    n = {"calls": 0}

    def flaky(origin, dest, dep, now):
        n["calls"] += 1
        return _redesigned(origin, dest, dep, now) if n["calls"] % 3 else released_at_midnight(origin, dest, dep, now)

    app, fr, bot = make_app(state, clock, flaky)
    app.tick()
    assert not any("failing" in m for m in bot.sent) and not app.health_alerted


def test_empty_day_counts_as_a_failure_when_that_weekday_flew_last_week(state):
    clock = Clock(local(2026, 10, 19, 9, 5))
    app, _, _ = make_app(state, clock, released_at_midnight)
    app.tick()   # records Oct 19-22
    clock.t += timedelta(days=7)
    app2, _, bot = make_app(state, clock, lambda *a: page([]))
    app2.tick()
    # Each route: today (Oct 26) doesn't count, since departed flights drop off; Oct 27-29
    # flew a week earlier, so those 3 do.
    assert state.runtime["health"]["fail_streak"] == 3
    assert app2.health_alerted and any("no flights listed" in m for m in bot.sent)
