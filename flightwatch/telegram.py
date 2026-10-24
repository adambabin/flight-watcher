"""Minimal Telegram Bot API client (stdlib only).

The bot only talks to one chat: TELEGRAM_CHAT_ID. Messages from anyone else are ignored.
"""
import json
import os
import urllib.request

API = "https://api.telegram.org"

COMMANDS = [
    ("status", "Settings, armed alerts, last check"),
    ("alert", "Ping me when GoWild seats open, e.g. /alert wed"),
    ("alerts", "List armed alerts"),
    ("cancel", "Cancel alerts: /cancel all or /cancel wed"),
    ("nightly", "Alert every night: /nightly on|off"),
    ("pause", "Mute a direction: /pause IAH-ORD"),
    ("resume", "Unmute a direction: /resume IAH-ORD"),
    ("times", "Departure window: /times ORD-IAH 6am-2pm (or any)"),
    ("add", "Track a route: /add ORD-DEN"),
    ("remove", "Stop tracking a route: /remove ORD-DEN"),
    ("digest", "Morning report time: /digest 6:00 (or off)"),
    ("history", "Recent release and sell-out times"),
    ("help", "All commands"),
]


class Telegram:
    def __init__(self, token, chat_id, opener=None):
        self.token = token
        self.chat_id = str(chat_id)
        self._open = opener or urllib.request.urlopen

    @classmethod
    def from_env(cls):
        token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
        if not token or not chat:
            return None
        return cls(token, chat)

    def _call(self, method, **params):
        req = urllib.request.Request(
            f"{API}/bot{self.token}/{method}",
            data=json.dumps(params).encode(),
            headers={"Content-Type": "application/json"},
        )
        with self._open(req, timeout=30) as r:
            body = json.load(r)
        if not body.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {body.get('description')}")
        return body["result"]

    def send(self, text):
        # Telegram caps messages at 4096 chars; split on blank lines to stay under it.
        chunks, cur = [], ""
        for block in text.split("\n\n"):
            if cur and len(cur) + len(block) + 2 > 4000:
                chunks.append(cur)
                cur = block
            else:
                cur = f"{cur}\n\n{block}" if cur else block
        chunks.append(cur)
        for chunk in chunks:
            self._call("sendMessage", chat_id=self.chat_id, text=chunk, parse_mode="HTML",
                       disable_web_page_preview=True)

    def commands_since(self, offset):
        """([(text, date)], new_offset) for messages from our chat since offset."""
        updates = self._call("getUpdates", offset=offset, timeout=0, allowed_updates=["message"])
        out = []
        for u in updates:
            offset = max(offset, u["update_id"] + 1)
            msg = u.get("message") or {}
            if str((msg.get("chat") or {}).get("id")) == self.chat_id and msg.get("text"):
                out.append((msg["text"], msg.get("date")))
        return out, offset

    def register_commands(self):
        self._call("setMyCommands", commands=[{"command": c, "description": d} for c, d in COMMANDS])
