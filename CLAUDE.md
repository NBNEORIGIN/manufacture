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

### Phase 2 — FBA Shipments (next)
Shipment model, box tracking, historical shipment log, country-specific planning.

### Phase 3 — CSV Import Automation
FBA Inventory, Sales & Traffic, Restock report parsers. Upload via web UI.

### Phase 4 — D2C Queue
Personalised order tracking. Gabby is the primary user.

### Phase 5 — Procurement
Materials, suppliers, reorder points (replaces PROCUREMENT sheet).

### Phase 6 — SP-API Integration
Automated report retrieval replaces manual CSV uploads.

---

## Development Rules

- Read files before editing — never assume contents
- Commit atomically: `type(scope): description`
- Write back to Cairn memory after significant decisions
- Do not invent domain terms — use the vocabulary above
- Stock changes require explicit confirmation
- Replicate before you innovate
