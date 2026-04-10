# CLAUDE.md — Manufacture
# NBNE Production Intelligence System
# North By North East Print & Sign Ltd
# Repo: https://github.com/NBNEORIGIN/manufacture
# Local: D:\manufacture

---

## Read First

Before doing anything in this repo, read the Cairn protocol:
- `D:\claw\CAIRN_PROTOCOL.md` — your standing orders
- `D:\claw\projects\manufacturing\core.md` — this project's decision log
- Pull memory: `GET http://localhost:8765/retrieve?query=<task>&project=manufacturing&limit=10`

Do not skip retrieval. This project has domain complexity that is not obvious from
the code alone.

---

## What This Is

Manufacture is NBNE's internal production intelligence system. It replaces a complex
Excel workbook (Shipment_Stock_Sheet.xlsx, 32 tabs) that currently runs the entire
e-commerce manufacturing operation.

The core question this app answers every morning is:
**"What do we make today, and how many?"**

It does this by combining stock levels, sales velocity, optimal stock targets, and
batch planning rules into a prioritised daily make list.

**Critical context**: The current spreadsheet mostly works well. Ivan built a
Worksheet tab that already calculates the make list automatically. The team likes
it and uses it daily. This app does NOT reinvent that logic — it replicates it
faithfully and adds the one thing the spreadsheet can't do well: **tracking
production stages across multiple people**.

Ben (production lead) was explicit: "I would like it to resemble 99% of the system
we currently have." Respect that. Do not over-engineer. Do not redesign what works.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 5.x, PostgreSQL, DRF |
| Frontend | Next.js 14, React 18, Tailwind CSS |
| Hosting | Hetzner (same infrastructure as Phloe) |
| Auth | Django session auth, no public-facing access |

## Project Structure

```
manufacture/
├── backend/
│   ├── config/          # Django settings, urls, wsgi
│   ├── core/            # Base models (TimestampedModel)
│   ├── products/        # Product (M-number), SKU (channel mapping)
│   ├── stock/           # StockLevel, deficit calculations
│   ├── production/      # ProductionOrder, ProductionStage, make-list engine
│   ├── shipments/       # FBA shipment tracking (Phase 2)
│   ├── procurement/     # Materials, suppliers, reorder points
│   ├── imports/         # CSV/TSV upload, seed management commands
│   └── requirements.txt
├── frontend/            # Next.js app
│   └── src/app/         # Dashboard, Products, Make List, Production pages
├── scripts/
│   └── index_manufacturing_domain.py  # Cairn pgvector indexer
├── CLAUDE.md            # This file
└── .gitignore
```

---

## Domain Vocabulary — MEMORISE THESE

### M-number
Master product reference (M0001, M0002, ... M2059+).
The canonical identifier for a product design. Permanent. Never modify once assigned.
One M-number can have multiple SKUs across channels.

### Blank
The physical substrate a product is printed on. Named after (in)famous people.
See `D:\claw\projects\manufacturing\core.md` for the full list.
Key blanks: DONALD (circular), SAVILLE (rectangular), DICK (acrylic plaque),
IDI (push/pull), TOM (memorial stake).

### Machine Names
ROLF (UV flatbed), MIMAKI (sublimation), MUTOH (wide format),
ROLAND (vinyl cutter), EPSON (sublimation SC-F500), HULKY (large format).

### Machine Assignment
Blank type determines machine. Composite blanks (e.g. "DICK, TOM") resolve
by first word. See `production/services/make_list.py:BLANK_MACHINE_MAP`.

### Production Pipeline Stages (in order)
```
Designed → Printed → Processed → Cut → Labelled → Packed → Shipped
```
Sublimation products also go through Heat Press and Laminate stages.

### Channels
UK, US, CA, AU, FR, DE, EBAY, ETSY (plus FR_CRAFTS, FR_DESIGNED, IT, etc.)

---

## Critical Rules

1. **Never modify an M-number once assigned** — they are permanent references
2. **Stock levels are sacrosanct** — never auto-update without explicit confirmation
3. **FBA shipments have strict labelling requirements** — FNSKU labels, box content info
4. **Always distinguish between DIP1 (Amazon warehouse) and local stock**
5. **D2C (personalised) orders and FBA (generic) stock are separate workflows**
6. **Blank determines machine assignment** — see machine assignment rules above
7. **Do not reinvent the Worksheet logic** — replicate Ivan's approach faithfully

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/products/` | Product catalogue with stock info |
| GET | `/api/make-list/` | Computed make list (deficit-ordered) |
| GET | `/api/make-list/?group_by_blank=true` | Make list grouped by blank |
| GET | `/api/production-orders/` | All production orders with stages |
| GET | `/api/production-orders/?active=true` | Active (incomplete) orders only |
| POST | `/api/production-orders/` | Create order `{product: "M0001", quantity: 12}` |
| PATCH | `/api/production-orders/{id}/stages/{stage}/` | Advance a stage |
| POST | `/api/production-orders/{id}/confirm-stock/` | Confirm stock update after packing |
| GET | `/api/stock/` | Stock levels |
| GET | `/api/shipments/` | All shipments |
| GET | `/api/shipments/?status=shipped` | Filtered by status |
| GET | `/api/shipments/stats/` | Shipment totals by country |
| POST | `/api/shipments/` | Create shipment `{country: "UK"}` |
| POST | `/api/shipments/{id}/add-items/` | Add items `{items: [{product: "M0001", quantity: 10}]}` |
| POST | `/api/shipments/{id}/mark-shipped/` | Mark shipment as shipped |
| POST | `/api/imports/upload/` | Upload CSV (multipart, preview mode) |
| POST | `/api/imports/upload/` | Upload CSV with `confirm=true` to apply |
| GET | `/api/imports/history/` | Import audit log |

---

## Seed Data Commands

Run in order (each is idempotent):
```
cd backend
..\.venv\Scripts\python manage.py import_master_stock
..\.venv\Scripts\python manage.py import_assembly
..\.venv\Scripts\python manage.py import_sku_assignment
..\.venv\Scripts\python manage.py import_scratchpad
..\.venv\Scripts\python manage.py import_procurement
..\.venv\Scripts\python manage.py import_fba_shipments
```

---

## Build Phases

### Phase 0 — COMPLETE
Django scaffolding, models, seed imports, Next.js skeleton.

### Phase 1 — COMPLETE
Make list engine, production stage tracking, frontend wiring.

### Phase 2 — FBA Shipment Automation — COMPLETE
SP-API Fulfillment Inbound v2024-03-20 workflow. Resumable state machine driven
by Django-Q2 (Postgres ORM broker). See the Deployment Runbook below for
architecture, env vars, and deploy steps. Carrier booking is MANUAL —
Ben books externally and captures tracking via the UI dispatch endpoint.

Code-complete and smoke-tested end to end:
- 115 backend tests (workflow, sp_api_client, api, alert command) pass.
- Django-Q2 broker round-trip verified against Postgres ORM broker (no Redis).
- Next.js `/fba` list + `/fba/[id]` detail pages wired with polling, pickers,
  dispatch capture, and labels PDF download.
- `qcluster` sidecar container in `docker/docker-compose.yml`, same image as
  backend, depends on backend migrations.
- `fba_alert_stuck_plans` management command + 15-minute cron line documented
  below for stuck/errored plan paging.

### Phase 3 — CSV Import Automation — COMPLETE
FBA Inventory, Sales & Traffic, Restock, and Zenstores parsers in
`backend/imports/`. Upload via `/api/imports/upload/` with a preview/confirm
flow and full audit trail (`ImportLog`). Next.js page at `frontend/src/app/imports/`.

Test coverage added in the Phase 3 hardening sweep:
- `imports/tests/test_parsers.py` — 34 unit tests (parsers, delimiter
  detection, auto-detect, column-header variants).
- `imports/tests/test_services.py` — 18 DB-backed tests for each applier
  (preview guard, confirm mutation, unknown SKU skip, idempotency).
- `imports/tests/test_upload_view.py` — 15 HTTP tests (preview vs confirm,
  error paths, auto-detect, utf-8-sig/latin-1 fallback, history ordering).
- Fixed a latent silent-save bug in `apply_sales_traffic` where
  `StockLevel.recalculate_deficit()` (which calls `save(update_fields=
  ['stock_deficit', 'updated_at'])`) was dropping the new `sixty_day_sales`
  write. Sales imports now persist the velocity value explicitly before
  recalculating the deficit.

### Phase 4 — D2C Queue — COMPLETE
Personalised order tracking for Gabby. `DispatchOrder` model keyed on
`(order_id, sku)` for idempotent Zenstores imports, with status machine
`pending → in_progress → made → dispatched` and `completed_at` / `completed_by`
stamping on `mark-made`. REST API at `/api/dispatch/` (list + filter by
status/channel, search across order_id/sku/description/flags/customer/m_number,
stats aggregate, create-with-m_number product resolution). Next.js page at
`frontend/src/app/dispatch/`.

Test coverage added in the Phase 3 hardening sweep:
- `d2c/tests/test_dispatch_api.py` — 14 HTTP tests (list/filter/search,
  create with m_number → product FK resolution, mark-made stamps user,
  unauthenticated mark-made leaves completed_by null, mark-dispatched,
  stats shape, empty-DB stats).

### Phase 5 — Procurement — PARTIAL
Materials CRUD is live. `procurement.Material` model has stock, reorder
point, standard order qty, preferred supplier, lead time, safety stock,
and a `needs_reorder` property. REST API at `/api/materials/` (filter by
category, search, `?needs_reorder=true`, `/stats/`). Next.js page at
`frontend/src/app/materials/`.

Not yet done (deferred pending owner priority): supplier model as a FK
(currently a CharField), purchase order / goods-receipt workflow,
automated reorder triggering off `needs_reorder` + lead time, and a
test suite (`backend/procurement/tests/` does not exist yet). When this
phase is picked up, write parser + applier + viewset tests in the same
shape as `imports/tests/` and `d2c/tests/`.

### Phase 6 — SP-API Integration — COMPLETE
Three independent live SP-API integrations now feed the system; the
manual CSV upload path in `imports/` is preserved as a fallback and for
one-off imports.

- **`fba_shipments/services/sp_api_client.py`** — Fulfillment Inbound
  v2024-03-20 (Phase 2 shipment automation). Drives the resumable state
  machine via Django-Q2.
- **`restock/spapi_client.py`** — raw LWA HTTP client that pulls
  `GET_FBA_INVENTORY_PLANNING_DATA` for GB/US/CA/AU/DE/FR. Driven by
  `manage.py sync_restock_all`; the parser consumes the raw report bytes
  directly (no more manual CSV upload step in production).
- **`barcodes/services/sp_api_sync.py`** — python-amazon-sp-api SDK
  wrapper for FNSKU sync. Driven by `manage.py sync_fnskus`.

Test coverage repaired in the Phase 6 hardening sweep:
- `restock/tests/test_newsvendor.py` rewritten (15 tests) to match the
  simplified production formula `max(0, units_sold_30d*3 -
  (available + inbound))`. The prior suite targeted an older richer
  newsvendor model (critical ratio, safety stock, margin-weighted
  confidence) that had been deleted from the production code.
- `restock/tests/test_integration.py` fixture rewritten (14 tests) from
  comma-separated human-readable CSV to tab-separated SP-API canonical
  headers (`sku`, `units-shipped-t30`, `available`, `days-of-supply`,
  `Recommended ship-in quantity`, `Recommended ship-in date`, etc.) —
  matching what `restock.spapi_client.download_report()` actually
  returns. Report uses `UK` for GB which the parser normalises on read.
- `barcodes/tests/test_print_agent_api.py` migrated from
  `@override_settings` class decoration (Django 5 rejects this on
  non-SimpleTestCase classes) to a pytest-django `settings` fixture.
- **SECURITY DRIFT flagged (not fixed):**
  `/api/print-agent/pending/` currently allows unauthenticated access —
  `PrintAgentAuthentication.authenticate()` returns `None` on missing
  header and the view is decorated `@permission_classes([AllowAny])`,
  so a request without a token reaches the queue and can claim jobs.
  `test_agent_pending_requires_token` is marked `@pytest.mark.xfail
  (strict=True)` with a verbose reason. Owner review required: either
  tighten `permission_classes` to `IsAuthenticated` and raise on missing
  token, or formally acknowledge reliance on network isolation.

---

## Development Rules

- Read files before editing — never assume contents
- Commit atomically: `type(scope): description`
- Write back to Cairn memory after significant decisions
- Do not invent domain terms — use the vocabulary above
- Stock changes require explicit confirmation
- Replicate before you innovate

---

## FBA Shipment Automation — Deployment Runbook (Phase 2)

The automated FBA flow lives in `backend/fba_shipments/` and the Next.js UI
lives under `frontend/src/app/fba/`. It is fully separate from the legacy
manual `/shipments` module, which stays in place for non-Amazon exports.

### Architecture

```
           +-------------------------+
           |  Next.js (/fba, /fba/..)|
           +-----------+-------------+
                       |  HTTPS + session cookies
           +-----------v-------------+
           |  Django REST /api/fba/  |   (backend container)
           +---+-----------------+---+
               |                 | async_task / Schedule
               |                 v
       +-------v-------+   +----------------+
       |  Postgres DB  |<--+  Django-Q2     |   (qcluster container)
       +---------------+   |  cluster       |
                           +-------+--------+
                                   |
                                   v
                       SP-API Fulfillment Inbound v2024-03-20
```

- **Broker:** Postgres via the Django ORM (`orm: default` in `Q_CLUSTER`).
  No Redis, no RabbitMQ — the `qcluster` container only needs the DB.
- **Retry policy:** `max_attempts: 1` at the Django-Q level. The state
  machine itself owns retry logic (`retry` action + `error` status).
- **State machine entry:** `fba_shipments.services.workflow.advance_plan`.
  Enqueue boundary is in views — `submit()` and `pick_*_option()` call
  `wf.kick_off(plan)`, nothing else.

### Required environment variables

See `backend/.env.example` for the full list. Minimum viable config:

| Var | Notes |
|---|---|
| `AMAZON_CLIENT_ID` / `AMAZON_CLIENT_SECRET` | SP-API LWA app credentials |
| `AMAZON_REFRESH_TOKEN_EU` | UK/DE/FR/IT/ES/NL |
| `AMAZON_REFRESH_TOKEN_NA` | US/CA |
| `AMAZON_REFRESH_TOKEN_AU` | AU |
| `SP_API_ENVIRONMENT` | `PRODUCTION` (use `SANDBOX` only for schema testing) |
| `FBA_SHIP_FROM_*` | Address fields snapshotted onto each plan |
| `Q_CLUSTER_WORKERS` | Default 2; bump if plan volume grows |
| `FBA_ALERT_RECIPIENT` | Email for stuck/errored plan alerts |
| `SMTP_*` | Re-used from the bug-report integration |

### Deploy steps (Hetzner)

1. Pull on host: `git pull origin main` in `/opt/nbne/manufacture`.
2. Update `.env` with any new `FBA_*` values.
3. Rebuild images:
   `docker compose -f docker/docker-compose.yml build backend qcluster frontend`
4. Run migrations (one-shot):
   `docker compose -f docker/docker-compose.yml run --rm backend python manage.py migrate`
5. Start everything: `docker compose -f docker/docker-compose.yml up -d`
6. Sanity checks:
   - `docker compose logs -f qcluster` → should show "Q Cluster manufacture-nn starting"
   - `docker compose exec backend python manage.py fba_preflight_check --marketplace UK`
   - Open `https://<domain>/fba` and confirm the preflight widget renders

### Stuck-plan alerting

Add a host cron (or systemd timer) that runs every 15 minutes:

```
*/15 * * * * docker compose -f /opt/nbne/manufacture/docker/docker-compose.yml \
  exec -T backend python manage.py fba_alert_stuck_plans
```

The command emails `FBA_ALERT_RECIPIENT` only if there are errored or stuck
plans. A plan is "stuck" if it is in a waiting status (e.g. `plan_creating`,
`packing_options_generating`, …) and hasn't polled in 30 minutes — which
almost always means the Django-Q cluster died mid-task.

### Troubleshooting

- **Plan stuck in `plan_creating`:**
  Check `docker compose logs qcluster`. If the cluster is running but plans
  aren't advancing, inspect `FBAAPICall` rows for the plan
  (`GET /api/fba/plans/{id}/api-calls/`) and look for 5xx errors or
  throttling. Retry via the UI or `retry()` action.
- **`packing_options_ready` but no snapshot in UI:**
  Amazon returned zero packing options — usually means items or prep
  categories aren't set up in Seller Central. Check the plan's
  `packing_options_snapshot` in Django admin and re-run `fba_preflight_check`.
- **Dispatch form won't enable:**
  Plan must be in `ready_to_ship` (or already partially `dispatched`) —
  meaning labels have been fetched and at least one shipment row exists.
  Check `GET /api/fba/plans/{id}/` for the `shipments` array.
- **qcluster container won't start:**
  Run `docker compose exec backend python manage.py migrate` — the
  `django_q` tables need to exist before qcluster can boot.
