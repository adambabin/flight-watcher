import re
from html import escape
from datetime import datetime, time, timezone


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


_TIME_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*(a|am|p|pm)?$", re.I)


def parse_clock(text):
    """'6', '6am', '6:30pm', '18:30', 'noon' -> datetime.time. Raises ValueError."""
    text = {"noon": "12pm", "midnight": "12am"}.get(text.strip().lower(), text)
    m = _TIME_RE.match(text.strip().replace(".", ""))
    if not m:
        raise ValueError(f"can't read time {escape(text)!r}")
    h, mi, ampm = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if ampm:
        if not 1 <= h <= 12:
            raise ValueError(f"can't read time {escape(text)!r}")
        h = h % 12 + (12 if ampm.startswith("p") else 0)
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        raise ValueError(f"can't read time {escape(text)!r}")
    return time(h, mi)


def hhmm(t):
    return t.strftime("%H:%M")


def clock(t):
    """time or datetime -> '6:05 AM'."""
    return t.strftime("%I:%M %p").lstrip("0")


def local_clock(ts, tz):
    """ISO UTC timestamp -> '12:01 AM' in tz."""
    return clock(parse_iso(ts).astimezone(tz))


def local_stamp(ts, tz, ref_date=None):
    """'12:01 AM', or 'Mon 11:58 PM' when the local date differs from ref_date."""
    dt = parse_iso(ts).astimezone(tz)
    if ref_date is not None and dt.date() != ref_date:
        return dt.strftime("%a ") + clock(dt)
    return clock(dt)


def dep_clock(dep_iso):
    """Frontier's local departure '2026-10-28T06:05:00' -> time(6, 5)."""
    return datetime.fromisoformat(dep_iso).time()


def in_window(dep_iso, after, before):
    """after/before are 'HH:MM' strings or None."""
    if not dep_iso:
        return True
    t = hhmm(dep_clock(dep_iso))
    if after and t < after:
        return False
    if before and t > before:
        return False
    return True


def day_label(d):
    return d.strftime("%a %b ") + str(d.day)
