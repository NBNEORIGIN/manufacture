"""
Cairn module federation view for the Manufacture app.

Exposes GET /api/cairn/snapshot — returns a markdown summary of Manufacture's
current live state that Cairn's module-snapshot poller ingests on a fixed
interval (every ~15 minutes) into claw_code_chunks as chunk_type='module_snapshot'.

Contract:
  - Response is text/markdown (not JSON), pre-rendered as a short summary.
  - Body covers: open production orders, stock deficits, in-flight FBA plans,
    recent shipments. Kept under ~6k characters so the Cairn embedder can
    consume the full snapshot in one call.
  - Auth: Bearer token matching settings.CAIRN_API_KEY (or disabled if not set).

Registered in config/urls.py at path('api/cairn/snapshot', ...).
"""
from __future__ import annotations

from datetime import datetime, timezone

from django.conf import settings
from django.db.models import Count, Sum
from django.http import HttpResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request


def _unauthorised() -> HttpResponse:
    return HttpResponse("unauthorised\n", status=401, content_type="text/plain")


def _check_auth(request: Request) -> bool:
    """Bearer-token auth against settings.CAIRN_API_KEY. If unset, auth is open."""
    expected = getattr(settings, "CAIRN_API_KEY", "") or ""
    if not expected:
        return True
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if not header.startswith("Bearer "):
        return False
    return header[7:].strip() == expected


def _safe(fn, default):
    """Run a query lambda and return default on any failure."""
    try:
        return fn()
    except Exception as exc:  # pragma: no cover — defensive only
        return default


@api_view(["GET"])
@permission_classes([AllowAny])  # Auth handled manually (Bearer token)
def cairn_snapshot(request: Request) -> HttpResponse:
    """Markdown live snapshot for Cairn ingestion."""
    if not _check_auth(request):
        return _unauthorised()

    # Lazy imports so this module loads even if a sibling app fails to register
    from production.models import ProductionOrder
    from stock.models import StockLevel
    from shipments.models import Shipment
    from fba_shipments.models import FBAShipmentPlan

    now_iso = datetime.now(timezone.utc).isoformat()

    # ── Production: open orders ──────────────────────────────────────────
    open_qs = ProductionOrder.objects.filter(completed_at__isnull=True)
    open_total = _safe(open_qs.count, 0)

    by_machine = _safe(
        lambda: list(
            open_qs.values("machine").annotate(n=Count("id"), units=Sum("quantity")).order_by("-n")
        ),
        [],
    )
    by_stage = _safe(
        lambda: list(
            open_qs.values("simple_stage").annotate(n=Count("id")).order_by("simple_stage")
        ),
        [],
    )

    # ── Stock: deficits ─────────────────────────────────────────────────
    deficit_qs = StockLevel.objects.filter(stock_deficit__gt=0)
    deficit_count = _safe(deficit_qs.count, 0)
    deficit_sum = _safe(
        lambda: deficit_qs.aggregate(s=Sum("stock_deficit"))["s"] or 0, 0
    )
    top_deficits = _safe(
        lambda: list(
            deficit_qs.order_by("-stock_deficit")
            .select_related("product")
            .values("product__m_number", "current_stock", "stock_deficit")[:10]
        ),
        [],
    )
    zero_stock = _safe(
        lambda: StockLevel.objects.filter(current_stock=0).count(), 0
    )

    # ── FBA: in-flight plans ────────────────────────────────────────────
    fba_active = _safe(
        lambda: FBAShipmentPlan.objects.exclude(
            status__in=list(FBAShipmentPlan.TERMINAL_STATUSES)
        ).count(),
        0,
    )
    fba_by_status = _safe(
        lambda: list(
            FBAShipmentPlan.objects.exclude(
                status__in=list(FBAShipmentPlan.TERMINAL_STATUSES)
            )
            .values("status", "marketplace")
            .annotate(n=Count("id"))
            .order_by("-n")
        ),
        [],
    )

    # ── Shipments: recent 10 ───────────────────────────────────────────
    recent_shipments = _safe(
        lambda: list(
            Shipment.objects.order_by("-shipment_date", "-created_at")
            .values("id", "country", "status", "shipment_date", "total_units", "box_count")[:10]
        ),
        [],
    )

    # ── Render markdown ────────────────────────────────────────────────
    lines: list[str] = []
    lines.append("# manufacture live snapshot")
    lines.append("")
    lines.append(f"Generated at {now_iso} by Manufacture /api/cairn/snapshot")
    lines.append("")
    lines.append("## Production — open orders")
    lines.append("")
    lines.append(f"- Total open orders: **{open_total}**")
    if by_machine:
        lines.append("- By machine:")
        for row in by_machine:
            mach = row.get("machine") or "(unassigned)"
            units = row.get("units") or 0
            lines.append(f"  - {mach}: {row['n']} orders, {units} units")
    if by_stage:
        lines.append("- By simple stage:")
        for row in by_stage:
            stage = row.get("simple_stage") or "(none)"
            lines.append(f"  - {stage}: {row['n']}")
    lines.append("")

    lines.append("## Stock — deficits")
    lines.append("")
    lines.append(f"- Products below target: **{deficit_count}**")
    lines.append(f"- Total deficit units: **{deficit_sum}**")
    lines.append(f"- Products at zero stock: **{zero_stock}**")
    if top_deficits:
        lines.append("- Top 10 by deficit:")
        for row in top_deficits:
            m = row.get("product__m_number") or "?"
            cur = row.get("current_stock") or 0
            dfc = row.get("stock_deficit") or 0
            lines.append(f"  - {m}: {cur} on hand, {dfc} short")
    lines.append("")

    lines.append("## FBA — in-flight plans")
    lines.append("")
    lines.append(f"- Active plans (non-terminal): **{fba_active}**")
    if fba_by_status:
        lines.append("- By status × marketplace:")
        for row in fba_by_status:
            lines.append(
                f"  - {row['marketplace']} / {row['status']}: {row['n']}"
            )
    lines.append("")

    lines.append("## Shipments — most recent 10")
    lines.append("")
    if recent_shipments:
        for s in recent_shipments:
            date = s.get("shipment_date")
            date_s = date.isoformat() if date else "(unscheduled)"
            lines.append(
                f"- FBA-{s['id']} {s['country']} / {s['status']}"
                f" — {s['total_units']} units in {s['box_count']} boxes ({date_s})"
            )
    else:
        lines.append("- None")
    lines.append("")

    body = "\n".join(lines)
    return HttpResponse(body, status=200, content_type="text/markdown; charset=utf-8")
