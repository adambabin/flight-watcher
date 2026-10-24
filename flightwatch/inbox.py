"""Commands relayed from Telegram as comments on the "Telegram inbox" issue.

Once the relay (relay/worker.js) is set up, Telegram delivers messages to it instead
of holding them for getUpdates, so this is where commands come from. Each comment is
deleted after it's answered.
"""
import json
import os
import urllib.request

API = "https://api.github.com"


class GitHubInbox:
    def __init__(self, token, repo, issue, opener=None):
        self.token = token
        self.repo = repo
        self.issue = issue
        self._open = opener or urllib.request.urlopen

    @classmethod
    def from_env(cls):
        issue, token, repo = (os.environ.get(k) for k in ("INBOX_ISSUE", "GITHUB_TOKEN", "GITHUB_REPOSITORY"))
        if not (issue and token and repo):
            return None
        return cls(token, repo, int(issue))

    def _call(self, method, path):
        req = urllib.request.Request(f"{API}{path}", method=method, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "flightwatch",
        })
        with self._open(req, timeout=30) as r:
            body = r.read()
        return json.loads(body) if body else None

    def pending(self):
        """[(comment_id, text)], oldest first."""
        comments = self._call("GET", f"/repos/{self.repo}/issues/{self.issue}/comments?per_page=100")
        return [(c["id"], c["body"]) for c in comments if (c.get("body") or "").strip()]

    def done(self, comment_id):
        self._call("DELETE", f"/repos/{self.repo}/issues/comments/{comment_id}")
