"""Everything the tracker remembers between runs, as plain JSON files in one directory.

On GitHub Actions that directory is a checkout of the repo's `state` branch, committed
after every run, so the history is browsable on GitHub.

  settings.json            routes, time windows, digest time (changed via Telegram)
  runtime.json             Telegram offset, armed alerts, digest bookkeeping, block log
  flights.json             one record per (date, route, flight): when GoWild opened, sold out...
  days.json                one record per (date, route): first/last check, when the window opened
  observations/YYYY-MM.jsonl  every check, raw, append-only
"""
import copy
import json
import os

DEFAULT_SETTINGS = {
    "timezone": "America/Chicago",
    "routes": [
        {"origin": "ORD", "dest": "IAH", "notify": True, "depart_after": None, "depart_before": None},
        {"origin": "IAH", "dest": "ORD", "notify": True, "depart_after": None, "depart_before": None},
    ],
    "digest": {"enabled": True, "time": "06:00"},
    "nightly_alert": False,
}

DEFAULT_RUNTIME = {
    "telegram_offset": 0,
    "digest_sent": None,
    "alerts": [],
    "blocks": [],
    "block_notified": None,
    "last_check": None,
    "next_alert_id": 1,
}


def route_key(route):
    return f"{route['origin']}-{route['dest']}"


class State:
    def __init__(self, path):
        self.path = path
        self.settings = self._load("settings.json", DEFAULT_SETTINGS)
        self.runtime = self._load("runtime.json", DEFAULT_RUNTIME)
        self.flights = self._load("flights.json", {})
        self.days = self._load("days.json", {})
        self._observations = []

    def _load(self, name, default):
        try:
            with open(os.path.join(self.path, name), encoding="utf-8") as f:
                loaded = json.load(f)
        except (OSError, ValueError):
            return copy.deepcopy(default)
        if isinstance(default, dict) and default:
            return {**copy.deepcopy(default), **loaded}
        return loaded

    def _dump(self, name, obj):
        full = os.path.join(self.path, name)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full + ".tmp", "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=1, sort_keys=True)
            f.write("\n")
        os.replace(full + ".tmp", full)

    def save(self):
        self._dump("settings.json", self.settings)
        self._dump("runtime.json", self.runtime)
        self._dump("flights.json", self.flights)
        self._dump("days.json", self.days)
        for obs in self._observations:
            full = os.path.join(self.path, "observations", obs["ts"][:7] + ".jsonl")
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "a", encoding="utf-8") as f:
                f.write(json.dumps(obs, sort_keys=True) + "\n")
        self._observations = []

    def log_observation(self, obs):
        self._observations.append(obs)

    # ------------------------------------------------------------ routes

    def routes(self):
        return self.settings["routes"]

    def find_route(self, key):
        for r in self.settings["routes"]:
            if route_key(r) == key:
                return r
        return None
