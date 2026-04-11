# Sales Velocity — Operations Runbook

This doc covers how to operate the Sales Velocity module after it ships. The
implementation brief is at `docs/sales_velocity_brief.md`; this file is for
day-to-day and day-zero operations.

---

## One-time setup (before first run)

### 1. Cairn side — `/etsy/sales` endpoint deployed

The Etsy adapter consumes `GET /etsy/sales` on Cairn. The endpoint was added
in Cairn PR [NBNEORIGIN/cairn#7](https://github.com/NBNEORIGIN/cairn/pull/7)
and must be merged and deployed on `nbne1` before the manufacture side can
fetch Etsy data.

Smoke test after Cairn deploy:

```bash
curl -H "X-API-Key: $CLAW_API_KEY" \
  "http://nbne1:8765/etsy/sales?days=7" | jq '{row_count, skipped_null_sku, skipped_multi_sku}'
```

- `row_count > 0` — confirms Cairn's daily Etsy sync is populating data.
- `skipped_multi_sku == 0` — confirms the one-listing-per-variation model
  holds. If this is non-zero, stop and investigate upstream Cairn sync
  (`D:\claw\core\etsy_intel\sync.py::_parse_receipts`).

### 2. Manufacture `.env` — add credentials

Required additions to `/opt/nbne/manufacture/.env` on Hetzner (see
`backend/.env.example` for the authoritative list):

```
SALES_VELOCITY_WRITE_ENABLED=False
CAIRN_API_URL=http://nbne1:8765
CAIRN_API_KEY=<value of CLAW_API_KEY on nbne1>
EBAY_CLIENT_ID=<copied from render .env>
EBAY_CLIENT_SECRET=<copied from render .env>
EBAY_RU_NAME=<manufacture's eBay redirect URI, see below>
EBAY_ENVIRONMENT=production
```

### 3. eBay dev app — register manufacture's redirect URI

The eBay OAuth consent flow needs a redirect URI registered on the eBay dev
app (the same app render uses). Go to eBay Developer Program → Your App →
User Tokens → "Get a Token from eBay via Your Application" → add a new RU
name pointing at manufacture's callback URL, e.g.
`https://manufacture.nbnesigns.co.uk/admin/oauth/ebay/callback`.

Paste the RU name value into `EBAY_RU_NAME` in the manufacture `.env`.

### 4. Run the eBay consent flow (one-time, per environment)

After deploying manufacture with the env vars set:

1. Log into `https://manufacture.nbnesigns.co.uk/admin/` as a staff user.
2. Visit `https://manufacture.nbnesigns.co.uk/admin/oauth/ebay/connect`.
3. You'll be redirected to eBay's consent page. Log in and approve the scopes.
4. eBay redirects back to `/admin/oauth/ebay/callback?code=...&state=...`.
5. The callback view upserts the `OAuthCredential(provider='ebay')` row.
6. You should see a success page showing the token expiry.

If this fails:
- `HTTP 400 — eBay rejected the authorization code`: the `EBAY_RU_NAME` in
  manufacture's `.env` doesn't match what's registered on the eBay dev app.
  Double-check the exact string.
- `State mismatch`: browser session expired between `/connect` and
  `/callback`. Restart the flow.

### 5. Run `migrate` and restart qcluster

```bash
docker compose -f docker/docker-compose.yml run --rm backend python manage.py migrate
docker compose -f docker/docker-compose.yml restart backend qcluster
```

The `0002_register_daily_schedule` migration registers three Django-Q
Schedule rows:
- `sales_velocity_daily_refresh` — DAILY 04:17 UTC
- `sales_velocity_weekly_sanity` — WEEKLY Monday 06:42 UTC
- `sales_velocity_purge_audit` — WEEKLY Sunday 05:07 UTC

The qcluster needs a restart to pick up new schedule entries.

---

## Day-to-day operations

### The daily aggregator

Runs automatically every day at 04:17 UTC. It:

1. Calls all 9 Amazon marketplace adapters + Etsy (via Cairn) + eBay.
2. Joins external SKUs to Products channel-agnostically via the SKU table.
3. Writes today's snapshot to `SalesVelocityHistory`.
4. Captures unknowable SKUs into `UnmatchedSKU`.
5. If `SALES_VELOCITY_WRITE_ENABLED=True`, writes the 60-day equivalent
   (sum × 2) into `StockLevel.sixty_day_sales`.

### Manually triggering the aggregator

```bash
docker compose exec backend python manage.py refresh_sales_velocity
```

Options:
- `--dry-run` — make real API calls but roll back all DB writes
- `--channels=amazon_uk,etsy` — only run specific adapters
- `--days=7` — lookback window (default 30)

Or via the UI: Sales Velocity tab → "Refresh now" button. This enqueues
an async task via Django-Q; the tab auto-reloads after ~3 seconds.

### Flipping shadow mode to live (cutover)

Shadow mode is the default. While shadow mode is on, the aggregator writes
to `SalesVelocityHistory` but does **not** touch `StockLevel.sixty_day_sales`.
This lets you eyeball the diff for N days (brief suggests 14) via the Sales
Velocity tab's "Shadow vs Live" panel.

To cut over:

1. Open the Sales Velocity tab. Sort the Shadow/Live panel by variance.
2. For any product with >20% variance, investigate: is the spreadsheet
   baseline stale, or is the API reporting something wrong?
3. When happy, edit `/opt/nbne/manufacture/.env` and set:
   ```
   SALES_VELOCITY_WRITE_ENABLED=True
   ```
4. Restart the backend + qcluster:
   ```bash
   docker compose -f docker/docker-compose.yml restart backend qcluster
   ```
5. On the next daily run (or manual refresh), the aggregator will write
   through to `StockLevel.sixty_day_sales`. The **first** write-through
   fires a one-off `cutover` audit row in `SalesVelocityAPICall`, visible
   in Django admin at
   `/admin/sales_velocity/salesvelocityapicall/?q=cutover`.
6. The Shadow/Live panel disappears from the UI. The post-cutover weekly
   sanity check starts running Mondays at 06:42 UTC.

### Rolling back to shadow mode

Set `SALES_VELOCITY_WRITE_ENABLED=False` in `.env` and restart. The
aggregator stops updating `StockLevel`. **Note:** this does NOT revert
previously-written `StockLevel.sixty_day_sales` values — you'd need to
re-import the spreadsheet-fed values manually if you wanted to fully
roll back.

### Dealing with unmatched SKUs

The Sales Velocity tab has an "Unmatched SKUs" panel. Each row is a SKU
returned by an adapter that didn't join to any Product in the SKU table.

- **Map** — opens a prompt for a numeric Product ID. On submit, creates a
  new `products.SKU` row linking the external SKU to the Product, and
  marks the unmatched entry as resolved. The next aggregator run picks up
  the resolution.
- **Ignore** — marks the entry as ignored so it disappears from the
  panel. Useful for throwaway Amazon test orders, sample shipments, etc.

The rolling 30-day counter on `UnmatchedSKU.units_sold_30d` is overwritten
on every aggregator run — a SKU that stops selling decays to zero naturally.

### Dealing with drift alerts

After cutover, the weekly sanity check (Mondays at 06:42 UTC) compares
today's velocity to the 7-day rolling average. Any product with >5%
variance gets a `DriftAlert` row, shown in the Sales Velocity tab with
a red border.

Alerts are informational only — they do NOT auto-revert
`StockLevel.sixty_day_sales`. Use the "Acknowledge" button to dismiss
an alert once you've confirmed it's expected (e.g. seasonal spike).

Acknowledged alerts auto-purge after 90 days via the weekly
`sales_velocity_purge_audit` schedule.

### Reconnecting eBay if the token is revoked

If the eBay red "reauth required" pill appears in the Sales Velocity tab:

1. Log in as staff.
2. Visit `/admin/oauth/ebay/connect`.
3. Re-consent in the eBay UI.
4. The callback upserts the OAuthCredential row with a fresh refresh token.
5. Next aggregator run picks it up automatically.

---

## Troubleshooting

### Amazon adapter: "throttled on get_orders"

The Orders API has a sustained rate of 0.0167 req/s with a burst of 20.
The adapter handles throttling with exponential backoff (2s → 4s → 8s, max
3 retries), but if all three retries fail the channel is recorded as errored
for that run and the other channels proceed.

Check the audit log:
```
/admin/sales_velocity/salesvelocityapicall/?channel=amazon_uk&response_status=429
```

If throttling is persistent, the issue is usually a separate process
hitting the same marketplace credentials — check that `barcodes` and
`restock` modules aren't running concurrently with the sales velocity
04:17 UTC slot.

### Etsy adapter: "Cairn unreachable"

The Etsy adapter depends on Cairn being up at 04:17 UTC. If Cairn is
down:
- The Etsy leg of that day's aggregation is skipped.
- Other channels still run.
- An audit row is written with `endpoint='GET /etsy/sales'` and
  `error_message='ConnectError: ...'`.
- The next daily run tries again.

No auto-retry within the same day. If Cairn is down for longer than
24 hours, consider running `refresh_sales_velocity --channels=etsy`
manually after Cairn comes back up.

### "Duplicate SKU mapping to multiple products"

The aggregator's channel-agnostic SKU join has a safety mechanism: if one
external SKU matches multiple `SKU` rows pointing to **different**
Products, the row is SKIPPED with a warning logged to `SalesVelocityAPICall`
and counted in `total_duplicate_skus_skipped`.

This should never happen in practice — Ivan's SKU taxonomy is meant to be
1:1 SKU → Product. If you see duplicates reported, investigate:

```sql
SELECT sku, COUNT(DISTINCT product_id) AS n, ARRAY_AGG(DISTINCT product_id)
FROM products_sku
GROUP BY sku
HAVING COUNT(DISTINCT product_id) > 1;
```

Then fix the underlying SKU data via Django admin or a one-off migration.

### "I flipped WRITE_ENABLED but StockLevel didn't update"

1. Did you restart the **qcluster** container? Django-Q reads the env var
   at worker start. A backend-only restart misses the change.
2. Did the daily schedule fire after the flip? Check the Sales Velocity
   tab header for "Last snapshot" — if it hasn't updated since the flip,
   trigger a manual `refresh_sales_velocity`.
3. Is there a `cutover` audit row? If yes, the flip took effect. Check
   the Django admin for `StockLevel` rows.

### "Tests pass locally but fail in production"

The test suite uses pytest-django `settings` fixtures, not the
`@override_settings` class decorator. Django 5 rejects the latter on
non-`SimpleTestCase` classes. Same pattern as the `barcodes` test
migration in `CLAUDE.md`.

---

## Known limitations (v1)

- **Gross shipped units only.** The Amazon adapter filters to shipped
  orders but does not net out returns via `getOrderMetrics` or the
  Reports API. Returns are <5% for NBNE's product mix; if this becomes
  a problem, add a returns adapter in a follow-up phase.
- **30-day fixed lookback.** No seasonality adjustment. The 60-day
  equivalent is just `units_sold_30d * 2`. Seasonality comes in a
  follow-up once `SalesVelocityHistory` has enough data.
- **No concurrency.** Amazon adapters run sequentially, not in parallel.
  Saleweaver shares a single HTTP client internally so concurrent calls
  would just race the rate limiter.
- **Cairn dependency for Etsy.** If Cairn is down at 04:17 UTC, the Etsy
  leg fails. Alternative (building `ebay_intel` into Cairn and reading
  both legs from there) is a future architectural cleanup.
- **Single Etsy shop.** Copper Bracelets Shop is out of scope — it
  doesn't sell M-numbered products. If that changes, edit Cairn's
  `ETSY_SHOP_IDS` env var and the aggregator picks up the new data
  automatically.
- **No auto-map for unmatched SKUs.** Resolution is manual via the
  tab UI. If the unmatched-SKU panel grows to hundreds of rows,
  consider a bulk-import command.

---

## Related files

- Implementation brief: `docs/sales_velocity_brief.md`
- Models + channel classification: `backend/sales_velocity/models.py`
- Adapter framework: `backend/sales_velocity/adapters/__init__.py`
- Amazon adapter: `backend/sales_velocity/adapters/amazon.py`
- Etsy adapter: `backend/sales_velocity/adapters/etsy.py`
- eBay adapter + OAuth: `backend/sales_velocity/adapters/ebay.py` +
  `backend/sales_velocity/views_oauth.py`
- Aggregator: `backend/sales_velocity/services/aggregator.py`
- Schedule migration: `backend/sales_velocity/migrations/0002_register_daily_schedule.py`
- Frontend: `frontend/src/app/sales-velocity/page.tsx`
- Tests: `backend/sales_velocity/tests/`
