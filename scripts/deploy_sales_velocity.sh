#!/usr/bin/env bash
#
# Sales Velocity — Hetzner deploy runbook
#
# Runs on nbne1 as the user who owns /opt/nbne/manufacture and /opt/nbne/claw
# (or wherever Cairn is deployed). Steps through every action needed to
# bring the Sales Velocity module live in production.
#
# NOT idempotent in full — intended to be read and executed step by step
# the first time. Individual commands can be re-run safely where noted.
#
# Before running: read docs/sales_velocity_operations.md § "One-time setup".
#
set -e

MANUFACTURE_DIR="${MANUFACTURE_DIR:-/opt/nbne/manufacture}"
CAIRN_DIR="${CAIRN_DIR:-/opt/nbne/cairn}"
DOCKER_COMPOSE="${DOCKER_COMPOSE:-docker compose -f ${MANUFACTURE_DIR}/docker/docker-compose.yml}"

say() { printf '\n\033[1;35m==> %s\033[0m\n' "$*"; }

# ── 1. Pull the merged code for both repos ──────────────────────────────────

say "Step 1: pull master on Cairn (/etsy/sales endpoint)"
cd "$CAIRN_DIR"
git fetch origin
git checkout master
git pull origin master
# Confirm the endpoint is present in the pulled tree
if ! grep -q 'GET /etsy/sales' api/routes/etsy_intel.py; then
  echo "ERROR: /etsy/sales endpoint not found in Cairn after pull. Check merge commit."
  exit 1
fi
echo "  Cairn: /etsy/sales endpoint present"

say "Step 2: pull master on manufacture (sales_velocity module)"
cd "$MANUFACTURE_DIR"
git fetch origin
git checkout master
git pull origin master
if [ ! -d backend/sales_velocity ]; then
  echo "ERROR: sales_velocity app missing after pull."
  exit 1
fi
echo "  Manufacture: sales_velocity app present"

# ── 3. Add the new env vars to manufacture's .env ─────────────────────────────

say "Step 3: add new env vars to manufacture .env (edit now if needed)"
echo "The following variables must be present in ${MANUFACTURE_DIR}/.env:"
cat <<'VARS'

    # Sales Velocity Phase 2B additions:
    SALES_VELOCITY_WRITE_ENABLED=False

    # Cairn cross-service (CAIRN_API_URL/CAIRN_API_KEY may already exist).
    # CAIRN_API_KEY MUST match CLAW_API_KEY in Cairn's own .env.
    CAIRN_API_URL=http://nbne1:8765
    CAIRN_API_KEY=<value-of-CLAW_API_KEY-in-cairn-.env>

    # eBay OAuth — reuse render's existing dev app, new consent grant here.
    EBAY_CLIENT_ID=<copy-from-render-.env>
    EBAY_CLIENT_SECRET=<copy-from-render-.env>
    EBAY_RU_NAME=<the-RU-name-you-registered-on-the-eBay-dev-app-for-manufacture>
    EBAY_ENVIRONMENT=production

VARS
read -r -p "Have you edited .env with the above vars? (y/N) " yn
[ "$yn" = "y" ] || { echo "Aborting. Re-run after editing .env."; exit 1; }

# ── 4. Restart Cairn + run its tests ──────────────────────────────────────────

say "Step 4: restart Cairn so the new /etsy/sales endpoint is live"
# Cairn's restart mechanism — adjust if you use systemd or docker
if systemctl is-active cairn >/dev/null 2>&1; then
  sudo systemctl restart cairn
  sleep 3
  echo "  Cairn restarted via systemd"
elif docker ps --format '{{.Names}}' | grep -q '^cairn'; then
  docker restart cairn
  sleep 3
  echo "  Cairn restarted via docker"
else
  echo "  Unknown Cairn runner — please restart manually, then press Enter"
  read -r _
fi

say "Step 5: smoke-test /etsy/sales on Cairn"
CLAW_KEY="$(grep -E '^CLAW_API_KEY=' "$CAIRN_DIR/.env" | cut -d= -f2-)"
RESP=$(curl -sf -H "X-API-Key: $CLAW_KEY" "http://localhost:8765/etsy/sales?days=7" \
        | python3 -c 'import json,sys; d=json.load(sys.stdin); print(f"row_count={d.get(\"row_count\",0)} skipped_null_sku={d.get(\"skipped_null_sku\",0)} skipped_multi_sku={d.get(\"skipped_multi_sku\",0)}")')
echo "  $RESP"
echo "$RESP" | grep -q 'skipped_multi_sku=0' \
  || { echo "WARNING: skipped_multi_sku != 0. Investigate before proceeding."; read -r -p 'Continue anyway? (y/N) ' yn; [ "$yn" = "y" ] || exit 1; }

# ── 6. Manufacture migrations + qcluster restart ──────────────────────────────

say "Step 6: apply manufacture migrations (sales_velocity 0001, 0002, 0003)"
$DOCKER_COMPOSE run --rm backend python manage.py migrate
$DOCKER_COMPOSE run --rm backend python manage.py check

say "Step 7: restart manufacture backend + qcluster"
$DOCKER_COMPOSE restart backend qcluster
sleep 5

# ── 8. Verify scheduled tasks registered ─────────────────────────────────────

say "Step 8: verify Django-Q schedules registered"
$DOCKER_COMPOSE exec -T backend python manage.py shell -c "
from django_q.models import Schedule
for s in Schedule.objects.filter(name__startswith='sales_velocity'):
    print(f'  {s.name}: type={s.schedule_type} next={s.next_run}')
"

# ── 9. Complete the eBay OAuth consent flow ──────────────────────────────────

say "Step 9: COMPLETE THE eBay OAUTH CONSENT FLOW IN A BROWSER"
cat <<'INSTRUCTIONS'
  This is the only step the deploy script cannot automate.

  1. Open https://manufacture.nbnesigns.co.uk/admin/ and log in as Toby.
  2. In another tab visit:
     https://manufacture.nbnesigns.co.uk/admin/oauth/ebay/connect
  3. You will be redirected to eBay's consent page. Log in (if not already)
     and approve the scopes:
       - api_scope
       - sell.inventory
       - sell.account
       - sell.fulfillment
       - sell.marketing
  4. eBay will redirect back to /admin/oauth/ebay/callback. You should
     see a success page showing the token expiry.
  5. If you get "eBay rejected the authorization code", the EBAY_RU_NAME
     in manufacture's .env doesn't match what's registered on the eBay
     dev app. Double-check and restart from step 3.

  After the callback succeeds, the OAuthCredential row is persisted and
  subsequent aggregator runs will refresh the access token automatically.
INSTRUCTIONS
read -r -p "Completed the eBay consent flow? (y/N) " yn
[ "$yn" = "y" ] || { echo "Come back and run step 10 after completing it."; exit 0; }

# ── 10. First manual aggregator run (dry-run) ─────────────────────────────────

say "Step 10: first manual aggregator run (dry-run)"
$DOCKER_COMPOSE exec -T backend python manage.py refresh_sales_velocity --dry-run

say "Step 11: first real aggregator run (still in shadow mode)"
$DOCKER_COMPOSE exec -T backend python manage.py refresh_sales_velocity

cat <<'NEXT'

╔══════════════════════════════════════════════════════════════════════╗
║ Sales Velocity is now live in SHADOW MODE.                           ║
║                                                                      ║
║ Next steps:                                                          ║
║   1. Open https://manufacture.nbnesigns.co.uk/sales-velocity         ║
║      (Other dropdown → Sales Velocity).                              ║
║   2. Eyeball the "Shadow vs Live" diff panel for N days.             ║
║      Investigate any row with abs(variance) > 20%.                   ║
║   3. The daily schedule fires at 04:17 UTC.                          ║
║   4. When happy, edit .env:                                          ║
║         SALES_VELOCITY_WRITE_ENABLED=True                            ║
║      Then restart backend + qcluster:                                ║
║         docker compose restart backend qcluster                      ║
║   5. The next aggregator run fires the one-off "cutover" audit row   ║
║      and starts writing StockLevel.sixty_day_sales.                  ║
║                                                                      ║
║ Rollback: set SALES_VELOCITY_WRITE_ENABLED=False and restart.        ║
║ The existing StockLevel values are not reverted — if you need to     ║
║ restore the spreadsheet-fed values, re-run the import.               ║
╚══════════════════════════════════════════════════════════════════════╝
NEXT
