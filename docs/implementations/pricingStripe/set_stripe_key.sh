#!/usr/bin/env bash
# Paste a Stripe TEST secret key into the repo-root .env.local.
#
# The key is read silently: it never shows on screen, never lands in shell
# history, and is never passed as a command-line argument (so `ps` cannot see
# it). Before writing, it asks Stripe whether the key works AND whether it can
# see STRIPE_PRICE_ID_PRO — a 404 there means the key is from a different
# account or sandbox than the price, the most common setup mistake.
#
# Usage (from anywhere in the repo):
#   bash docs/implementations/pricingStripe/set_stripe_key.sh
set -euo pipefail

root="$(git rev-parse --show-toplevel)"
env_file="${ENV_FILE:-$root/.env.local}"
touch "$env_file"

read -rsp "Paste your Stripe secret key (sk_test_...), then press Enter: " key
echo
key="${key//[[:space:]]/}"

case "$key" in
  sk_test_* | rk_test_*) ;;
  sk_live_* | rk_live_*)
    echo "That is a LIVE key. Local dev must use a sandbox/test key. Nothing written." >&2
    exit 1
    ;;
  *)
    echo "That does not look like a Stripe secret key (expected sk_test_...). Nothing written." >&2
    exit 1
    ;;
esac

price_id="$(grep -E '^STRIPE_PRICE_ID_PRO=' "$env_file" | tail -1 | cut -d= -f2- | tr -d '"' || true)"
if [ -n "$price_id" ]; then
  url="https://api.stripe.com/v1/prices/$price_id"
else
  url="https://api.stripe.com/v1/balance"
fi
# curl reads the credential from stdin (-K -), not from its argv.
status="$(printf 'user = "%s:"\n' "$key" | curl -s -o /dev/null -w '%{http_code}' -K - "$url" || true)"

case "$status" in
  200) echo "Stripe accepted the key${price_id:+ and can see $price_id}." ;;
  401)
    echo "Stripe rejected this key (401). Copy it again from Developers -> API keys. Nothing written." >&2
    exit 1
    ;;
  404)
    echo "The key works, but it cannot see $price_id: it is from a different account or sandbox." >&2
    echo "Copy the key from the SAME sandbox as the price (onesecondswe sandbox). Nothing written." >&2
    exit 1
    ;;
  *) echo "Could not verify the key with Stripe (HTTP $status). Writing it anyway." >&2 ;;
esac

# Replace the existing STRIPE_SECRET_KEY line (commented or not), else append.
# The key reaches awk through its environment, not its arguments.
tmp="$(mktemp "$env_file.XXXXXX")"
KEY="$key" awk '
  /^#? *STRIPE_SECRET_KEY=/ { if (!done) { print "STRIPE_SECRET_KEY=" ENVIRON["KEY"]; done = 1 } next }
  { print }
  END { if (!done) print "STRIPE_SECRET_KEY=" ENVIRON["KEY"] }
' "$env_file" >"$tmp"
chmod 600 "$tmp"
mv "$tmp" "$env_file"

echo "Saved STRIPE_SECRET_KEY=${key:0:8}...${key: -4} to $env_file (permissions 600)."
echo "Restart the backend so it picks the key up."
