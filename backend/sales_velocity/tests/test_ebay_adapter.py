"""
Tests for the EbayAdapter (post-Deek-cutover, 2026-05-08).

The adapter is now a thin HTTP wrapper over Cairn's /ebay/sales endpoint
(commit 4f40a1a on the Deek side). Tests mock httpx.Client via the
`_http_client=` injection hook and assert on the request shape +
response parsing — same pattern as test_etsy_adapter.py.

The previous test file exercised the original direct-to-eBay
implementation (OAuth refresh, paginated /sell/fulfillment/v1/order,
the lot). All of that moved to Deek so those tests no longer reflect
reality. Replaced wholesale with this file.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import httpx
import pytest

from sales_velocity.adapters.ebay import EbayAdapter
from sales_velocity.models import SalesVelocityAPICall


def _http_response(status_code, json_payload=None, text=''):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_payload or {})
    resp.text = text
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f'{status_code}', request=MagicMock(), response=resp,
        )
    return resp


@pytest.fixture
def mock_client():
    return MagicMock(spec=httpx.Client)


@pytest.fixture
def adapter(mock_client):
    return EbayAdapter(_http_client=mock_client)


@pytest.fixture(autouse=True)
def _cairn_settings(settings):
    """Set CAIRN_API_URL + CAIRN_API_KEY for every test in this module."""
    settings.CAIRN_API_URL = 'http://cairn.example/'
    settings.CAIRN_API_KEY = 'test-key'


def _sale(**overrides):
    """Build a sale row matching Cairn's /ebay/sales response shape."""
    base = {
        'order_id':           '27-14574-55634',
        'legacy_order_id':    '27-14574-55634',
        'line_item_id':       '10084809895427',
        'item_id':            187478519465,
        'sku':                'OD014002White',
        'quantity':           1,
        'unit_price':         12.99,
        'total_price':        12.99,
        'shipping_cost':      0.0,
        'total_paid':         12.99,
        'fees':               None,
        'currency':           'GBP',
        'buyer_country':      'GB',
        'fulfillment_status': 'FULFILLED',
        'payment_status':     'PAID',
        'sale_date':          '2026-05-06T09:14:47+00:00',
    }
    base.update(overrides)
    return base


@pytest.mark.django_db
class TestFetchOrders:
    def test_happy_path(self, adapter, mock_client):
        mock_client.get.return_value = _http_response(200, {
            'count': 2,
            'days_back': 30,
            'sales': [
                _sale(sku='OD014002White', quantity=1, sale_date='2026-05-06T09:14:47+00:00'),
                _sale(sku='M0726-Saville', quantity=3, line_item_id='lid-2',
                      sale_date='2026-05-04T15:30:00+00:00'),
            ],
        })

        lines = adapter.fetch_orders(date(2026, 4, 7), date(2026, 5, 6))

        assert len(lines) == 2
        assert lines[0].external_sku == 'OD014002White'
        assert lines[0].quantity == 1
        assert lines[0].sale_date == datetime(2026, 5, 6, 9, 14, 47, tzinfo=timezone.utc)
        assert lines[1].external_sku == 'M0726-Saville'
        assert lines[1].quantity == 3

    def test_sends_x_api_key_header(self, adapter, mock_client):
        mock_client.get.return_value = _http_response(200, {'count': 0, 'sales': []})
        adapter.fetch_orders(date(2026, 4, 7), date(2026, 5, 6))
        call_kwargs = mock_client.get.call_args.kwargs
        assert call_kwargs['headers']['X-API-Key'] == 'test-key'

    def test_sends_days_back_param(self, adapter, mock_client):
        mock_client.get.return_value = _http_response(200, {'count': 0, 'sales': []})
        adapter.fetch_orders(date(2026, 4, 7), date(2026, 5, 6))  # 30 days inclusive
        call_kwargs = mock_client.get.call_args.kwargs
        assert call_kwargs['params']['days_back'] == 30

    def test_same_day_floors_at_one(self, adapter, mock_client):
        """end_date == start_date should still send days_back=1 (not 0)."""
        mock_client.get.return_value = _http_response(200, {'count': 0, 'sales': []})
        adapter.fetch_orders(date(2026, 5, 6), date(2026, 5, 6))
        assert mock_client.get.call_args.kwargs['params']['days_back'] == 1

    def test_empty_sales_returns_empty_list(self, adapter, mock_client):
        mock_client.get.return_value = _http_response(200, {'count': 0, 'sales': []})
        assert adapter.fetch_orders(date(2026, 4, 1), date(2026, 5, 6)) == []

    def test_zero_quantity_rows_skipped(self, adapter, mock_client):
        mock_client.get.return_value = _http_response(200, {
            'count': 2,
            'sales': [
                _sale(sku='A', quantity=0),
                _sale(sku='B', quantity=3, line_item_id='lid-2'),
            ],
        })
        lines = adapter.fetch_orders(date(2026, 4, 7), date(2026, 5, 6))
        assert len(lines) == 1
        assert lines[0].external_sku == 'B'

    def test_missing_sku_skipped(self, adapter, mock_client):
        """A row with no SKU can't be attributed to a Product — skip silently."""
        mock_client.get.return_value = _http_response(200, {
            'count': 3,
            'sales': [
                _sale(sku=None, quantity=1),
                _sale(sku='', quantity=1, line_item_id='lid-2'),
                _sale(sku='OD014002White', quantity=1, line_item_id='lid-3'),
            ],
        })
        lines = adapter.fetch_orders(date(2026, 4, 7), date(2026, 5, 6))
        assert len(lines) == 1
        assert lines[0].external_sku == 'OD014002White'

    def test_raw_data_carries_order_metadata(self, adapter, mock_client):
        mock_client.get.return_value = _http_response(200, {
            'count': 1,
            'sales': [_sale(
                order_id='ORD-1', legacy_order_id='LOG-1',
                line_item_id='LI-1', item_id=999,
                fulfillment_status='FULFILLED', total_paid=42.50,
                buyer_country='IE',
            )],
        })
        lines = adapter.fetch_orders(date(2026, 4, 7), date(2026, 5, 6))
        assert lines[0].raw_data['order_id'] == 'ORD-1'
        assert lines[0].raw_data['legacy_order_id'] == 'LOG-1'
        assert lines[0].raw_data['line_item_id'] == 'LI-1'
        assert lines[0].raw_data['item_id'] == 999
        assert lines[0].raw_data['total_paid'] == 42.50
        assert lines[0].raw_data['buyer_country'] == 'IE'

    def test_cairn_unreachable_raises_and_logs_audit(self, adapter, mock_client):
        mock_client.get.side_effect = httpx.ConnectError('connection refused')
        with pytest.raises(httpx.ConnectError):
            adapter.fetch_orders(date(2026, 4, 7), date(2026, 5, 6))
        row = SalesVelocityAPICall.objects.filter(channel='ebay').last()
        assert row is not None
        assert 'ConnectError' in row.error_message
        assert row.response_status is None

    def test_500_from_cairn_logs_and_raises(self, adapter, mock_client):
        mock_client.get.return_value = _http_response(500, text='internal error')
        with pytest.raises(httpx.HTTPStatusError):
            adapter.fetch_orders(date(2026, 4, 7), date(2026, 5, 6))
        row = SalesVelocityAPICall.objects.filter(channel='ebay').last()
        assert row is not None
        assert row.response_status == 500


@pytest.mark.django_db
class TestAuditLogging:
    def test_success_writes_audit_row(self, adapter, mock_client):
        mock_client.get.return_value = _http_response(200, {
            'count': 1,
            'sales': [_sale()],
        })
        adapter.fetch_orders(date(2026, 4, 7), date(2026, 5, 6))
        rows = SalesVelocityAPICall.objects.filter(channel='ebay')
        assert rows.count() == 1
        assert rows.first().endpoint == 'GET /ebay/sales'
        assert rows.first().response_status == 200

    def test_scrub_drops_unknown_top_level_keys(self, adapter, mock_client):
        mock_client.get.return_value = _http_response(200, {
            'count': 1,
            'sales': [_sale()],
            'secret_debug_field': 'should-be-dropped',
        })
        adapter.fetch_orders(date(2026, 4, 7), date(2026, 5, 6))
        audit = SalesVelocityAPICall.objects.filter(channel='ebay').first()
        body = audit.response_body
        assert 'secret_debug_field' not in body
        assert body['count'] == 1

    def test_scrub_drops_unknown_per_sale_keys(self, adapter, mock_client):
        """The /ebay/sales response is PII-clean upstream, but the
        whitelist defends against future endpoint additions."""
        mock_client.get.return_value = _http_response(200, {
            'count': 1,
            'sales': [{
                **_sale(),
                'buyer_email':   'pii@example.com',  # never sent by Cairn, but defend
                'buyer_address': '1 Privacy Lane',
            }],
        })
        adapter.fetch_orders(date(2026, 4, 7), date(2026, 5, 6))
        audit = SalesVelocityAPICall.objects.filter(channel='ebay').first()
        sale = audit.response_body['sales'][0]
        assert 'buyer_email' not in sale
        assert 'buyer_address' not in sale
        assert sale['sku'] == 'OD014002White'
        assert sale['buyer_country'] == 'GB'
