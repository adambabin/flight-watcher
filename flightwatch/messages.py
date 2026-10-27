"""Telegram message text (HTML parse mode)."""
from datetime import date, timedelta
from html import escape
from zoneinfo import ZoneInfo

from . import rules
from .airports import airport_tz
from .frontier import search_url
from .state import HEALTH_ALERT_AFTER, route_key
from .timeutil import clock, day_label, dep_clock, local_stamp, parse_clock
from .tracker import flights_for, matching, release_estimate


def arrow(rkey):
    return rkey.replace("-", " → ")


def _tz(state, rkey):
    return airport_tz(rkey.split("-")[0], state.settings["timezone"])


def _stamp(ts, tz, dep):
    return local_stamp(ts, tz, dep) if ts else "?"


def flight_line(rec, tz, dep):
    times = ""
    if rec.get("dep"):
        times = f" · {clock(dep_clock(rec['dep']))} → {clock(dep_clock(rec['arr']))}"
    head = f"{escape(rec['flight'])}{times}"
    if rec["status"] == "open":
        seats = f"{rec['seats']} left" if rec["seats"] else "open"
        price = f" · ${rec['price']:.2f}" if rec.get("price") else ""
        opened = f" · opened {_stamp(rec['opened_at'], tz, dep)}" if rec["opened_prev"] else ""
        return f"✅ {head} · GoWild {seats}{price}{opened}"
    if rec["opened_at"]:
        opened = _stamp(rec["opened_at"], tz, dep) if rec["opened_prev"] else f"seen {_stamp(rec['opened_at'], tz, dep)}"
        gone = f"sold out by {_stamp(rec['sold_out_at'], tz, dep)}" if rec.get("sold_out_at") else "sold out"
        return f"❌ {head} · {gone} (opened {opened})"
    return f"▫️ {head} · no GoWild seats"


def release_line(state, rkey, dep):
    tz = _tz(state, rkey)
    est = release_estimate(state, rkey, dep)
    if not est:
        return None
    seen, before = est
    if not any(r["opened_at"] for r in flights_for(state, rkey, dep)):
        return (f"GoWild booking opened between {_stamp(before, tz, dep)} and {_stamp(seen, tz, dep)}, "
                "but no nonstop had seats.")
    if before:
        return f"GoWild opened between {_stamp(before, tz, dep)} and {_stamp(seen, tz, dep)}."
    return f"GoWild was already open at our first check ({_stamp(seen, tz, dep)})."


def booking_link(rkey, dep):
    o, d = rkey.split("-")
    return f'<a href="{escape(search_url(o, d, dep))}">Open on Frontier</a> (log in to use your pass)'


def route_day_block(state, route, dep, title):
    rkey = route_key(route)
    tz = _tz(state, rkey)
    head = f"<b>{arrow(rkey)} · {day_label(dep)}</b> {title}".rstrip()
    if rules.is_blackout(dep):
        return f"{head}\nBlackout date: no GoWild fares."
    all_recs = flights_for(state, rkey, dep)
    recs = matching(route, all_recs)
    if not all_recs:
        return f"{head}\nNo checks yet (or no nonstop flights listed)."
    lines = [head] + [flight_line(r, tz, dep) for r in recs]
    hidden = len(all_recs) - len(recs)
    if hidden:
        lines.append(f"<i>{hidden} more outside your {window_text(route)} window</i>")
    rel = release_line(state, rkey, dep)
    if rel:
        lines.append(rel)
    return "\n".join(lines)


def window_text(route):
    a, b = route.get("depart_after"), route.get("depart_before")
    if not a and not b:
        return "any time"
    fmt = lambda s: clock(dep_clock(f"2000-01-01T{s}"))
    if a and b:
        return f"{fmt(a)}–{fmt(b)}"
    return f"after {fmt(a)}" if a else f"before {fmt(b)}"


def digest(state, today, recent_blocks=0):
    tomorrow = today + timedelta(days=1)
    parts = [f"☀️ <b>GoWild morning report · {day_label(today)}</b>"]
    muted = []
    for route in state.routes():
        if not route["notify"]:
            muted.append(arrow(route_key(route)))
            continue
        parts.append(route_day_block(state, route, tomorrow, "(released last night)"))
        parts.append(route_day_block(state, route, today, "(today)"))
    if rules.is_blackout(tomorrow + timedelta(days=1)):
        parts.append(f"Heads up: {day_label(tomorrow + timedelta(days=1))} is a blackout date, "
                     "so nothing opens tonight.")
    if muted:
        parts.append("Paused: " + ", ".join(muted))
    if recent_blocks:
        parts.append(f"⚠️ Frontier blocked {recent_blocks} check(s) in the last day, so some "
                     "times may be missing.")
    h = state.runtime["health"]
    if h["fail_streak"] >= HEALTH_ALERT_AFTER:
        parts.append(f"⚠️ Frontier checks have been failing since {_since(h, ZoneInfo(state.settings["timezone"]), today)}, "
                     "so the times above may be stale. Latest error: "
                     f"<code>{escape(h['last_error'] or '?')}</code>")
    return "\n\n".join(parts)


def _since(h, tz, ref_date):
    return _stamp(h["first_fail"], tz, ref_date)


def health_alert(h, now_local):
    return "\n".join([
        "⚠️ <b>Frontier checks are failing</b>",
        f"The last {h['fail_streak']} checks failed, starting {_since(h, now_local.tzinfo, now_local.date())}. "
        "Until this is fixed I can't see GoWild seats, so alerts won't fire.",
        f"Latest error: <code>{escape(h['last_error'] or '?')}</code>",
        "If Frontier changed its site, the parser needs an update. What Frontier sent is saved "
        "on the state branch as <code>debug/last_failure.html</code>. GitHub marks this run as failed too.",
    ])


def health_ok(h, now_local):
    return (f"✅ Frontier checks are working again (they had been failing since "
            f"{_since(h, now_local.tzinfo, now_local.date())}). Tracking has resumed.")


def alert_open(state, route, dep, recs):
    rkey = route_key(route)
    tz = _tz(state, rkey)
    lines = [f"🟢 <b>GoWild seats open: {arrow(rkey)} · {day_label(dep)}</b>"]
    lines += [flight_line(r, tz, dep) for r in recs]
    rel = release_line(state, rkey, dep)
    if rel:
        lines.append(rel)
    lines.append(booking_link(rkey, dep))
    return "\n".join(lines)


def alert_none(state, route, dep, until):
    rkey = route_key(route)
    tz = _tz(state, rkey)
    return (f"⚪ {arrow(rkey)} · {day_label(dep)}: no GoWild seats on nonstops in your window "
            f"as of {clock(until.astimezone(tz))}. I'll keep checking through the day and ping "
            "you if any open up.")


def status(state, now_local):
    s = state.settings
    lines = ["<b>Routes</b>"]
    for r in state.routes():
        flag = "🔔" if r["notify"] else "🔕 paused"
        lines.append(f"{flag} {arrow(route_key(r))} · departing {window_text(r)}")
    d = s["digest"]
    lines.append(f"\nMorning report: {clock(parse_clock(d['time'])) if d['enabled'] else 'off'}")
    lines.append(f"Nightly midnight alert: {'on' if s['nightly_alert'] else 'off'}")
    lines.append("\n" + alerts_list(state))
    last = state.runtime.get("last_check")
    if last:
        lines.append(f"\nLast check: {local_stamp(last, now_local.tzinfo, now_local.date())}")
    h = state.runtime["health"]
    if h["fail_streak"]:
        lines.append(f"⚠️ {h['fail_streak']} check(s) in a row failed, since "
                     f"{_since(h, now_local.tzinfo, now_local.date())}: <code>{escape(h['last_error'] or '?')}</code>")
    return "\n".join(lines)


def alerts_list(state):
    alerts = state.runtime["alerts"]
    if not alerts:
        return "No alerts armed. Send /alert to get pinged when tonight's seats open."
    lines = ["<b>Armed alerts</b>"]
    for a in sorted(alerts, key=lambda a: a["date"]):
        who = arrow(a["route"]) if a["route"] else "all unmuted routes"
        fired = " (seats seen, still watching for reopenings)" if a.get("fired_at") else ""
        lines.append(f"#{a['id']} {day_label(date.fromisoformat(a['date']))} · {who}{fired}")
    return "\n".join(lines)


def history(state, route, today, days=10):
    rkey = route_key(route)
    tz = _tz(state, rkey)
    lines = [f"<b>{arrow(rkey)} · last {days} days</b>"]
    for i in range(days - 1, -1, -1):
        dep = today + timedelta(days=1 - i)
        recs = flights_for(state, rkey, dep)
        if not recs:
            continue
        est = release_estimate(state, rkey, dep)
        if est and est[1]:
            rel = f"opened {_stamp(est[1], tz, dep)}–{_stamp(est[0], tz, dep)}"
        elif est:
            rel = f"open at first check {_stamp(est[0], tz, dep)}"
        else:
            rel = "no GoWild seen"
        outs = []
        for r in recs:
            if r["status"] == "open":
                outs.append(f"{r['flight']} open")
            elif r.get("sold_out_at"):
                outs.append(f"{r['flight']} gone by {_stamp(r['sold_out_at'], tz, dep)}")
        tail = f" · {'; '.join(outs)}" if outs else ""
        lines.append(f"{day_label(dep)}: {rel}{tail}")
    if len(lines) == 1:
        lines.append("No history yet.")
    return "\n".join(lines)
