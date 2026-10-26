# flight-watcher

Tracks Frontier **GoWild pass** seats on nonstop flights (ORD ⇄ IAH to start) and talks to you on Telegram:

- **Midnight watch**: checks every couple of minutes from 11:50 PM to 12:15 AM Central, so it records when GoWild seats are actually released.
- **Release alerts**: `/alert` before bed and you get a ping the moment seats open (or a note that none did).
- **6 AM report**: flights released overnight (flight number, times, seats left, when they opened) plus how today's flights are doing.
- **History**: when each flight's GoWild seats opened, sold out, or reopened, kept as JSON on the `state` branch.
- **Settings from your phone**: pause a direction, set a departure-time window, add routes, change the report time.

## How GoWild works (what this is built around)

- Each GoWild flight costs a $0.01 fare plus taxes and fees, about $15 for a domestic nonstop. Bags and seats are extra.
- **Domestic GoWild fares open the day before departure**, usually right around **12:00 AM in the departure airport's time zone**. So Wednesday's ORD→IAH seats show up at midnight going into Tuesday, which is late Monday night. More seats can appear during the day when people cancel. International flights open 10 days out (not tracked here).
- Frontier releases only a handful of GoWild seats per flight, and they're confirmed bookings, not standby.
- **Blackout dates** have no GoWild fares at all, for example Nov 24–25, Nov 28–30, Dec 19–24 and Dec 26–31, 2026. They're in `flightwatch/rules.py`, posted through April 2027. Add new ones when Frontier posts them.
- Booking earlier than the window, or on blackout days, has sometimes been offered for an extra fee ($29–$89 early booking, $79–$159 peak day) during promotions.

These rules come from Frontier's GoWild page and FAQ plus third-party guides. Frontier doesn't publish an exact release time, and finding it out is part of what this tracker does.

## How it gets the data

Frontier has no public API. Its normal flight-search page, the one anyone sees logged out, embeds JSON with every flight's GoWild status, price and "N seats left" text. No pass login is needed, so no Frontier credentials are stored anywhere. The site uses DataDome bot protection, so the tracker makes one request at a time, 4–7 seconds apart, with a Chrome-like TLS fingerprint (`curl_cffi`).

**Not affiliated with Frontier.** This is unofficial and could break if Frontier changes its site.

## Setup (about 10 minutes)

1. **Create the bot.** In Telegram, message [@BotFather](https://t.me/BotFather), send `/newbot`, and follow the prompts. Copy the token it gives you.
2. **Find your chat ID.** Send your new bot any message, such as "hi". Then open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy the number in `"chat":{"id":…}`.
3. **Add two repo secrets.** In GitHub, go to Settings → Secrets and variables → Actions → New repository secret. Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
4. **Merge this into `main`.** GitHub only runs scheduled workflows from the default branch.
5. **Test it.** Go to Actions → *GoWild watch* → *Run workflow* → mode `check`. Within a minute or two you should get a 🛠 *Setup check* message listing tomorrow's flights.
   - ✅ means it's working, and scheduled runs take over from here.
   - ❌ with HTTP 403/405/406 means Frontier is blocking GitHub's servers. See [Running from home](#running-from-home).

## Telegram commands

| Command | What it does |
|---|---|
| `/alert` | Ping me when the next release opens (tonight's midnight) |
| `/alert wed`, `/alert 10/29`, `/alert ORD-IAH fri` | Alert for a specific travel date and/or route |
| `/alerts`, `/cancel all`, `/cancel wed` | List or cancel alerts |
| `/nightly on` / `off` | Alert every night, no need to arm it |
| `/pause IAH-ORD`, `/resume IAH-ORD` | Mute a direction. It's still tracked, just not reported. |
| `/times ORD-IAH 6am-2pm`, `after 5pm`, `before 9am`, `any` | Only report flights departing in that window |
| `/add ORD-DEN`, `/remove ORD-DEN` | Track another route (nonstops only) |
| `/digest 6:00`, `/digest off` | Morning report time |
| `/history`, `/history IAH-ORD` | Recent release and sell-out times |
| `/now` | Check Frontier right now: today's and tomorrow's flights |
| `/status` | Current settings and armed alerts |

**Dates mean travel dates.** `/alert wed` means Wednesday flights. Their seats open around midnight going into Tuesday, and the bot's reply always says when to expect them.

**How fast the bot answers:** once the relay below is set up, your message gets a 👀 reaction right away and a reply in about 30–60 seconds. That's how long GitHub takes to start a run. Without the relay, messages wait for the next scheduled check, which can be up to about 3 hours. `/now` checks Frontier on the spot.

An alert stays armed until its travel date passes. It pings when seats open, and again if they sell out and later reopen.

## Fast replies: the Telegram relay (optional, about 10 minutes)

Telegram can't start a GitHub run by itself. A tiny free Cloudflare Worker (`relay/worker.js`) bridges the two:

1. Telegram sends your message to the worker.
2. The worker posts the message as a comment on the [Telegram inbox](../../issues/2) issue and reacts 👀.
3. That comment starts the workflow, which answers your message and deletes the comment.

**Setup:**

1. **GitHub token.** Go to GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token.
   - **Repository access:** Only select repositories → `flight-watcher`.
   - **Permissions:** Repository permissions → **Issues: Read and write**.
   - Copy the token.
2. **Cloudflare worker.** Sign up free at [dash.cloudflare.com](https://dash.cloudflare.com).
   - Go to **Workers & Pages → Create → Start with Hello World → Deploy**.
   - Choose **Edit code**, replace everything with the contents of `relay/worker.js`, and **Deploy**.
3. **Worker settings.** In the worker, go to **Settings → Variables and secrets** and add three, each as type *Secret*:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `GITHUB_TOKEN` (the token from step 1)
4. **Connect the bot.** Open `https://<your-worker>.workers.dev/setup` in a browser. It should say *Done!*. Then send `/status` to the bot.

**To undo:** open `https://api.telegram.org/bot<TOKEN>/deleteWebhook`. The tracker falls back to reading Telegram directly at each scheduled check.

**Cost:** each command run uses about 1 Actions minute.

## Schedule

The repo is **public**, so GitHub Actions minutes are free and unlimited. Your secrets (bot token, chat ID) stay private in GitHub's secret store and never appear in code or logs.

| When (Central) | What |
|---|---|
| 10:40 PM – 12:30 AM | **Night watch:** checks the date about to open every 4 minutes, and every 2 minutes from 10:57–11:12 PM (midnight Eastern) and 11:57 PM–12:12 AM (midnight Central). GoWild seats have shown up before midnight Central. |
| Every hour at :05 | Checks flights from today through 3 days out. Seats have opened well before the night before, so this finds when they really appear. It also answers commands and sends the 6 AM report. |

**Sell-out times** are known to within about an hour ("sold out by 10:05 AM").

**Late starts:** GitHub can start scheduled runs a few minutes late. If the night watch starts after the seats are already open, the history says "already open at first check" instead of guessing a release time.

**Other time zones:** only Central-time nights are watched closely. A route departing from another time zone is still checked hourly. To catch its exact release, add a cron line for that zone's 10:40 PM.

## Dashboard (GitHub Pages)

`docs/index.html` is an interactive dashboard. It has:
- **A flight picker:** each flight labeled with route and times, e.g. "F9 1882 · IAH → ORD · 11:36 AM → 2:25 PM".
- **Open-window bars** for each night.
- **Release times:** what time seats appeared each night.
- **Week-over-week bars:** tap a weekday to filter the page to it.
- **Seat counts** through one departure.
- **A day-by-day table.**

After every run, the tracker writes `dashboard.json` to the `state` branch, and the page reads it from `raw.githubusercontent.com`, so it's always current (GitHub caches the file for up to ~5 minutes).

**Turn it on once:** go to repo Settings → Pages → Build and deployment → Source: **Deploy from a branch** → Branch: **main**, folder **/docs** → Save. The site appears at https://adambabin.github.io/flight-watcher/.

## Where the data lives

Every run commits to the **`state` branch**:

- `settings.json`: routes, windows, report time
- `flights.json`: per flight and date, when GoWild opened (`opened_prev` → `opened_at` brackets the moment), sold out, reopened, plus a seat-count timeline
- `days.json`: per route and date, when the booking window opened
- `observations/YYYY-MM.jsonl`: every raw check, for your own analysis
- `runtime.json`: armed alerts, Telegram bookkeeping
- `dashboard.json`: what the Pages dashboard draws

## Running from home

If Frontier blocks GitHub's servers, run the same code on any always-on Mac, Linux box or Raspberry Pi:

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=...
python -m flightwatch check --state ~/.flightwatch     # setup test
```

Then add crontab entries, with the machine's clock on Central time:

```
50 23 * * *  cd /path/to/flight-watcher && python -m flightwatch auto --state ~/.flightwatch
5 */3 * * *  cd /path/to/flight-watcher && python -m flightwatch auto --state ~/.flightwatch
5 6 * * *    cd /path/to/flight-watcher && python -m flightwatch auto --state ~/.flightwatch
```

## Development

```bash
pip install -r requirements.txt pytest
python -m pytest
python -m flightwatch search ORD IAH 2026-10-28    # raw parsed result for one route/date
```

Code map: `frontier.py` reads Frontier's page. `tracker.py` turns checks into opened/sold-out history. `runner.py` holds the tick and night-watch logic. `commands.py` and `messages.py` are the Telegram side. `rules.py` has blackout dates.
