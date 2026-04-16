"""
Cost-config API.

- /api/costs/blanks/          CRUD (no create/delete — seeded from migrations;
                              resync action to pick up new blanks).
- /api/costs/overrides/       M-number overrides CRUD.
- /api/costs/config/          Singleton GET/PATCH.
- /api/costs/price/<m>/       Computed cost for an M-number (Cairn consumer).
- /api/costs/blanks/upload-csv/   Batch update from CSV.
- /api/costs/blanks/resync/   Rescan Product.blank, create rows for new blanks
                              and refresh product_count.
"""
from __future__ import annotations

import csv
import io
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.http import Http404
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


def _cairn_auth_ok(request) -> bool:
    """Accept either a logged-in session OR a matching CAIRN_API_KEY Bearer.

    Used by price endpoints that Cairn's margin engine calls server-to-server.
    If CAIRN_API_KEY is unset (dev), Bearer check is bypassed and we fall back
    to normal session auth.
    """
    if request.user and request.user.is_authenticated:
        return True
    expected = getattr(settings, 'CAIRN_API_KEY', '') or ''
    if not expected:
        return False
    header = request.META.get('HTTP_AUTHORIZATION', '')
    if not header.startswith('Bearer '):
        return False
    return header[7:].strip() == expected

from products.models import Product

from .models import (
    BlankCost,
    CostConfig,
    MNumberCostOverride,
    get_cost_price,
    is_composite_blank,
    normalise_blank,
)
from .serializers import (
    BlankCostSerializer,
    CostConfigSerializer,
    MNumberCostOverrideSerializer,
)


def _serialise_price(payload: dict) -> dict:
    """Coerce Decimals to strings for JSON — avoids float-precision drift."""
    out = {}
    for k, v in payload.items():
        if isinstance(v, Decimal):
            out[k] = str(v)
        else:
            out[k] = v
    return out


class BlankCostViewSet(viewsets.ModelViewSet):
    """Edit per-blank material/labour. No user-created rows — use resync."""
    queryset = BlankCost.objects.all()
    serializer_class = BlankCostSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['normalized_name', 'display_name', 'sample_raw_blank']
    ordering_fields = ['normalized_name', 'material_cost_gbp',
                       'labour_minutes', 'product_count']
    ordering = ['normalized_name']
    pagination_class = None
    http_method_names = ['get', 'patch', 'head', 'options']

    @action(detail=False, methods=['post'], url_path='resync')
    def resync(self, request):
        """
        Scan active Product.blank values, create a BlankCost row for any new
        normalised blank (seeded at config defaults), and refresh
        product_count for every existing row.
        """
        cfg = CostConfig.get()
        products = Product.objects.filter(active=True).values_list('blank', flat=True)
        counts: dict[str, dict] = {}
        for raw in products:
            norm = normalise_blank(raw)
            if not norm:
                continue
            entry = counts.setdefault(norm, {'count': 0, 'sample': raw or ''})
            entry['count'] += 1

        created = 0
        updated = 0
        with transaction.atomic():
            for norm, info in counts.items():
                bc, made = BlankCost.objects.get_or_create(
                    normalized_name=norm,
                    defaults={
                        'display_name': info['sample'].strip().upper(),
                        'material_cost_gbp': cfg.default_material_gbp,
                        'labour_minutes': Decimal('0'),
                        'is_composite': is_composite_blank(info['sample']),
                        'sample_raw_blank': info['sample'],
                        'product_count': info['count'],
                    },
                )
                if made:
                    created += 1
                elif bc.product_count != info['count']:
                    bc.product_count = info['count']
                    bc.save(update_fields=['product_count', 'updated_at'])
                    updated += 1
        return Response({
            'blanks_created': created,
            'product_counts_updated': updated,
            'total_blanks': BlankCost.objects.count(),
        })

    @action(detail=False, methods=['post'], url_path='upload-csv',
            parser_classes=[])  # allow multipart + raw
    def upload_csv(self, request):
        """
        Batch edit via CSV.

        Accepted columns (header row required, case-insensitive):
          normalized_name OR display_name OR sample_raw_blank  (one matches a row)
          material_cost_gbp     — £ per unit
          labour_minutes        — minutes per unit
          notes                 — optional

        Rows without a matching BlankCost are reported in `not_found`; no new
        rows are created. Use /resync for that.
        """
        upload = request.FILES.get('file') or request.data.get('file')
        if upload is None:
            # Raw body fallback
            body = request.body or b''
            if not body:
                return Response({'error': 'upload a CSV as form field "file" or raw body'},
                                status=status.HTTP_400_BAD_REQUEST)
            text = body.decode('utf-8-sig', errors='replace')
        else:
            raw = upload.read() if hasattr(upload, 'read') else upload
            if isinstance(raw, bytes):
                text = raw.decode('utf-8-sig', errors='replace')
            else:
                text = raw

        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            return Response({'error': 'CSV appears empty'},
                            status=status.HTTP_400_BAD_REQUEST)
        headers_lower = {h.lower().strip(): h for h in reader.fieldnames}

        def col(row, *aliases):
            for a in aliases:
                key = headers_lower.get(a.lower())
                if key is not None and row.get(key) not in (None, ''):
                    return row[key]
            return None

        updated, not_found, errors = [], [], []
        with transaction.atomic():
            for i, row in enumerate(reader, start=2):
                key_norm = col(row, 'normalized_name')
                key_display = col(row, 'display_name')
                key_raw = col(row, 'sample_raw_blank', 'blank')

                bc = None
                if key_norm:
                    bc = BlankCost.objects.filter(
                        normalized_name=normalise_blank(key_norm)
                    ).first()
                if bc is None and key_raw:
                    bc = BlankCost.objects.filter(
                        normalized_name=normalise_blank(key_raw)
                    ).first()
                if bc is None and key_display:
                    bc = BlankCost.objects.filter(display_name__iexact=key_display.strip()).first()
                if bc is None:
                    not_found.append({'row': i, 'key': key_norm or key_display or key_raw})
                    continue

                changed = []
                mat = col(row, 'material_cost_gbp', 'material', 'cost')
                if mat is not None:
                    try:
                        bc.material_cost_gbp = Decimal(str(mat).strip())
                        changed.append('material_cost_gbp')
                    except (InvalidOperation, ValueError):
                        errors.append({'row': i, 'field': 'material_cost_gbp', 'value': mat})
                        continue
                lab = col(row, 'labour_minutes', 'labor_minutes', 'minutes')
                if lab is not None:
                    try:
                        bc.labour_minutes = Decimal(str(lab).strip())
                        changed.append('labour_minutes')
                    except (InvalidOperation, ValueError):
                        errors.append({'row': i, 'field': 'labour_minutes', 'value': lab})
                        continue
                notes = col(row, 'notes')
                if notes is not None:
                    bc.notes = notes.strip()
                    changed.append('notes')

                if changed:
                    bc.save(update_fields=changed + ['updated_at'])
                    updated.append({'row': i, 'normalized_name': bc.normalized_name,
                                    'fields': changed})

        return Response({
            'updated': updated,
            'not_found': not_found,
            'errors': errors,
            'total_updated': len(updated),
        })


class MNumberCostOverrideViewSet(viewsets.ModelViewSet):
    queryset = MNumberCostOverride.objects.select_related('product').all()
    serializer_class = MNumberCostOverrideSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['product__m_number', 'product__description', 'notes']
    ordering_fields = ['product__m_number', 'cost_price_gbp']
    ordering = ['product__m_number']
    pagination_class = None

    def create(self, request, *args, **kwargs):
        """
        Accept either {product: <id>} (standard) or {m_number: 'M0123'} so the
        UI doesn't need to resolve to pk first.
        """
        data = request.data.copy()
        if 'product' not in data and 'm_number' in data:
            try:
                data['product'] = Product.objects.get(m_number=data['m_number']).pk
            except Product.DoesNotExist:
                return Response({'error': f'No product with M-number {data["m_number"]}'},
                                status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH'])
def cost_config_view(request):
    """Singleton GET/PATCH at /api/costs/config/."""
    cfg = CostConfig.get()
    if request.method == 'PATCH':
        serializer = CostConfigSerializer(cfg, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
    return Response(CostConfigSerializer(cfg).data)


@api_view(['GET'])
@permission_classes([AllowAny])  # Auth handled manually — Cairn uses Bearer.
def cost_price_view(request, m_number: str):
    if not _cairn_auth_ok(request):
        return Response({'detail': 'unauthorised'}, status=401)
    try:
        product = Product.objects.get(m_number=m_number)
    except Product.DoesNotExist:
        raise Http404(f'No product with M-number {m_number}')
    return Response(_serialise_price(get_cost_price(product)))


@api_view(['GET'])
@permission_classes([AllowAny])  # Auth handled manually — Cairn uses Bearer.
def cost_price_bulk_view(request):
    """
    Bulk cost lookup. Used by Cairn margin engine for batch compute.

    Query: ?m_numbers=M0001,M0002,... (comma-separated, up to ~2000).
           Omit to get all active products.
    """
    if not _cairn_auth_ok(request):
        return Response({'detail': 'unauthorised'}, status=401)
    raw = request.query_params.get('m_numbers')
    qs = Product.objects.all()  # Include inactive — they still have real costs & sales
    if raw:
        ms = [x.strip() for x in raw.split(',') if x.strip()]
        qs = qs.filter(m_number__in=ms)
    qs = qs.select_related('cost_override')
    out = [_serialise_price(get_cost_price(p)) for p in qs]
    return Response({'count': len(out), 'results': out})
