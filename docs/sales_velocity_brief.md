# Manufacture App — Sales Velocity Module
## Claude Code Implementation Brief (Patched — Phase 2B)

**Repo:** `github.com/NBNEORIGIN/manufacture`
**Base commit:** `87bacc8` (blanks tool just shipped)
**Depends on:** Feature 1 (FNSKU sync) and Feature 2 (FBA shipment automation) complete and merged.
**Cross-project dependency:** a new `/etsy/sales` endpoint on Cairn (`D:\claw`) — see Phase 2B.0.

> **Status:** This is the patched brief — it supersedes
> `SALES_VELOCITY_CC_PROMPT.md` (the original skeleton) and applies every
> correction from `SALES_VELOCITY_CC_PROMPT_CORRECTIONS.md`, every user
> modification from the 2026-04-11 Opus planning session, and the Option B
> architecture decision (Cairn handles Etsy, manufacture handles eBay).
> Do not read the original skeleton in isolation — it has known errors about
> Postmark, systemd scheduling, channel codes, and OAuth.

---

## Decisions baked in (do not re-litigate)

1. **Scheduling:** Django-Q2 `Schedule` entries in data migrations, **not** systemd timers or host cron. The `manufacture-qcluster-1` container already processes the schedule queue.
2. **Notifications:** no email infrastructure in this feature. All status/diff/drift surfaces live in the Sales Velocity Next.js tab. (User decision: `"this should just be a simple api pull and compilation of sales to determine a 60 day stock value"`.) Existing SMTP alert path in `fba_alert_stuck_plans.py` is untouched; no `core/notifications.py` is extracted as part of this feature. Postmark migration is a separate follow-up.
3. **Variance/cutover gate:** **shadow mode** controlled by `SALES_VELOCITY_WRITE_ENABLED` env var (default `False`). No Google Sheets integration. Ben eyeballs the Shadow/Live diff panel in the Sales Velocity tab for N days, flips the env var when satisfied. Weekly drift sanity check runs post-cutover and populates a `DriftAlert` panel in the same tab.
4. **Tab placement:** new entry inside the **Other** dropdown (`frontend/src/app/client-layout.tsx`), alongside Materials, Records, Import. Violet bauble `#674ea7`. Sales velocity is analytics, not shipments.
5. **Channel vocabulary:** `sales_velocity` uses its own `CHANNEL_CHOICES` namespace (`amazon_uk`, `etsy`, `ebay`, …). Join to `products.SKU` is **channel-agnostic** on `SKU.sku → Product`. `SKU_CHANNEL_MAP` exists only for display/attribution, not join logic. Duplicate `external_sku` across multiple Products is logged to the audit trail and **skipped** — never silently resolved.
6. **OAuth architecture — Option B:**
   - **Etsy:** Cairn (`D:\claw\core\etsy_intel\`) already handles Etsy OAuth + daily receipt sync into its `etsy_sales` Postgres table. Manufacture reads a new `GET /etsy/sales` endpoint on Cairn that aggregates `etsy_sales` by listing_id for the last N days. Manufacture holds **no Etsy credentials**. Cross-module access is via Cairn's existing `X-API-Key` header auth (`CLAW_API_KEY`).
   - **eBay:** no existing NBNE integration reads eBay orders. Manufacture implements its own OAuth flow, ported in pattern from `D:\render\ebay_auth.py`, with refresh tokens stored in a new `OAuthCredential` Django model. Client ID/secret reused from render's existing eBay app (same app, new consent grant).
7. **v1 scope:** gross shipped units, no returns netting. Documented as a known limitation; revisit if returns exceed 5%.
8. **Single Etsy shop:** NBNE Print and Sign only. The secondary Copper Bracelets Shop is out of scope (doesn't sell M-numbered products).

---

## Context

NBNE currently calculates 60-day sales velocity manually: download orders from each Amazon marketplace, Etsy, and eBay; paste into Google Sheets; run pivot tables to map SKUs to M-numbers; pro-rata to a 60-day equivalent; copy results back into the manufacture pipeline. Hours per week, error-prone, only as fresh as the last manual run.

This module automates the entire process:
- **Amazon SP-API** (already integrated): 9 marketplaces — UK, US, CA, AU, DE, FR, ES, NL, IT.
- **Etsy** via Cairn's existing sync: read-only HTTP call to `cairn.nbnesigns.co.uk/etsy/sales`. No Etsy credentials in manufacture.
- **eBay Sell API**: new integration, OAuth flow lives in manufacture, refresh tokens in `OAuthCredential` model.
- **Manual entry** for footfall (no API).
- **Stub adapter** for `app.nbnesigns.co.uk/shop` (deferred until that app exists).

A daily Django-Q schedule pulls 30 days of orders from every channel, joins to M-numbers via the existing `SKU` table channel-agnostically, snapshots per-channel velocity into `SalesVelocityHistory`, and (once `SALES_VELOCITY_WRITE_ENABLED=True`) writes 60-day equivalents into `StockLevel.sixty_day_sales` for use by the Make List priority score and the Restock Newsvendor planner.

---

## Canonical vocabulary

- **Velocity** — units sold per unit time per M-number per channel.
- **Snapshot** — a point-in-time `SalesVelocityHistory` row for one `(product, channel, snapshot_date)` tuple.
- **Lookback window** — 30 days, doubled to estimate 60-day equivalent for `StockLevel.sixty_day_sales`. Will become smarter once seasonality data accumulates (out of scope for v1).
- **Channel** — one of the keys in `CHANNEL_CHOICES` below.
- **Unmatched SKU** — a SKU returned by an adapter that doesn't map to any `Product` via the `SKU` table.
- **Shadow mode** — the `SALES_VELOCITY_WRITE_ENABLED=False` state: velocity is computed and stored in `SalesVelocityHistory` but `StockLevel.sixty_day_sales` is not touched. The Sales Velocity tab shows a Shadow-vs-Live diff panel.
- **Cutover** — flipping `SALES_VELOCITY_WRITE_ENABLED=True`, after which the aggregator writes through to `StockLevel.sixty_day_sales` on the next daily run.
- **Drift alert** — a post-cutover anomaly where the weekly sanity check at 5% tolerance finds an M-number whose current API-derived velocity has drifted from the `SalesVelocityHistory` 7-day rolling average. Surfaced in the Sales Velocity tab; no email.

---

## Architecture

```
 ┌─────────────────────────────┐
 │ Channel adapters            │
 │  - AmazonAdapter × 9 mkts   │──┐
 │  - EtsyAdapter (→ Cairn)    │  │   ┌──────────────────┐    ┌─────────────────┐
 │  - EbayAdapter (→ eBay API) │  ├──▶│ SalesAggregator  │───▶│ SalesVelocity-  │
 │  - ManualAdapter (footfall) │  │   │  service         │    │ History         │
 │  - ShopAdapter (stub)       │  │   │  - dedupe        │    │ UnmatchedSKU    │
 └─────────────────────────────┘  │   │  - SKU join      │    │ ManualSale      │
          ▲            ▲          │   │    (agnostic)    │    │ SalesVelocity-  │
          │            │          │   │  - aggregate     │    │ APICall (audit) │
 ┌────────┴─────┐   ┌──┴───────┐  │   │  - shadow gate   │    │ OAuthCredential │
 │ Feature 1    │   │ Cairn    │  │   │  - (opt) write   │    │ DriftAlert      │
 │ SP-API client│   │ /etsy/   │  │   │    StockLevel    │    └─────────────────┘
 └──────────────┘   │ sales    │  │   └──────────────────┘           │
                    │ endpoint │  │          ▲                        ▼
                    └──────────┘  │          │               ┌─────────────────┐
                                  │          │               │ Sales Velocity  │
                                  │   ┌──────┴─────────┐     │ tab (UI)        │
                                  └──▶│ Django-Q       │     │  - per-channel  │
                                      │ Schedule.DAILY │     │  - sparklines   │
                                      │ 04:17 UTC      │     │  - Shadow/Live  │
                                      └────────────────┘     │    diff panel   │
                                                             │  - DriftAlert   │
                                                             │    panel        │
                                                             │  - Unmatched    │
                                                             │  - Footfall     │
                                                             └─────────────────┘
```

---

## Phase 2B.0 — Prerequisites

This phase splits into a **Cairn-side** sub-phase and a **manufacture-side** sub-phase. Cairn work runs first.

### 2B.0(a) — Cairn-side work (repo: `D:\claw`)

All Cairn work happens on a **new branch** (`feat/etsy-sales-endpoint`), not master. In-flight changes to `scripts/backfill/` and `wiki/modules/` from a parallel chat instance are orthogonal to this work, but a branch is safer in case of rebase.

Cairn's `CLAUDE.md` protocol is the governing document for this sub-phase. Follow Steps 1–5 (retrieve → classify → implement → write-back → reindex) before committing.

1. **Add `GET /etsy/sales` endpoint** to `api/routes/etsy_intel.py`:
   - Query params: `days: int = 30`, `shop_id: int | None = None` (optional filter — default is "all configured shops").
   - Auth: `Depends(verify_api_key)` from `api/middleware/auth.py`. This is a new dependency on this route file — the existing `/etsy/*` routes have no auth, but the new `/etsy/sales` endpoint **must** require the `X-API-Key` header. Retrofitting auth to the rest of `/etsy/*` is out of scope for this feature unless the user asks.
   - Response: pre-aggregated JSON. One object per `listing_id` that had any sales in the window:
     ```json
     {
       "shop_id": 12345,
       "listing_id": 67890,
       "external_sku": "NBN-M0823-LG-OAK",
       "total_quantity": 14,
       "first_sale_date": "2026-03-12T09:31:00Z",
       "last_sale_date": "2026-04-10T16:02:44Z",
       "window_days": 30,
       "window_end": "2026-04-11"
     }
     ```
   - `external_sku` comes from joining `etsy_sales.listing_id → etsy_listings.sku` (verify that column exists in `etsy_listings`; if not, extend `etsy_intel.sync._parse_receipts` to capture sku from the transaction payload — Etsy receipts include per-transaction SKU).
   - SQL sketch:
     ```sql
     SELECT el.shop_id, el.listing_id, el.sku AS external_sku,
            SUM(es.quantity) AS total_quantity,
            MIN(es.sale_date) AS first_sale_date,
            MAX(es.sale_date) AS last_sale_date
     FROM etsy_sales es
     JOIN etsy_listings el ON el.listing_id = es.listing_id
     WHERE es.sale_date >= NOW() - INTERVAL ':days days'
       AND (:shop_id IS NULL OR el.shop_id = :shop_id)
     GROUP BY el.shop_id, el.listing_id, el.sku
     ORDER BY el.listing_id;
     ```
   - Empty result set is returned as `{"rows": [], "window_end": "...", "window_days": N}` — not a 404.
2. **Tests** at `tests/api/routes/test_etsy_intel_sales.py`:
   - fixture rows in `etsy_sales` + `etsy_listings`, assert aggregation shape
   - auth required (401 without header, 200 with correct header, 401 with wrong header)
   - `days=7` filters correctly
   - `shop_id` filter works
   - empty window returns `{"rows": []}`
3. **Decision log + wiki update** per Cairn's `CLAUDE.md` Step 4. Update `projects/etsy-intelligence/core.md` and `wiki/modules/etsy-intelligence.md` with a one-paragraph entry noting the new endpoint.
4. **Reindex** per Cairn Step 5: `POST http://localhost:8765/index?project=claw`.
5. **Deploy to Hetzner nbne1** (this is Toby's call — the AI stops here and asks for permission before the Cairn PR merges).

### 2B.0(b) — Manufacture-side prerequisites

1. Confirm Feature 2 is merged and `FBAAPICall` audit log shows healthy SP-API operation. `python manage.py fba_preflight_check --marketplace UK`.
2. **Verify SKU↔M-number mapping completeness** (query has already been run once as part of the 2026-04-11 planning session — rerun if SKU data has changed):
   ```sql
   SELECT DISTINCT channel FROM products_sku ORDER BY channel;
   ```
   Expected values (from 2026-04-11 planning session):
   - In scope: `UK`, `US`, `CA`, `AU`, `DE`, `FR`, `ES`, `NL`, `IT`, `FR_CRAFTS`, `FR CRAFTS`, `FR_DESIGNED`, `IT_DESIGNED`, `ETSY`, `EBAY`
   - Out of scope: `SHOPIFY` (deprecated), `STOCK` (sentinel)
   - Data cleanup follow-up (not modelled): `AMAZON` (generic, probably migration debris), `ETSYOD001198` (garbage), `M0781 IS FREE TO USE` (garbage)
   - Normalise on load: `FR CRAFTS` (space) → `FR_CRAFTS` (underscore) — treat as typo.
   - Flag any **new** channel value not in the expected list: fail the migration/test rather than silently drop rows.
3. **Add new env vars** to `backend/.env.example` with placeholder values and inline comments explaining the source:
   ```
   # Cross-service read-only access to Cairn's Etsy sales endpoint
   # (Option B architecture: Etsy OAuth lives in Cairn, not here)
   CAIRN_API_BASE=http://nbne1:8765
   CAIRN_API_KEY=<value of CLAW_API_KEY on the Cairn host>

   # eBay OAuth credentials (reused from render app's eBay developer app)
   # Manufacture gets its own refresh token via a one-time consent flow;
   # this does not affect render's separate grant.
   EBAY_CLIENT_ID=<from render .env>
   EBAY_CLIENT_SECRET=<from render .env>
   EBAY_RU_NAME=<manufacture's own redirect URI, registered in eBay dev app>
   EBAY_ENVIRONMENT=production

   # Shadow mode gate — flip to True only after the Sales Velocity tab's
   # Shadow/Live diff has been eyeballed for N days and looks sane.
   SALES_VELOCITY_WRITE_ENABLED=False
   ```
4. Verify `AMAZON_REFRESH_TOKEN_EU/NA/AU` cover all 9 Amazon marketplaces in scope (FR/ES/NL/IT share the EU token; confirm via `fba_preflight_check`).

### Acceptance

- Cairn `/etsy/sales` endpoint deployed to Hetzner, `X-API-Key` auth verified with curl.
- Manufacture `.env.example` contains the six new vars with placeholders.
- `python manage.py check` passes.
- Channel-coverage query has been run and results pasted into this brief (replace the 2026-04-11 baseline if it has drifted).
- Feature 2 health check passes.

---

## Phase 2B.1 — Models

Create new Django app: `sales_velocity`. Inherit from `core.models.TimestampedModel`.

```python
# sales_velocity/models.py
from core.models import TimestampedModel

# NOTE: sales_velocity channels use their own namespace which deliberately
# differs from products.SKU.channel. The SKU_CHANNEL_MAP below is
# informational (used for display/attribution in the UI) — the aggregator
# does NOT use it for join logic. Join is channel-agnostic on SKU.sku.

CHANNEL_CHOICES = [
    ('amazon_uk', 'Amazon UK'),
    ('amazon_us', 'Amazon US'),
    ('amazon_ca', 'Amazon CA'),
    ('amazon_au', 'Amazon AU'),
    ('amazon_de', 'Amazon DE'),
    ('amazon_fr', 'Amazon FR'),
    ('amazon_es', 'Amazon ES'),
    ('amazon_nl', 'Amazon NL'),
    ('amazon_it', 'Amazon IT'),
    ('etsy',      'Etsy'),
    ('ebay',      'eBay'),
    ('footfall',  'Footfall'),
    ('shop',      'Shop (stub)'),
]

# Display-only mapping from sales_velocity channel code to the set of
# products.SKU.channel values attributed to it. Used by the UI's per-channel
# breakdown columns. NOT used by the aggregator's join logic.
#
# FR_CRAFTS, FR CRAFTS, FR_DESIGNED, IT_DESIGNED are normalised onto their
# base Amazon marketplace (Option A, per 2026-04-11 user decision) — the
# subcategory subdivision is not preserved in sales velocity.
SKU_CHANNEL_MAP = {
    'amazon_uk': {'UK'},
    'amazon_us': {'US'},
    'amazon_ca': {'CA'},
    'amazon_au': {'AU'},
    'amazon_de': {'DE'},
    'amazon_fr': {'FR', 'FR_CRAFTS', 'FR CRAFTS', 'FR_DESIGNED'},
    'amazon_es': {'ES'},
    'amazon_nl': {'NL'},
    'amazon_it': {'IT', 'IT_DESIGNED'},
    'etsy':      {'ETSY'},
    'ebay':      {'EBAY'},
    'footfall':  set(),   # manual entry, no SKU join
    'shop':      set(),   # stub until shop backend exists
}

# Explicit "we know about these and ignored them" set — prevents silent
# drop of unexpected channel values. A new Amazon marketplace in SKU data
# that is not covered here will fail the test suite.
CHANNELS_OUT_OF_SCOPE = {'SHOPIFY', 'STOCK'}

# Known garbage rows to be cleaned up in a separate data-cleanup follow-up.
# Keeping them here as an explicit allow-list prevents test failures while
# we wait for Ben/Gabby to decide how to clean the SKU table.
CHANNELS_DATA_CLEANUP = {'AMAZON', 'ETSYOD001198', 'M0781 IS FREE TO USE'}


class SalesVelocityHistory(TimestampedModel):
    """Daily snapshot of 30-day rolling units sold per (product, channel)."""
    product = models.ForeignKey(
        'products.Product', on_delete=models.CASCADE,
        related_name='velocity_snapshots',
    )
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, db_index=True)
    snapshot_date = models.DateField(db_index=True)
    units_sold_30d = models.PositiveIntegerField()
    # NOTE: raw_response deliberately lives on SalesVelocityAPICall, not here,
    # to keep this hot table small and indexable.

    class Meta:
        unique_together = [('product', 'channel', 'snapshot_date')]
        indexes = [models.Index(fields=['product', 'snapshot_date'])]


class UnmatchedSKU(TimestampedModel):
    """
    A SKU returned by an adapter that doesn't map to any Product.

    `units_sold_30d` is a ROLLING counter overwritten on each aggregator run —
    it reflects the most recent 30-day window, not a cumulative total.
    `first_seen` / `last_seen` track the full discovery lifecycle; a SKU
    that stops selling retains its last_seen date but its units_sold_30d
    decays to zero as the rolling window moves past it.
    """
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    external_sku = models.CharField(max_length=120, db_index=True)
    title = models.CharField(max_length=200, blank=True)
    units_sold_30d = models.PositiveIntegerField(default=0)
    first_seen = models.DateField()
    last_seen = models.DateField()
    ignored = models.BooleanField(default=False, help_text="User explicitly ignored this SKU")
    resolved_to = models.ForeignKey(
        'products.Product', null=True, blank=True, on_delete=models.SET_NULL,
    )

    class Meta:
        unique_together = [('channel', 'external_sku')]


class ManualSale(TimestampedModel):
    """Footfall or other manually-entered sales not captured by any API."""
    product = models.ForeignKey('products.Product', on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    sale_date = models.DateField()
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, default='footfall')
    notes = models.TextField(blank=True)
    entered_by = models.ForeignKey('auth.User', null=True, on_delete=models.SET_NULL)


class SalesVelocityAPICall(TimestampedModel):
    """
    Audit log for every adapter call — parallel to FBAAPICall. Raw request
    and response live here, NOT on SalesVelocityHistory, so the snapshot
    table stays small and indexable.

    Cleanup policy: a Django-Q scheduled command (`sales_velocity_purge_audit`)
    deletes rows older than 14 days on a weekly cadence. Failed calls are
    retained for 90 days.

    PII: before persisting `response_body`, strip customer-level fields
    (BuyerName, BuyerEmail, ShippingAddress, etc.). Whitelist keys to keep
    (external_sku, quantity, sale_date, order_id for dedupe) rather than
    blacklisting what to drop.
    """
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, db_index=True)
    endpoint = models.CharField(max_length=120)
    request_params = models.JSONField(null=True, blank=True)
    response_status = models.IntegerField(null=True)
    response_body = models.JSONField(null=True, blank=True)  # PII-stripped
    duration_ms = models.IntegerField(null=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['channel', '-created_at']),
            models.Index(fields=['response_status']),
        ]


class OAuthCredential(TimestampedModel):
    """
    OAuth2 refresh-token storage for providers whose OAuth flow lives in
    manufacture itself (currently: eBay only — Etsy is handled by Cairn and
    is accessed via the Cairn /etsy/sales endpoint, so no Etsy row exists
    in this table).

    One row per provider. Adapter refreshes the access token in-place when
    it's within 5 minutes of expiry, holding a SELECT FOR UPDATE lock to
    avoid refresh races between the qcluster worker and the web process.
    """
    PROVIDER_CHOICES = [('ebay', 'eBay')]

    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, unique=True)
    refresh_token = models.TextField()
    access_token = models.TextField(blank=True)
    access_token_expires_at = models.DateTimeField(null=True, blank=True)
    last_refreshed_at = models.DateTimeField(null=True, blank=True)
    scope = models.TextField(blank=True, help_text="Space-separated OAuth scopes")
    # No client_id/client_secret here — those come from env vars
    # (EBAY_CLIENT_ID / EBAY_CLIENT_SECRET) so rotating the app credentials
    # doesn't require a DB migration.


class DriftAlert(TimestampedModel):
    """
    Post-cutover drift warning: the weekly sanity check at 5% tolerance
    found an M-number whose current API-derived velocity has moved more
    than 5% from the 7-day rolling average in SalesVelocityHistory.

    These are surfaced in the Sales Velocity tab's DriftAlert panel.
    Acknowledging an alert marks it as seen but does not delete it —
    retention is 90 days then automatic purge.
    """
    product = models.ForeignKey('products.Product', on_delete=models.CASCADE)
    detected_at = models.DateTimeField()
    current_velocity = models.PositiveIntegerField()
    rolling_avg_velocity = models.PositiveIntegerField()
    variance_pct = models.DecimalField(max_digits=6, decimal_places=2)
    acknowledged = models.BooleanField(default=False)
    acknowledged_by = models.ForeignKey(
        'auth.User', null=True, blank=True, on_delete=models.SET_NULL,
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-detected_at']
```

**Deleted vs the original brief:** `VarianceGateState` is gone — shadow mode replaces it. `SalesVelocityHistory.raw_response` is gone — moved to `SalesVelocityAPICall`.

**Added:** `SalesVelocityAPICall` (audit log), `OAuthCredential` (eBay only), `DriftAlert` (post-cutover safety panel).

Add `'sales_velocity'` to `INSTALLED_APPS`. Migrations + admin pages.

---

## Phase 2B.2 — Channel adapter ABC + Amazon adapter

Pattern matches Feature 2's wrapper approach. Each adapter:
- Inherits `ChannelAdapter` ABC.
- Implements `fetch_orders(start_date, end_date) -> list[NormalisedOrderLine]`.
- Handles its own pagination, rate limiting, and retries internally.
- Returns a flat list of `NormalisedOrderLine(external_sku, quantity, sale_date, raw_data)`.
- Writes an audit row to `SalesVelocityAPICall` for every outbound call (PII-stripped).

**Amazon adapter:** reuses the Feature 1 SP-API client. Calls `getOrders` per marketplace, paginates via `NextToken`, filters to shipped orders only. **9 `AmazonAdapter` instances** total: UK, US, CA, AU, DE, FR, ES, NL, IT.

**Critical inspection step:** before coding, verify the `saleweaver` (or python-amazon-sp-api) `Orders` API method names exist in the installed version. Class/method names drift across minor versions — this has burned Features 1 and 2 before. Open a Python shell and dir() the Orders client before writing the wrapper.

**Out of scope for v1: net-of-returns.** Adapters report gross shipped units. The Amazon adapter filters to shipped orders only (which catches pre-ship cancellations) but makes no attempt to subtract post-ship returns via `getOrderMetrics` or the Reports API. Returns are typically <5% for NBNE's product mix; if this becomes a problem, add a returns adapter in a follow-up phase. Document this limitation in `docs/sales_velocity_operations.md` before the cutover.

---

## Phase 2B.3 — Etsy adapter (Cairn proxy) + eBay adapter (native OAuth)

### EtsyAdapter — thin HTTP wrapper over Cairn

Under Option B, the Etsy adapter is **~40 LOC**. No OAuth state, no token refresh, no Etsy API endpoints — just an authenticated HTTP call to Cairn.

```python
# sales_velocity/adapters/etsy.py (sketch)
class EtsyAdapter(ChannelAdapter):
    channel = 'etsy'

    def fetch_orders(self, start_date, end_date):
        days = (end_date - start_date).days
        resp = requests.get(
            f"{settings.CAIRN_API_BASE}/etsy/sales",
            headers={'X-API-Key': settings.CAIRN_API_KEY},
            params={'days': days},
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        # Log to audit trail, PII-stripped (no buyer info from Cairn anyway)
        self._log_audit(endpoint='/etsy/sales', response=payload)
        return [
            NormalisedOrderLine(
                external_sku=row['external_sku'],
                quantity=row['total_quantity'],
                sale_date=row['last_sale_date'],
                raw_data={'cairn_row': row},
            )
            for row in payload['rows']
            if row.get('external_sku')
        ]
```

**Failure mode:** if Cairn is down at 04:17 UTC (the daily schedule slot), the Etsy adapter raises and the aggregator logs the failure in `SalesVelocityAPICall` with `error_message` set. The other channels still run. The Etsy leg of that day's aggregation is skipped; the Sales Velocity tab shows the last successful Etsy sync date per-channel. No email, no auto-retry within the same day — the next day's schedule picks it up. If this proves to be a problem in practice, add a retry loop with exponential backoff in a follow-up phase.

### EbayAdapter — native OAuth

Ported in pattern (not copy-pasted) from `D:\render\ebay_auth.py`. eBay's OAuth is Basic-auth at the token endpoint with an 18-month refresh token lifetime. Scopes needed: `https://api.ebay.com/oauth/api_scope`, `sell.fulfillment` (for `/sell/fulfillment/v1/order` — the getOrders equivalent).

Components:
1. **One-time consent flow**: a small admin-only Django view at `/admin/oauth/ebay/connect` that generates the authorization URL and redirects the browser. Callback at `/admin/oauth/ebay/callback` exchanges the code for tokens and writes them to `OAuthCredential(provider='ebay')`. Toby runs this once per environment.
2. **Refresh logic inside the adapter**: check `OAuthCredential.access_token_expires_at`; if within 5 minutes of expiry, refresh via POST to `https://api.ebay.com/identity/v1/oauth2/token` with `grant_type=refresh_token`. Wrap the read+refresh in `SELECT ... FOR UPDATE` to avoid the qcluster-worker-and-web-process refresh race.
3. **Order fetch**: `GET /sell/fulfillment/v1/order?filter=orderfulfillmentstatus:{FULFILLED|IN_PROGRESS}&limit=200` with pagination via `next` links. Filter to the 30-day window in code. Rate limit 5000 calls/day (very generous).
4. **Audit rows** to `SalesVelocityAPICall` on every call, PII-stripped.
5. **Health check**: weekly `Schedule.WEEKLY` that forces a refresh regardless of actual expiry, so if the aggregator ever pauses for >1 year, the 18-month refresh window never lapses. Cheap insurance.

**If refresh fails (token revoked or expired):**
- Mark `OAuthCredential.access_token=''` and log to `SalesVelocityAPICall.error_message`.
- The Sales Velocity tab shows a red "eBay: reauth required" status pill.
- Admin clicks "Reconnect eBay" in the tab, which kicks the one-time consent flow again.
- No email — the UI pill is the notification surface.

**eBay client credentials:** reuse render's existing `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET`. Same eBay dev app, separate consent grant, separate refresh token. `EBAY_RU_NAME` is manufacture-specific and must be registered against the eBay dev app as a second redirect URI alongside render's.

---

## Phase 2B.4 — Aggregator service + shadow mode + Django-Q schedule

### `sales_velocity/services/aggregator.py`

```python
def run_daily_aggregation() -> dict:
    """
    1. Call every adapter for the last 30 days, collecting NormalisedOrderLines.
    2. Join external_sku → SKU.sku → Product CHANNEL-AGNOSTICALLY.
       If one external_sku matches SKU rows pointing to different Products,
       log a duplicate warning to SalesVelocityAPICall.error_message and
       SKIP the row — never silently pick one.
    3. Insert/update SalesVelocityHistory rows for today, one per
       (product, channel, snapshot_date) tuple. Re-run on same day is
       idempotent via unique_together.
    4. Capture unmatched SKUs into UnmatchedSKU (rolling 30-day counter).
    5. If settings.SALES_VELOCITY_WRITE_ENABLED is True:
         a. Compute 60-day equivalent per product: sum(units_sold_30d
            across channels) * 2.
         b. Update StockLevel.sixty_day_sales on the relevant stock rows.
         c. On the FIRST successful write-through after a flip from False,
            write a one-off row to SalesVelocityAPICall with
            endpoint='cutover' for audit purposes.
    6. Return a dict summary for the management command to print.
    """
```

### Shadow mode mechanics

- `settings.SALES_VELOCITY_WRITE_ENABLED` reads `config('SALES_VELOCITY_WRITE_ENABLED', default=False, cast=bool)` from env.
- Until flipped: `SalesVelocityHistory` fills every day, but `StockLevel.sixty_day_sales` is untouched. The Sales Velocity tab's **Shadow/Live diff panel** shows a per-M-number table: `m_number | current_stock.sixty_day_sales (spreadsheet-fed) | api_30d*2 | variance_pct | sparkline`. Sortable by variance_pct descending so Ben can eyeball the biggest differences.
- Ben watches the panel for N days (recommend 14, not enforced in code). When satisfied he sets `SALES_VELOCITY_WRITE_ENABLED=True` in `/opt/nbne/manufacture/.env` and restarts the backend + qcluster.
- On the next daily run, the aggregator flips to write-through mode and the Shadow/Live panel collapses down to "Shadow mode disabled — live since YYYY-MM-DD".

### Post-cutover sanity check

- A **weekly** Django-Q `Schedule.WEEKLY` entry runs `sales_velocity_weekly_sanity` every Monday at 06:42 UTC:
  - For each Product, compare today's `units_sold_30d * 2` against the 7-day rolling average of the same metric from `SalesVelocityHistory`.
  - If `abs(today - rolling_avg) / rolling_avg * 100 > 5`, insert a `DriftAlert` row.
  - Does **not** auto-revert `StockLevel`. Does **not** send email. The Sales Velocity tab's **DriftAlert panel** shows unacknowledged rows.
  - Old drift alerts auto-purge at 90 days via `sales_velocity_purge_audit` (same command cleans `SalesVelocityAPICall`).

### Management command

`python manage.py refresh_sales_velocity [--dry-run] [--channels=amazon_uk,etsy] [--days=30]`.
- `--dry-run` runs the full aggregation but rolls back the transaction and prints a summary.
- `--channels` filters to specific channels (e.g. skip Amazon for a test run).
- `--days` overrides the 30-day window (for backfill experiments).

### Scheduling via Django-Q

Register the daily Schedule in a **data migration** inside `sales_velocity/migrations/0002_register_daily_schedule.py`:

```python
def create_schedule(apps, schema_editor):
    from django_q.models import Schedule
    Schedule.objects.get_or_create(
        name='sales_velocity_daily_refresh',
        defaults={
            'func': 'sales_velocity.services.aggregator.run_daily_aggregation',
            'schedule_type': Schedule.DAILY,
            'next_run': datetime(2026, 4, 12, 4, 17, tzinfo=timezone.utc),
            # 04:17 UTC — after FNSKU sync (03:00) and Feature 2's hourly
            # reconciliation. 17 minutes past the hour to avoid clashing
            # with other on-the-hour jobs.
        },
    )
```

Reference pattern: `fba_shipments/services/workflow.py:225-237` uses `Schedule.objects.create(ONCE, next_run=...)` for delay-enqueued tasks. This is the first DAILY-type Schedule in the codebase — there is **no** precedent for daily recurring schedules in manufacture (the FBA stuck-plan alert still runs via host cron, per the Deployment Runbook in `CLAUDE.md`). Do not be misled by any doc claiming otherwise.

### Test requirements (non-optional)

- `sales_velocity/tests/test_aggregator.py` — covers the SKU-join logic with a fixture product that has SKUs in two channels; asserts `SalesVelocityHistory` rows are created per `(product, channel, date)` and that duplicates don't violate the unique constraint on re-run.
- `sales_velocity/tests/test_duplicate_detection.py` — asserts that when the same `external_sku` appears on `SKU` rows pointing to **different** Products, the aggregator logs a warning and **skips** the row rather than silently picking one. (Replaces the `SKU_CHANNEL_MAP` coverage test from correction #12 per user modification (b).)
- `sales_velocity/tests/test_channel_coverage.py` — asserts every value in `products.SKU.channel` that exists on prod is either covered by `SKU_CHANNEL_MAP`, `CHANNELS_OUT_OF_SCOPE`, or `CHANNELS_DATA_CLEANUP`. A new unexpected channel value fails the test.
- `sales_velocity/tests/test_shadow_mode.py` — asserts that when `SALES_VELOCITY_WRITE_ENABLED=False`, the aggregator writes to `SalesVelocityHistory` but does NOT modify `StockLevel.sixty_day_sales`, and that flipping the flag changes that behaviour on the next run. Also asserts the one-off cutover audit row is written on the first write-through.
- `sales_velocity/tests/test_etsy_adapter.py` — uses `responses` library to mock Cairn's `/etsy/sales` endpoint; asserts the adapter sends the `X-API-Key` header, handles empty payloads, and handles 5xx from Cairn gracefully (logs to audit, returns empty list, doesn't crash the aggregator).
- `sales_velocity/tests/test_ebay_adapter.py` — mocks eBay's OAuth and order endpoints; asserts refresh happens when token is within 5 min of expiry, SELECT FOR UPDATE prevents races, and 401 on getOrders marks the credential as broken.
- `sales_velocity/tests/test_drift_alert.py` — fixture data that triggers a 5% drift; asserts `DriftAlert` row is inserted and no email is sent.

---

## Phase 2B.5 — Sales Velocity tab UI

New nav entry inside the **Other** dropdown in `frontend/src/app/client-layout.tsx`, alongside Materials, Records, Import. Label: **Sales Velocity**. Violet bauble `#674ea7`.

Edits:
- Add `'/sales-velocity': '#674ea7'` to `TAB_COLOURS` (verify the hex isn't already used elsewhere — it isn't as of `87bacc8`).
- Add `{ href: '/sales-velocity', label: 'Sales Velocity' }` to the `'Other'` group's `items` array, between `/records` and `/imports`.

### Panels (top to bottom)

1. **Top status bar**: last sync timestamp, "Refresh now" button (calls the management command via API), per-channel status pills (green/amber/red), shadow-mode banner showing either `Shadow mode — writes disabled` or `Live — writing since YYYY-MM-DD`, eBay reauth-required pill if applicable.
2. **DriftAlert panel** (collapsible, only appears if count > 0, prominent red border): list of unacknowledged drift alerts with `m_number`, `variance_pct`, `detected_at`, "Acknowledge" button.
3. **Shadow/Live diff panel** (only appears if `SALES_VELOCITY_WRITE_ENABLED=False`): sortable table of `m_number | current_stock.sixty_day_sales | api_30d*2 | variance_pct | sparkline`, defaulting to sort by `|variance_pct|` descending.
4. **Unmatched SKUs panel** (collapsible, only appears if any unresolved): list with channel, external SKU, units, "Map to existing SKU" or "Ignore" buttons. "Map to existing SKU" opens an autocomplete picker that writes a new `products.SKU` row (carefully: the user approves the mapping, we don't auto-resolve).
5. **Main velocity table**: M-number, title, last 30-day total, per-channel breakdown columns, 60-day estimate, 30-day sparkline (from `SalesVelocityHistory`), status badge.
6. **Footfall entry form**: M-number autocomplete, quantity, date (default today), notes, submit. Inline list of recent manual entries with delete (admin only). Date picker allows back-dating up to 90 days (arbitrary but sensible default; confirm with Ben/Gabby if they want longer).

Frontend pattern: plain `fetch` + `useEffect` (manufacture app convention — no data-fetching library). Polling: DriftAlert count every 60s; rest of the page is refresh-on-navigate.

---

## Phase 2B.6 — Post-cutover monitoring

Renamed from "Cross-check + cutover" — the cutover mechanism is just the env var flip, so the Phase 2B.4 aggregator owns it. Phase 2B.6 is the ongoing monitoring layer.

1. **`sales_velocity_compare` management command** (typo `fba_velocity_compare` in the original brief is fixed here): ad-hoc diagnostic that prints a per-M-number variance CSV between `SalesVelocityHistory` latest and `StockLevel.sixty_day_sales`. Useful for debugging post-cutover. Not scheduled.
2. **`sales_velocity_weekly_sanity`** — scheduled Django-Q weekly, populates `DriftAlert` rows. Described in Phase 2B.4.
3. **`sales_velocity_purge_audit`** — scheduled Django-Q weekly, deletes `SalesVelocityAPICall` rows older than 14 days (90 days for errors) and `DriftAlert` rows older than 90 days.
4. **Operations doc**: `docs/sales_velocity_operations.md` documenting:
   - How to run the aggregator manually (`python manage.py refresh_sales_velocity`)
   - How to flip the shadow-mode gate
   - How to reauth eBay if the token is revoked
   - How to deal with an unmatched SKU
   - The returns-are-out-of-scope limitation
   - How to diagnose a stuck daily schedule

---

## Delivery order

1. **Phase 2B.0(a)** — Cairn `/etsy/sales` endpoint + auth + tests + deploy. Separate commit in `D:\claw`. Follow Cairn CLAUDE.md protocol. **Stop for sign-off before deploying to Hetzner.**
2. **Phase 2B.0(b)** — Manufacture prerequisites (env vars, channel coverage query, FBA health check). **Stop-and-verify.**
3. **Phase 2B.1** — Models + migrations + admin. **Stop-and-verify.**
4. **Phase 2B.2** — ChannelAdapter ABC + Amazon × 9 marketplaces. **Stop-and-verify.**
5. **Phase 2B.3** — EtsyAdapter (Cairn proxy, ~40 LOC) + EbayAdapter (OAuth, ~300 LOC). **Stop-and-verify.**
6. **Phase 2B.4** — Aggregator + shadow mode + Django-Q DAILY Schedule + weekly sanity check + management command + tests. **Stop-and-verify.**
7. **Phase 2B.5** — Sales Velocity tab UI with all panels. **Stop-and-verify.**
8. **Phase 2B.6** — Operations doc + purge commands + compare command. **Stop-and-verify.**

Stop-and-verify between every phase. No exceptions. (Lessons from Features 1 and 2 reviews — the phases that shipped cleanly all had pause-points; the ones that didn't all tried to bundle.)

---

## Patterns to inherit from previous briefs (mandatory)

1. `TimestampedModel` inheritance — never manually define `created_at`/`updated_at`.
2. JSONField mutation safety — `obj.field = obj.field + [new]`, never `.append()`.
3. Library inspection step at the start of each adapter phase before writing wrapper code.
4. `_safe_json()` helper for audit log writes (handle Decimals, datetimes).
5. Sandbox/production environment switching via env var.
6. Capture the failing step before mutating status in error handlers.
7. Per-API audit log table for debugging (parallel to `FBAAPICall` — this feature's is `SalesVelocityAPICall`).
8. **New scheduled jobs use `django_q.models.Schedule`, never systemd timers or host cron.** The `manufacture-qcluster-1` container processes the Schedule queue in production. Reference pattern: `fba_shipments/services/workflow.py:225-237`.
9. **Notifications** — this feature is deliberately email-free. If you think you need email, read the UI panel spec in Phase 2B.5 first. The existing SMTP path in `fba_alert_stuck_plans.py` is reserved for off-hours paging only.
10. **Cross-module DB access is forbidden** per `D:\claw\CLAUDE.md`. Manufacture calls Cairn's HTTP API; it does not connect to Cairn's Postgres. Same rule applies in reverse.

---

## Resolved open questions

1. **Spreadsheet access for variance gate** — resolved: shadow mode replaces the variance gate; no Google Sheets integration.
2. **Footfall historical backfill** — confirmed: start counting from day one. Manual entry form allows back-dating up to 90 days for ad-hoc corrections. Ben/Gabby do not have historical footfall data to import.
3. **Variance threshold** — resolved: shadow mode has no threshold (it's a human-eyeballs UI panel). The weekly post-cutover sanity check uses 5%.
4. **Spreadsheet refresh frequency** — resolved: N/A (no spreadsheet integration).
5. **OAuth2 refresh flow on the render app** — resolved 2026-04-11: render has `ebay_auth.py` as a solid pattern to port; render's `etsy_auth.py` is dead code (render's `.env` has no Etsy keys). Etsy is handled via Cairn, not render.
6. **Footfall form default date range** — 90 days back, today forward (confirm with Ben before 2B.5 if he wants different).
7. **Returns tolerance** — gross shipped units acceptable for v1 per Ben/Toby (see Phase 2B.2 note).
8. **Distinct channel values on prod** — captured above in Phase 2B.0(b).

## Open operational questions (not blocking)

- **Footfall back-dating window**: 90 days is arbitrary. Worth asking Ben/Gabby before Phase 2B.5.
- **DriftAlert acknowledge-then-unignore**: do we need a way to re-trigger an alert the user previously acknowledged? v1 says no, they auto-purge at 90 days.
- **Refresh-now button rate-limiting**: a user spamming the refresh button should not hammer Cairn or Amazon. v1 implementation: UI disables the button for 5 minutes after a click.
- **Amazon EU token covers all 5 EU marketplaces**: verified in principle (one LWA refresh token per region), verify in practice during Phase 2B.2.

---

## Known limitations (documented in v1)

- Gross shipped units only. No return/refund netting.
- 30-day fixed lookback, doubled for 60-day equivalent. No seasonality adjustment.
- Amazon `AMAZON` generic channel, `ETSYOD001198`, `M0781 IS FREE TO USE` are in `CHANNELS_DATA_CLEANUP` and skipped — a separate data-cleanup follow-up will handle them.
- `SHOPIFY` is deprecated and ignored.
- Copper Bracelets Shop is out of scope (doesn't sell M-numbered products).
- If Cairn is down at 04:17 UTC, the Etsy leg of that day's aggregation is skipped with no auto-retry within the day.

---

## What I would build next (after this ships)

1. **Seasonality analyser** using `SalesVelocityHistory` to detect monthly patterns and apply adjustment factors to the raw 30-day figure.
2. **Anomaly detection** flagging M-numbers whose velocity changes >50% week-on-week (similar to drift alerts but more sensitive).
3. **`ebay_intel` Cairn project** to consolidate eBay order sync into Cairn alongside Etsy, retiring manufacture's native eBay OAuth.
4. **Returns adapter** for Amazon via `getOrderMetrics` or the Reports API.
5. **Restock auto-trigger** wiring velocity changes into FBA shipment plan auto-creation.
6. **Postmark migration** for the existing SMTP alert path (`fba_alert_stuck_plans`, `core/views_bugreport`) — separate security-hardening ticket, not bundled with this feature.

---

*Patched 2026-04-11 as a review of `SALES_VELOCITY_CC_PROMPT.md` against the*
*live manufacture codebase at commit `87bacc8`, incorporating all corrections*
*from `SALES_VELOCITY_CC_PROMPT_CORRECTIONS.md` and the 2026-04-11 Opus planning*
*session decisions (email dropped, Option B architecture, channel set expanded,*
*duplicate-detection join logic).*
