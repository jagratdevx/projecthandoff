#!/usr/bin/env bash
# ProjectHandoff — run locally and, optionally, publish it on a free tunnel.
#
#   ./deploy/local/start.sh                      # local only (http://localhost:5173)
#   TUNNEL=tailscale  ./deploy/local/start.sh    # stable https://<host>.<tailnet>.ts.net
#   TUNNEL=cloudflare ./deploy/local/start.sh    # instant https://<random>.trycloudflare.com
#   TUNNEL=ngrok      ./deploy/local/start.sh    # https://<name>.ngrok-free.app
#
# Everything is served from one origin: Vite's preview server serves the built
# React app and proxies /api to the FastAPI backend, so the tunnel only has to
# expose port 5173. No CORS, no second URL.
#
# Overrides:
#   PUBLIC_URL=https://app.example.com   # you already have a tunnel/reverse proxy
#   PH_FRONTEND_PORT=5173
#   NGROK_DOMAIN=my-club.ngrok-free.app  # your free static ngrok domain
#
# The backend port is fixed at 8000 because frontend/vite.config.ts proxies
# /api there.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"
BACKEND_PORT=8000
FRONTEND_PORT="${PH_FRONTEND_PORT:-5173}"
TUNNEL="${TUNNEL:-none}"
PUBLIC_URL="${PUBLIC_URL:-}"
LOG_DIR="${TMPDIR:-/tmp}/projecthandoff"
mkdir -p "$LOG_DIR"

PIDS=()
TUNNEL_URL=""
cleanup() {
  trap - EXIT INT TERM
  echo
  echo "Shutting down…"
  if [ "${TUNNEL:-none}" = "tailscale" ]; then
    tailscale funnel reset >/dev/null 2>&1 || true
  fi
  for pid in "${PIDS[@]:-}"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
  sleep 1
  for pid in "${PIDS[@]:-}"; do
    [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null || true
  done
  exec 2>/dev/null
  exit 0
}
trap cleanup EXIT INT TERM

say() { printf '\n\033[1;32m%s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m%s\033[0m\n' "$*"; }
die() { printf '\033[1;31m%s\033[0m\n' "$*" >&2; exit 1; }

listening() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t >/dev/null 2>&1; }

wait_for_http() { # url seconds
  local url="$1" tries="${2:-90}" i
  for ((i = 0; i < tries; i++)); do
    curl -fsS -o /dev/null --max-time 2 "$url" 2>/dev/null && return 0
    sleep 1
  done
  return 1
}

# ---------------------------------------------------------------- tunnel URL
# Each starter records the public URL in TUNNEL_URL (never via $(...) — that
# would run the function in a subshell and lose the PID we need to clean up).
start_cloudflare() {
  command -v cloudflared >/dev/null || die "cloudflared not installed. Run: brew install cloudflared"
  local log="$LOG_DIR/cloudflared.log"
  : >"$log"
  cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:$FRONTEND_PORT" >"$log" 2>&1 &
  PIDS+=("$!")
  local i
  for ((i = 0; i < 40; i++)); do
    TUNNEL_URL="$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' "$log" | head -1 || true)"
    [ -n "$TUNNEL_URL" ] && return 0
    sleep 1
  done
  tail -20 "$log" >&2
  die "cloudflared did not report a URL"
}

start_ngrok() {
  command -v ngrok >/dev/null || die "ngrok not installed. Run: brew install ngrok, then: ngrok config add-authtoken <token>"
  local args=(http "$FRONTEND_PORT" --log=stdout --log-format=json)
  [ -n "${NGROK_DOMAIN:-}" ] && args+=(--url "$NGROK_DOMAIN")
  ngrok "${args[@]}" >"$LOG_DIR/ngrok.log" 2>&1 &
  PIDS+=("$!")
  local i
  for ((i = 0; i < 30; i++)); do
    TUNNEL_URL="$(curl -fsS --max-time 2 http://127.0.0.1:4040/api/tunnels 2>/dev/null |
      python3 -c 'import json,sys;d=json.load(sys.stdin);print(next((t["public_url"] for t in d.get("tunnels",[]) if t["public_url"].startswith("https")),""))' 2>/dev/null || true)"
    [ -n "$TUNNEL_URL" ] && return 0
    sleep 1
  done
  die "ngrok did not report a URL (see $LOG_DIR/ngrok.log)"
}

tailscale_url() {
  command -v tailscale >/dev/null || die "Tailscale CLI not found. Install the Tailscale app, sign in, then run 'tailscale funnel --help' once to add the CLI to PATH."
  tailscale status --json | python3 -c '
import json, sys
name = json.load(sys.stdin)["Self"]["DNSName"].rstrip(".")
print(f"https://{name}")'
}

if [ -z "$PUBLIC_URL" ]; then
  case "$TUNNEL" in
    tailscale) TUNNEL_URL="$(tailscale_url)" ;;
    cloudflare) start_cloudflare ;;
    ngrok) start_ngrok ;;
    none) ;;
    *) die "Unknown TUNNEL=$TUNNEL (use tailscale, cloudflare, ngrok or none)" ;;
  esac
  PUBLIC_URL="$TUNNEL_URL"
fi

# ------------------------------------------------------------ backend config
export PH_FRONTEND_URL="${PUBLIC_URL:-http://localhost:$FRONTEND_PORT}"
export PH_CORS_ORIGINS="${PUBLIC_URL:+$PUBLIC_URL,}http://localhost:$FRONTEND_PORT,http://127.0.0.1:$FRONTEND_PORT"
if [ -n "$PUBLIC_URL" ]; then
  export PH_GOOGLE_OAUTH_REDIRECT_URI="$PUBLIC_URL/api/drive/oauth/callback"
fi

# ------------------------------------------------------------------- backend
[ -x "$BACKEND_DIR/.venv/bin/python" ] || die "Missing backend/.venv. Create it: cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"

if listening "$BACKEND_PORT"; then
  warn "Port $BACKEND_PORT already in use — reusing the running backend."
  warn "It was started with different env vars; restart it for $PH_FRONTEND_URL to apply."
else
  say "Starting backend on 127.0.0.1:$BACKEND_PORT"
  (
    cd "$BACKEND_DIR"
    exec .venv/bin/python -m uvicorn app.main:create_app --factory \
      --host 127.0.0.1 --port "$BACKEND_PORT"
  ) >"$LOG_DIR/backend.log" 2>&1 &
  PIDS+=("$!")
  wait_for_http "http://127.0.0.1:$BACKEND_PORT/api/health" 60 ||
    { tail -30 "$LOG_DIR/backend.log" >&2; die "Backend failed to start (see $LOG_DIR/backend.log)"; }
fi

# ------------------------------------------------------------------ frontend
STALE=""
if [ -f "$FRONTEND_DIR/dist/index.html" ]; then
  STALE="$(find "$FRONTEND_DIR/src" "$FRONTEND_DIR/index.html" "$FRONTEND_DIR/tailwind.config.js" \
    -newer "$FRONTEND_DIR/dist/index.html" -print -quit 2>/dev/null || true)"
fi

if [ "${REBUILD:-0}" = "1" ] || [ ! -f "$FRONTEND_DIR/dist/index.html" ] || [ -n "$STALE" ]; then
  say "Building frontend"
  [ -d "$FRONTEND_DIR/node_modules" ] || (cd "$FRONTEND_DIR" && npm ci --silent --no-audit --no-fund)
  (cd "$FRONTEND_DIR" && npm run build)
fi

if listening "$FRONTEND_PORT"; then
  warn "Port $FRONTEND_PORT already in use — reusing the running frontend."
else
  say "Starting frontend on 127.0.0.1:$FRONTEND_PORT"
  (
    cd "$FRONTEND_DIR"
    exec ./node_modules/.bin/vite preview --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort
  ) >"$LOG_DIR/frontend.log" 2>&1 &
  PIDS+=("$!")
  wait_for_http "http://127.0.0.1:$FRONTEND_PORT" 60 ||
    { tail -30 "$LOG_DIR/frontend.log" >&2; die "Frontend failed to start (see $LOG_DIR/frontend.log)"; }
fi

# -------------------------------------------------------------- tailscale up
if [ "$TUNNEL" = "tailscale" ]; then
  say "Publishing $PUBLIC_URL via Tailscale Funnel"
  tailscale funnel --bg "$FRONTEND_PORT" ||
    die "Funnel failed. Enable HTTPS + Funnel for this device: https://login.tailscale.com/admin/dns"
fi

# ------------------------------------------------------------ keep mac awake
if [ "$(uname)" = "Darwin" ] && ! pgrep -f "caffeinate -dimsu" >/dev/null; then
  caffeinate -dimsu >/dev/null 2>&1 &
  PIDS+=("$!")
fi

# --------------------------------------------------------------------- ready
say "ProjectHandoff is running"
echo "  Local:   http://localhost:$FRONTEND_PORT"
if [ -n "$PUBLIC_URL" ]; then
  echo "  Public:  $PUBLIC_URL"
  cat <<EOF

Register these in Google Cloud → APIs & Services → Credentials → your OAuth client:
  Authorized JavaScript origin:  $PUBLIC_URL
  Authorized redirect URI:       $PUBLIC_URL/api/drive/oauth/callback
  Authorized redirect URI:       $PUBLIC_URL/api/teams/drive/oauth/callback

Logs: $LOG_DIR/{backend,frontend}.log
Press Ctrl-C to stop everything.
EOF
else
  echo "  Logs:    $LOG_DIR"
fi

# Stay in the foreground so Ctrl-C tears the stack down. (A one-second sleep
# lets bash run the traps promptly; macOS ships bash 3.2, which has no `wait -n`.)
while :; do sleep 1; done
