import json

from flightwatch import dashboard

from conftest import Clock, local, make_app
from test_runner import released_at_midnight


def test_dashboard_export_after_a_night(state):
    clock = Clock(local(2026, 10, 26, 23, 50))
    app, fr, bot = make_app(state, clock, released_at_midnight)
    app.night()
    state.save()
    dashboard.write(state, app.local_now())
    out = json.load(open(state.path + "/dashboard.json", encoding="utf-8"))
    days = [dict(zip(out["days"]["columns"], r)) for r in out["days"]["rows"]]
    d = {r["Flight"]: r for r in days}
    ord_iah = d["F9 1234 · ORD → IAH · 6:05 AM → 8:42 AM"]
    assert ord_iah["Date"] == "2026-10-28" and ord_iah["Weekday"] == "Wed"
    # First seen open at the 12:01 AM check; the 11:59 PM check saw it closed.
    assert ord_iah["Released at"] == "2026-10-27 00:01" and ord_iah["Release known"] is True
    assert ord_iah["Release (min after midnight)"] == 1
    assert ord_iah["Outcome"] == "Open now" and ord_iah["Max seats seen"] == 2
    assert d["F9 1235 · IAH → ORD · 6:05 AM → 8:42 AM"]["Outcome"] == "Not open yet"
    checks = [dict(zip(out["checks"]["columns"], r)) for r in out["checks"]["rows"]]
    mine = [c for c in checks if c["Flight"].startswith("F9 1234")]
    assert mine[0]["Checked at"] == "2026-10-26 23:50" and mine[0]["GoWild open"] is False
    assert any(c["GoWild open"] and c["Seats left"] == 2 and 0 <= c["Hours after midnight"] < 0.1 for c in mine)


def test_dashboard_reports_failing_checks(state):
    clock = Clock(local(2026, 10, 26, 9, 5))
    app, _, _ = make_app(state, clock, lambda *a: "<html>new site</html>")
    app.tick()
    out = dashboard.build(state, app.local_now())
    assert out["health"]["failing"] and out["health"]["failing_since"] == "2026-10-26 09:05"
    assert "layout changed" in out["health"]["last_error"]
