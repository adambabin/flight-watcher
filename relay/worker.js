// Telegram -> GitHub relay (Cloudflare Worker).
//
// Telegram can't start a GitHub Actions run by itself, so this tiny worker sits in
// between: Telegram pushes each message here (webhook), the worker posts it as a
// comment on the "Telegram inbox" issue, and that comment starts the GoWild watch
// workflow, which answers within about a minute. The worker reacts 👀 right away so
// you know the message arrived.
//
// Settings (Cloudflare: Worker -> Settings -> Variables and secrets):
//   TELEGRAM_BOT_TOKEN  the bot token from BotFather                       (Secret)
//   TELEGRAM_CHAT_ID    your chat id (only your messages are passed on)    (Secret)
//   GITHUB_TOKEN        fine-grained token, this repo only, Issues: read and write (Secret)
//   GITHUB_REPO         your repo, e.g. yourname/flight-watcher            (Text)
//   INBOX_ISSUE         the number of your "Telegram inbox" issue, e.g. 1  (Text)
//
// After deploying, open https://<your-worker>.workers.dev/setup once to point the bot at it.
//
// It is also the tracker's clock: GitHub's own schedule drops and delays runs, so add
// Cron Triggers to this worker (Settings -> Triggers -> Cron Triggers, times in UTC):
//   5 * * * *       every hour
//   40 3,4 * * *    10:40 PM Central, the night watch (the pair covers daylight time).
//                   Other time zones: send the bot /timezone <zone> and it tells you the line.
// Each one posts "/tick" to the inbox issue, which starts a run within seconds.

const SETTINGS = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GITHUB_TOKEN", "GITHUB_REPO", "INBOX_ISSUE"];

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(postToInbox(env, "/tick"));
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    const secret = await webhookSecret(env.TELEGRAM_BOT_TOKEN || "");

    if (request.method === "GET" && url.pathname === "/setup") {
      const missing = SETTINGS.filter((k) => !env[k]);
      if (missing.length) return new Response(`Missing settings: ${missing.join(", ")}`, { status: 500 });
      const r = await telegram(env, "setWebhook", {
        url: `${url.origin}/telegram`,
        secret_token: secret,
        allowed_updates: ["message"],
      });
      return new Response(r.ok ? "Done! Send your bot /status to try it." : `Telegram said: ${r.description}`);
    }

    if (request.method === "POST" && url.pathname === "/telegram") {
      if (request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== secret) {
        return new Response("forbidden", { status: 403 });
      }
      const msg = (await request.json()).message;
      if (msg && msg.text && String(msg.chat.id) === String(env.TELEGRAM_CHAT_ID)) {
        const gh = await postToInbox(env, msg.text);
        if (gh.ok) {
          await telegram(env, "setMessageReaction", {
            chat_id: msg.chat.id,
            message_id: msg.message_id,
            reaction: [{ type: "emoji", emoji: "👀" }],
          });
        } else {
          await telegram(env, "sendMessage", {
            chat_id: msg.chat.id,
            text: `Couldn't pass that on to GitHub (HTTP ${gh.status}). Check the relay's GITHUB_TOKEN, GITHUB_REPO and INBOX_ISSUE.`,
          });
        }
      }
      return new Response("ok"); // always 200, or Telegram keeps retrying
    }

    return new Response("GoWild relay is running.");
  },
};

function postToInbox(env, body) {
  const repo = String(env.GITHUB_REPO || "").trim().replace(/^https:\/\/github\.com\//, "").replace(/\/+$/, "");
  const issue = String(env.INBOX_ISSUE || "").trim().replace(/^#/, "");
  return fetch(`https://api.github.com/repos/${repo}/issues/${issue}/comments`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "gowild-relay",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ body }),
  });
}

async function telegram(env, method, params) {
  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  return r.json();
}

// Derived from the bot token so there's no extra secret to set up.
async function webhookSecret(token) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`gowild-relay:${token}`));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 32);
}
