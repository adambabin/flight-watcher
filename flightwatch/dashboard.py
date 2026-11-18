"""dashboard.json: what the GitHub Pages dashboard (docs/index.html) draws.

Written into the state directory after every run, so it rides along to the public
`state` branch and the page fetches it from raw.githubusercontent.com. Tables are
{columns, rows} to keep the file small. All times are local to the route's origin.
"""
import json
import os
from datetime import date, datetime, timedelta

from .airports import airport_tz
from .rules import is_blackout
from .state import HEALTH_ALERT_AFTER, route_key
from .timeutil import clock, dep_clock, parse_iso

DAY_COLUMNS = ["Flight", "Route", "Date", "Weekday", "Departs at", "Released at", "Release known",
               "Release (min after midnight)", "Sold out at", "Hours open", "Max seats seen",
               "Reopened", "Outcome", "Opened after", "Sold out after", "GoWild fare", "Standard fare",
               "Timeline"]
# One row per (departure date, route) that was checked, so the calendar can tell "no nonstop
# flights that day" apart from "not tracked". Blackout dates are listed even when unchecked.
DATE_COLUMNS = ["Date", "Route", "Checks", "First check", "Last check", "Nonstops", "Blackout"]


def label(num, rkey, dep, arr):
    o, d = rkey.split("-")
    times = f" · {clock(dep_clock(dep))} → {clock(dep_clock(arr))}" if dep and arr else ""
    return f"{num} · {o} → {d}{times}"


def _local(ts, tz):
    return parse_iso(ts).astimezone(tz) if ts else None


def _stamp(dt):
    return dt.strftime("%Y-%m-%d %H:%M") if dt else None


def _release_midnight(dep_date, tz):
    d = dep_date - timedelta(days=1)
    return datetime(d.year, d.month, d.day, tzinfo=tz)


def _day_row(key, r, fallback_tz, now):
    dep_day, rkey, num = key.split("|")
    tz = airport_tz(rkey.split("-")[0], fallback_tz)
    dep_date = date.fromisoformat(dep_day)
    departs = datetime.fromisoformat(r["dep"]).replace(tzinfo=tz) if r.get("dep") else None
    opened = _local(r.get("opened_at"), tz)
    sold = _local(r.get("sold_out_at"), tz)
    gone = departs is not None and now >= departs
    midnight = _release_midnight(dep_date, tz)
    if opened is None:
        # "Never opened" only if we were watching before the release night; otherwise
        # we may simply have started tracking after the seats were gone.
        watched = _local(r.get("first_seen"), tz)
        outcome = ("Never opened" if watched and watched <= midnight else "No seats seen") if gone else "Not open yet"
    elif r["status"] == "open":
        outcome = "Open at departure" if gone else "Open now"
    else:
        outcome = "Sold out"
    end = sold or (min(now, departs) if departs and opened else now)
    seats = [s for _, st, s in r.get("timeline", []) if st == "open" and isinstance(s, int)]
    return [
        label(num, rkey, r.get("dep"), r.get("arr")),
        rkey,
        dep_day,
        dep_date.strftime("%a"),
        _stamp(departs),
        _stamp(opened),
        bool(opened) and r.get("opened_prev") is not None,
        round((opened - midnight).total_seconds() / 60) if opened else None,
        _stamp(sold),
        round((end - opened).total_seconds() / 3600, 1) if opened else 0,
        max(seats) if seats else None,
        r.get("reopens", 0),
        outcome,
        _stamp(_local(r.get("opened_prev"), tz)),
        _stamp(_local(r.get("sold_out_prev"), tz)),
        r.get("price"),
        r.get("standard"),
        # Every status change: [local time, "open"/"closed", seats or None].
        [[_stamp(_local(ts, tz)), st, seats] for ts, st, seats in r.get("timeline", [])],
    ]


def _date_rows(state, fallback_tz):
    nonstops = {}
    for key in state.flights:
        dep_day, rkey, _ = key.split("|")
        nonstops[(dep_day, rkey)] = nonstops.get((dep_day, rkey), 0) + 1
    rows, seen = [], set()
    for rec in state.days.values():
        rkey, dep_day = rec["route"], rec["date"]
        tz = airport_tz(rkey.split("-")[0], fallback_tz)
        seen.add(dep_day)
        rows.append([dep_day, rkey, rec.get("checks", 0), _stamp(_local(rec.get("first_check"), tz)),
                     _stamp(_local(rec.get("last_check"), tz)), nonstops.get((dep_day, rkey), 0),
                     is_blackout(date.fromisoformat(dep_day))])
    # Blackouts across the months on screen, so the calendar can grey them out before any check.
    if seen:
        first, last = date.fromisoformat(min(seen)).replace(day=1), date.fromisoformat(max(seen)) + timedelta(days=31)
        d = first
        while d <= last:
            if is_blackout(d) and d.isoformat() not in seen:
                rows.append([d.isoformat(), None, 0, None, None, 0, True])
            d += timedelta(days=1)
    return sorted(rows, key=lambda r: (r[0], r[1] or ""))


def _health(state, tz):
    h = state.runtime["health"]
    return {"failing": h["fail_streak"] >= HEALTH_ALERT_AFTER, "fail_streak": h["fail_streak"],
            "failing_since": _stamp(_local(h["first_fail"], tz)), "last_error": h["last_error"],
            "last_ok": _stamp(_local(h["last_ok"], tz))}


def build(state, now):
    fallback = state.settings["timezone"]
    days = [_day_row(k, r, fallback, now) for k, r in sorted(state.flights.items())]
    return {
        "generated_at": now.astimezone(airport_tz("", fallback)).isoformat(timespec="seconds"),
        "days": {"columns": DAY_COLUMNS, "rows": days},
        "dates": {"columns": DATE_COLUMNS, "rows": _date_rows(state, fallback)},
        # Routes in the owner's settings order, so the calendar lists them the way they were added.
        "routes": [route_key(r) for r in state.settings.get("routes", [])],
        "health": _health(state, airport_tz("", fallback)),
    }


def write(state, now):
    path = os.path.join(state.path, "dashboard.json")
    os.makedirs(state.path, exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(build(state, now), f, ensure_ascii=False, separators=(",", ":"))
    os.replace(path + ".tmp", path)
