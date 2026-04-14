"""
Cairn module federation + proxy views for the Manufacture app.

Two roles:

1. `cairn_snapshot` — exposes GET /api/cairn/snapshot. Markdown summary of
   Manufacture's live state. Cairn's module-snapshot poller ingests this
   every ~15 minutes into claw_code_chunks as chunk_type='module_snapshot'.
   Auth: Bearer token against settings.CAIRN_API_KEY (or disabled if unset).

2. Cairn-proxy views — session-authenticated Manufacture endpoints that
   forward to Cairn's AMI/margin APIs so the Next.js frontend can render
   Cairn-produced data (e.g. the Quartile ACOS brief) without having to
   authenticate to Cairn directly from the browser. The outbound call
   uses settings.CAIRN_API_URL + X-API-Key (pattern matches
   sales_velocity/adapters/etsy.py).

Registered in config/urls.py.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from django.conf import settings
from django.db.models import Count, Sum
from django.http import HttpResponse, JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

logger = logging.getLogger(__name__)


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


# ── Cairn proxy views ─────────────────────────────────────────────────────────


_CAIRN_TIMEOUT_S = 30


def _cairn_base() -> str:
    """Return the Cairn API base URL, trimmed."""
    return (getattr(settings, "CAIRN_API_URL", "") or "http://localhost:8765").rstrip("/")


def _cairn_headers() -> dict:
    """Standard outbound headers — X-API-Key pattern matches sales_velocity.adapters.etsy."""
    api_key = getattr(settings, "CAIRN_API_KEY", "")
    return {"X-API-Key": api_key} if api_key else {}


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def cairn_quartile_brief(request: Request) -> Response:
    """
    Proxy to Cairn GET /ami/margin/quartile-brief/preview.

    Query params (forwarded):
      - marketplace: optional country code (UK/US/CA/DE/FR/...)
      - lookback_days: default 30
      - target_margin_pct: default 0.06
      - non_ad_cost_pct: default 0.82
      - format: 'json' (default) or 'text'

    Returns the Cairn response verbatim for json, or text/plain for format=text.
    Session-authenticated (Manufacture user must be logged in); the outbound
    call uses the shared CAIRN_API_KEY.
    """
    url = f"{_cairn_base()}/ami/margin/quartile-brief/preview"
    params = {k: v for k, v in request.query_params.items() if v not in (None, "")}
    fmt = (params.get("format") or "json").lower()

    try:
        with httpx.Client(timeout=_CAIRN_TIMEOUT_S) as client:
            resp = client.get(url, params=params, headers=_cairn_headers())
    except httpx.HTTPError as exc:
        logger.error("cairn_quartile_brief: upstream unreachable: %s", exc)
        return Response(
            {"error": "cairn_unreachable", "detail": f"{type(exc).__name__}: {exc}"},
            status=503,
        )

    if resp.status_code >= 500:
        logger.error(
            "cairn_quartile_brief: upstream %s — body: %s",
            resp.status_code, resp.text[:500],
        )
        return Response(
            {"error": "cairn_upstream_error", "status": resp.status_code,
             "detail": resp.text[:500]},
            status=502,
        )

    if fmt == "text":
        return HttpResponse(
            resp.text,
            status=resp.status_code,
            content_type="text/plain; charset=utf-8",
        )
    if fmt == "csv":
        # Attach Content-Disposition so the browser triggers a download
        # when the frontend navigates to / fetches the endpoint with csv.
        mkt = params.get("marketplace") or "all"
        from datetime import date as _date
        filename = f"quartile-brief-{mkt}-{_date.today().isoformat()}.csv"
        r = HttpResponse(
            resp.text,
            status=resp.status_code,
            content_type="text/csv; charset=utf-8",
        )
        r["Content-Disposition"] = f'attachment; filename="{filename}"'
        return r

    try:
        return Response(resp.json(), status=resp.status_code)
    except ValueError:
        # Upstream didn't return valid JSON — relay as-is so the UI can
        # surface the raw error rather than swallowing it.
        return HttpResponse(
            resp.text,
            status=resp.status_code,
            content_type=resp.headers.get("content-type", "text/plain"),
        )
