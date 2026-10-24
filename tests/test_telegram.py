import io
import json

from flightwatch.telegram import Telegram


class FakeOpener:
    def __init__(self, results):
        self.results = list(results)
        self.requests = []

    def __call__(self, req, timeout):
        self.requests.append((req.full_url.rsplit("/", 1)[1], json.loads(req.data)))
        return io.BytesIO(json.dumps({"ok": True, "result": self.results.pop(0)}).encode())


def test_only_our_chat_is_listened_to():
    op = FakeOpener([[
        {"update_id": 10, "message": {"chat": {"id": 42}, "text": "/status", "date": 1}},
        {"update_id": 11, "message": {"chat": {"id": 666}, "text": "/remove ORD-IAH", "date": 2}},
        {"update_id": 12, "edited_message": {}},
    ]])
    cmds, offset = Telegram("tok", "42", opener=op).commands_since(5)
    assert cmds == [("/status", 1)] and offset == 13
    assert op.requests[0] == ("getUpdates", {"offset": 5, "timeout": 0, "allowed_updates": ["message"]})


def test_long_messages_are_split():
    op = FakeOpener([{}, {}])
    Telegram("tok", "42", opener=op).send("\n\n".join(["x" * 3000, "y" * 3000]))
    assert [r[1]["text"][0] for r in op.requests] == ["x", "y"]
    assert op.requests[0][1]["parse_mode"] == "HTML"
