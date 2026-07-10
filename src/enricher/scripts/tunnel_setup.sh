#!/bin/sh
# One-time setup for the OPTIONAL inbound Cloudflare tunnel (pull mode does not
# need this). Mirrors boop: create a named tunnel, route DNS, write ingress.
set -eu
TUNNEL="${1:-jobnorm}"
HOST="${2:-jobnorm.localhostings.com}"
PORT="${3:-8787}"

command -v cloudflared >/dev/null || { echo "install cloudflared: brew install cloudflared"; exit 1; }

cloudflared tunnel create "$TUNNEL" || echo "tunnel may already exist"
cloudflared tunnel route dns "$TUNNEL" "$HOST"

CFG="$HOME/.cloudflared/config.yml"
echo "Add this ingress to $CFG (merge with existing tunnels):"
cat <<CFGEOF
tunnel: $TUNNEL
ingress:
  - hostname: $HOST
    service: http://localhost:$PORT
  - service: http_status:404
CFGEOF
echo "Then run: cloudflared tunnel run $TUNNEL"
