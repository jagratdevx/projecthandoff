# ProjectHandoff on Oracle Cloud Always Free

This is a complete, no-cost production setup:

- **VM:** Oracle Cloud Always Free `VM.Standard.A1.Flex` — 2 OCPU / 12 GB RAM, 50 GB boot volume
- **HTTPS:** Caddy with an automatic Let's Encrypt certificate
- **Domain:** a free DuckDNS subdomain (or any domain you already own)
- **App:** FastAPI backend on `127.0.0.1:8000`, React build served by Caddy
- **Data:** stays in the team's Google Drive. The VM only stores OAuth tokens and a small cache.

> Oracle's Always Free A1 allowance is **2 OCPUs and 12 GB RAM total** (1,500 OCPU-hours + 9,000 GB-hours per month). If A1 capacity is unavailable in your region, use the AMD `VM.Standard.E2.1.Micro` shape (1 GB RAM) — the bootstrap script adds swap automatically.

---

## 1. Create the VM

1. Sign up at <https://www.oracle.com/cloud/free/>. A card is used for identity verification; Always Free resources are not charged.
2. Pick a **home region** close to you. Always Free resources must live in the home region.
3. Open **Compute → Instances → Create instance**.
4. Configure:
   - **Name:** `projecthandoff`
   - **Image:** Ubuntu 24.04 (or 22.04)
   - **Shape:** `VM.Standard.A1.Flex`, **2 OCPUs / 12 GB memory**
   - **Boot volume:** 50 GB
   - **Networking:** create/select a VCN with a **public subnet**, and **assign a public IPv4 address**
   - **SSH keys:** upload your public key (`~/.ssh/id_ed25519.pub`) or generate a new key pair
5. Create the instance and note its **public IP**.
6. Reserve the IP so it survives reboots: **Networking → Reserved public IPs → Reserve**, or use the instance's attached reserved IP.
7. Open the web ports in the VCN:
   - **Networking → Virtual Cloud Networks → your VCN → Security Lists → Default Security List**
   - Add ingress rules:
     - `0.0.0.0/0` TCP **80**
     - `0.0.0.0/0` TCP **443**
     - `0.0.0.0/0` TCP **22** (or restrict to your own IP)

> If you see **“Out of host capacity”** for the A1 shape, try another availability domain, retry later, or use `VM.Standard.E2.1.Micro`.

---

## 2. Point a free domain at the VM

### DuckDNS (recommended — free, stable name)

1. Go to <https://www.duckdns.org> and sign in.
2. Create a subdomain, e.g. `projecthandoff-yourname`.
3. Set its **current IP** to the VM's public IP and save.
4. Your URL is `https://projecthandoff-yourname.duckdns.org`.

### sslip.io (zero signup, IP-based)

If you do not want a DuckDNS account, use `https://<public-ip-with-dashes>.sslip.io`, e.g. `https://203-0-113-10.sslip.io`. Caddy can still obtain a certificate.

---

## 3. Install the app

SSH into the VM:

```bash
ssh -i ~/.ssh/your_key ubuntu@YOUR_VM_IP
```

Clone the public repo and run the bootstrap script:

```bash
sudo apt-get update && sudo apt-get install -y git
sudo git clone --branch projecthandoff --depth 1 \
  https://github.com/jagratdevx/projecthandoff.git /opt/projecthandoff

sudo bash /opt/projecthandoff/ProjectHandoff/deploy/oracle/bootstrap.sh \
  projecthandoff-yourname.duckdns.org
```

The script installs Python, Node, Caddy, builds the frontend, creates a dedicated `projecthandoff` user, writes a production `.env` with a generated `PH_SECRET_KEY`, and starts:

- `projecthandoff.service` (uvicorn on `127.0.0.1:8000`)
- `caddy.service` (HTTPS + static frontend)

It is idempotent — run it again to update the deployment.

---

## 4. Google OAuth

In <https://console.cloud.google.com>:

1. Create/select a project and enable **Google Drive API**.
2. **OAuth consent screen:** External → Testing. Add your volunteers as **test users** (up to 100). Publishing for arbitrary users requires Google verification for the Drive scope.
3. **APIs & Services → Credentials → Create credentials → OAuth client ID → Web application**.
4. Add:
   - **Authorized JavaScript origins:** `https://YOUR_DOMAIN`
   - **Authorized redirect URIs:**
     - `https://YOUR_DOMAIN/api/drive/oauth/callback`
     - `https://YOUR_DOMAIN/api/teams/drive/oauth/callback`

Then open:

```text
https://YOUR_DOMAIN/setup
```

Paste the client ID and secret and save. The wizard stores them under `.tokens/oauth_client.json` on the VM, so they survive restarts and updates.

---

## 5. First run

1. Open `https://YOUR_DOMAIN` and create the first account.
2. Create a team.
   - **Host mode:** leave the Drive fields empty, then go to **Settings → Storage & synchronization** and connect the organizer's Google account.
   - **Team-owned Drive:** paste the team's shared Drive folder link and authorize as the team owner.
3. Invite members from the **Team** page. Invite links use `PH_FRONTEND_URL`, which the bootstrap sets to your public URL.

---

## Updating

```bash
sudo bash /opt/projecthandoff/ProjectHandoff/deploy/oracle/bootstrap.sh YOUR_DOMAIN
```

This pulls the latest `projecthandoff` branch, reinstalls dependencies, rebuilds the frontend and restarts the services. `.env` and `.tokens/` are preserved.

## Logs and operations

```bash
sudo journalctl -u projecthandoff -f      # backend
sudo journalctl -u caddy -f               # HTTPS / static
sudo systemctl restart projecthandoff
sudo systemctl status projecthandoff caddy
```

Back up the secrets (the team data itself is already in Google Drive):

```bash
sudo tar czf ~/projecthandoff-secrets.tgz \
  -C /opt/projecthandoff/ProjectHandoff .env .tokens
```

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `502 Bad Gateway` | `sudo journalctl -u projecthandoff -n 100` — backend failed to start |
| Caddy cannot get a certificate | DNS must point to the VM; ports 80/443 must be open in the **VCN security list** and the OS firewall |
| `redirect_uri_mismatch` | The URL in Google Console must match `PH_GOOGLE_OAUTH_REDIRECT_URI` **exactly** (https, no trailing slash) |
| OOM while building the frontend | The bootstrap adds 2 GB swap on 1 GB machines; or build locally and copy `frontend/dist` |
| A1 “out of host capacity” | Try another availability domain, retry, or use `VM.Standard.E2.1.Micro` |
| Instance disappeared after a week | Oracle may reclaim **idle** Always Free instances. See below |

### Idle reclamation

Oracle may reclaim Always Free instances that stay idle for 7 days (95th-percentile CPU < 20%, network < 20%, and for A1 memory < 20%). A quiet club app can qualify as idle. If the instance must be permanent, the reliable fix is to **upgrade the account to Pay As You Go** — Always Free resources remain free, but set a budget alert so paid overages cannot surprise you. Keeping a small external uptime monitor pointed at the app also helps demonstrate activity.
