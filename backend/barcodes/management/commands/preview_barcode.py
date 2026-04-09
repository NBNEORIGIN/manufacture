"""
Render a barcode label PNG preview via Labelary and write to /tmp.

    python manage.py preview_barcode <barcode_id>
"""
from django.core.management.base import BaseCommand, CommandError
from barcodes.models import ProductBarcode
from barcodes.services.rendering.base import build_spec_from_settings
from barcodes.services.rendering.factory import get_renderer
from barcodes.services.rendering.preview import render_preview_png


class Command(BaseCommand):
    help = 'Render a barcode label to PNG via Labelary and write to /tmp/preview_<id>.png'

    def add_arguments(self, parser):
        parser.add_argument('barcode_id', type=int)

    def handle(self, *args, **options):
        barcode_id = options['barcode_id']
        try:
            barcode = ProductBarcode.objects.select_related('product').get(pk=barcode_id)
        except ProductBarcode.DoesNotExist:
            raise CommandError(f"ProductBarcode #{barcode_id} not found")

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
            raise CommandError(f"Labelary request failed: {e}")

        out_path = f'/tmp/preview_{barcode_id}.png'
        with open(out_path, 'wb') as f:
            f.write(png_bytes)

        self.stdout.write(self.style.SUCCESS(f'Preview written to {out_path}'))
