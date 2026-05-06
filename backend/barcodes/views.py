import os
from django.db import transaction
from django.utils import timezone
from rest_framework import viewsets, status, mixins
from rest_framework.decorators import api_view, action, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .authentication import PrintAgentAuthentication
from .services.sp_api_sync import sync_fnskus_for_marketplace
from .services.pdf import generate_label_pdf
from .models import ProductBarcode, PrintJob, FNSKUSyncLog, Printer
from .serializers import ProductBarcodeSerializer, PrintJobSerializer, PrintJobAgentSerializer
from .services.rendering.base import build_spec_from_settings
from .services.rendering.factory import get_renderer
from .services.rendering.preview import render_preview_png


def _resolve_printer(ref) -> Printer | None:
    """Accept an int pk, a slug string, or None. Active printers only."""
    if ref is None or ref == '':
        return None
    qs = Printer.objects.filter(active=True)
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        return qs.filter(pk=int(ref)).first()
    return qs.filter(slug=str(ref)).first()


def _create_print_job(
    barcode: ProductBarcode,
    quantity: int,
    user=None,
    printer: Printer | None = None,
) -> PrintJob:
    """
    Render a label and queue it for printing.

    If `printer` is supplied, the spec respects its label dimensions and the
    renderer is chosen by its `command_language`. Without a printer, the
    legacy global LABEL_* settings are used (ZPL by default) and the job
    becomes claimable by any agent.
    """
    spec = build_spec_from_settings(
        barcode_value=barcode.barcode_value,
        label_title=barcode.label_title,
        condition=barcode.condition,
        width_mm=printer.label_width_mm if printer else None,
        height_mm=printer.label_height_mm if printer else None,
        dpi=printer.label_dpi if printer else None,
    )
    renderer = get_renderer(printer.command_language if printer else None)
    payload = renderer.render(spec, quantity=quantity)
    return PrintJob.objects.create(
        barcode=barcode,
        quantity=quantity,
        command_payload=payload,
        command_language=renderer.content_type.split('/')[-1],
        printer=printer,
        requested_by=user,
        status='pending',
    )


class ProductBarcodeViewSet(viewsets.ModelViewSet):
    serializer_class = ProductBarcodeSerializer
    queryset = ProductBarcode.objects.select_related('product').all()
    pagination_class = None  # barcodes list is always loaded in full per marketplace

    def get_queryset(self):
        qs = super().get_queryset()
        product = self.request.query_params.get('product')
        marketplace = self.request.query_params.get('marketplace')
        if product:
            qs = qs.filter(product_id=product)
        if marketplace:
            qs = qs.filter(marketplace=marketplace)
        return qs.order_by('product__m_number', 'marketplace')

    @action(detail=True, methods=['post'])
    def preview(self, request, pk=None):
        barcode = self.get_object()
        spec = build_spec_from_settings(
            barcode_value=barcode.barcode_value,
            label_title=barcode.label_title,
            condition=barcode.condition,
        )
        renderer = get_renderer()
        command_string = renderer.render(spec, quantity=1)
        try:
            png_bytes = render_preview_png(command_string, spec)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_502_BAD_GATEWAY)
        from django.http import HttpResponse
        return HttpResponse(png_bytes, content_type='image/png')

    @action(detail=True, methods=['post'])
    def print(self, request, pk=None):
        barcode = self.get_object()
        quantity = request.data.get('quantity', 1)
        try:
            quantity = int(quantity)
            if quantity < 1:
                raise ValueError
        except (TypeError, ValueError):
            return Response({'error': 'quantity must be a positive integer'}, status=status.HTTP_400_BAD_REQUEST)
        printer = _resolve_printer(request.data.get('printer_id') or request.data.get('printer_slug'))
        job = _create_print_job(
            barcode, quantity,
            user=request.user if request.user.is_authenticated else None,
            printer=printer,
        )
        return Response(PrintJobSerializer(job).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='pdf')
    def pdf(self, request):
        """
        Generate a PDF of barcode labels.

        Body:
          {
            "items": [{"barcode_id": 1, "quantity": 3}, ...],
            "format": "roll"   // optional: 'roll' (default) or 'avery'
          }

        format=roll  → one label per page at 50×25mm (continuous thermal roll)
        format=avery → A4 sheet with Avery 27-up grid layout

        Returns: application/pdf
        """
        items = request.data.get('items', [])
        if not items:
            return Response({'error': 'items list is required'}, status=status.HTTP_400_BAD_REQUEST)

        fmt = (request.data.get('format') or 'roll').strip().lower()
        if fmt not in ('roll', 'avery'):
            return Response(
                {'error': f"format must be 'roll' or 'avery', got {fmt!r}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        label_items = []
        for item in items:
            try:
                barcode = ProductBarcode.objects.select_related('product').get(pk=item['barcode_id'])
                quantity = max(1, int(item.get('quantity', 1)))
            except (ProductBarcode.DoesNotExist, KeyError, TypeError, ValueError) as e:
                return Response({'error': f'Invalid item: {e}'}, status=status.HTTP_400_BAD_REQUEST)
            label_items.append({
                'barcode_value': barcode.barcode_value,
                'label_title': barcode.label_title,
                'condition': barcode.condition,
                'quantity': quantity,
                'm_number': barcode.product.m_number if barcode.product_id else '',
            })

        try:
            pdf_bytes = generate_label_pdf(label_items, format=fmt)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        from django.http import HttpResponse
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        suffix = 'thermal' if fmt == 'roll' else 'avery'
        response['Content-Disposition'] = f'inline; filename="barcode-labels-{suffix}.pdf"'
        return response

    SUPPORTED_MARKETPLACES = ['UK', 'US', 'CA', 'AU', 'DE', 'FR', 'IT', 'ES', 'NL']

    @action(detail=False, methods=['get'], url_path='production-quantities')
    def production_quantities(self, request):
        """
        Return {m_number: pending_qty} — sum of uncompleted production order
        quantities per product. Used by the Barcodes page to pre-fill label qty
        inputs with the amount currently in production.
        """
        from django.db.models import Sum
        from production.models import ProductionOrder
        rows = (
            ProductionOrder.objects
            .filter(completed_at__isnull=True)
            .values('product__m_number')
            .annotate(qty=Sum('quantity'))
        )
        return Response({r['product__m_number']: int(r['qty'] or 0) for r in rows})

    @action(detail=False, methods=['post'], url_path='sync-fnskus')
    def sync_fnskus(self, request):
        marketplace = request.data.get('marketplace', 'UK')
        from django.utils import timezone

        # Handle 'ALL' by iterating every supported marketplace and aggregating
        if marketplace == 'ALL':
            totals = {'created': 0, 'updated': 0, 'unmatched_skus': []}
            per_market = {}
            for mk in self.SUPPORTED_MARKETPLACES:
                log = FNSKUSyncLog(marketplace=mk, ran_at=timezone.now())
                try:
                    result = sync_fnskus_for_marketplace(mk)
                    log.created = result['created']
                    log.updated = result['updated']
                    log.unmatched_count = len(result['unmatched_skus'])
                    log.save()
                    totals['created'] += result['created']
                    totals['updated'] += result['updated']
                    totals['unmatched_skus'].extend(result['unmatched_skus'])
                    per_market[mk] = {
                        'created': result['created'],
                        'updated': result['updated'],
                        'unmatched': log.unmatched_count,
                    }
                except Exception as exc:
                    log.error_message = str(exc)
                    log.save()
                    per_market[mk] = {'error': str(exc)}
            return Response({
                **totals,
                'unmatched_count': len(totals['unmatched_skus']),
                'per_marketplace': per_market,
            })

        # Single marketplace path
        log = FNSKUSyncLog(marketplace=marketplace, ran_at=timezone.now())
        try:
            result = sync_fnskus_for_marketplace(marketplace)
            log.created = result['created']
            log.updated = result['updated']
            log.unmatched_count = len(result['unmatched_skus'])
            log.save()
            return Response({**result, 'unmatched_count': log.unmatched_count})
        except Exception as exc:
            log.error_message = str(exc)
            log.save()
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    @action(detail=False, methods=['post'], url_path='bulk-print')
    def bulk_print(self, request):
        items = request.data.get('items', [])
        if not items:
            return Response({'error': 'items list is required'}, status=status.HTTP_400_BAD_REQUEST)
        printer = _resolve_printer(request.data.get('printer_id') or request.data.get('printer_slug'))
        user = request.user if request.user.is_authenticated else None
        jobs = []
        with transaction.atomic():
            for item in items:
                try:
                    barcode = ProductBarcode.objects.get(pk=item['barcode_id'])
                    quantity = int(item['quantity'])
                    if quantity < 1:
                        raise ValueError
                except (ProductBarcode.DoesNotExist, KeyError, TypeError, ValueError) as e:
                    return Response({'error': f'Invalid item: {e}'}, status=status.HTTP_400_BAD_REQUEST)
                jobs.append(_create_print_job(barcode, quantity, user=user, printer=printer))

        return Response(PrintJobSerializer(jobs, many=True).data, status=status.HTTP_201_CREATED)


class PrintJobViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Read + delete only. Print jobs are created via /barcodes/bulk-print/.

    Ivan #22: DELETE enabled so staff can clear log rows from the
    Print Queue tab. Refuses to delete jobs that are actively being
    processed by an agent ('claimed' / 'printing') — those rows
    should be cancelled first via the cancel action.
    """
    serializer_class = PrintJobSerializer
    queryset = PrintJob.objects.select_related('barcode__product').all()

    def get_queryset(self):
        qs = super().get_queryset()
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def destroy(self, request, *args, **kwargs):
        job = self.get_object()
        if job.status in ('claimed', 'printing'):
            return Response(
                {'error': f'Cannot delete a job with status "{job.status}". '
                          f'Cancel it first, or wait for the agent to finish.'},
                status=status.HTTP_409_CONFLICT,
            )
        job.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['get'], url_path='pending-count')
    def pending_count(self, request):
        count = PrintJob.objects.filter(status='pending').count()
        return Response({'count': count})

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        job = self.get_object()
        if job.status != 'pending':
            return Response(
                {'error': f'Cannot cancel a job with status "{job.status}"'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        job.status = 'cancelled'
        job.save(update_fields=['status', 'updated_at'])
        return Response(PrintJobSerializer(job).data)

    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        original = self.get_object()
        user = request.user if request.user.is_authenticated else None
        new_job = PrintJob.objects.create(
            barcode=original.barcode,
            quantity=original.quantity,
            command_payload=original.command_payload,
            command_language=original.command_language,
            status='pending',
            retry_count=original.retry_count + 1,
            requested_by=user,
        )
        return Response(PrintJobSerializer(new_job).data, status=status.HTTP_201_CREATED)


# --- Agent-facing views ---

@api_view(['GET'])
@authentication_classes([PrintAgentAuthentication])
@permission_classes([AllowAny])
def agent_pending(request):
    """
    Claim up to 10 pending jobs atomically.

    Agents identify themselves via two optional headers:
      - X-Agent-Id   — free-text hostname / instance id (logged on the job)
      - X-Printer    — slug of the Printer this agent serves (e.g. "pm-2411-bt").
                       When set, only jobs targeting that printer (or with no
                       printer_fk) are considered. When absent, only legacy
                       printer-less jobs are claimable — protects routed jobs
                       from being grabbed by an old agent that doesn't know
                       about printer routing.
    """
    from django.db.models import Q
    from .models import Printer

    batch_size = int(request.query_params.get('batch', 10))
    printer_slug = (request.headers.get('X-Printer') or '').strip()

    qs = (
        PrintJob.objects
        .select_for_update(skip_locked=True)
        .filter(status='pending')
    )
    if printer_slug:
        printer = Printer.objects.filter(slug=printer_slug, active=True).first()
        if printer:
            qs = qs.filter(Q(printer=printer) | Q(printer__isnull=True))
        else:
            # Unknown / inactive printer slug — claim nothing
            return Response([])
    else:
        # No printer header — legacy mode: only printer-less jobs
        qs = qs.filter(printer__isnull=True)

    with transaction.atomic():
        jobs = list(qs.order_by('created_at')[:batch_size])
        for job in jobs:
            job.status = 'claimed'
            job.claimed_at = timezone.now()
            job.agent_id = request.headers.get('X-Agent-Id', 'unknown')
            job.save(update_fields=['status', 'claimed_at', 'agent_id', 'updated_at'])
    return Response(PrintJobAgentSerializer(jobs, many=True).data)


@api_view(['POST'])
@authentication_classes([PrintAgentAuthentication])
@permission_classes([AllowAny])
def agent_complete(request, job_id):
    """Agent reports job done or error."""
    try:
        job = PrintJob.objects.get(pk=job_id)
    except PrintJob.DoesNotExist:
        return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)

    new_status = request.data.get('status')
    if new_status not in ('done', 'error'):
        return Response({'error': 'status must be "done" or "error"'}, status=status.HTTP_400_BAD_REQUEST)

    job.status = new_status
    if new_status == 'done':
        job.printed_at = timezone.now()
    if new_status == 'error':
        job.error_message = request.data.get('error_message', '')
    job.save(update_fields=['status', 'printed_at', 'error_message', 'updated_at'])
    return Response(PrintJobSerializer(job).data)


@api_view(['GET'])
@permission_classes([AllowAny])
def list_printers(request):
    """
    Public list of active printers — used by the barcodes page to render
    the "Send to" dropdown. No secrets exposed (transport / address shown
    so admins can sanity-check from the UI).
    """
    printers = Printer.objects.filter(active=True).order_by('name')
    return Response([
        {
            'id': p.pk,
            'name': p.name,
            'slug': p.slug,
            'transport': p.transport,
            'address': p.address,
            'command_language': p.command_language,
            'label_width_mm': p.label_width_mm,
            'label_height_mm': p.label_height_mm,
            'label_dpi': p.label_dpi,
        }
        for p in printers
    ])


def _print_agent_root() -> str:
    """Resolve the print_agent/ directory in dev (sibling of backend/) and
    in the Docker image (copied to /app/print_agent at build time)."""
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for candidate in (
        '/app/print_agent',                        # production container path
        os.path.join(here, 'print_agent'),         # repo-root sibling in dev
        os.path.join(here, '..', 'print_agent'),   # dev fallback
    ):
        if os.path.isdir(candidate):
            return os.path.abspath(candidate)
    return ''


@api_view(['GET'])
@permission_classes([AllowAny])
def serve_setup_script(request):
    """Serve the self-contained printer setup script for download."""
    from django.http import HttpResponse, Http404
    root = _print_agent_root()
    path = os.path.join(root, 'setup_printer.py') if root else ''
    if not path or not os.path.isfile(path):
        raise Http404('setup_printer.py not bundled')
    with open(path, 'r', encoding='utf-8') as fh:
        body = fh.read()
    resp = HttpResponse(body, content_type='text/x-python; charset=utf-8')
    resp['Content-Disposition'] = 'attachment; filename="setup_printer.py"'
    return resp


@api_view(['GET'])
@permission_classes([AllowAny])
def serve_agent_script(request):
    """Serve the latest agent.py so the installer can pick up updates."""
    from django.http import HttpResponse, Http404
    root = _print_agent_root()
    path = os.path.join(root, 'agent.py') if root else ''
    if not path or not os.path.isfile(path):
        raise Http404('agent.py not bundled')
    with open(path, 'r', encoding='utf-8') as fh:
        body = fh.read()
    return HttpResponse(body, content_type='text/x-python; charset=utf-8')
