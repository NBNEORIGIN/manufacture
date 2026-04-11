"""
Tests for the Amazon sales-velocity adapter.

Uses `_client=` injection on `AmazonAdapter.__init__` to bypass saleweaver
instantiation entirely, so the tests don't need live SP-API credentials.
The injected mock returns pre-canned ApiResponse-shaped objects.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sales_velocity.adapters import NormalisedOrderLine
from sales_velocity.adapters.amazon import (
    AmazonAdapter,
    SALES_VELOCITY_TO_ENUM,
    SHIPPED_STATUSES,
    _whitelist,
    build_all_amazon_adapters,
)
from sales_velocity.models import SalesVelocityAPICall


def _api_response(payload):
    """Wrap a dict in a saleweaver-shaped ApiResponse stub (has .payload)."""
    return SimpleNamespace(payload=payload)


# ── Factory / construction ────────────────────────────────────────────────────

class TestConstruction:
    def test_build_all_amazon_adapters_returns_nine(self):
        adapters = build_all_amazon_adapters()
        assert len(adapters) == 9
        channels = {a.channel for a in adapters}
        assert channels == set(SALES_VELOCITY_TO_ENUM.keys())

    def test_rejects_unknown_channel(self):
        with pytest.raises(ValueError, match='Unknown Amazon sales_velocity channel'):
            AmazonAdapter('amazon_jp')

    def test_channel_attr_set_before_super_init(self):
        # Must not raise — channel is set before ABC validation
        adapter = AmazonAdapter('amazon_uk', _client=MagicMock())
        assert adapter.channel == 'amazon_uk'
        assert adapter._marketplace_code == 'UK'


# ── Fetch orders — happy path ─────────────────────────────────────────────────

@pytest.mark.django_db
class TestFetchOrdersHappyPath:
    def _make_mock(self, orders_payloads, items_payloads):
        """
        Build a mock client whose get_orders returns each payload in
        `orders_payloads` in sequence (for pagination), and whose
        get_order_items returns payloads from the `items_payloads` dict
        keyed by order_id.
        """
        mock = MagicMock()
        mock.get_orders = MagicMock(
            side_effect=[_api_response(p) for p in orders_payloads]
        )
        def _items(order_id, **kwargs):
            return _api_response(items_payloads[order_id])
        mock.get_order_items = MagicMock(side_effect=_items)
        return mock

    def test_single_page_single_order_single_item(self):
        orders_payloads = [{
            'Orders': [{
                'AmazonOrderId': '123-4567890-1234567',
                'PurchaseDate': '2026-04-05T10:15:00Z',
                'OrderStatus': 'Shipped',
            }],
            'NextToken': None,
        }]
        items_payloads = {
            '123-4567890-1234567': {
                'OrderItems': [{
                    'SellerSKU': 'NBN-M0823-SM-OAK',
                    'ASIN': 'B08XXXXXX',
                    'QuantityShipped': 3,
                    'QuantityOrdered': 3,
                    'OrderItemId': 'item-1',
                }],
            },
        }
        adapter = AmazonAdapter(
            'amazon_uk',
            _client=self._make_mock(orders_payloads, items_payloads),
        )

        lines = adapter.fetch_orders(date(2026, 4, 1), date(2026, 4, 11))

        assert len(lines) == 1
        assert lines[0].external_sku == 'NBN-M0823-SM-OAK'
        assert lines[0].quantity == 3
        assert lines[0].sale_date == datetime(2026, 4, 5, 10, 15, tzinfo=timezone.utc)
        assert lines[0].raw_data['marketplace'] == 'UK'

    def test_pagination_follows_next_token(self):
        orders_payloads = [
            {
                'Orders': [{
                    'AmazonOrderId': 'order-1',
                    'PurchaseDate': '2026-04-05T10:00:00Z',
                }],
                'NextToken': 'tok-abc',
            },
            {
                'Orders': [{
                    'AmazonOrderId': 'order-2',
                    'PurchaseDate': '2026-04-06T10:00:00Z',
                }],
                'NextToken': None,
            },
        ]
        items_payloads = {
            'order-1': {'OrderItems': [{'SellerSKU': 'SKU-A', 'QuantityShipped': 1}]},
            'order-2': {'OrderItems': [{'SellerSKU': 'SKU-B', 'QuantityShipped': 2}]},
        }
        mock = self._make_mock(orders_payloads, items_payloads)
        adapter = AmazonAdapter('amazon_uk', _client=mock)
        lines = adapter.fetch_orders(date(2026, 4, 1), date(2026, 4, 11))

        assert mock.get_orders.call_count == 2
        # Second call must include the NextToken from page 1
        second_kwargs = mock.get_orders.call_args_list[1].kwargs
        assert second_kwargs.get('NextToken') == 'tok-abc'
        assert len(lines) == 2
        assert {l.external_sku for l in lines} == {'SKU-A', 'SKU-B'}

    def test_shipped_statuses_passed_to_get_orders(self):
        mock = self._make_mock(
            orders_payloads=[{'Orders': [], 'NextToken': None}],
            items_payloads={},
        )
        adapter = AmazonAdapter('amazon_us', _client=mock)
        adapter.fetch_orders(date(2026, 4, 1), date(2026, 4, 11))

        call_kwargs = mock.get_orders.call_args.kwargs
        assert call_kwargs['OrderStatuses'] == SHIPPED_STATUSES
        assert 'CreatedAfter' in call_kwargs
        assert 'CreatedBefore' in call_kwargs

    def test_line_items_with_zero_shipped_qty_are_skipped(self):
        orders_payloads = [{
            'Orders': [{
                'AmazonOrderId': 'order-1',
                'PurchaseDate': '2026-04-05T10:00:00Z',
            }],
            'NextToken': None,
        }]
        items_payloads = {
            'order-1': {
                'OrderItems': [
                    {'SellerSKU': 'SKU-A', 'QuantityShipped': 2},
                    {'SellerSKU': 'SKU-B', 'QuantityShipped': 0},  # unshipped line
                    {'SellerSKU': None, 'QuantityShipped': 5},     # missing SKU
                ],
            },
        }
        adapter = AmazonAdapter(
            'amazon_uk',
            _client=self._make_mock(orders_payloads, items_payloads),
        )
        lines = adapter.fetch_orders(date(2026, 4, 1), date(2026, 4, 11))
        assert len(lines) == 1
        assert lines[0].external_sku == 'SKU-A'
        assert lines[0].quantity == 2

    def test_empty_window_returns_empty_list(self):
        mock = self._make_mock(
            orders_payloads=[{'Orders': [], 'NextToken': None}],
            items_payloads={},
        )
        adapter = AmazonAdapter('amazon_uk', _client=mock)
        lines = adapter.fetch_orders(date(2026, 4, 1), date(2026, 4, 11))
        assert lines == []
        # No get_order_items call if there were no orders
        mock.get_order_items.assert_not_called()


# ── Audit logging ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestAuditLogging:
    def test_success_writes_audit_row_per_call(self):
        mock = MagicMock()
        mock.get_orders = MagicMock(
            return_value=_api_response({
                'Orders': [{'AmazonOrderId': 'o1', 'PurchaseDate': '2026-04-05T10:00:00Z'}],
                'NextToken': None,
            })
        )
        mock.get_order_items = MagicMock(
            return_value=_api_response({
                'OrderItems': [{'SellerSKU': 'SKU-A', 'QuantityShipped': 1}],
            })
        )
        adapter = AmazonAdapter('amazon_uk', _client=mock)
        adapter.fetch_orders(date(2026, 4, 1), date(2026, 4, 11))

        rows = SalesVelocityAPICall.objects.filter(channel='amazon_uk')
        # One get_orders call + one get_order_items call
        assert rows.count() == 2
        endpoints = {r.endpoint for r in rows}
        assert 'orders/v0/orders' in endpoints
        assert any(ep.startswith('orders/v0/orders/o1') for ep in endpoints)
        # All success
        assert all(r.response_status == 200 for r in rows)
        assert all(r.error_message == '' for r in rows)

    def test_pii_is_scrubbed_from_audit_response_body(self):
        # Amazon would return BuyerEmail, BuyerName, etc. The scrub
        # must drop them before the row is persisted.
        mock = MagicMock()
        mock.get_orders = MagicMock(return_value=_api_response({
            'Orders': [{
                'AmazonOrderId': 'o1',
                'PurchaseDate': '2026-04-05T10:00:00Z',
                'BuyerEmail': 'customer@example.com',
                'BuyerName': 'Jane Doe',
                'ShippingAddress': {'Name': 'Jane Doe', 'AddressLine1': '10 Something St'},
                'OrderStatus': 'Shipped',
                'MarketplaceId': 'A1F83G8C2ARO7P',
            }],
            'NextToken': None,
        }))
        mock.get_order_items = MagicMock(return_value=_api_response({'OrderItems': []}))

        adapter = AmazonAdapter('amazon_uk', _client=mock)
        adapter.fetch_orders(date(2026, 4, 1), date(2026, 4, 11))

        row = SalesVelocityAPICall.objects.get(endpoint='orders/v0/orders')
        body = row.response_body
        order = body['Orders'][0]
        assert 'AmazonOrderId' in order
        assert 'OrderStatus' in order
        assert 'MarketplaceId' in order
        assert 'BuyerEmail' not in order
        assert 'BuyerName' not in order
        assert 'ShippingAddress' not in order


# ── Whitelist unit tests ──────────────────────────────────────────────────────

class TestWhitelistScrub:
    def test_drops_top_level_unknown_keys(self):
        scrubbed = _whitelist({
            'Orders': [{'AmazonOrderId': 'x', 'BuyerEmail': 'y@z.com'}],
            'NextToken': 'tok-keep',
            'SomeRandomField': 'drop-me',
        })
        assert 'NextToken' in scrubbed
        assert 'SomeRandomField' not in scrubbed
        assert 'BuyerEmail' not in scrubbed['Orders'][0]
        assert scrubbed['Orders'][0]['AmazonOrderId'] == 'x'

    def test_drops_pii_from_order_items(self):
        scrubbed = _whitelist({
            'OrderItems': [{
                'SellerSKU': 'SKU-A',
                'QuantityShipped': 3,
                'GiftMessageText': 'HAPPY BIRTHDAY JANE',
                'BuyerCustomizedInfo': 'custom text',
            }],
        })
        item = scrubbed['OrderItems'][0]
        assert item['SellerSKU'] == 'SKU-A'
        assert item['QuantityShipped'] == 3
        assert 'GiftMessageText' not in item
        assert 'BuyerCustomizedInfo' not in item

    def test_none_passthrough(self):
        assert _whitelist(None) is None

    def test_list_passthrough_at_top_level(self):
        # An unusual shape but the scrub shouldn't crash
        assert _whitelist([1, 2, 3]) == [1, 2, 3]
