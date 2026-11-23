# Running ProjectHandoff without a credit card

Oracle Cloud, Google Cloud, Fly.io and Azure pay-as-you-go all ask for a card
(for identity verification, even on free tiers). If you don't have one, the two
realistic paths are:

1. **Run it on your own machine and publish it through a free tunnel.** No
   account needed for Cloudflare; no card for Tailscale or ngrok.
2. **Use a student/education credit** if you have one — GitHub Student Developer
   Pack gives Azure for Students ($100, no card) and DigitalOcean credit.

The app is a good fit for path 1 because the data lives in Google Drive. The
machine only stores OAuth tokens and a small read cache.

---

## Which tunnel?

| Tunnel | Card? | URL | Notes |
| --- | --- | --- | --- |
| **Tailscale Funnel** | No | **Stable** `https://<host>.<tailnet>.ts.net` | Best option. Needs the Tailscale app + a free account. |
| **ngrok free** | No | Stable if you claim the free static domain (`*.ngrok-free.app`) | 1 GB/month + 20k requests/month. |
| **Cloudflare Quick Tunnel** | No | Random `https://<words>.trycloudflare.com`, changes on every restart | Zero setup, great for a demo, bad for OAuth (redirect URI changes). |

All three need this Mac to stay awake and online. The script starts
`caffeinate` for you; closing the lid still sleeps the machine unless you run
`sudo pmset -a disablesleep 1`.

---

## Start it

```bash
cd ProjectHandoff

# local only
./deploy/local/start.sh

# stable public URL via Tailscale (recommended)
TUNNEL=tailscale ./deploy/local/start.sh

# instant public URL, no account
TUNNEL=cloudflare ./deploy/local/start.sh

# ngrok (run `ngrok config add-authtoken <token>` once)
NGROK_DOMAIN=my-club.ngrok-free.app TUNNEL=ngrok ./deploy/local/start.sh
```

The script builds the frontend if needed (it rebuilds automatically when
`src/`, `index.html` or the Tailwind config are newer than the build; force it
with `REBUILD=1`), starts FastAPI on `127.0.0.1:8000` and Vite's preview server
on `127.0.0.1:5173`, waits for both to answer, opens the tunnel, and prints the
URLs plus the Google OAuth values to register. Ctrl-C stops everything, including
the tunnel and `caffeinate`.

Everything is served from **one origin**: the preview server serves the built
React app and proxies `/api` to the backend, so the tunnel only exposes one
port and there is no CORS to configure.

---

## Tailscale Funnel, step by step

1. Install the app: <https://pkgs.tailscale.com/stable/Tailscale-latest-macos.pkg>
   (or `brew install --cask tailscale`), open it and sign in with Google/GitHub.
2. Enable **HTTPS certificates** and **Funnel** for the tailnet:
   <https://login.tailscale.com/admin/dns> → *Enable HTTPS*.
   Funnel is allowed by default for your own devices in the default ACL.
3. Make the CLI available (the app ships it inside the bundle):
   ```bash
   sudo ln -sf /Applications/Tailscale.app/Contents/MacOS/Tailscale /usr/local/bin/tailscale
   ```
4. Run `TUNNEL=tailscale ./deploy/local/start.sh`. The first run prints a link
   to approve Funnel if the ACL needs it.
5. Your URL is `https://<machine-name>.<tailnet-name>.ts.net` and it stays the
   same across restarts, so the Google OAuth redirect URI stays valid.

## ngrok, step by step

1. Sign up at <https://dashboard.ngrok.com> (email, no card) and copy the
   authtoken.
2. `brew install ngrok && ngrok config add-authtoken <token>`
3. Claim your one free static domain on the dashboard (Domains → New domain).
4. `NGROK_DOMAIN=<your-domain>.ngrok-free.app TUNNEL=ngrok ./deploy/local/start.sh`

The free plan allows 1 GB of transfer and 20k requests per month — fine for a
club, tight if people upload/download large files.

## Cloudflare Quick Tunnel

```bash
brew install cloudflared
TUNNEL=cloudflare ./deploy/local/start.sh
```

No account. The `trycloudflare.com` URL changes every run, so you must update
the Google OAuth redirect URI each time you restart, or sign in with an existing
session and skip the Drive connection.

---

## Google OAuth with a public URL

Whichever tunnel you use, add these to
**Google Cloud → APIs & Services → Credentials → your OAuth client**:

- Authorized JavaScript origin: `https://YOUR_URL`
- Authorized redirect URI: `https://YOUR_URL/api/drive/oauth/callback`
- Authorized redirect URI: `https://YOUR_URL/api/teams/drive/oauth/callback`

The start script exports `PH_FRONTEND_URL`, `PH_CORS_ORIGINS` and
`PH_GOOGLE_OAUTH_REDIRECT_URI` from the detected public URL, so invite links and
the post-OAuth redirect point at the tunnel instead of localhost.

If the OAuth consent screen is still in **Testing** mode, only the test users
you added (up to 100) can connect a Drive. That is normally fine for one club.

---

## Keeping it alive

- `caffeinate -dimsu` is started by the script; the Mac must not sleep.
- A tunnel dies when the process or the Mac stops. For a link that survives
  reboots, run the script from a LaunchAgent or `tmux`/`screen` session and add
  `sudo pmset -a disablesleep 1`.
- Nothing here is a paid SLA. If the link must be up while the laptop is off,
  you need a real VM — see [`../oracle/README.md`](../oracle/README.md), which
  needs a card only for Oracle's identity check. A student GitHub Pack →
  Azure for Students credit also works without one.
