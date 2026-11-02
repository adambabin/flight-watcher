# Set up your own GoWild seat tracker, with Claude walking you through it

**How to use this:** copy everything below the line into a new chat with Claude (the Claude app, claude.ai, or Claude Code) and send it. Claude will ask you a few questions and then guide you one step at a time. Set aside about an hour, and use a computer for the GitHub and Cloudflare parts. Your phone works for the Telegram parts.

The latest version of this page is always at https://github.com/adambabin/flight-watcher/blob/main/SETUP_PROMPT.md

---

You're going to help me set up my own copy of **flight-watcher**, an open-source tracker for Frontier Airlines **GoWild pass** seats. Its public repo is **https://github.com/adambabin/flight-watcher**. I'm not technical, so please:

- **Go one step at a time.** Give me one small step, tell me exactly what to click or type and what I should see afterwards, then wait for me to say it worked before moving on. Number the steps so we can keep our place.
- **Use plain words.** If you must use a technical term, explain it in a few words the first time.
- **Ask for a screenshot** whenever I'm stuck or what I see doesn't match what you described. Websites change their buttons, so adapt to what's actually on my screen.
- **Never ask me to paste a token, password or secret into this chat**, and stop me if I start to. Tokens go only into the GitHub and Cloudflare settings boxes. My Telegram chat ID is fine to share, but I don't need to.
- **Keep a short "setup notes" list** as we go, of things I'll want later: my bot's name, my repo address, my worker address, my inbox issue number, my token's expiry date. Show me the full list at the end. Leave out the secret values themselves.
- If you can read web pages or GitHub (for example in Claude Code), read the repo's `README.md` and `relay/worker.js` for the current details. The repo's `CLAUDE.md` describes the original owner's own setup (their routes, their Notion, their tokens' dates). Use it to understand how things work, but don't apply their personal settings to me.
- If you're Claude Code with access to my fork, you can make code edits for me, but walk me through every click in GitHub, Cloudflare and Telegram. Claude Code's cloud sandbox can't reach flyfrontier.com, so live checks only happen in GitHub Actions.

Everything below is the reference you need. Read it all before starting.

## Part A. What this is and how it works

### What it does
- Every hour, it checks Frontier's website for **GoWild seats** on the nonstop routes I choose, from today through 3 days ahead.
- Each night from **10:40 PM to 12:30 AM** in my time zone, it checks every 2–4 minutes for the date about to open (the "night watch").
- It records **when seats appear and when they sell out**, and messages me on **Telegram**:
  - alerts when seats open (`/alert`, or every night with `/nightly on`)
  - a morning report (6 AM by default)
  - answers to commands like `/status` and `/now`
- It has a **dashboard** website with charts of each flight's history.
- It runs for free on GitHub's servers (GitHub Actions). My computer doesn't need to be on.

### How GoWild seats work (what the tracker is built around)
- Officially, domestic GoWild seats open **the day before departure, around midnight** in the departure airport's time zone. Wednesday's flights open around midnight going into Tuesday, which is late Monday night.
- **In practice, they often open earlier.** The original owner's data shows seats opening before midnight, and sometimes **about 3 days before departure**, e.g. late morning three days out. That's why it checks hourly up to 3 days ahead. The dashboard's release chart shows how many days or hours before departure seats appeared.
- Each flight gets only a few GoWild seats, and they can **reappear later** when someone cancels. An alert fires again if seats sell out and come back.
- **Blackout dates** (holidays) have no GoWild seats at all. The tracker knows the ones Frontier has posted (through April 2027) and won't arm alerts for them.
- The tracker reads Frontier's normal public search page. It never logs in, so it never needs my Frontier password. It's unofficial, not affiliated with Frontier, and could break if Frontier redesigns its site.

### The pieces, and why each exists
1. **GitHub** (free account): holds my copy of the code (a "fork"), runs the checks (GitHub Actions), keeps the history (a branch called `state`), and hosts the dashboard (GitHub Pages).
2. **Telegram** (free app): a bot I create sends me the alerts and reads my commands.
3. **Cloudflare** (free account): a small "relay" program (a Worker) does two jobs:
   - It passes my Telegram messages to GitHub instantly. Without it, replies wait for the next hourly check.
   - It acts as the **clock** that starts the hourly checks and the night watch. GitHub's own built-in schedule turned out to be unreliable: it skipped the night watch and the morning report entirely on some nights, so the original owner moved the clock to Cloudflare. GitHub's schedule stays on as a backup, and duplicate runs are harmless.

How a message travels: I text the bot → Telegram sends it to my Cloudflare worker → the worker posts it as a comment on an issue in my GitHub repo called "Telegram inbox" and reacts 👀 → that comment starts a GitHub run → the run answers me on Telegram and deletes the comment. This takes about 30–60 seconds.

### Privacy: please tell me this clearly before we start
- My fork will be **public** (it has to be: free unlimited GitHub Actions minutes only apply to public repos, and a private repo would run out of free minutes within days).
- That means **anyone could see the routes I track and the seat history** on my repo's `state` branch and dashboard. It does **not** show my name, my bookings or anything personal. My Telegram token, chat ID and GitHub token are stored as secrets, which are never visible to anyone.
- Don't commit personal information (names, phone numbers, trip plans) into the repo.
- Ask me to confirm I'm OK with this before we start.

## Part B. Questions to ask me first

Ask these together, in one message:
1. Do I already have accounts for **GitHub**, **Telegram** and **Cloudflare**? (If not, we'll create them. All are free.)
2. Which **routes** do I want to track? I need airport codes, e.g. DEN → LAS. Do I want both directions? (Each direction is its own route.) Frontier nonstops only. Keep it to a few routes: each one adds requests to Frontier, and more requests make it likelier that Frontier's bot protection blocks the tracker.
3. What **time zone** am I in: Eastern, Central, Mountain, Arizona, Pacific, Alaska or Hawaii? (This is when the night watch and morning report run.)
4. Do I only care about flights in certain **departure-time windows**, e.g. only after 5 PM? What time do I want the **morning report**? (Default 6 AM, or off.)
5. Do I want an alert **every night** when seats open, or only when I ask?
6. Do I have a computer at home that's **always on** (Mac, Linux or a Raspberry Pi)? It's only needed for a fallback if Frontier ever blocks GitHub's servers. Most people won't need it.

Then give me a short overview of the phases below, with time estimates, and start Phase 1.

## Part C. The setup, phase by phase

Use the exact names shown in `code font`. They're case-sensitive, with no spaces and no quotes.

### Phase 1. Create accounts (skip any I have), about 10 min
- GitHub: https://github.com/signup. Note my **GitHub username**, because it appears in my repo and dashboard addresses.
- Telegram: install the app on my phone and sign up.
- Cloudflare: https://dash.cloudflare.com/sign-up (free plan; no credit card needed for Workers).

### Phase 2. Copy ("fork") the repo, about 3 min
1. Signed in to GitHub, open https://github.com/adambabin/flight-watcher and click **Fork** (top right).
2. Leave the name `flight-watcher`. Make sure **"Copy the `main` branch only" stays CHECKED.** This matters: unchecked, I'd copy the original owner's history and settings.
3. Click **Create fork**. My repo is now `https://github.com/<my-username>/flight-watcher`. Add it to the setup notes.
- **If I unchecked it by mistake:** go to my fork → the branch dropdown → **View all branches**, and delete the branch named `state` (trash-can icon). The tracker creates a fresh one on its first run.

### Phase 3. Create the Telegram bot, about 5 min
1. In Telegram, search for **@BotFather** (blue check mark), open it, tap **Start**, and send `/newbot`.
2. Give it a display name (anything, e.g. "My GoWild Watch"), then a username that **ends in `bot`** and isn't taken (e.g. `jane_gowild_bot`).
3. BotFather replies with a **token** that looks like `123456789:AAH...`, a number, a colon, then letters. **Copy the whole thing including the number and colon.** Keep it private: anyone with it controls the bot. If it ever leaks, send BotFather `/revoke` to get a new one, then update it everywhere we put it.
4. Open my new bot (tap the link BotFather gives), tap **Start**, and send it a message like `hi`. **This step is required:** the bot can't message me until I've messaged it.
5. Find my **chat ID**: on a computer, open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser, replacing `<TOKEN>` with my token (no `<` `>`, and keep the word `bot` in front of the token).
   - Look for `"chat":{"id":` followed by a number, e.g. `"chat":{"id":987654321`. That number is my chat ID.
   - `{"ok":true,"result":[]}` (empty): send the bot another message and refresh the page.
   - `{"ok":false,"error_code":401,"description":"Unauthorized"}`: the token was copied wrong.
   - `"error_code":409 ... webhook`: a webhook is already set (that only happens after Phase 8). Open `https://api.telegram.org/bot<TOKEN>/deleteWebhook`, retry, and later redo the worker's `/setup` step.
   - Use the number from my **private chat** with the bot. A negative number means a group: use my private chat instead.

### Phase 4. Give GitHub the two Telegram secrets, about 3 min
In my fork: **Settings** (the repo's settings tab, not my profile settings) → **Secrets and variables** → **Actions** → **Secrets** tab → **New repository secret**. Add two:
- Name `TELEGRAM_BOT_TOKEN`, value: the whole bot token
- Name `TELEGRAM_CHAT_ID`, value: just the number

Common mistakes: extra spaces, quotes around the value, a missing number-and-colon at the start of the token, or the names typed differently.

### Phase 5. Turn on GitHub Actions and run the setup test, about 5 min
1. Open my fork's **Actions** tab. GitHub turns Actions off on new forks, so click **"I understand my workflows, go ahead and enable them"**.
2. Click the **GoWild watch** workflow on the left. If it says scheduled runs are disabled, click **Enable workflow**.
3. Click **Run workflow** (right side) → Branch `main`, mode **`check`** → the green **Run workflow** button.
4. Refresh after a few seconds. A run appears. Within about 1–2 minutes it should turn ✅ green, and Telegram should get a **🛠 Setup check** message listing tomorrow's flights.
   - **It will show ORD ⇄ IAH flights.** That's normal: those are the starter routes from the original repo. We change them in Phase 10.
   - ✅ in the message means it can read Frontier. 🎉
   - ❌ with **HTTP 403, 405, 406 or 429**, or "blocked/captcha": Frontier's bot protection refused GitHub's server this time. Wait 30–60 minutes and run it again. If it keeps failing over several hours, see Phase 12.
   - Run went **red ❌ and no Telegram message**: click the run → the `watch` job → expand the red step, and send Claude a screenshot. Usually a secret is misnamed or wrong (Phase 4).
   - **Green run but no message**: the chat ID is wrong, or I never pressed Start in the bot (Phase 3, step 4).

### Phase 6. Create the "Telegram inbox" issue, about 3 min
1. Forks start with Issues turned off. In my fork: **Settings** → **General** → scroll to **Features** → check **Issues**.
2. Open the **Issues** tab → **New issue** → title `Telegram inbox` (body can be empty) → **Create**.
3. Note its **number** (shown as `#1`, usually 1 on a new fork). Add it to the setup notes.
4. Tell GitHub the number: **Settings** → **Secrets and variables** → **Actions** → **Variables** tab (not Secrets) → **New repository variable** → Name `INBOX_ISSUE`, Value: the number only (e.g. `1`, no `#`).
- Don't delete, lock or rename this issue later. Closed is fine, but leaving it open is simplest. Comments will appear and vanish on it, which is normal. Comments by anyone other than me are ignored, so strangers can't control my bot.

### Phase 7. Make a GitHub token for the relay, about 5 min
This lets the Cloudflare worker post comments to my inbox issue, and nothing else.
1. GitHub, top-right profile picture → **Settings** (my account settings this time) → bottom of the left menu: **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
2. Fill in:
   - Name: `gowild-relay`
   - **Expiration:** the longest allowed (custom, up to 1 year). **Put the expiry date in my calendar** with a reminder a week before, and in the setup notes.
   - **Repository access:** **Only select repositories** → my `flight-watcher` fork.
   - **Permissions:** Repository permissions → **Issues** → **Read and write**. ("Metadata: Read" is added automatically. Leave everything else alone.)
3. Click **Generate token** and confirm. **Quirk:** the confirmation sometimes looks like nothing happened, but the token was created. Check the token list before making another.
4. **Copy the token now** (it starts with `github_pat_`). GitHub shows it only once. If it's lost, open the token and click **Regenerate token**, then use the new value.

### Phase 8. Create the Cloudflare relay worker, about 10 min
1. Cloudflare dashboard → **Workers & Pages** (under Compute in the left menu) → **Create** → **Start with Hello World** (or "Create Worker") → name it `gowild-relay` → **Deploy**.
2. Click **Edit code**. Delete everything in the editor and paste the full contents of `relay/worker.js`, opened in raw form: `https://raw.githubusercontent.com/<my-username>/flight-watcher/main/relay/worker.js` (select all, copy). Click **Deploy**.
3. Go back to the worker → **Settings** → **Variables and secrets** → **Add**, five times:

   | Type | Name | Value |
   |---|---|---|
   | Secret | `TELEGRAM_BOT_TOKEN` | the bot token |
   | Secret | `TELEGRAM_CHAT_ID` | my chat ID number |
   | Secret | `GITHUB_TOKEN` | the `github_pat_...` token from Phase 7 |
   | Text | `GITHUB_REPO` | `<my-username>/flight-watcher` (just that, no https://) |
   | Text | `INBOX_ISSUE` | my inbox issue number, e.g. `1` |

   Click **Deploy** or **Save** when Cloudflare offers it, so the settings take effect.
4. Note the worker's address, something like `https://gowild-relay.<something>.workers.dev`, shown on the worker's overview page. Add it to the setup notes.
5. Connect the bot: open `https://gowild-relay.<something>.workers.dev/setup` in a browser.
   - **"Done! Send your bot /status to try it."** means it worked.
   - **"Missing settings: …"** names a variable that's missing or misnamed (step 3). Fix it, deploy, and reload `/setup`.
   - **"Telegram said: Unauthorized"**: `TELEGRAM_BOT_TOKEN` in Cloudflare is wrong.
   - Visiting the worker's plain address (without `/setup`) shows "GoWild relay is running." That's normal.
6. **Test:** send the bot `/status`.
   - Within a second or two, my message should get a 👀 reaction (meaning the relay received it and posted it to GitHub).
   - About 30–60 seconds later, the bot replies with my settings.
   - See the troubleshooting table in Part E if either doesn't happen.

### Phase 9. Make Cloudflare the clock, about 3 min
1. First, send the bot `/timezone <my zone>` (e.g. `/timezone mountain`; choices are eastern, central, mountain, arizona, pacific, alaska, hawaii). It replies with a line like `40 4,5 * * *`. That's the night-watch time for my zone, written in UTC, which is what Cloudflare uses. Central is `40 3,4 * * *`.
2. Cloudflare → my worker → **Settings** → **Triggers** (or "Trigger events") → **Cron Triggers** → **Add**, twice:
   - `5 * * * *` (every hour at 5 past)
   - the night line the bot gave me (e.g. `40 4,5 * * *`)
3. Why two hours in the night line: daylight saving time. One of the two fires at 10:40 PM local, and the other an hour off, where it just does a normal check. That's harmless.
4. **Verify** after the next :05: my fork's **Actions** tab should show a new GoWild watch run marked `issue_comment` (rather than `schedule`), within about a minute of :05. That run is Cloudflare's clock working. The comment it posts says `/tick`, and the run deletes it; I never get a message for it.
- The repo's file `.github/workflows/watch.yml` has GitHub's own backup schedule, set for Central time. **For any time zone, leave it alone**: Cloudflare is the real clock, and in other zones the backup just runs as an ordinary check. (Editing that file makes future "Sync fork" updates conflict.)

### Phase 10. Set my routes and preferences (all by Telegram), about 5 min
Send these to the bot one at a time, waiting for each reply (about 30–60 s each):
- Remove the starting routes: `/remove ORD-IAH`, then `/remove IAH-ORD`
- Add mine, each direction separately: e.g. `/add DEN-LAS`, `/add LAS-DEN`
- Optional departure windows: `/times DEN-LAS after 5pm`, `/times LAS-DEN 6am-2pm`, `/times DEN-LAS before 9am`, or `/times DEN-LAS any`
- Morning report: `/digest 6:00`, `/digest 7am` or `/digest off`. It arrives with the first check at or after that time, so about 6:05.
- Nightly alerts: `/nightly on` (every night) or arm one: `/alert`, `/alert fri`, `/alert 12/14`, `/alert DEN-LAS fri`
- Check everything: `/status`. Try `/now` for a live check of today's and tomorrow's flights.

Airport codes must be Frontier stations with **nonstop** service on that route. If `/now` shows no flights for a route on several days, the route may not exist or may not run on those days. Check flyfrontier.com.

### Phase 11. Turn on the dashboard, about 3 min
1. My fork → **Settings** → **Pages** → Build and deployment → Source: **Deploy from a branch** → Branch **main**, folder **/docs** → **Save**.
2. After a minute or two, it's live at `https://<my-username>.github.io/flight-watcher/`. Bookmark it on my phone and add it to the setup notes.
3. It reads my own repo's data automatically. It will be **empty or sparse at first**: it fills in as the tracker records flights over the next days. Data can lag up to about 5 minutes (GitHub caches it). Pull-to-refresh or reload.
4. On it: pick a flight (each is labeled like `F9 1234 · DEN → LAS · 7:40 AM → 9:05 AM`), and see when seats opened each night, how long they stayed open, week-over-week by weekday, and seat counts. Tap a chart to pin its details. It works on phones.

### Phase 12. (Only if needed) Run it from a home computer
Only do this if Frontier keeps blocking GitHub's servers: a "Frontier checks are failing" alert that mentions blocking, and red runs for 3+ hours in a row.
1. On an always-on Mac or Linux computer (Raspberry Pi works), install Python 3.11+ and git, then in Terminal:
   ```
   git clone https://github.com/<my-username>/flight-watcher.git
   cd flight-watcher
   pip3 install -r requirements.txt
   export TELEGRAM_BOT_TOKEN='...' TELEGRAM_CHAT_ID='...'
   python3 -m flightwatch check --state ~/.flightwatch
   ```
   If `pip3` refuses with "externally managed environment", make a private Python first: `python3 -m venv .venv`, then use `.venv/bin/pip` and `.venv/bin/python` in place of `pip3` and `python3` here and below.
2. If the setup check works, schedule it: run `crontab -e` and add the lines below. The computer's clock must be in my time zone. The token values go in place of `...`, and on a Mac, cron also needs Full Disk Access for Terminal.
   ```
   TELEGRAM_BOT_TOKEN=...
   TELEGRAM_CHAT_ID=...
   40 22 * * *  cd ~/flight-watcher && python3 -m flightwatch auto --state ~/.flightwatch
   5 * * * *    cd ~/flight-watcher && python3 -m flightwatch auto --state ~/.flightwatch
   ```
3. Stop the GitHub copy so the two don't both answer:
   - GitHub → Actions → GoWild watch → **⋯** → **Disable workflow**
   - remove the Cloudflare Cron Triggers
   - open `https://api.telegram.org/bot<TOKEN>/deleteWebhook`, so Telegram messages wait for the home computer's next check
   - The home copy keeps its own history and doesn't update the dashboard. Replies take up to an hour.
4. If the computer must restart, the schedule continues afterwards. The `/timezone` setting lives in the home copy separately: send `/timezone …` again once it's running.

### Finish
Show me my setup notes. Remind me:
- the token expiry date and what to do then (Part E)
- to try `/alert` tonight
- to check the dashboard in a few days

## Part D. Using it day to day

### Commands
| Command | What it does |
|---|---|
| `/now` | Check Frontier right now: today's and tomorrow's flights |
| `/status` | Routes, windows, report time, time zone, armed alerts, last check, any problems |
| `/alert` | Ping me when the next release opens (tonight's). The reply says when to expect it. |
| `/alert wed` · `/alert 12/14` · `/alert DEN-LAS fri` | A specific **travel** date and/or route |
| `/alerts` · `/cancel all` · `/cancel wed` · `/cancel #3` | List or cancel alerts |
| `/nightly on` / `off` | Alert every night without arming |
| `/pause DEN-LAS` · `/resume DEN-LAS` · `/pause all` | Mute a direction (still tracked, just no messages) |
| `/times DEN-LAS 6am-2pm` · `after 5pm` · `before 9am` · `any` | Only report flights departing in that window |
| `/add DEN-LAS` · `/remove DEN-LAS` | Track or stop a route (history is kept) |
| `/digest 6:00` · `/digest off` | Morning report time |
| `/timezone mountain` | Home time zone; replies with the Cloudflare night line |
| `/history` · `/history DEN-LAS` | Recent release and sell-out times |
| `/help` | All commands |

**Dates always mean travel dates.** `/alert wed` means Wednesday's flights, whose seats open around midnight going into Tuesday (or earlier). An alert stays armed until its travel date passes. It pings when seats open, and again if they sell out and later reopen. If nothing opened during the night watch, it sends a short "no seats" note.

### What the messages mean
- **"GoWild opened between 11:52 PM and 11:56 PM"**: seats appeared between two checks. Sell-outs are known to within about an hour.
- **"GoWild was already open at our first check"**: seats were open before the tracker first looked, so the exact release time is unknown.
- **Morning report**: flights released overnight (flight, times, seats left, when they opened), plus how today's flights are doing.
- **Times** are in the departure airport's time zone, with the weekday added if it's a different day.
- **A short note that Frontier blocked a check** (at most once a day; the morning report may also mention blocked checks): normal now and then. Nothing to do.
- **"Frontier checks are failing"** alarm: 3+ failed checks in a row. GitHub also marks runs red and emails me. If it says the checks are being **blocked**, see Phase 12. If it's a page/layout error, Frontier probably redesigned their site and the code needs a fix (Part E, "Getting updates"). I get a "working again" message when it recovers.

## Part E. Troubleshooting and FAQ

### The bot doesn't answer
| What I see | Likely cause | Fix |
|---|---|---|
| No 👀 at all | The webhook isn't set, or the worker's chat ID doesn't match mine (it silently ignores other chats) | Re-open `<worker>/setup`; recheck `TELEGRAM_CHAT_ID` in Cloudflare; make sure I'm messaging my own bot in my private chat |
| Bot says **"Couldn't pass that on to GitHub (HTTP 401)"** | GitHub token wrong or **expired** | Regenerate it (Phase 7) and replace `GITHUB_TOKEN` in Cloudflare |
| … **(HTTP 403)** | Token lacks Issues: Read and write, or isn't scoped to my fork | Edit the token's permissions and repository access |
| … **(HTTP 404)** | `GITHUB_REPO` or `INBOX_ISSUE` in Cloudflare is wrong, or Issues is turned off | Fix the values (`username/flight-watcher`, issue number only); check Issues is on |
| 👀 appears but no reply after 2+ min | The GitHub run was skipped or failed | Open the Actions tab and look at the newest run. **Skipped** (grey) means the `INBOX_ISSUE` *GitHub variable* doesn't match the issue (Phase 6). **Red** means open it and screenshot the failed step. **No run at all** means Actions is disabled (Phase 5). Unanswered comments stay on the inbox issue and get answered by the next run. |
| Replies slow during the night | The night watch is running; it answers between checks | Wait up to 4 minutes |
| Reply takes 1–3 min sometimes | GitHub is slow starting a run, or one run is queued behind another (only one runs at a time) | Normal |

### Checks and schedule
- **No hourly runs in Actions:** check the Cloudflare Cron Triggers exist (Phase 9) and that the relay still works (`/status`). GitHub's backup schedule often runs late or skips runs, which is exactly why Cloudflare is the clock.
- **The night watch didn't run:** the night Cron Trigger must match my time zone (`/timezone` tells me the line). Runs that start after 12:20 AM do a normal check instead.
- **Two runs at once, or extra runs:** harmless. They queue and never collide.
- **GitHub emailed me "Run failed":** one-offs (a block, a network hiccup) are normal. Several in a row come with a Telegram alarm, so act on that.
- **GitHub says scheduled workflows were disabled for inactivity** (public repos after 60 days without activity): Actions → GoWild watch → **Enable workflow**. The Cloudflare clock isn't affected.
- **Telegram "409 Conflict" in run logs:** expected once the relay is set up. Ignore it.

### Data and dashboard
- **Dashboard empty or "couldn't load":** Pages must be on (Phase 11), and at least one run must have finished since. Wait 5 minutes and reload. The address must be `https://<my-username>.github.io/flight-watcher/` exactly.
- **Where's the raw data?** On my fork's `state` branch: `flights.json` (each flight's open/sell-out history), `observations/` (every check), `settings.json` (my settings), `dashboard.json`. Don't edit these by hand: change settings with bot commands.
- **A flight shows "Never opened" or "No seats seen":** GoWild seats never appeared for that flight and date. That's common on busy days.

### Getting updates from the original repo
- When the original repo gets fixes (e.g. after a Frontier site change): my fork's main page → **Sync fork** → **Update branch**. My settings and history are on the `state` branch and aren't touched.
- If an update changes `relay/worker.js`, re-paste it into Cloudflare (Phase 8, step 2) and deploy. My Cloudflare variables stay.
- If Sync fork reports a conflict, it's almost always because I edited a file. Ask Claude to help; usually the answer is "Discard commits" and redoing my edit.

### Upkeep
- **Token expiry** (date in my notes): before then, GitHub → Developer settings → Fine-grained tokens → `gowild-relay` → **Regenerate token** → copy it → Cloudflare worker → Settings → Variables and secrets → edit `GITHUB_TOKEN` → paste → deploy. If I forget: the bot says HTTP 401, and the hourly clock silently stops (GitHub's backup schedule keeps things limping along).
- **New blackout dates:** they live in `flightwatch/rules.py`. They arrive via Sync fork when the original repo adds them.
- **Pausing for a while:** `/pause all`, or disable the workflow in Actions. **Stopping for good:** disable the workflow, delete the Cloudflare worker, and delete the fork (Settings → bottom → Delete this repository).

### Good habits
- Keep only a few routes: every route adds requests, and Frontier's bot protection gets suspicious of lots of traffic.
- Never share the bot token or GitHub token. If one leaks, revoke or regenerate it and update it where it's stored (GitHub secrets, Cloudflare).
- This tells me when seats are open. Booking is still on flyfrontier.com or the Frontier app with my GoWild pass, and seats can go fast, so book quickly after an alert.
