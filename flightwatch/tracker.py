"""Turns raw checks into history: when each flight's GoWild seats opened, sold out, reopened.

Every event time comes with the previous check's time, so we can say "opened between
11:58 PM and 12:01 AM" instead of pretending we saw the exact second.
"""
from .state import route_key
from .timeutil import in_window, iso


def day_key(dep_date, rkey):
    return f"{dep_date.isoformat()}|{rkey}"


def record(state, route, dep_date, result, now, mode):
    """Store one check of route on dep_date. Returns [(event, flight_key)]."""
    rkey = route_key(route)
    dkey = day_key(dep_date, rkey)
    ts = iso(now)
    day = state.days.setdefault(dkey, {
        "route": rkey, "date": dep_date.isoformat(), "first_check": ts, "last_check": None,
        "checks": 0, "window_closed_seen": False, "window_open_at": None, "window_open_prev": None,
    })
    oor = result.get("out_of_range")
    if oor:
        day["window_closed_seen"] = True
    elif oor is False and day["window_open_at"] is None:
        day["window_open_at"] = ts
        day["window_open_prev"] = day["last_check"] if day["window_closed_seen"] else None

    events = []
    nonstop = [f for f in result["flights"] if f["stops"] == 0]
    for f in nonstop:
        fkey = f"{dkey}|{f['flight']}"
        rec = state.flights.get(fkey)
        if rec is None:
            rec = state.flights[fkey] = {
                "route": rkey, "date": dep_date.isoformat(), "flight": f["flight"],
                "first_seen": ts, "last_check": None, "status": None, "seats": None, "price": None,
                "opened_at": None, "opened_prev": None, "sold_out_at": None, "sold_out_prev": None,
                "reopens": 0, "timeline": [],
            }
        new = "open" if f["gowild"] else "closed"
        old = rec["status"]
        if new != old:
            if new == "open":
                if rec["opened_at"] is None:
                    rec["opened_at"] = ts
                    # None means it was already open the first time we looked.
                    rec["opened_prev"] = rec["last_check"] if old == "closed" else None
                    events.append(("opened", fkey))
                else:
                    rec["reopens"] += 1
                    rec["sold_out_at"] = rec["sold_out_prev"] = None
                    events.append(("reopened", fkey))
            elif old == "open":
                rec["sold_out_at"] = ts
                rec["sold_out_prev"] = rec["last_check"]
                events.append(("sold_out", fkey))
            rec["timeline"].append([ts, new, f["seats"]])
        elif new == "open" and f["seats"] != rec["seats"]:
            rec["timeline"].append([ts, new, f["seats"]])
        rec.update(status=new, seats=f["seats"], price=f["price"] or rec["price"],
                   standard=f["standard"], dep=f["dep"], arr=f["arr"], last_check=ts)

    day["last_check"] = ts
    day["checks"] += 1
    state.log_observation({
        "ts": ts, "mode": mode, "route": rkey, "date": dep_date.isoformat(),
        "out_of_range": oor, "itineraries": len(result["flights"]),
        "nonstop": [{k: f[k] for k in ("flight", "dep", "arr", "gowild", "price", "seats", "standard")}
                    for f in nonstop],
    })
    return events


def flights_for(state, rkey, dep_date):
    prefix = day_key(dep_date, rkey) + "|"
    recs = [r for k, r in state.flights.items() if k.startswith(prefix)]
    return sorted(recs, key=lambda r: r.get("dep") or "")


def matching(route, recs):
    """Flights inside the route's departure-time window."""
    return [r for r in recs if in_window(r.get("dep"), route.get("depart_after"), route.get("depart_before"))]


def release_estimate(state, rkey, dep_date):
    """(earliest, latest_known_closed) bracket for when GoWild first opened on this route/date.

    earliest = first check that saw it open; latest_known_closed = the check before
    (None if it was already open when we started looking). None if never seen open.
    """
    day = state.days.get(day_key(dep_date, rkey)) or {}
    candidates = []
    for r in flights_for(state, rkey, dep_date):
        if r["opened_at"]:
            candidates.append((r["opened_at"], r["opened_prev"]))
    if day.get("window_open_at") and day.get("window_open_prev"):
        candidates.append((day["window_open_at"], day["window_open_prev"]))
    if not candidates:
        return None
    return min(candidates, key=lambda c: c[0])
