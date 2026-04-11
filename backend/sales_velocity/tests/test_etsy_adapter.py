"""
Tests for the EtsyAdapter (Phase 2B.3).

The adapter is a thin HTTP wrapper over Cairn's /etsy/sales endpoint,
so the tests mock httpx.Client via the `_http_client=` injection hook
and assert on the request shape + response parsing.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import httpx
import pytest

from sales_velocity.adapters.etsy import EtsyAdapter
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
    return EtsyAdapter(_http_client=mock_client)


@pytest.fixture(autouse=True)
def _cairn_settings(settings):
    """Set CAIRN_API_URL + CAIRN_API_KEY for every test in this module."""
    settings.CAIRN_API_URL = 'http://cairn.example/'
    settings.CAIRN_API_KEY = 'test-key'


@pytest.mark.django_db
class TestFetchOrders:
    def test_happy_path(self, adapter, mock_client):
        mock_client.get.return_value = _http_response(200, {
            'rows': [
                {
                    'shop_id': 11706740,
                    'listing_id': 2001,
                    'external_sku': 'NBN-M0823-SM-OAK',
                    'total_quantity': 5,
                    'first_sale_date': '2026-04-01T10:00:00+00:00',
                    'last_sale_date':  '2026-04-10T10:00:00+00:00',
                },
                {
                    'shop_id': 11706740,
                    'listing_id': 2002,
                    'external_sku': 'NBN-M0824-MD-OAK',
                    'total_quantity': 2,
                    'first_sale_date': '2026-04-05T10:00:00+00:00',
                    'last_sale_date':  '2026-04-08T10:00:00+00:00',
                },
            ],
            'window_days': 30, 'window_end': '2026-04-11T00:00:00+00:00',
            'shop_id_filter': None, 'row_count': 2,
            'skipped_null_sku': 0, 'skipped_multi_sku': 0,
        })

        lines = adapter.fetch_orders(date(2026, 3, 12), date(2026, 4, 11))

        assert len(lines) == 2
        assert lines[0].external_sku == 'NBN-M0823-SM-OAK'
        assert lines[0].quantity == 5
        assert lines[0].sale_date == datetime(2026, 4, 10, 10, 0, tzinfo=timezone.utc)
        assert lines[1].external_sku == 'NBN-M0824-MD-OAK'
        assert lines[1].quantity == 2

    def test_sends_x_api_key_header(self, adapter, mock_client):
        mock_client.get.return_value = _http_response(200, {'rows': []})
        adapter.fetch_orders(date(2026, 3, 12), date(2026, 4, 11))
        call_kwargs = mock_client.get.call_args.kwargs
        assert call_kwargs['headers']['X-API-Key'] == 'test-key'

    def test_sends_days_query_param(self, adapter, mock_client):
        mock_client.get.return_value = _http_response(200, {'rows': []})
        adapter.fetch_orders(date(2026, 3, 13), date(2026, 4, 11))  # 30 days
        call_kwargs = mock_client.get.call_args.kwargs
        # Inclusive range means end - start + 1
        assert call_kwargs['params']['days'] == 30

    def test_empty_rows_returns_empty_list(self, adapter, mock_client):
        mock_client.get.return_value = _http_response(200, {
            'rows': [], 'row_count': 0,
            'skipped_null_sku': 0, 'skipped_multi_sku': 0,
        })
        assert adapter.fetch_orders(date(2026, 4, 1), date(2026, 4, 11)) == []

    def test_zero_quantity_rows_are_skipped(self, adapter, mock_client):
        mock_client.get.return_value = _http_response(200, {
            'rows': [
                {'external_sku': 'A', 'total_quantity': 0, 'shop_id': 1, 'listing_id': 1,
                 'last_sale_date': '2026-04-10T00:00:00+00:00'},
                {'external_sku': 'B', 'total_quantity': 3, 'shop_id': 1, 'listing_id': 2,
                 'last_sale_date': '2026-04-10T00:00:00+00:00'},
            ],
        })
        lines = adapter.fetch_orders(date(2026, 4, 1), date(2026, 4, 11))
        assert len(lines) == 1
        assert lines[0].external_sku == 'B'

    def test_cairn_unreachable_raises_and_logs_audit(self, adapter, mock_client):
        mock_client.get.side_effect = httpx.ConnectError('connection refused')
        with pytest.raises(httpx.ConnectError):
            adapter.fetch_orders(date(2026, 4, 1), date(2026, 4, 11))
        row = SalesVelocityAPICall.objects.filter(channel='etsy').last()
        assert row is not None
        assert 'ConnectError' in row.error_message
        assert row.response_status is None

    def test_500_from_cairn_logs_and_raises(self, adapter, mock_client):
        mock_client.get.return_value = _http_response(500, text='internal error')
        with pytest.raises(httpx.HTTPStatusError):
            adapter.fetch_orders(date(2026, 4, 1), date(2026, 4, 11))
        row = SalesVelocityAPICall.objects.filter(channel='etsy').last()
        assert row is not None
        assert row.response_status == 500


@pytest.mark.django_db
class TestAuditLogging:
    def test_success_writes_audit_row(self, adapter, mock_client):
        mock_client.get.return_value = _http_response(200, {
            'rows': [{'external_sku': 'X', 'total_quantity': 1, 'shop_id': 1,
                      'listing_id': 1, 'last_sale_date': '2026-04-10T00:00:00+00:00'}],
        })
        adapter.fetch_orders(date(2026, 4, 1), date(2026, 4, 11))
        rows = SalesVelocityAPICall.objects.filter(channel='etsy')
        assert rows.count() == 1
        assert rows.first().endpoint == 'GET /etsy/sales'
        assert rows.first().response_status == 200

    def test_scrub_keeps_whitelisted_only(self, adapter, mock_client):
        # Add an extra key the whitelist should drop
        mock_client.get.return_value = _http_response(200, {
            'rows': [{
                'shop_id': 1, 'listing_id': 1,
                'external_sku': 'X', 'total_quantity': 1,
                'first_sale_date': '2026-04-01T00:00:00+00:00',
                'last_sale_date': '2026-04-10T00:00:00+00:00',
                'buyer_email': 'pii@example.com',
            }],
            'row_count': 1,
            'secret_debug_field': 'should-be-dropped',
        })
        adapter.fetch_orders(date(2026, 4, 1), date(2026, 4, 11))
        audit = SalesVelocityAPICall.objects.filter(channel='etsy').first()
        body = audit.response_body
        assert 'secret_debug_field' not in body
        assert 'buyer_email' not in body['rows'][0]
        assert body['rows'][0]['external_sku'] == 'X'
