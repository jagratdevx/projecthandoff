#!/usr/bin/env bash
# ProjectHandoff — one-shot installer for an Oracle Cloud Always Free VM.
#
#   sudo bash deploy/oracle/bootstrap.sh YOUR_DOMAIN
#
# Installs Python, Node, Caddy and a systemd service, builds the frontend,
# writes a production .env with a generated secret, and starts everything on
# HTTPS. Safe to re-run: it updates the code and preserves .env and .tokens/.
set -euo pipefail

DOMAIN="${1:-}"
if [ -z "$DOMAIN" ]; then
  echo "usage: sudo bash $0 <domain>" >&2
  exit 2
fi
if [ "$(id -u)" -ne 0 ]; then
  echo "run this with sudo" >&2
  exit 1
fi

REPO_URL="${REPO_URL:-https://github.com/jagratdevx/projecthandoff.git}"
REPO_BRANCH="${REPO_BRANCH:-projecthandoff}"
REPO_DIR="${REPO_DIR:-/opt/projecthandoff}"
APP_DIR="$REPO_DIR/ProjectHandoff"
RUN_USER="projecthandoff"
TEMPLATES="$APP_DIR/deploy/oracle"

say() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }

export DEBIAN_FRONTEND=noninteractive

# ---------------------------------------------------------------- packages
say "Installing system packages"
apt-get update -qq
apt-get install -y -qq git curl ca-certificates python3 python3-venv python3-pip \
  debian-keyring debian-archive-keyring apt-transport-https gpg openssl

if ! command -v node >/dev/null || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 18 ]; then
  say "Installing Node.js 20"
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y -qq nodejs
fi

if ! command -v caddy >/dev/null; then
  say "Installing Caddy"
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' |
    gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    >/etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq
  apt-get install -y -qq caddy
fi

# -------------------------------------------------------------------- swap
# The frontend build needs ~1 GB; the AMD micro shape has exactly that.
if [ "$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)" -lt 2048 ] && [ ! -f /swapfile ]; then
  say "Adding 2 GB swap (small instance)"
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab
fi

# -------------------------------------------------------------------- code
if [ -d "$REPO_DIR/.git" ]; then
  say "Updating $REPO_DIR"
  git -C "$REPO_DIR" fetch --depth 1 origin "$REPO_BRANCH"
  git -C "$REPO_DIR" reset --hard FETCH_HEAD
else
  say "Cloning $REPO_URL"
  git clone --branch "$REPO_BRANCH" --depth 1 "$REPO_URL" "$REPO_DIR"
fi

# --------------------------------------------------------------------- user
if ! id -u "$RUN_USER" >/dev/null 2>&1; then
  say "Creating $RUN_USER user"
  useradd --system --create-home --shell /usr/sbin/nologin "$RUN_USER"
fi

# ---------------------------------------------------------------- backend
say "Installing backend dependencies"
[ -d "$APP_DIR/backend/.venv" ] || python3 -m venv "$APP_DIR/backend/.venv"
"$APP_DIR/backend/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/backend/.venv/bin/pip" install --quiet -r "$APP_DIR/backend/requirements.txt"

# --------------------------------------------------------------- frontend
say "Building frontend"
(
  cd "$APP_DIR/frontend"
  npm ci --silent --no-audit --no-fund
  npm run build
)

# --------------------------------------------------------------------- env
if [ -f "$APP_DIR/.env" ]; then
  say "Keeping existing .env (check PH_FRONTEND_URL points at https://$DOMAIN)"
else
  say "Writing .env"
  SECRET="$(openssl rand -hex 32)"
  sed -e "s|__SECRET__|$SECRET|g" \
    -e "s|__DOMAIN__|$DOMAIN|g" \
    -e "s|__APP_DIR__|$APP_DIR|g" \
    "$TEMPLATES/env.production" >"$APP_DIR/.env"
  chmod 600 "$APP_DIR/.env"
fi

mkdir -p "$APP_DIR/.tokens" "$APP_DIR/.cache" "$APP_DIR/data"
chown -R "$RUN_USER:$RUN_USER" "$APP_DIR/.tokens" "$APP_DIR/.cache" "$APP_DIR/data" "$APP_DIR/.env"

# ----------------------------------------------------------------- systemd
say "Installing projecthandoff.service"
sed -e "s|__RUN_USER__|$RUN_USER|g" \
  -e "s|__APP_DIR__|$APP_DIR|g" \
  "$TEMPLATES/projecthandoff.service" >/etc/systemd/system/projecthandoff.service
systemctl daemon-reload
systemctl enable projecthandoff >/dev/null
systemctl restart projecthandoff

# ------------------------------------------------------------------- caddy
say "Configuring Caddy for $DOMAIN"
sed -e "s|__DOMAIN__|$DOMAIN|g" \
  -e "s|__APP_DIR__|$APP_DIR|g" \
  "$TEMPLATES/Caddyfile" >/etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
systemctl enable caddy >/dev/null
systemctl restart caddy

# ----------------------------------------------------------------- firewall
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  say "Opening 80/443 in ufw"
  ufw allow 80/tcp >/dev/null
  ufw allow 443/tcp >/dev/null
fi

# -------------------------------------------------------------------- check
say "Waiting for the backend"
for _ in $(seq 1 30); do
  if curl -fsS -o /dev/null http://127.0.0.1:8000/api/health; then
    break
  fi
  sleep 2
done
curl -fsS http://127.0.0.1:8000/api/health || {
  echo "backend did not start — check: journalctl -u projecthandoff -n 100" >&2
  exit 1
}

say "Done"
cat <<EOF

  App:      https://$DOMAIN
  Setup:    https://$DOMAIN/setup   (paste your Google OAuth client id/secret)

  Google Cloud → Credentials → your OAuth client:
    Authorized JavaScript origin:  https://$DOMAIN
    Authorized redirect URI:       https://$DOMAIN/api/drive/oauth/callback
    Authorized redirect URI:       https://$DOMAIN/api/teams/drive/oauth/callback

  Logs:     journalctl -u projecthandoff -f
            journalctl -u caddy -f
EOF
