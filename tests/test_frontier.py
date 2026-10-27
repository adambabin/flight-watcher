import html
import json

import pytest

from flightwatch.frontier import FrontierError, parse_select_page, search_url
from datetime import date

from conftest import flight, page


def test_parses_flightdata_blob():
    p = page([
        flight("1234", "2026-10-28T06:05:00", "2026-10-28T08:42:00", gowild=True, seats=2),
        flight("2401", "2026-10-28T17:30:00", "2026-10-28T20:05:00"),
        flight(None, None, None, gowild=True, legs=[
            {"carrierCode": "F9", "flightNumber": "11", "departureDate": "2026-10-28T09:00:00",
             "arrivalDate": "2026-10-28T10:30:00"},
            {"carrierCode": "F9", "flightNumber": "22", "departureDate": "2026-10-28T12:00:00",
             "arrivalDate": "2026-10-28T15:10:00"}]),
    ])
    r = parse_select_page(p)
    assert r["out_of_range"] is False
    assert r["lowest_gowild"] == 15.41
    f = {x["flight"]: x for x in r["flights"]}
    assert f["F9 1234"] == {"flight": "F9 1234", "dep": "2026-10-28T06:05:00", "arr": "2026-10-28T08:42:00",
                            "stops": 0, "gowild": True, "price": 15.41, "seats": 2,
                            "seats_text": "2 Seats Left!", "standard": 89.0}
    assert f["F9 2401"]["gowild"] is False and f["F9 2401"]["price"] is None
    assert f["F9 11+F9 22"]["stops"] == 1
    assert [x["dep"][11:16] for x in r["flights"]] == ["06:05", "09:00", "17:30"]


def test_gowild_open_without_seat_count():
    r = parse_select_page(page([flight("1", "2026-10-28T06:05:00", "2026-10-28T08:42:00", gowild=True)]))
    assert r["flights"][0]["gowild"] and r["flights"][0]["seats"] is None


def test_fallback_finds_entity_escaped_journeys():
    data = {"wrapper": {"journeys": [{"flights": [flight("7", "2026-10-28T06:00:00", "2026-10-28T08:00:00", True, 1)]}],
                        "note": "brace } in a string {"}}
    p = f'<div data-x="{html.escape(json.dumps(data))}"></div>'
    r = parse_select_page(p)
    assert r["flights"][0]["flight"] == "F9 7" and r["flights"][0]["seats"] == 1
    assert r["out_of_range"] is None


def test_captcha_page_is_reported_as_blocked():
    with pytest.raises(FrontierError) as e:
        parse_select_page("<html>Please enable JS ... captcha-delivery.com datadome</html>")
    assert e.value.blocked


def test_search_url():
    assert search_url("ORD", "IAH", date(2026, 10, 28)) == (
        "https://booking.flyfrontier.com/Flight/InternalSelect?o1=ORD&d1=IAH&dd1=Oct+28%2C+2026"
        "&ADT=1&mon=true&promo=")


def _layout_error(p):
    with pytest.raises(FrontierError) as e:
        parse_select_page(p)
    assert e.value.layout and not e.value.blocked
    return str(e.value)


def _blob(data):
    return f"<script>var FlightData = '{html.escape(json.dumps(data))}';</script>"


def test_redesigned_page_without_flight_data_is_a_layout_change():
    _layout_error("<html><div id='new-react-app'></div></html>")


def test_renamed_gowild_field_is_a_layout_change_not_no_seats():
    f = flight("1234", "2026-10-28T06:05:00", "2026-10-28T08:42:00", gowild=True, seats=2)
    f["goWildEnabled"] = f.pop("isGoWildFareEnabled")
    assert "isGoWildFareEnabled" in _layout_error(page([f]))


def test_missing_journeys_or_legs_is_a_layout_change():
    _layout_error(_blob({"trips": [], "isGoWildOutOfRange": False}))
    _layout_error(_blob({"journeys": [{"segments": []}]}))
    f = flight("1234", "2026-10-28T06:05:00", "2026-10-28T08:42:00")
    f["legs"] = [{"carrier": "F9", "number": "1234", "departs": "2026-10-28T06:05:00"}]
    _layout_error(page([f]))


def test_a_day_with_no_flights_is_not_a_layout_change():
    assert parse_select_page(page([]))["flights"] == []
