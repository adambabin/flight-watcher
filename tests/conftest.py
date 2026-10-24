import html
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from flightwatch.frontier import parse_select_page
from flightwatch.runner import App
from flightwatch.state import State

CT = ZoneInfo("America/Chicago")


def flight(num, dep, arr, gowild=False, seats=None, legs=None):
    legs = legs or [{"carrierCode": "F9", "flightNumber": num, "departureDate": dep, "arrivalDate": arr}]
    return {
        "legs": legs,
        "isGoWildFareEnabled": gowild,
        "goWildFare": 15.41 if gowild else 0,
        "goWildFareSeatsRemaining": f"{seats} Seats Left!" if seats else None,
        "standardFare": 89.0,
    }


def page(flights, out_of_range=False):
    data = {"journeys": [{"isReturnTrip": False, "flights": flights}],
            "isGoWildOutOfRange": out_of_range, "lowestGWAmount": 15.41}
    return f"<html><script>var FlightData = '{html.escape(json.dumps(data))}';</script></html>"


class Clock:
    def __init__(self, local):
        self.t = local.astimezone(timezone.utc)

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += timedelta(seconds=seconds)


class FakeFrontier:
    """respond(origin, dest, dep, now_utc) -> page HTML, or raise."""

    def __init__(self, clock, respond):
        self.clock = clock
        self.respond = respond
        self.calls = []
        self.resets = 0

    def search(self, origin, dest, dep):
        self.calls.append((origin, dest, dep, self.clock.now()))
        return parse_select_page(self.respond(origin, dest, dep, self.clock.now()))

    def reset(self):
        self.resets += 1


class FakeBot:
    def __init__(self, inbox=()):
        self.sent = []
        self.inbox = list(inbox)

    def send(self, text):
        self.sent.append(text)

    def commands_since(self, offset):
        msgs, self.inbox = [(t, 0) for t in self.inbox], []
        return msgs, offset + len(msgs)

    def register_commands(self):
        pass


@pytest.fixture
def state(tmp_path):
    return State(str(tmp_path / "state"))


def make_app(state, clock, respond, inbox=()):
    fr = FakeFrontier(clock, respond)
    bot = FakeBot(inbox)
    app = App(state, fr, bot, now_fn=clock.now, sleep=clock.sleep, log=lambda m: None)
    return app, fr, bot


def local(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=CT)
