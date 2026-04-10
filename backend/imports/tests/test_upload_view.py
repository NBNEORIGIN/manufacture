"""
End-to-end HTTP tests for /api/imports/upload/ and /api/imports/history/.

Covers:
  * preview upload never creates an ImportLog row
  * confirmed upload creates exactly one ImportLog with correct counts
  * missing file → 400
  * unknown report_type → 400 with suggested options
  * auto-detection of report type from content
  * history endpoint ordering + shape
  * file encoding fallback (utf-8-sig → latin-1)
"""

from __future__ import annotations

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from imports.models import ImportLog


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def seeded_product(db):
    from products.models import Product, SKU
    from stock.models import StockLevel

    product = Product.objects.create(
        m_number='M0300',
        description='View Test Widget',
        blank='A4s',
    )
    SKU.objects.create(product=product, sku='NBNE-V-UK', channel='UK')
    StockLevel.objects.create(
        product=product,
        current_stock=5,
        fba_stock=10,
        sixty_day_sales=0,
        optimal_stock_30d=50,
        stock_deficit=45,
    )
    return product


def _upload(api, content: bytes, filename: str, **extra):
    f = SimpleUploadedFile(filename, content, content_type='text/csv')
    data = {'file': f, **extra}
    return api.post('/api/imports/upload/', data=data, format='multipart')


# --------------------------------------------------------------------------- #
# Preview vs confirm                                                          #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestUploadPreviewVsConfirm:
    def test_preview_does_not_create_import_log(self, api, seeded_product):
        csv = b'sku,asin,afn-fulfillable-quantity\nNBNE-V-UK,B0099,42\n'
        resp = _upload(api, csv, 'fba.csv', report_type='fba_inventory')

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body['preview'] is True
        assert body['report_type'] == 'fba_inventory'
        assert len(body['changes']) == 1
        assert ImportLog.objects.count() == 0

    def test_confirm_creates_import_log_with_correct_counts(self, api, seeded_product):
        csv = b'sku,asin,afn-fulfillable-quantity\nNBNE-V-UK,B0099,42\nUNKNOWN,B0000,5\n'
        resp = _upload(
            api, csv, 'fba.csv',
            report_type='fba_inventory',
            confirm='true',
        )
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body['preview'] is False
        assert len(body['changes']) == 1
        assert len(body['skipped']) == 1

        assert ImportLog.objects.count() == 1
        log = ImportLog.objects.first()
        assert log.import_type == 'fba_inventory'
        assert log.filename == 'fba.csv'
        assert log.rows_processed == 2
        assert log.rows_updated == 1
        assert log.rows_skipped == 1

    def test_preview_does_not_mutate_stock_level(self, api, seeded_product):
        from stock.models import StockLevel
        csv = b'sku,asin,afn-fulfillable-quantity\nNBNE-V-UK,B0099,42\n'
        _upload(api, csv, 'fba.csv', report_type='fba_inventory')
        stock = StockLevel.objects.get(product=seeded_product)
        assert stock.fba_stock == 10  # unchanged


# --------------------------------------------------------------------------- #
# Error paths                                                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestUploadErrors:
    def test_missing_file_returns_400(self, api):
        resp = api.post('/api/imports/upload/', data={}, format='multipart')
        assert resp.status_code == 400
        assert 'error' in resp.json()

    def test_unknown_report_type_returns_400_with_options(self, api):
        csv = b'sku,other\nfoo,bar\n'
        resp = _upload(api, csv, 'x.csv', report_type='magic_report')
        assert resp.status_code == 400
        body = resp.json()
        assert 'error' in body
        assert 'options' in body
        assert 'fba_inventory' in body['options']

    def test_undetectable_report_type_returns_400(self, api):
        # No known columns, no explicit report_type
        csv = b'foo,bar,baz\n1,2,3\n'
        resp = _upload(api, csv, 'x.csv')
        assert resp.status_code == 400
        body = resp.json()
        assert 'options' in body

    def test_empty_file_returns_400(self, api):
        csv = b'sku,afn-fulfillable-quantity\n'  # header only
        resp = _upload(api, csv, 'x.csv', report_type='fba_inventory')
        assert resp.status_code == 400
        assert 'No items found' in resp.json()['error']


# --------------------------------------------------------------------------- #
# Auto-detection                                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestUploadAutoDetect:
    def test_auto_detects_fba_inventory(self, api, seeded_product):
        csv = b'sku,afn-fulfillable-quantity\nNBNE-V-UK,42\n'
        resp = _upload(api, csv, 'unknown.csv')  # no report_type given
        assert resp.status_code == 200
        assert resp.json()['report_type'] == 'fba_inventory'

    def test_auto_detects_sales_traffic(self, api, seeded_product):
        csv = b'SKU,Units Ordered\nNBNE-V-UK,7\n'
        resp = _upload(api, csv, 'unknown.csv')
        assert resp.status_code == 200
        assert resp.json()['report_type'] == 'sales_traffic'

    def test_auto_detects_zenstores(self, api):
        csv = (
            b'Order ID,Lineitem SKU,Lineitem quantity\n'
            b'O1,NBNE-V-UK,1\n'
        )
        resp = _upload(api, csv, 'orders.csv')
        assert resp.status_code == 200
        assert resp.json()['report_type'] == 'zenstores'


# --------------------------------------------------------------------------- #
# Encoding fallback                                                           #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestUploadEncoding:
    def test_utf8_bom_is_handled(self, api, seeded_product):
        # Seller Central exports often have a UTF-8 BOM
        csv = '\ufeffsku,afn-fulfillable-quantity\nNBNE-V-UK,42\n'.encode('utf-8')
        resp = _upload(api, csv, 'bom.csv', report_type='fba_inventory')
        assert resp.status_code == 200
        body = resp.json()
        assert len(body['changes']) == 1

    def test_latin1_fallback(self, api, seeded_product):
        # Latin-1 characters that break utf-8 decode should trigger the fallback
        raw = 'sku,afn-fulfillable-quantity,product-name\nNBNE-V-UK,42,Caf\xe9 Sign\n'
        csv = raw.encode('latin-1')
        resp = _upload(api, csv, 'latin.csv', report_type='fba_inventory')
        assert resp.status_code == 200
        assert len(resp.json()['changes']) == 1


# --------------------------------------------------------------------------- #
# History endpoint                                                            #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestImportHistory:
    def test_history_empty(self, api):
        resp = api.get('/api/imports/history/')
        assert resp.status_code == 200
        assert resp.json() == []

    def test_history_newest_first(self, api, seeded_product):
        # Create two confirmed uploads, newest should sort first
        csv1 = b'sku,afn-fulfillable-quantity\nNBNE-V-UK,1\n'
        csv2 = b'sku,afn-fulfillable-quantity\nNBNE-V-UK,2\n'
        _upload(api, csv1, 'first.csv', report_type='fba_inventory', confirm='true')
        _upload(api, csv2, 'second.csv', report_type='fba_inventory', confirm='true')

        resp = api.get('/api/imports/history/')
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        # ImportLog.Meta.ordering = ['-created_at'] → newest first
        assert body[0]['filename'] == 'second.csv'
        assert body[1]['filename'] == 'first.csv'

    def test_history_shape(self, api, seeded_product):
        csv = b'sku,afn-fulfillable-quantity\nNBNE-V-UK,3\n'
        _upload(api, csv, 'shape.csv', report_type='fba_inventory', confirm='true')
        resp = api.get('/api/imports/history/')
        entry = resp.json()[0]
        for k in (
            'id', 'import_type', 'filename',
            'rows_processed', 'rows_created', 'rows_updated', 'rows_skipped',
            'error_count', 'created_at',
        ):
            assert k in entry
        # import_type is the display label not the raw key
        assert entry['import_type'] == 'FBA Inventory Report'
