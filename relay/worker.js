// Telegram -> GitHub relay (Cloudflare Worker).
//
// Telegram can't start a GitHub Actions run by itself, so this tiny worker sits in
// between: Telegram pushes each message here (webhook), the worker posts it as a
// comment on the "Telegram inbox" issue, and that comment starts the GoWild watch
// workflow, which answers within about a minute. The worker reacts 👀 right away so
// you know the message arrived.
//
// Settings (Cloudflare: Worker -> Settings -> Variables and secrets):
//   TELEGRAM_BOT_TOKEN  the bot token from BotFather
//   TELEGRAM_CHAT_ID    your chat id (only your messages are passed on)
//   GITHUB_TOKEN        fine-grained token, this repo only, Issues: read and write
//
// After deploying, open https://<your-worker>.workers.dev/setup once to point the bot at it.

const REPO = "adambabin/flight-watcher";
const INBOX_ISSUE = 2;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const secret = await webhookSecret(env.TELEGRAM_BOT_TOKEN || "");

    if (request.method === "GET" && url.pathname === "/setup") {
      const missing = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GITHUB_TOKEN"].filter((k) => !env[k]);
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
        const gh = await fetch(`https://api.github.com/repos/${REPO}/issues/${INBOX_ISSUE}/comments`, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${env.GITHUB_TOKEN}`,
            Accept: "application/vnd.github+json",
            "User-Agent": "gowild-relay",
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ body: msg.text }),
        });
        if (gh.ok) {
          await telegram(env, "setMessageReaction", {
            chat_id: msg.chat.id,
            message_id: msg.message_id,
            reaction: [{ type: "emoji", emoji: "👀" }],
          });
        } else {
          await telegram(env, "sendMessage", {
            chat_id: msg.chat.id,
            text: `Couldn't pass that on to GitHub (HTTP ${gh.status}). Check the relay's GITHUB_TOKEN.`,
          });
        }
      }
      return new Response("ok"); // always 200, or Telegram keeps retrying
    }

    return new Response("GoWild relay is running.");
  },
};

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
