#!/usr/bin/env bash
# Install cloudflared and print Cloudflare Zero Trust tunnel setup steps.
# After running: create tunnel in Cloudflare dashboard → copy token → configure systemd.
set -euo pipefail

echo "==> Install cloudflared"
ARCH=$(dpkg --print-architecture)
DEB="cloudflared-linux-${ARCH}.deb"
curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/${DEB}" -o "/tmp/${DEB}"
dpkg -i "/tmp/${DEB}" || apt install -f -y
rm -f "/tmp/${DEB}"

cloudflared --version

cat <<'EOF'

==> Cloudflare Zero Trust — Tunnel (dashboard)

1. Zero Trust → Networks → Tunnels → Create tunnel → Cloudflared
2. Name: godelta-beta (or similar)
3. Public hostname:
     Subdomain: crm
     Domain: godelta.us
     Service type: HTTP
     URL: http://127.0.0.1:8000
4. Copy the install command (includes tunnel token) and run on this VPS, e.g.:
     cloudflared service install <TOKEN>
     systemctl enable --now cloudflared
5. DNS: Cloudflare should auto-create CNAME for crm.godelta.us → tunnel

==> Cloudflare Access (gate before Django)

1. Zero Trust → Access → Applications → Add application → Self-hosted
2. Application domain: crm.godelta.us
3. Policy: Allow — Emails ending in @yourdomain.com OR explicit allowlist (5 beta users)
4. Session duration: 24h (adjust as needed)

Verify: curl -sI https://crm.godelta.us/health/  (expect 302 to Access login or 200 after auth)

EOF
