# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Frontier Airlines **GoWild pass** seat tracker for one user (adambabin), who is based in Chicago. It watches nonstop ORD ⇄ IAH flights (more routes can be added), records when GoWild seats are released and when they sell out, and reports over a Telegram bot. It runs entirely on GitHub Actions. The repo is **public** (since 2026-10-26), so Actions minutes are unlimited. Never commit secrets: they live in GitHub/Cloudflare secret stores.

Domain facts the design relies on:
- Domestic GoWild fares open the day before departure, around midnight going into that day. Wednesday's flights open around midnight going into Tuesday.
  - **The exact time is unconfirmed.** On 2026-10-24 the ORD→IAH seats for Mon Oct 26 were already open at 11:18 PM CT Saturday. On 2026-10-25 at 9:54 PM, both Tue Oct 27 flights were already open, more than a day before the expected release. Hourly ticks now look 3 days out to find the real opening edge; once it's known, move the night watch to it.
  - Flight numbers and times differ by weekday. On Tue, ORD→IAH is F9 3135 at 2:11 PM and IAH→ORD is F9 3136 at 6:16 PM.
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
- **Layout checks** (`_check_layout`): if `journeys`/`flights`/`legs`, or `isGoWildFareEnabled`/`goWildFare` on every flight, are missing, or `FlightData` is gone without a captcha, it raises `FrontierError(layout=True)`. That way a redesign never gets recorded as "no GoWild seats".
- `Frontier.last_page`/`last_url` keep the latest raw response for snapshots.
- Verified working from GitHub Actions runners on 2026-10-24. At that point Frontier had one nonstop each way: F9 3135 ORD→IAH 7:40 AM, F9 1882 IAH→ORD 11:36 AM.

**Run modes** (`runner.py` `App`), picked by local Central time in `pick_mode()`, because cron is in UTC and covers both DST offsets:
- `tick` (hourly cron): answer commands, poll today through `LOOKAHEAD_DAYS` (3) days ahead for every route, fire alerts, send the digest if it's due (first run at or after `digest.time`, within 6 h).
- `night`: started at 10:40 PM CT by cron (`pick_mode` treats 10:30 PM–12:20 AM as night). It polls only the date about to open (midnight + 1 day) until 12:30 AM. `_next_poll` checks every 4 min, tightening to every 2 min within −3/+12 min of midnight Eastern (`HOT_ZONES`) and local midnight. It processes commands every cycle, arms nightly alerts, and afterwards sends a "no seats" note for armed alerts that saw nothing. Blackout targets fall back to `tick`.
- **Clock:** GitHub cron proved unreliable (on 2026-10-25/26 it dropped the night watch and the 6 AM digest), so the relay worker's Cron Triggers (`5 * * * *`, `40 3,4 * * *` UTC) post `/tick` to the inbox issue every hour. `commands_run` sees `/tick` (handled in `App._answer`, never sent to the user) and runs `tick()`, or `night()` in the night window. GitHub cron remains as a backup.
- `commands`: started by a relayed Telegram message or the relay's `/tick` (see below). If it lands in the night window it does `night()` instead. GitHub keeps only one pending run per concurrency group, so a commands run can replace a queued night run, and this keeps the night watch from being lost.
- All runs share concurrency group `flightwatch` (never parallel), so writes to the state branch never conflict.

**Health** (`runner.py` `_check_ok`/`_check_failed`, `runtime.health`): every failed check counts toward `fail_streak`. That includes layout errors, HTTP 5xx/404, network errors, and an empty result for a future date when the same weekday had flights a week earlier. Any good check resets it.
- Bot blocks count too, but at most one strike per `BLOCK_STRIKE_MINUTES` (45), using `health.last_block`. A burst of blocks in one night watch is one strike, so the alarm takes blocks across about 3 hourly runs.
- `health.blocked` marks a streak whose latest failure was a block, so the alarm suggests running from home instead of fixing the parser.
- The first block each day still sends its own short note (`block_notified`).
- At `HEALTH_ALERT_AFTER` (3) in a row, it sends a Telegram alert (at most once a day) and `__main__` exits 1, so the GitHub run goes red and GitHub emails the owner. Recovery sends one "working again" message.
- The digest, `/status` and the dashboard banner (`dashboard.json` `health`) show it while it's failing.
- Every failure writes `.state/debug/last_failure.html` plus `last_failure.json` (error, URL, time). A good page with nonstops is kept weekly as `debug/sample_ok.html`. Fixing a redesign means taking those from the `state` branch, dropping the new page into `tests/fixtures/`, and updating the parser until `test_frontier` passes.

**History** (`tracker.record`): turns each poll into per-flight records keyed `"YYYY-MM-DD|ORD-IAH|F9 1234"`.
- Every transition time (`opened_at`, `sold_out_at`) is stored with the previous check's time (`opened_prev`, `sold_out_prev`), so messages say "opened between X and Y". `opened_prev = None` means it was already open at the first check.
- Per route and date, `days.json` tracks the `isGoWildOutOfRange` true→false transition as a second release signal.

**State** (`state.py`, `scripts/state.sh`): JSON files in `.state/`, cloned from and pushed back to the orphan **`state` branch** on every run, even when the run fails.
- `settings.json` holds routes (`notify`, `depart_after`/`depart_before` "HH:MM"), the timezone, the digest and `nightly_alert`. These are changed only through bot commands.
- `runtime.json` holds alerts, the Telegram offset, `digest_sent` and the block log.
- `flights.json`, `days.json` and `observations/YYYY-MM.jsonl` hold the history (observations are raw and append-only).
- `debug/` holds raw Frontier pages: the latest failure and a weekly good sample.

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

**Dashboard** (`dashboard.py`, `docs/index.html`): after every run, `__main__` calls `dashboard.write`, which writes `.state/dashboard.json` as `{generated_at, days:{columns,rows}, checks:{columns,rows}}`.
- **days:** one row per flight-date. Flight labels look like `F9 1882 · IAH → ORD · 11:36 AM → 2:25 PM`. Times are local wall time `YYYY-MM-DD HH:MM`, and "Release known" is false when the flight was already open at the first check.
- **Outcome:** Open now / Open at departure / Sold out / Never opened (only when watched from before the release night) / No seats seen / Not open yet.
- **checks:** every observation for the last 14 departure dates. "Seats left" is null when the flight is open but Frontier showed no count.
- **The page:** `docs/index.html` is a standalone GitHub Pages page (d3 from cdnjs). It fetches the JSON from `raw.githubusercontent.com/adambabin/flight-watcher/state/dashboard.json`.
- **Testing the page:** render it with Playwright, routing that URL and d3 to local files (cdnjs is blocked in the cloud sandbox; d3 is available from npm).

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
- **#5** Check for site updates that would break this. Built: layout checks, the 3-strike Telegram + red-run alert, failure snapshots and a real-page parser test. A weekly field-drift warning was deferred.
- **#6** Add the updates to a dashboard (User feedback): view each flight's activity over time, e.g. filter to IAH→ORD 11:36 AM and see what time GoWild seats appear each night and when they sell out, day over day and week over week.
  - Dashboard home: **Google Sheets**. Notion was tried first, but its free plan shows only one chart.
  - The mockup is "GoWild Dashboard (SAMPLE mockup)" in the user's Drive: https://docs.google.com/spreadsheets/d/1bWLkpPrWtrwbJJM5HzPuEezgR1D58-ygOzn4gI5-WGk. Edit it with the Google Sheets MCP tools.
    - `Flight days`: one row per flight per departure date, with columns Flight label, Flight #, From, To, Departs, Arrives, Date, Weekday, Released at, Release (min after midnight), Sold out at, Hours open, Max seats seen, Reopened, Outcome.
    - `Seat checks`: one row per check (Flight label, Date, Checked at, Hours since release, Seats left, GoWild open).
    - `Day by day`: FILTER/AVERAGEIFS formulas keyed on `Dashboard!B2`, covering the last 30 days, week-over-week by weekday, and the latest day's seat checks.
    - `Dashboard`: a flight dropdown in B2, a summary line, and 5 charts (release time, open window as a stacked-column Gantt, weekday avg hours open, weekday avg seats, seats-left stepped area).
  - The user wants flights labeled with route and times: `F9 1882 · IAH → ORD · 11:36 AM → 2:25 PM`. The real arrivals are 2:25 PM for F9 1882 and 10:39 AM for F9 3135.
  - Older Notion mockup page (kept for comparison): https://app.notion.com/p/404f4a15b3ac81c096edee5f8a293761. Its SAMPLE databases are `collection://00269479-a49c-4308-a8d4-07ea3902e312` and `collection://04cd853d-1443-4216-afde-bed70b1e2104`.
  - Superseded by the interactive dashboard ticket below. The Sheets and Notion mockups can be deleted once it's live.
- **Interactive flight-history dashboard (live data)** (In progress): https://app.notion.com/p/405f4a15b3ac810ba97de1434c47c91b. The user tracks requests and progress for the dashboard here, so update it as work lands.
  - The real dashboard is the GitHub Pages site `docs/index.html`, at https://adambabin.github.io/flight-watcher/ once Pages is enabled.
  - There's also a claude.ai prototype of the same design, the "Dashboard"-type artifact https://claude.ai/artifact/MhXfXxwBTdroGj5ydFASnE. It reads the sample Google Sheet through the viewer's Google Sheets connector.
- **GoWild seats opened before midnight: widen the night watch** (Bug, Pending testing): https://app.notion.com/p/405f4a15b3ac818e96c3d68854b3b0db. The fix shipped with the 10:40 PM night watch and the hourly 3-day lookahead (PR #11). Confirm the real release time after a week of data.
- **#11 Make the dashboard mobile friendly** (Pending testing): https://app.notion.com/p/406f4a15b3ac804d8c99deda0aa4348f.
  - Done in PR #15: under 40rem, the flight chips become one sticky `<select>` grouped by route.
  - Tooltips pin on tap (`tips()` with `pinned` state that survives redraws) and clear when tapping elsewhere.
  - The seats chart scrubs to the nearest check.
  - The table wraps on phones.
  - Test it at iPhone size with Playwright `devices['iPhone 13']`.
- **#12 Release-time chart breaks when seats open days early** (Pending testing): https://app.notion.com/p/406f4a15b3ac814b83efe127ee3d52bc.
  - The page now measures release as hours before the departure date's midnight (`hoursBefore`, `relDay` in `docs/index.html`): 24 h is the official release.
  - The chart's y-axis is in days/hours.
  - The tiles and the takeaway say "11:05 AM, 3 days before departure".
  - `dashboard.json`'s "Release (min after midnight)" is no longer used by the page.
- **#10 GitHub skipped scheduled runs: no 6 AM report or night watch** (Bug, **Closed** 2026-10-28): https://app.notion.com/p/405f4a15b3ac8121a05de5011e205aa2. Fixed by the Cloudflare clock (PR #12). Verified: the first full night ran the 10:40 PM–12:30 AM watch, the report arrived at 6:06 AM, and hourly checks on Oct 27–28 had no gaps.

## Status (as of 2026-10-28)

Done and live on `main`:
- The tracker (PR #1) and the relay support (PR #3).
- Owner-only inbox commands (PR #9), the 10:40 PM night watch and Pages dashboard (PR #10), the hourly 3-day lookahead (PR #11), and the Cloudflare clock (PR #12).
- Site-change detection and the failure alarm, ticket #5 (PR #14).
- Mobile dashboard, ticket #11 (PR #15).
- Release chart in days before departure, ticket #12 (PR #16).
- Repeated bot blocks raise the failure alarm (PR #17).
- Secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set, and the bot works: the setup check, commands and `/status` were all answered.
- The user armed `/alert` for Mon Oct 26 flights.

- The relay is live (2026-10-26): Cloudflare Worker `gowild-relay` with secrets `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` and `GITHUB_TOKEN`, webhook set via `/setup`, and `/status` sent from Telegram got a fast reply.
  - `GITHUB_TOKEN` is the fine-grained PAT `gowild-relay` (only `flight-watcher`, Issues: Read and write). It **expires Thu, Oct 14 2027**. Before then, regenerate it on GitHub and replace the worker secret, or the relay stops forwarding and replies fall back to scheduled runs.
  - The PAT's "Generate token" confirmation looks like it does nothing (mobile and desktop) but the token does get created. Its value is shown only once, so if it's lost, use "Regenerate token".
- The Cloudflare clock is live (2026-10-26): the user deployed the new `relay/worker.js` and added Cron Triggers `5 * * * *` and `40 3,4 * * *`.
  - Verified: the 01:05 UTC trigger started issue_comment run 40430493952 about 39 s later, and it did a full `/tick`: 8 checks over Oct 27–29, both directions.
  - Verified: the first full night on the Cloudflare clock (Oct 27/28) ran the night watch and sent the 6:06 AM report.
  - To check: list the workflow runs. Cloudflare runs show `event: issue_comment` at about :05 past each hour, and GitHub cron runs show `schedule`.
- GitHub Pages is on and serves `docs/` from `main`.

Next steps:
1. Watch for Frontier bot blocks. The first one ever came at 7:06 PM CT on Oct 28, partway through a tick.
   - One block a day is fine.
   - If the failure alarm fires for blocks (about 3 hourly runs in a row), GitHub's runners are probably blocked. Then set up the README's "Running from home".
2. After a few days of 3-day-lookahead data, find when GoWild seats really open, using `flights.json` `opened_prev`/`opened_at` or the dashboard. Then move the night watch (`NIGHT_START`, `HOT_ZONES`, the `40 3,4` triggers) and the `/alert` default date (`next_release_date`) to that time. Early data:
   - Mon Oct 26 ORD→IAH was open by 11:18 PM Sat.
   - Both Tue Oct 27 flights were open by 9:54 PM Sun.
   - Thu Oct 29 ORD→IAH opened between 4:20 and 7:52 AM Mon, about 3 days out.
   - Wed Oct 28 IAH→ORD F9 3136 reopened on the evening of Oct 26.
   - Thu Oct 29 IAH→ORD F9 3136 (5:06 PM) opened between 7:53 and 11:05 AM Mon, about 3 days out.
   - The dashboard's release chart (ticket #12) shows this directly, as days before departure.
3. Ask the user to try the dashboard on their phone and the new release chart; then close tickets #11 and #12.
4. Once the Pages dashboard has real data, delete the sample Google Sheet, the Notion SAMPLE mockups and the claude.ai mockup artifact.

Ideas raised but not done:
- **Cron for other time zones**: only Central midnights are watched closely, so routes from other zones need their own 11:50 PM cron line.
- **Action versions**: `actions/checkout@v4` and `setup-python@v5` trigger a Node 20 deprecation warning. Bumping them is harmless.
