"""Telegram commands. Each handler changes settings/runtime and returns the reply text."""
import re
from datetime import datetime, timedelta
from html import escape

from . import messages, rules
from .state import route_key
from .timeutil import day_label, hhmm, iso, parse_clock

HELP = """<b>GoWild watcher</b>
I check Frontier for GoWild seats on your routes, watch the midnight release, and send a morning report.

/alert — ping me when the next release opens (tonight's midnight)
/alert wed · /alert 10/29 · /alert ORD-IAH fri — a specific travel date or route
/alerts · /cancel all · /cancel wed
/nightly on|off — midnight alert every night
/pause IAH-ORD · /resume IAH-ORD — mute a direction
/times ORD-IAH 6am-2pm · /times ORD-IAH after 5pm · /times ORD-IAH any
/add ORD-DEN · /remove ORD-DEN
/digest 6:00 · /digest off
/history · /history IAH-ORD
/status

Commands are picked up at the next check (within ~3 hours, or within minutes around midnight)."""

_ROUTE_RE = re.compile(r"^([A-Za-z]{3})(?:-|>|/|→)([A-Za-z]{3})$")
_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class CommandError(ValueError):
    pass


def parse_route(text):
    m = _ROUTE_RE.match(text.strip())
    return f"{m.group(1).upper()}-{m.group(2).upper()}" if m else None


def next_release_date(now_local):
    """Travel date whose GoWild seats open at the coming midnight (or the one that just passed,
    for the first two hours after midnight)."""
    return (now_local - timedelta(hours=2)).date() + timedelta(days=2)


def parse_travel_date(text, now_local):
    today = now_local.date()
    t = text.strip().lower().rstrip(".")
    if t in ("", "next", "tonight"):
        return next_release_date(now_local)
    if t == "today":
        return today
    if t in ("tomorrow", "tmrw", "tmr"):
        return today + timedelta(days=1)
    if t[:3] in _DAYS and (len(t) == 3 or _DAYS[_DAYS.index(t[:3])] in t):
        want = _DAYS.index(t[:3])
        ahead = (want - today.weekday()) % 7 or 7
        return today + timedelta(days=ahead)
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%b %d %Y", "%B %d %Y"):
        try:
            return datetime.strptime(t.replace(",", ""), fmt).date()
        except ValueError:
            pass
    for fmt in ("%m/%d", "%b %d", "%B %d"):
        try:
            d = datetime.strptime(f"{t.replace(',', '')} {today.year}", fmt + " %Y").date()
        except ValueError:
            continue
        return d if d >= today else d.replace(year=today.year + 1)
    raise CommandError(f"I couldn't read the date “{escape(text)}”. Try wed, tomorrow, 10/29 or 2026-10-29.")


def _split_route_and_rest(args):
    route, rest = None, []
    for a in args:
        r = parse_route(a) if route is None else None
        if r:
            route = r
        else:
            rest.append(a)
    return route, " ".join(rest)


def _need_route(state, key):
    r = state.find_route(key) if key else None
    if not r:
        known = ", ".join(route_key(x) for x in state.routes()) or "none"
        raise CommandError(f"Which route? Tracked routes: {known}.")
    return r


def handle(state, text, now_local):
    """Apply one command. Returns reply text (HTML)."""
    parts = text.strip().split()
    if not parts:
        return None
    cmd = parts[0].lower().lstrip("/").split("@")[0]
    args = parts[1:]
    try:
        fn = _HANDLERS.get(cmd)
        if fn is None:
            return f"Unknown command /{escape(cmd)}.\n\n{HELP}"
        return fn(state, args, now_local)
    except CommandError as e:
        return str(e)


def _help(state, args, now):
    return HELP


def _status(state, args, now):
    return messages.status(state, now)


def _alert(state, args, now):
    rkey, rest = _split_route_and_rest(args)
    if rkey:
        _need_route(state, rkey)
    d = parse_travel_date(rest, now)
    today = now.date()
    if d < today:
        raise CommandError(f"{day_label(d)} is in the past.")
    if d > today + timedelta(days=60):
        raise CommandError("That's more than 60 days out; pick a closer date.")
    if rules.is_blackout(d):
        raise CommandError(f"{day_label(d)} is a GoWild blackout date, so no seats will open.")
    rt = state.runtime
    for a in rt["alerts"]:
        if a["date"] == d.isoformat() and a["route"] == rkey:
            return f"Already armed (#{a['id']}). " + _expected(d, now)
    rt["alerts"].append({"id": rt["next_alert_id"], "route": rkey, "date": d.isoformat(),
                         "created": iso(now), "fired_at": None, "open_now": {},
                         "no_seats_noted": {}})
    rt["next_alert_id"] += 1
    who = messages.arrow(rkey) if rkey else "your unmuted routes"
    return f"🔔 Armed: GoWild seats on {who} for {day_label(d)}. " + _expected(d, now)


def _expected(d, now):
    release = d - timedelta(days=1)
    if release > now.date():
        return f"Seats usually open around 12:00 AM {day_label(release)} (night of {day_label(release - timedelta(days=1))})."
    return "That date's GoWild window is already open, so I'll ping you at the next check if seats are there."


def _alerts(state, args, now):
    return messages.alerts_list(state)


def _cancel(state, args, now):
    rt = state.runtime
    if not rt["alerts"]:
        return "No alerts armed."
    what = " ".join(args).strip().lower()
    if what in ("", "all"):
        n = len(rt["alerts"])
        rt["alerts"] = []
        return f"Cancelled {n} alert(s)."
    if what.lstrip("#").isdigit():
        keep = [a for a in rt["alerts"] if a["id"] != int(what.lstrip("#"))]
    else:
        d = parse_travel_date(what, now).isoformat()
        keep = [a for a in rt["alerts"] if a["date"] != d]
    n = len(rt["alerts"]) - len(keep)
    rt["alerts"] = keep
    return f"Cancelled {n} alert(s)." if n else "No matching alert. /alerts shows what's armed."


def _nightly(state, args, now):
    v = (args[0].lower() if args else "")
    if v not in ("on", "off"):
        raise CommandError("Use /nightly on or /nightly off.")
    state.settings["nightly_alert"] = v == "on"
    if v == "on":
        return "🔔 I'll ping you every night when GoWild seats open on your unmuted routes."
    return "Nightly alert off. Use /alert for a single night."


def _set_notify(on):
    def fn(state, args, now):
        key = parse_route(" ".join(args)) if args else None
        if args and args[0].lower() == "all":
            targets = state.routes()
        else:
            targets = [_need_route(state, key)]
        for r in targets:
            r["notify"] = on
        names = ", ".join(messages.arrow(route_key(r)) for r in targets)
        if on:
            return f"🔔 Resumed {names}."
        return f"🔕 Paused {names}. Still tracking its history; no alerts or report lines for it."
    return fn


def _times(state, args, now):
    if not args:
        raise CommandError("Use /times ORD-IAH 6am-2pm, /times ORD-IAH after 5pm, or /times ORD-IAH any.")
    rkey, rest = _split_route_and_rest(args)
    if rkey is None and len(state.routes()) == 1:
        rkey = route_key(state.routes()[0])
    route = _need_route(state, rkey)
    rest = rest.strip().lower()
    after = before = None
    if rest in ("any", "all", "off", ""):
        pass
    elif rest.startswith("after "):
        after = hhmm(_clock(rest[6:]))
    elif rest.startswith("before "):
        before = hhmm(_clock(rest[7:]))
    elif "-" in rest:
        a, b = rest.split("-", 1)
        after, before = hhmm(_clock(a)), hhmm(_clock(b))
        if after > before:
            raise CommandError("The start time has to be before the end time.")
    else:
        raise CommandError("Use a range like 6am-2pm, or after 5pm / before 9am / any.")
    route["depart_after"], route["depart_before"] = after, before
    return f"{messages.arrow(rkey)}: only flights departing {messages.window_text(route)}."


def _clock(s):
    try:
        return parse_clock(s)
    except ValueError as e:
        raise CommandError(str(e)) from None


def _add(state, args, now):
    rkey = parse_route(" ".join(args))
    if not rkey:
        raise CommandError("Use /add ORD-DEN (airport codes).")
    if state.find_route(rkey):
        return f"Already tracking {messages.arrow(rkey)}."
    o, d = rkey.split("-")
    state.settings["routes"].append({"origin": o, "dest": d, "notify": True,
                                     "depart_after": None, "depart_before": None})
    return (f"Now tracking {messages.arrow(rkey)} (nonstops only). Each route adds a few "
            "requests per check, so keep the list short.")


def _remove(state, args, now):
    rkey = parse_route(" ".join(args))
    route = _need_route(state, rkey)
    state.settings["routes"].remove(route)
    return f"Stopped tracking {messages.arrow(rkey)}. Its history stays in the state branch."


def _digest(state, args, now):
    v = " ".join(args).strip().lower()
    dg = state.settings["digest"]
    if v == "off":
        dg["enabled"] = False
        return "Morning report off."
    if v == "on":
        dg["enabled"] = True
        return f"Morning report on, at {dg['time']}."
    if not v:
        raise CommandError("Use /digest 6:00, /digest 7am, or /digest off.")
    dg["time"], dg["enabled"] = hhmm(_clock(v)), True
    return (f"Morning report at {dg['time']}. It goes out with the first check at or after that "
            "time (checks run about every 3 hours, plus 6:05 AM Central).")


def _history(state, args, now):
    rkey = parse_route(" ".join(args)) if args else None
    routes = [_need_route(state, rkey)] if rkey else state.routes()
    return "\n\n".join(messages.history(state, r, now.date()) for r in routes) or "No routes."


_HANDLERS = {
    "start": _help, "help": _help, "status": _status,
    "alert": _alert, "alerts": _alerts, "cancel": _cancel, "nightly": _nightly,
    "pause": _set_notify(False), "mute": _set_notify(False),
    "resume": _set_notify(True), "unmute": _set_notify(True),
    "times": _times, "add": _add, "remove": _remove,
    "digest": _digest, "history": _history,
}
