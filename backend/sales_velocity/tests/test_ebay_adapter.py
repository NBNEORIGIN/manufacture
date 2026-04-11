"""
Tests for the EbayAdapter (Phase 2B.3).

Mocks httpx.Client via `_http_client=` injection, and pre-seeds an
OAuthCredential row so the adapter can look up its refresh token.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import httpx
import pytest
from django.utils import timezone as django_tz

from sales_velocity.adapters.ebay import EbayAdapter, _whitelist
from sales_velocity.models import OAuthCredential, SalesVelocityAPICall


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
def valid_cred(db):
    return OAuthCredential.objects.create(
        provider='ebay',
        refresh_token='test-refresh-token',
        access_token='test-access-token',
        access_token_expires_at=django_tz.now() + timedelta(hours=1),
        scope='sell.fulfillment',
    )


@pytest.fixture
def expired_cred(db):
    return OAuthCredential.objects.create(
        provider='ebay',
        refresh_token='test-refresh-token',
        access_token='stale',
        access_token_expires_at=django_tz.now() - timedelta(hours=1),
        scope='sell.fulfillment',
    )


@pytest.fixture
def mock_client():
    return MagicMock(spec=httpx.Client)


@pytest.fixture
def adapter(mock_client):
    return EbayAdapter(_http_client=mock_client)


@pytest.fixture(autouse=True)
def _ebay_settings(settings):
    settings.EBAY_CLIENT_ID = 'test-id'
    settings.EBAY_CLIENT_SECRET = 'test-secret'
    settings.EBAY_RU_NAME = 'test-ru'
    settings.EBAY_ENVIRONMENT = 'production'


@pytest.mark.django_db
class TestFetchOrders:
    def test_happy_path_single_page(self, adapter, mock_client, valid_cred):
        mock_client.get.return_value = _http_response(200, {
            'orders': [{
                'orderId': 'O-1', 'creationDate': '2026-04-05T10:00:00+00:00',
                'orderFulfillmentStatus': 'FULFILLED',
                'lineItems': [
                    {'lineItemId': 'L-1', 'sku': 'NBN-M0900', 'quantity': 2},
                    {'lineItemId': 'L-2', 'sku': 'NBN-M0901', 'quantity': 1},
                ],
            }],
            'next': None,
        })

        lines = adapter.fetch_orders(date(2026, 3, 12), date(2026, 4, 11))

        assert len(lines) == 2
        assert {l.external_sku for l in lines} == {'NBN-M0900', 'NBN-M0901'}
        assert all(l.sale_date == datetime(2026, 4, 5, 10, 0, tzinfo=timezone.utc) for l in lines)

    def test_follows_next_pagination(self, adapter, mock_client, valid_cred):
        page1 = _http_response(200, {
            'orders': [{'orderId': 'O-1', 'creationDate': '2026-04-05T00:00:00+00:00',
                        'lineItems': [{'sku': 'A', 'quantity': 1}]}],
            'next': 'https://api.ebay.com/sell/fulfillment/v1/order?offset=200',
        })
        page2 = _http_response(200, {
            'orders': [{'orderId': 'O-2', 'creationDate': '2026-04-06T00:00:00+00:00',
                        'lineItems': [{'sku': 'B', 'quantity': 1}]}],
            'next': None,
        })
        mock_client.get.side_effect = [page1, page2]

        lines = adapter.fetch_orders(date(2026, 4, 1), date(2026, 4, 11))

        assert mock_client.get.call_count == 2
        assert len(lines) == 2

    def test_sends_bearer_token(self, adapter, mock_client, valid_cred):
        mock_client.get.return_value = _http_response(200, {'orders': [], 'next': None})
        adapter.fetch_orders(date(2026, 4, 1), date(2026, 4, 11))
        headers = mock_client.get.call_args.kwargs['headers']
        assert headers['Authorization'] == 'Bearer test-access-token'

    def test_creationdate_filter_in_url(self, adapter, mock_client, valid_cred):
        mock_client.get.return_value = _http_response(200, {'orders': [], 'next': None})
        adapter.fetch_orders(date(2026, 3, 12), date(2026, 4, 11))
        url = mock_client.get.call_args.args[0]
        assert 'creationdate:' in url
        assert '2026-03-12' in url
        assert '2026-04-11' in url
        assert 'orderfulfillmentstatus:' in url


@pytest.mark.django_db
class TestTokenRefresh:
    def test_expired_token_triggers_refresh(self, adapter, mock_client, expired_cred):
        # First call: refresh
        # Second call: get_orders
        mock_client.post.return_value = _http_response(200, {
            'access_token': 'fresh-token',
            'refresh_token': 'rotated-refresh',
            'expires_in': 7200,
        })
        mock_client.get.return_value = _http_response(200, {'orders': [], 'next': None})

        adapter.fetch_orders(date(2026, 4, 1), date(2026, 4, 11))

        # Refresh was called
        assert mock_client.post.call_count == 1
        refresh_url = mock_client.post.call_args.args[0]
        assert 'oauth2/token' in refresh_url
        data = mock_client.post.call_args.kwargs['data']
        assert data['grant_type'] == 'refresh_token'
        assert data['refresh_token'] == 'test-refresh-token'

        # Row updated with new token
        expired_cred.refresh_from_db()
        assert expired_cred.access_token == 'fresh-token'
        assert expired_cred.refresh_token == 'rotated-refresh'
        assert expired_cred.access_token_expires_at > django_tz.now()

    def test_refresh_failure_clears_access_token(self, adapter, mock_client, expired_cred):
        mock_client.post.return_value = _http_response(
            400, text='{"error":"invalid_grant"}',
        )
        with pytest.raises(httpx.HTTPStatusError):
            adapter.fetch_orders(date(2026, 4, 1), date(2026, 4, 11))
        expired_cred.refresh_from_db()
        assert expired_cred.access_token == ''
        assert expired_cred.access_token_expires_at is None

    def test_missing_credential_row_raises(self, adapter, mock_client):
        with pytest.raises(RuntimeError, match='OAuthCredential row does not exist'):
            adapter.fetch_orders(date(2026, 4, 1), date(2026, 4, 11))


@pytest.mark.django_db
class TestAuditLogging:
    def test_success_writes_audit_row(self, adapter, mock_client, valid_cred):
        mock_client.get.return_value = _http_response(200, {
            'orders': [{'orderId': 'O-1', 'creationDate': '2026-04-05T10:00:00+00:00',
                        'lineItems': [{'sku': 'A', 'quantity': 1}]}],
            'next': None,
        })
        adapter.fetch_orders(date(2026, 4, 1), date(2026, 4, 11))
        rows = SalesVelocityAPICall.objects.filter(channel='ebay')
        assert rows.count() >= 1
        assert rows.first().response_status == 200


class TestWhitelistScrub:
    def test_drops_buyer_pii_from_orders(self):
        scrubbed = _whitelist({
            'orders': [{
                'orderId': 'O-1',
                'buyer': {'username': 'pii-buyer', 'email': 'pii@example.com'},
                'fulfillmentStartInstructions': [{'shippingStep': {
                    'shipTo': {'fullName': 'PII Name', 'contactAddress': {'addressLine1': '10 Street'}}
                }}],
                'orderFulfillmentStatus': 'FULFILLED',
                'lineItems': [{'sku': 'A', 'quantity': 2, 'title': 'SAFE'}],
            }],
            'next': None,
        })
        order = scrubbed['orders'][0]
        assert 'orderId' in order
        assert 'orderFulfillmentStatus' in order
        assert 'buyer' not in order
        assert 'fulfillmentStartInstructions' not in order
        assert order['lineItems'][0]['sku'] == 'A'
        assert order['lineItems'][0]['quantity'] == 2

    def test_none_passthrough(self):
        assert _whitelist(None) is None
