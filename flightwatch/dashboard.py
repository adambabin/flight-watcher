"""dashboard.json: what the GitHub Pages dashboard (docs/index.html) draws.

Written into the state directory after every run, so it rides along to the public
`state` branch and the page fetches it from raw.githubusercontent.com. Tables are
{columns, rows} to keep the file small. All times are local to the route's origin.
"""
import glob
import json
import os
from datetime import date, datetime, timedelta

from .airports import airport_tz
from .timeutil import clock, dep_clock, parse_iso

CHECK_DAYS = 14   # departures whose every check is included (the seat-count chart)

DAY_COLUMNS = ["Flight", "Route", "Date", "Weekday", "Departs at", "Released at", "Release known",
               "Release (min after midnight)", "Sold out at", "Hours open", "Max seats seen",
               "Reopened", "Outcome"]
CHECK_COLUMNS = ["Flight", "Date", "Checked at", "Hours after midnight", "Seats left", "GoWild open"]


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
    ]


def _check_rows(state_dir, flights, fallback_tz, keep_dates):
    labels = {}
    for key, r in flights.items():
        labels[key] = label(key.split("|")[2], key.split("|")[1], r.get("dep"), r.get("arr"))
    rows = []
    for path in sorted(glob.glob(os.path.join(state_dir, "observations", "*.jsonl")))[-2:]:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    obs = json.loads(line)
                except ValueError:
                    continue
                if obs["date"] not in keep_dates:
                    continue
                tz = airport_tz(obs["route"].split("-")[0], fallback_tz)
                checked = _local(obs["ts"], tz)
                midnight = _release_midnight(date.fromisoformat(obs["date"]), tz)
                for fl in obs.get("nonstop", []):
                    key = f"{obs['date']}|{obs['route']}|{fl['flight']}"
                    rows.append([
                        labels.get(key) or label(fl["flight"], obs["route"], fl.get("dep"), fl.get("arr")),
                        obs["date"],
                        _stamp(checked),
                        round((checked - midnight).total_seconds() / 3600, 2),
                        fl.get("seats") if fl.get("gowild") else 0,
                        bool(fl.get("gowild")),
                    ])
    return rows


def build(state, now):
    fallback = state.settings["timezone"]
    days = [_day_row(k, r, fallback, now) for k, r in sorted(state.flights.items())]
    keep = sorted({k.split("|")[0] for k in state.flights})[-CHECK_DAYS:]
    return {
        "generated_at": now.astimezone(airport_tz("", fallback)).isoformat(timespec="seconds"),
        "days": {"columns": DAY_COLUMNS, "rows": days},
        "checks": {"columns": CHECK_COLUMNS, "rows": _check_rows(state.path, state.flights, fallback, set(keep))},
    }


def write(state, now):
    path = os.path.join(state.path, "dashboard.json")
    os.makedirs(state.path, exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(build(state, now), f, ensure_ascii=False, separators=(",", ":"))
    os.replace(path + ".tmp", path)
