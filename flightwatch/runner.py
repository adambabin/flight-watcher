"""The two kinds of run.

tick:  answer Telegram commands, check today's and tomorrow's flights on every route
       (and, in the evening, the day after, in case it opens early), fire armed alerts,
       send the morning report when it's due.
night: started at 10:40 PM; checks the date that's about to open every few minutes
       until 12:30 AM, every 2 minutes around midnight Eastern and midnight local, so we
       see the exact release and can ping right away.
"""
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import commands, messages, rules, tracker
from .airports import airport_tz
from .frontier import FrontierError
from .state import route_key
from .timeutil import iso, parse_clock, parse_iso

NIGHT_START = (22, 30)          # local time from which a run counts as the night watch
NIGHT_END_AFTER_MIDNIGHT = 30   # minutes
NIGHT_LATE_START = 20           # a run starting this many minutes after midnight still watches
POLL_EVERY = 4                  # minutes between checks
POLL_HOT = 2                    # minutes between checks around a likely release moment
HOT_ZONES = ("America/New_York",)   # midnights besides the local one where seats have shown up
EVENING_LOOKAHEAD_FROM = 18     # from this local hour, ticks also check the day after tomorrow
NIGHT_MAX_BLOCKS = 3
DIGEST_LATE_LIMIT = timedelta(hours=6)


class Blocked(Exception):
    pass


class App:
    def __init__(self, state, frontier, bot, now_fn=None, sleep=time.sleep, log=print, inbox=None):
        self.state = state
        self.frontier = frontier
        self.bot = bot
        self.inbox = inbox
        self._now = now_fn or (lambda: datetime.now(timezone.utc))
        self.sleep = sleep
        self.log = log

    # ------------------------------------------------------------ basics

    @property
    def tz(self):
        return ZoneInfo(self.state.settings["timezone"])

    def local_now(self):
        return self._now().astimezone(self.tz)

    def route_today(self, route):
        return self._now().astimezone(airport_tz(route["origin"], self.state.settings["timezone"])).date()

    def notify(self, text):
        if self.bot is None:
            self.log("[telegram not configured]\n" + text)
            return
        try:
            self.bot.send(text)
        except Exception as e:  # a failed message shouldn't lose the run's data
            self.log(f"telegram send failed: {e}")

    def process_commands(self):
        """Answer pending commands from the relay's GitHub inbox and from Telegram getUpdates."""
        if self.inbox is not None:
            try:
                pending = self.inbox.pending()
            except Exception as e:
                self.log(f"inbox read failed: {e}")
                return
            for comment_id, text in pending:
                self._answer(text)
                try:
                    self.inbox.done(comment_id)
                except Exception as e:
                    self.log(f"inbox delete failed: {e}")
        if self.bot is None:
            return
        # Without the relay, messages wait in Telegram for getUpdates. With it, Telegram
        # refuses getUpdates (409, webhook active) and the inbox above has them instead.
        rt = self.state.runtime
        try:
            cmds, rt["telegram_offset"] = self.bot.commands_since(rt["telegram_offset"])
        except Exception as e:
            if "409" not in str(e) and "webhook" not in str(e).lower():
                self.log(f"telegram getUpdates failed: {e}")
            return
        for text, _ in cmds:
            self._answer(text)

    def _answer(self, text):
        self.log(f"command: {text}")
        if text.strip().lower().split("@")[0] == "/now":
            return self.now_report()
        reply = commands.handle(self.state, text, self.local_now())
        if reply:
            self.notify(reply)

    def now_report(self):
        """/now: check Frontier right away and report today's and tomorrow's flights."""
        blocks = []
        try:
            for route in self.state.routes():
                today = self.route_today(route)
                for dep, title in ((today, "(today)"), (today + timedelta(days=1), "(tomorrow)")):
                    if not rules.is_blackout(dep):
                        self.poll(route, dep, "now")
                    blocks.append(messages.route_day_block(self.state, route, dep, title))
        except Blocked:
            blocks.append("⚠️ Frontier refused the check, so this may be incomplete.")
        self.notify("🔎 <b>Right now</b>\n\n" + "\n\n".join(blocks))

    # ------------------------------------------------------------ checking

    def poll(self, route, dep, mode):
        """Check one route/date and fire alerts. Raises Blocked if Frontier is refusing us."""
        try:
            result = self.frontier.search(route["origin"], route["dest"], dep)
        except FrontierError as e:
            self.log(f"{route_key(route)} {dep}: {e}")
            if e.blocked:
                self._note_block()
                raise Blocked(str(e)) from None
            return
        now = self._now()
        events = tracker.record(self.state, route, dep, result, now, mode)
        self.state.runtime["last_check"] = iso(now)
        nonstop = [f for f in result["flights"] if f["stops"] == 0]
        open_n = sum(f["gowild"] for f in nonstop)
        self.log(f"{route_key(route)} {dep}: {len(nonstop)} nonstop, {open_n} GoWild open"
                 + (f", events {events}" if events else ""))
        self.check_alerts(route, dep)

    def _note_block(self):
        rt = self.state.runtime
        rt["blocks"] = (rt["blocks"] + [iso(self._now())])[-50:]
        today = self.local_now().date().isoformat()
        if rt.get("block_notified") != today:
            rt["block_notified"] = today
            self.notify("⚠️ Frontier's bot protection refused a check. I'll keep trying on the "
                        "normal schedule. If this happens every day, GitHub's servers are probably "
                        "blocked; see the README for running the tracker from home instead.")

    def recent_blocks(self):
        cutoff = self._now() - timedelta(hours=24)
        return sum(parse_iso(t) >= cutoff for t in self.state.runtime["blocks"])

    # ------------------------------------------------------------ alerts

    def _alert_routes(self, alert):
        if alert["route"]:
            r = self.state.find_route(alert["route"])
            return [r] if r else []
        return [r for r in self.state.routes() if r["notify"]]

    def check_alerts(self, route, dep):
        rkey = route_key(route)
        for a in self.state.runtime["alerts"]:
            if a["date"] != dep.isoformat() or route not in self._alert_routes(a):
                continue
            recs = tracker.matching(route, tracker.flights_for(self.state, rkey, dep))
            open_recs = [r for r in recs if r["status"] == "open"]
            seen = a.setdefault("open_now", {})
            if open_recs and not seen.get(rkey):
                self.notify(messages.alert_open(self.state, route, dep, open_recs))
                a["fired_at"] = a.get("fired_at") or iso(self._now())
            seen[rkey] = bool(open_recs)

    def expire_alerts(self):
        today = self.local_now().date().isoformat()
        self.state.runtime["alerts"] = [a for a in self.state.runtime["alerts"] if a["date"] >= today]

    def arm_nightly(self, target):
        rt = self.state.runtime
        if any(a["date"] == target.isoformat() and a["route"] is None for a in rt["alerts"]):
            return
        rt["alerts"].append({"id": rt["next_alert_id"], "route": None, "date": target.isoformat(),
                             "created": iso(self._now()), "fired_at": None, "nightly": True})
        rt["next_alert_id"] += 1

    # ------------------------------------------------------------ modes

    def pick_mode(self):
        t = self.local_now()
        if (t.hour, t.minute) >= NIGHT_START or (t.hour == 0 and t.minute < NIGHT_LATE_START):
            return "night"
        return "tick"

    def commands_run(self):
        """Started by a relayed Telegram message. Answers it; if this run took the place of
        the night watch in GitHub's queue, does the night watch too."""
        if self.pick_mode() == "night":
            return self.night()
        self.process_commands()
        self.maybe_digest()

    def tick(self):
        self.process_commands()
        self.expire_alerts()
        try:
            for route in self.state.routes():
                today = self.route_today(route)
                ahead = 2 if self.local_now().hour >= EVENING_LOOKAHEAD_FROM else 1
                for i in range(ahead + 1):
                    dep = today + timedelta(days=i)
                    if not rules.is_blackout(dep):
                        self.poll(route, dep, "tick")
        except Blocked:
            pass
        self.maybe_digest()

    def night(self):
        self.process_commands()
        self.expire_alerts()
        now_l = self.local_now()
        day = now_l.date() + timedelta(days=1) if now_l.hour >= 12 else now_l.date()
        midnight = datetime(day.year, day.month, day.day, tzinfo=self.tz)
        target = day + timedelta(days=1)
        end = midnight + timedelta(minutes=NIGHT_END_AFTER_MIDNIGHT)
        if rules.is_blackout(target):
            self.log(f"{target} is a blackout date; nothing opens tonight")
            return self.tick()
        if self.state.settings["nightly_alert"]:
            self.arm_nightly(target)
        self.log(f"night watch for {target} flights, midnight {midnight.isoformat()}, until {end.isoformat()}")

        blocks = 0
        while True:
            self.process_commands()
            try:
                for route in self.state.routes():
                    self.poll(route, target, "night")
            except Blocked:
                blocks += 1
                if blocks >= NIGHT_MAX_BLOCKS:
                    self.log("blocked too many times; ending night watch")
                    break
                self.frontier.reset()
            self.state.save()
            now_l = self.local_now()
            if now_l >= end:
                break
            nxt = self._next_poll(now_l, midnight)
            self.sleep(max(0.0, (nxt - now_l).total_seconds()))

        self._report_no_seats(target)

    def _next_poll(self, now_l, midnight):
        """Every POLL_EVERY minutes, tightening to POLL_HOT from 3 minutes before to 12 after
        each likely release moment (midnight Eastern, midnight local)."""
        day = midnight.date()
        hot = [midnight] + [datetime(day.year, day.month, day.day, tzinfo=ZoneInfo(z)) for z in HOT_ZONES]
        for h in hot:
            if h - timedelta(minutes=3) <= now_l < h + timedelta(minutes=12):
                return now_l + timedelta(minutes=POLL_HOT)
        nxt = now_l + timedelta(minutes=POLL_EVERY)
        for h in hot:
            start = h - timedelta(minutes=3)
            if now_l < start < nxt:
                nxt = start
        return nxt

    def _report_no_seats(self, target):
        until = self._now()
        for a in self.state.runtime["alerts"]:
            if a["date"] != target.isoformat():
                continue
            noted = a.setdefault("no_seats_noted", {})
            for route in self._alert_routes(a):
                rkey = route_key(route)
                if not a.get("open_now", {}).get(rkey) and not noted.get(rkey):
                    if (tracker.day_key(target, rkey)) in self.state.days:
                        self.notify(messages.alert_none(self.state, route, target, until))
                        noted[rkey] = True

    def maybe_digest(self, force=False):
        dg = self.state.settings["digest"]
        now_l = self.local_now()
        today = now_l.date()
        if not force:
            if not dg["enabled"] or self.state.runtime.get("digest_sent") == today.isoformat():
                return
            due = datetime.combine(today, parse_clock(dg["time"]), tzinfo=self.tz)
            if not (due <= now_l <= due + DIGEST_LATE_LIMIT):
                return
        self.notify(messages.digest(self.state, today, self.recent_blocks()))
        self.state.runtime["digest_sent"] = today.isoformat()

    def check(self):
        """Setup test: hit Frontier once per route for tomorrow and report back on Telegram."""
        if self.bot:
            try:
                self.bot.register_commands()
            except Exception as e:
                self.log(f"setMyCommands failed: {e}")
        lines = ["🛠 <b>Setup check</b>"]
        for route in self.state.routes():
            dep = self.route_today(route) + timedelta(days=1)
            rkey = route_key(route)
            try:
                result = self.frontier.search(route["origin"], route["dest"], dep)
            except FrontierError as e:
                lines.append(f"❌ {messages.arrow(rkey)}: {e}")
                continue
            tracker.record(self.state, route, dep, result, self._now(), "check")
            nonstop = [f for f in result["flights"] if f["stops"] == 0]
            lines.append(f"✅ {messages.arrow(rkey)} {dep}: {len(result['flights'])} itineraries, "
                         f"{len(nonstop)} nonstop, {sum(f['gowild'] for f in nonstop)} with GoWild open")
            for f in nonstop:
                self.log(f"  {f}")
        lines.append("Send /help to see what I can do.")
        self.notify("\n".join(lines))
