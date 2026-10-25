# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Frontier Airlines **GoWild pass** seat tracker for one user (adambabin), who is based in Chicago. It watches nonstop ORD ⇄ IAH flights (more routes can be added), records when GoWild seats are released and when they sell out, and reports over a Telegram bot. It runs entirely on GitHub Actions, and the repo is **private**, so the schedule is sized for the 2,000 free Actions minutes a month.

Domain facts the design relies on:
- Domestic GoWild fares open the day before departure, around **12:00 AM in the origin airport's time zone**. Wednesday's flights open at midnight going into Tuesday.
- Seats are few and can reappear later when people cancel.
- Blackout dates have no GoWild fares (`flightwatch/rules.py`, posted through Apr 2027; add new dates there when Frontier posts them).

## Commands

```bash
pip install -r requirements.txt pytest          # only runtime dep is curl_cffi
python -m pytest                                # all tests (pytest.ini puts . and tests/ on the path)
python -m pytest tests/test_runner.py::test_night_watch_catches_release_and_alerts_once   # one test
python -m pyflakes flightwatch tests            # lint used so far

python -m flightwatch search ORD IAH 2026-10-28                 # raw parsed Frontier result, no state
python -m flightwatch {auto|tick|night|digest|check|commands} --state .state
```

Without `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`, messages are printed to stdout instead of sent. Frontier (flyfrontier.com) is blocked by the network policy of the Claude Code cloud sandbox, so live checks only work from GitHub Actions or a local machine. The workflow can be triggered by hand with `workflow_dispatch`, using mode `check` (setup test), `tick`, `digest`, `night` or `commands`.

## Architecture

**Data source** (`frontier.py`): Frontier has no API. `GET booking.flyfrontier.com/Flight/InternalSelect?o1=..&d1=..&dd1=Oct 28, 2026&ADT=1&mon=true&promo=` returns the logged-out select page.
- That page embeds `FlightData = '<html-escaped JSON>'`. Each flight in `journeys[].flights[]` has `legs[]`, `isGoWildFareEnabled`, `goWildFare` and `goWildFareSeatsRemaining` ("2 Seats Left!"; missing means plenty). The top level has `isGoWildOutOfRange`.
- Nonstop means `len(legs) == 1`.
- The site uses DataDome: one `curl_cffi` Chrome-impersonating session, 4–7 s between requests. HTTP 403/405/406/429 or captcha means `blocked`.
- Verified working from GitHub Actions runners on 2026-10-24. At that point Frontier had one nonstop each way: F9 3135 ORD→IAH 7:40 AM, F9 1882 IAH→ORD 11:36 AM.

**Run modes** (`runner.py` `App`), picked by local Central time in `pick_mode()`, because cron is in UTC and covers both DST offsets:
- `tick`: answer commands, poll today and tomorrow for every route, fire alerts, send the digest if it's due (first run at or after `digest.time`, within 6 h).
- `night`: started at 11:50 PM by cron. It polls only the date about to open (midnight + 1 day), every 4 min and then every 2 min from 11:58 PM until 12:15 AM. It processes commands every cycle, arms nightly alerts, and afterwards sends a "no seats" note for armed alerts that saw nothing. Blackout targets fall back to `tick`.
- `commands`: started by a relayed Telegram message (see below). If it lands in the night window it does `night()` instead. GitHub keeps only one pending run per concurrency group, so a commands run can replace a queued night run, and this keeps the night watch from being lost.
- All runs share concurrency group `flightwatch` (never parallel), so writes to the state branch never conflict.

**History** (`tracker.record`): turns each poll into per-flight records keyed `"YYYY-MM-DD|ORD-IAH|F9 1234"`.
- Every transition time (`opened_at`, `sold_out_at`) is stored with the previous check's time (`opened_prev`, `sold_out_prev`), so messages say "opened between X and Y". `opened_prev = None` means it was already open at the first check.
- Per route and date, `days.json` tracks the `isGoWildOutOfRange` true→false transition as a second release signal.

**State** (`state.py`, `scripts/state.sh`): JSON files in `.state/`, cloned from and pushed back to the orphan **`state` branch** on every run, even when the run fails.
- `settings.json` holds routes (`notify`, `depart_after`/`depart_before` "HH:MM"), the timezone, the digest and `nightly_alert`. These are changed only through bot commands.
- `runtime.json` holds alerts, the Telegram offset, `digest_sent` and the block log.
- `flights.json`, `days.json` and `observations/YYYY-MM.jsonl` hold the history (observations are raw and append-only).

**Commands** (`commands.py`): `handle(state, text, now_local)` mutates state and returns HTML reply text. `/now` is special-cased in `App._answer`, because it needs Frontier.
- Dates in `/alert` mean **travel** dates. The default is `next_release_date()` (the coming midnight's date + 1, with a 2-hour grace after midnight).
- An alert with `route=None` covers all unmuted routes. One with an explicit route fires even if that route is paused.
- An alert re-fires only after its matching flights have all sold out and something reopens (tracked in `open_now[route]`).

**Telegram I/O** has two paths, and `process_commands` reads both:
1. `telegram.py` `getUpdates`, which only gets messages at scheduled runs. Once the webhook is set, Telegram returns 409 for this, and that's ignored on purpose.
2. Relay: the Cloudflare Worker `relay/worker.js` receives the Telegram webhook, posts the text as a comment on **issue #2 ("Telegram inbox")** using the user's fine-grained PAT, and reacts 👀. The `issue_comment` event starts the workflow in `commands` mode. `inbox.py` reads the comments with the workflow's `GITHUB_TOKEN` and deletes each one after answering it.
- The repo and issue number are hard-coded in `relay/worker.js` (`INBOX_ISSUE = 2`) and in the workflow (`INBOX_ISSUE: "2"` plus the `if:` on the job).
- The webhook secret is SHA-256 of `gowild-relay:<bot token>`, and `/setup` on the worker registers the webhook.
- Measured: comment → reply in about 11 s.

**Messages** (`messages.py`): Telegram HTML parse mode. Escape anything user-supplied. Flight and check times show in the route's origin-airport tz (`airports.py`), with the weekday added when the date differs from the departure date.

## Testing conventions

`tests/conftest.py` provides:
- `page(flights, out_of_range)`, which builds a fake select page, and `flight(...)`
- `Clock`, a fake clock whose `sleep` advances it, so a whole night watch runs instantly
- `FakeFrontier`, `FakeBot` (its inbox is Telegram getUpdates) and `FakeInbox` (the GitHub issue inbox)
- `make_app(state, clock, respond, inbox=[...])`

`test_runner.released_at_midnight` is the standard fake Frontier: ORD-IAH F9 1234 opens at midnight with 2 seats, and IAH-ORD never opens.

## Backlog (Notion)

The user tracks work in the Notion database **"✈️ GoWild Tracker Backlog"**: https://app.notion.com/p/171f4a15b3ac8356afef81c264e0dece. Read and update it with the Notion MCP tools, using data source `collection://987f4a15-b3ac-83de-8c50-87c77ec7962d`.

When the user says "ticket N", they mean the `ID` property (auto-increment).

| Property | Values |
|---|---|
| Status | Backlog, User feedback, In progress, Pending testing, Closed, Never |
| Type | Feature, Bug, Idea |
| Theme | Multi-select. Many options are leftovers from another project's template. |

Page templates: "Basic", "Mock options".

Tickets 2–4 are setup notes (the bot, userinfobot, the relay token) and may contain secrets, so never copy their contents into the repo. As of 2026-10-25:
- **#5** Check for site updates that would break this (Backlog)
- **#6** Add the updates to a dashboard (User feedback): view each flight's activity over time, e.g. filter to IAH→ORD 11:36 AM and see what time GoWild seats appear each night and when they sell out, day over day and week over week.
  - The user chose **Notion** as the dashboard home. They want all four views: release-time timeline, open window per day, week-over-week, and seat count through a day.
  - The mockups are on the subpage "📊 Dashboard mockups" (https://app.notion.com/p/404f4a15b3ac81c096edee5f8a293761). It shows options A–E as linked views over two **SAMPLE** databases under the ticket: "Flight days (SAMPLE)" `collection://00269479-a49c-4308-a8d4-07ea3902e312` (one row per flight per departure date) and "Seat checks (SAMPLE)" `collection://04cd853d-1443-4216-afde-bed70b1e2104` (one row per check).
  - We're waiting on the user's picks (the questions are at the bottom of that page). Building it for real means the tracker writes those rows after every check. That needs a Notion integration token as a GitHub secret, plus deleting the SAMPLE databases.

## Status (as of 2026-10-25)

Done and live on `main`:
- The tracker (PR #1) and the relay support (PR #3).
- Secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set, and the bot works: the setup check, commands and `/status` were all answered.
- The user armed `/alert` for Mon Oct 26 flights.

Pending, waiting on the user at a computer:
1. **Create the fine-grained PAT**: github.com/settings/personal-access-tokens/new. Settings: only `flight-watcher`, Issues: Read and write. The mobile Safari "Generate token" confirmation button didn't respond, so the user will retry on desktop.
2. **Deploy `relay/worker.js` on Cloudflare Workers** (free) with secrets `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` and `GITHUB_TOKEN` (the PAT). Then open `https://<worker>.workers.dev/setup` and send `/status` to test. Full steps are in the README under "Fast replies".

Ideas raised but not done:
- **Public repo**: unlimited minutes would allow hourly checks and a longer night window. The tradeoff is that the state branch becomes public.
- **Cron for other time zones**: only Central midnights are watched closely, so routes from other zones need their own 11:50 PM cron line.
- **Action versions**: `actions/checkout@v4` and `setup-python@v5` trigger a Node 20 deprecation warning. Bumping them is harmless.
