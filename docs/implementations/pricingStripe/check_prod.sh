#!/usr/bin/env bash
# Read-only go-live check for Stripe billing. Prints one line per SETUP.md step.
#
#   bash docs/implementations/pricingStripe/check_prod.sh
#
# Stripe reads use the CLI profile `live` (see SETUP.md), so the default
# profile stays on the sandbox for `stripe listen` and the e2e gate.
# STRIPE_PROFILE=default STRIPE_MODE=test runs the same checks on the sandbox.
set -uo pipefail

BACKEND=https://job-visualizer-notifier-production.up.railway.app
WEBHOOK_URL="$BACKEND/api/billing/webhook"
EVENTS="checkout.session.completed customer.subscription.created customer.subscription.updated customer.subscription.deleted invoice.paid invoice.payment_failed"
PROFILE="${STRIPE_PROFILE:-live}"
MODE_FLAG=(--live)
[ "${STRIPE_MODE:-live}" = test ] && MODE_FLAG=()

ok() { printf '  done      %s\n' "$1"; }
todo() { printf '  TODO      %s\n' "$1"; }

stripe_get() { stripe -p "$PROFILE" "$@" ${MODE_FLAG[@]+"${MODE_FLAG[@]}"} 2>/dev/null; }

# Field checks on a JSON list read from stdin; prints the match or nothing.
pick() { python3 -I -c "import json,sys
data=json.load(sys.stdin).get('data',[])
$1" 2>/dev/null; }

echo "Stripe (CLI profile '$PROFILE', ${STRIPE_MODE:-live} mode)"
if ! stripe_get prices list --limit 1 >/dev/null; then
  todo "1 Activate the account, then log the CLI in to it (SETUP.md step 1). Stripe checks skipped."
else
  ok "1 Account answers ${STRIPE_MODE:-live} API calls"

  price=$(stripe_get prices list --active=true --type recurring --currency usd --limit 100 | pick "
print(next((p['id'] for p in data if p['unit_amount']==600 and p['recurring']['interval']=='month' and p['recurring']['interval_count']==1),''))")
  [ -n "$price" ] && ok "2 Pro price \$6/month: $price" || todo "2 Create the \$6/month Pro price"

  portal=$(stripe_get billing_portal configurations list --is-default=true --limit 1 | pick "
c=data[0] if data else None
f=c['features'] if c else {}
print('yes' if c and f['payment_method_update']['enabled'] and f['subscription_cancel']['enabled']
      and f['subscription_cancel']['mode']=='at_period_end' and not f['subscription_update']['enabled'] else '')")
  [ -n "$portal" ] && ok "3 Customer portal saved (card updates, cancel at period end, no plan switching)" \
                   || todo "3 Save the Customer portal settings"

  echo "  manual    4 'Limit customers to 1 subscription' has no API; check it in the Dashboard"

  hook=$(stripe_get webhook_endpoints list --limit 100 | pick "
want=set('$EVENTS'.split())
e=next((e for e in data if e['url']=='$WEBHOOK_URL'),None)
print('' if not e else 'ok' if e['status']=='enabled' and want<=set(e['enabled_events']) else 'events')")
  case "$hook" in
    ok) ok "6 Webhook endpoint -> $WEBHOOK_URL (6 events, enabled)" ;;
    events) todo "6 Webhook endpoint exists but is disabled or missing events" ;;
    *) todo "6 Add the webhook endpoint $WEBHOOK_URL" ;;
  esac
fi

echo "Production backend"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$WEBHOOK_URL" -d '{}')
case "$code" in
  400) ok "7-8 Billing code deployed and all four Railway variables set (unsigned POST -> 400)" ;;
  503) todo "7 Deployed, but a Railway variable is missing (unsigned POST -> 503)" ;;
  401|404) todo "8 Billing code is not deployed yet: merge PR #364 (unsigned POST -> $code)" ;;
  *) todo "Backend answered $code; check Railway logs" ;;
esac
