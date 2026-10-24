import io
import json

from flightwatch.inbox import GitHubInbox

from conftest import Clock, FakeInbox, local, make_app
from test_runner import released_at_midnight


def test_relayed_commands_are_answered_and_deleted(state):
    clock = Clock(local(2026, 10, 24, 15, 45))
    app, fr, bot = make_app(state, clock, released_at_midnight, inbox=["/pause IAH-ORD"])
    app.inbox = FakeInbox(["/status", "/alert"])
    app.commands_run()
    assert app.inbox.deleted == [1, 2] and app.inbox.items == []
    assert bot.sent[0].startswith("<b>Routes</b>") and bot.sent[1].startswith("🔔 Armed")
    assert "Paused" in bot.sent[2]  # still reads Telegram's own queue too
    assert fr.calls == []  # answering commands doesn't hit Frontier


def test_now_checks_frontier_and_reports(state):
    clock = Clock(local(2026, 10, 26, 0, 30))
    app, fr, bot = make_app(state, clock, released_at_midnight)
    app.inbox = FakeInbox(["/now"])
    app.commands_run()
    assert len(fr.calls) == 4
    msg = bot.sent[-1]
    assert msg.startswith("🔎 <b>Right now</b>")
    assert "<b>ORD → IAH · Tue Oct 27</b> (tomorrow)" in msg and "✅ F9 1234" in msg


def test_commands_run_in_night_window_does_the_night_watch(state):
    clock = Clock(local(2026, 10, 26, 23, 52))
    app, fr, bot = make_app(state, clock, released_at_midnight)
    app.inbox = FakeInbox(["/alert"])
    app.commands_run()
    assert any(m.startswith("🟢") for m in bot.sent)
    assert fr.calls[-1][3] >= local(2026, 10, 27, 0, 15)


class Opener:
    def __init__(self, bodies):
        self.bodies = list(bodies)
        self.requests = []

    def __call__(self, req, timeout):
        self.requests.append((req.get_method(), req.full_url, req.headers.get("Authorization")))
        return io.BytesIO(self.bodies.pop(0))


def test_github_inbox_calls():
    op = Opener([json.dumps([{"id": 7, "body": "/status"}, {"id": 8, "body": "  "}]).encode(), b""])
    inbox = GitHubInbox("tok", "adambabin/flight-watcher", 2, opener=op)
    assert inbox.pending() == [(7, "/status")]
    inbox.done(7)
    assert op.requests == [
        ("GET", "https://api.github.com/repos/adambabin/flight-watcher/issues/2/comments?per_page=100", "Bearer tok"),
        ("DELETE", "https://api.github.com/repos/adambabin/flight-watcher/issues/comments/7", "Bearer tok"),
    ]
