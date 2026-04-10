from django.db import transaction
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, action, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .authentication import PrintAgentAuthentication
from .services.sp_api_sync import sync_fnskus_for_marketplace
from .services.pdf import generate_label_pdf
from .models import ProductBarcode, PrintJob, FNSKUSyncLog
from .serializers import ProductBarcodeSerializer, PrintJobSerializer, PrintJobAgentSerializer
from .services.rendering.base import build_spec_from_settings
from .services.rendering.factory import get_renderer
from .services.rendering.preview import render_preview_png


def _create_print_job(barcode: ProductBarcode, quantity: int, user=None) -> PrintJob:
    spec = build_spec_from_settings(
        barcode_value=barcode.barcode_value,
        label_title=barcode.label_title,
        condition=barcode.condition,
    )
    renderer = get_renderer()
    payload = renderer.render(spec, quantity=quantity)
    return PrintJob.objects.create(
        barcode=barcode,
        quantity=quantity,
        command_payload=payload,
        command_language=renderer.content_type.split('/')[-1],
        requested_by=user,
        status='pending',
    )


class ProductBarcodeViewSet(viewsets.ModelViewSet):
    serializer_class = ProductBarcodeSerializer
    queryset = ProductBarcode.objects.select_related('product').all()

    def get_queryset(self):
        qs = super().get_queryset()
        product = self.request.query_params.get('product')
        marketplace = self.request.query_params.get('marketplace')
        if product:
            qs = qs.filter(product_id=product)
        if marketplace:
            qs = qs.filter(marketplace=marketplace)
        return qs

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
        job = _create_print_job(barcode, quantity, user=request.user if request.user.is_authenticated else None)
        return Response(PrintJobSerializer(job).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='pdf')
    def pdf(self, request):
        """
        Generate an Avery 27-up PDF for the given barcodes.

        Body: { "items": [{"barcode_id": 1, "quantity": 3}, ...] }
        Returns: application/pdf
        """
        items = request.data.get('items', [])
        if not items:
            return Response({'error': 'items list is required'}, status=status.HTTP_400_BAD_REQUEST)

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
            })

        try:
            pdf_bytes = generate_label_pdf(label_items)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        from django.http import HttpResponse
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = 'inline; filename="barcode-labels.pdf"'
        return response

    @action(detail=False, methods=['post'], url_path='sync-fnskus')
    def sync_fnskus(self, request):
        marketplace = request.data.get('marketplace', 'UK')
        from django.utils import timezone
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
                jobs.append(_create_print_job(barcode, quantity, user=user))

        return Response(PrintJobSerializer(jobs, many=True).data, status=status.HTTP_201_CREATED)


class PrintJobViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PrintJobSerializer
    queryset = PrintJob.objects.select_related('barcode__product').all()

    def get_queryset(self):
        qs = super().get_queryset()
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

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
    """Claim up to 10 pending jobs atomically."""
    batch_size = int(request.query_params.get('batch', 10))
    with transaction.atomic():
        jobs = list(
            PrintJob.objects
            .select_for_update(skip_locked=True)
            .filter(status='pending')
            .order_by('created_at')[:batch_size]
        )
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
