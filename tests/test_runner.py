from datetime import timedelta

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
                       (local(2026, 10, 26, 22, 45), "tick"), (local(2026, 10, 27, 0, 45), "tick"),
                       (local(2026, 10, 27, 6, 5), "tick")]:
        app, _, _ = make_app(State("/nonexistent"), Clock(when), released_at_midnight)
        assert app.pick_mode() == mode, when


def test_night_watch_catches_release_and_alerts_once(state):
    clock = Clock(local(2026, 10, 26, 23, 50))  # Monday night
    app, fr, bot = make_app(state, clock, released_at_midnight, inbox=["/alert"])
    app.night()

    # Checked Wednesday's flights only, every few minutes, and stopped after 12:15 AM.
    assert {c[2].isoformat() for c in fr.calls} == {"2026-10-28"}
    last = fr.calls[-1][3]
    assert local(2026, 10, 27, 0, 15) <= last < local(2026, 10, 27, 0, 18)
    assert len(fr.calls) <= 2 * 14

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
    assert {c[2].isoformat() for c in fr.calls} <= {"2026-11-23"}
