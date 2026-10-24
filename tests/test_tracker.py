from datetime import date, datetime, timedelta, timezone

from flightwatch import tracker
from flightwatch.frontier import parse_select_page
from flightwatch.state import State

from conftest import flight, page

ROUTE = {"origin": "ORD", "dest": "IAH", "notify": True, "depart_after": None, "depart_before": None}
DEP = date(2026, 10, 28)
T0 = datetime(2026, 10, 27, 4, 50, tzinfo=timezone.utc)  # 11:50 PM CDT


def check(state, minutes, gowild, seats=None, oor=False):
    p = page([flight("1234", "2026-10-28T06:05:00", "2026-10-28T08:42:00", gowild, seats)], oor)
    return tracker.record(state, ROUTE, DEP, parse_select_page(p), T0 + timedelta(minutes=minutes), "test")


def test_open_sold_out_reopen(state):
    assert check(state, 0, False, oor=True) == []
    assert check(state, 10, True, 3) == [("opened", "2026-10-28|ORD-IAH|F9 1234")]
    assert check(state, 20, True, 1) == []
    assert check(state, 30, False) == [("sold_out", "2026-10-28|ORD-IAH|F9 1234")]
    assert check(state, 40, True, 1) == [("reopened", "2026-10-28|ORD-IAH|F9 1234")]

    rec = state.flights["2026-10-28|ORD-IAH|F9 1234"]
    assert rec["opened_at"] == "2026-10-27T05:00:00Z"
    assert rec["opened_prev"] == "2026-10-27T04:50:00Z"
    assert rec["reopens"] == 1 and rec["sold_out_at"] is None
    assert [t[1:] for t in rec["timeline"]] == [["closed", None], ["open", 3], ["open", 1], ["closed", None], ["open", 1]]

    day = state.days["2026-10-28|ORD-IAH"]
    assert day["window_open_at"] == "2026-10-27T05:00:00Z"
    assert day["window_open_prev"] == "2026-10-27T04:50:00Z"
    assert tracker.release_estimate(state, "ORD-IAH", DEP) == ("2026-10-27T05:00:00Z", "2026-10-27T04:50:00Z")


def test_already_open_at_first_check_has_no_lower_bound(state):
    check(state, 0, True, 2)
    rec = state.flights["2026-10-28|ORD-IAH|F9 1234"]
    assert rec["opened_prev"] is None
    assert tracker.release_estimate(state, "ORD-IAH", DEP) == ("2026-10-27T04:50:00Z", None)


def test_connections_are_ignored_and_window_filter(state):
    p = page([
        flight("1", "2026-10-28T06:05:00", "2026-10-28T08:42:00", True),
        flight("2", "2026-10-28T17:30:00", "2026-10-28T20:05:00", True),
        flight(None, None, None, True, legs=[
            {"carrierCode": "F9", "flightNumber": "3", "departureDate": "2026-10-28T07:00:00", "arrivalDate": "x"},
            {"carrierCode": "F9", "flightNumber": "4", "departureDate": "2026-10-28T09:00:00",
             "arrivalDate": "2026-10-28T11:00:00"}]),
    ])
    tracker.record(state, ROUTE, DEP, parse_select_page(p), T0, "test")
    recs = tracker.flights_for(state, "ORD-IAH", DEP)
    assert [r["flight"] for r in recs] == ["F9 1", "F9 2"]
    morning = dict(ROUTE, depart_before="12:00")
    assert [r["flight"] for r in tracker.matching(morning, recs)] == ["F9 1"]


def test_state_round_trip(tmp_path):
    s = State(str(tmp_path))
    check(s, 0, True, 2)
    s.settings["routes"][1]["notify"] = False
    s.save()
    s2 = State(str(tmp_path))
    assert s2.flights == s.flights
    assert s2.settings["routes"][1]["notify"] is False
    assert (tmp_path / "observations" / "2026-10.jsonl").read_text().count("\n") == 1
