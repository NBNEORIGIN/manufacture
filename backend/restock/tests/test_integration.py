"""
Integration tests for the restock pipeline.

Tests the full chain: parse raw SP-API TSV → derive alerts → run quantity
calculator → assert recommendations. Does NOT require a running database
or SP-API credentials.

NOTE on the fixture format:
  The fixture is tab-separated in the exact shape returned by SP-API's
  GET_FBA_INVENTORY_PLANNING_DATA report. Column names match the
  canonical SP-API headers (sku, fnsku, asin, available, units-shipped-t30,
  days-of-supply, 'Recommended ship-in quantity', 'Recommended ship-in date').
  An earlier version of these tests used a comma-separated human-readable
  fixture; that was the old manual-CSV upload format, which the parser
  no longer supports — it now consumes the raw report bytes directly from
  restock.spapi_client.download_report(). If SP-API ever changes its
  column names this fixture will need updating alongside schema.COLUMN_MAP.

Run: pytest restock/tests/test_integration.py
"""

from datetime import date

import pytest

from restock.newsvendor import NewsvendorInput, calculate_restock_qty
from restock.parser import parse_restock_csv


# Tab-separated, SP-API canonical headers. Report uses 'UK' for GB,
# which the parser normalises to 'GB' on read.
SAMPLE_TSV = (
    b'sku\tfnsku\tasin\tproduct-name\tmarketplace\tyour-price\t'
    b'sales-shipped-last-30-days\tunits-shipped-t30\tavailable\t'
    b'inbound-quantity\tdays-of-supply\talert\tRecommended ship-in quantity\t'
    b'Recommended ship-in date\tstorage-type\n'
    # Row 1: GB out_of_stock — 0 available, 24 units sold in 30d
    b'OD001209UK\tX00123\tB01EXAMPLE1\tWooden Push Sign DONALD\tUK\t9.99\t'
    b'245.00\t24\t0\t0\t0\t\t227\t04/07/2026\tSmall\n'
    # Row 2: GB reorder_now — 10 available, 18 sold/30d, dos=10, rec_qty=18
    b'OD045085UK\tX00124\tB01EXAMPLE2\tMetal Plate SAVILLE\tUK\t12.99\t'
    b'180.00\t18\t10\t5\t10\t\t18\t07/07/2026\tSmall\n'
    # Row 3: GB normal — 200 available, 3 sold/30d, dos=200 (healthy)
    b'OD009033UK\tX00125\tB01EXAMPLE3\tAcrylic Plaque DICK\tUK\t8.99\t'
    b'30.00\t3\t200\t0\t200\t\t0\t\tSmall\n'
    # Row 4: GB zero velocity — 50 available, 0 sold/30d
    b'M0045UKALL\tX00126\tB01EXAMPLE4\tGarden Stake TOM\tUK\t11.99\t'
    b'0\t0\t50\t0\t\t\t0\t\tSmall\n'
    # Row 5: GB reorder_now — 5 available, 12 sold/30d, dos=5, rec_qty=150
    b'OD088002UK\tX00127\tB01EXAMPLE5\tLarge Panel STALIN\tUK\t24.99\t'
    b'120.00\t12\t5\t2\t5\t\t150\t05/07/2026\tLarge\n'
    # Row 6: US out_of_stock — for marketplace filter test
    b'OD001209US\tX00200\tB02EXAMPLE1\tUS Product\tUS\t12.99\t'
    b'100.00\t10\t0\t0\t0\t\t100\t04/07/2026\tSmall\n'
)


# --------------------------------------------------------------------------- #
# Parser — format + filter                                                    #
# --------------------------------------------------------------------------- #


def test_parse_csv_all_rows():
    """Parser extracts every row when no marketplace filter is given."""
    rows = parse_restock_csv(SAMPLE_TSV)
    assert len(rows) == 6


def test_parse_csv_filter_marketplace_gb():
    rows = parse_restock_csv(SAMPLE_TSV, filter_marketplace='GB')
    assert len(rows) == 5
    assert all(r['marketplace'] == 'GB' for r in rows)


def test_parse_csv_filter_marketplace_us():
    rows = parse_restock_csv(SAMPLE_TSV, filter_marketplace='US')
    assert len(rows) == 1
    assert rows[0]['marketplace'] == 'US'
    assert rows[0]['merchant_sku'] == 'OD001209US'


def test_uk_marketplace_is_normalised_to_gb():
    """Report uses 'UK' but our internal code is 'GB'."""
    rows = parse_restock_csv(SAMPLE_TSV, filter_marketplace='GB')
    for row in rows:
        assert row['marketplace'] == 'GB'


def test_type_coercions():
    rows = parse_restock_csv(SAMPLE_TSV, filter_marketplace='GB')
    r1 = rows[0]
    assert isinstance(r1['units_sold_30d'], int)
    assert isinstance(r1['units_available'], int)
    assert isinstance(r1['units_inbound'], int)
    assert isinstance(r1['units_total'], int)
    assert r1['price'] == pytest.approx(9.99)
    assert r1['units_sold_30d'] == 24
    assert r1['units_available'] == 0
    assert r1['units_total'] == 0  # 0 + 0


# --------------------------------------------------------------------------- #
# Alert derivation (done inside the parser)                                   #
# --------------------------------------------------------------------------- #


class TestAlertDerivation:
    def test_out_of_stock_detected(self):
        rows = parse_restock_csv(SAMPLE_TSV, filter_marketplace='GB')
        oos = [r for r in rows if r['alert'] == 'out_of_stock']
        assert len(oos) == 1
        assert oos[0]['merchant_sku'] == 'OD001209UK'

    def test_reorder_now_detected(self):
        rows = parse_restock_csv(SAMPLE_TSV, filter_marketplace='GB')
        reorder = [r for r in rows if r['alert'] == 'reorder_now']
        # Rows 2 and 5 both have available > 0, dos < 30, rec_qty > 0
        assert len(reorder) == 2
        skus = {r['merchant_sku'] for r in reorder}
        assert skus == {'OD045085UK', 'OD088002UK'}

    def test_healthy_items_have_blank_alert(self):
        rows = parse_restock_csv(SAMPLE_TSV, filter_marketplace='GB')
        healthy = [r for r in rows if r['alert'] == '']
        # Row 3 (dos=200) and row 4 (zero velocity) both get blank alert
        assert len(healthy) == 2

    def test_alert_values_are_lowercase_underscored(self):
        rows = parse_restock_csv(SAMPLE_TSV)
        alerts = {r['alert'] for r in rows if r['alert']}
        for a in alerts:
            assert a == a.lower()
            assert ' ' not in a


# --------------------------------------------------------------------------- #
# Date parsing                                                                #
# --------------------------------------------------------------------------- #


def test_date_parsing():
    rows = parse_restock_csv(SAMPLE_TSV, filter_marketplace='GB')
    dated = [r for r in rows if r['amazon_ship_date']]
    assert len(dated) >= 1
    assert isinstance(dated[0]['amazon_ship_date'], date)


def test_missing_date_is_none():
    rows = parse_restock_csv(SAMPLE_TSV, filter_marketplace='GB')
    undated = [r for r in rows if r['amazon_ship_date'] is None]
    # Rows 3 and 4 have no ship date
    assert len(undated) == 2


# --------------------------------------------------------------------------- #
# Parser → Newsvendor integration                                             #
# --------------------------------------------------------------------------- #


def test_out_of_stock_gets_positive_recommendation():
    """Out-of-stock items with sales get a positive restock quantity."""
    rows = parse_restock_csv(SAMPLE_TSV, filter_marketplace='GB')
    out_of_stock = [r for r in rows if r['alert'] == 'out_of_stock']
    assert len(out_of_stock) >= 1

    for row in out_of_stock:
        inp = NewsvendorInput(
            units_sold_30d=row['units_sold_30d'],
            days_of_supply_amazon=row['days_of_supply_amazon'],
            alert=row['alert'],
            price=row.get('price') or 9.99,
            margin=0.35,
            units_available=row['units_available'],
            units_inbound=row['units_inbound'],
        )
        result = calculate_restock_qty(inp)
        assert result.recommended_qty > 0, (
            f"Out-of-stock item {row['merchant_sku']} should get qty > 0"
        )
        # Sanity: the recommendation should equal the 90d demand when
        # everything is out of stock.
        assert result.recommended_qty == row['units_sold_30d'] * 3


def test_zero_velocity_returns_zero_recommendation():
    rows = parse_restock_csv(SAMPLE_TSV, filter_marketplace='GB')
    zero_velocity = [r for r in rows if r['units_sold_30d'] == 0]
    assert len(zero_velocity) == 1  # row 4

    for row in zero_velocity:
        inp = NewsvendorInput(
            units_sold_30d=0,
            days_of_supply_amazon=row['days_of_supply_amazon'],
            alert=row['alert'],
            price=row.get('price') or 9.99,
            units_available=row['units_available'],
            units_inbound=row['units_inbound'],
        )
        result = calculate_restock_qty(inp)
        assert result.recommended_qty == 0


def test_reorder_now_recommendation_accounts_for_on_hand():
    """
    A reorder_now item with 10 available + 5 inbound (on_hand=15) and
    18 units sold in 30d (90d demand = 54) should recommend 54 - 15 = 39.
    """
    rows = parse_restock_csv(SAMPLE_TSV, filter_marketplace='GB')
    r2 = next(r for r in rows if r['merchant_sku'] == 'OD045085UK')

    inp = NewsvendorInput(
        units_sold_30d=r2['units_sold_30d'],
        days_of_supply_amazon=r2['days_of_supply_amazon'],
        alert=r2['alert'],
        price=r2.get('price') or 9.99,
        margin=0.30,
        units_available=r2['units_available'],
        units_inbound=r2['units_inbound'],
    )
    result = calculate_restock_qty(inp)
    assert result.recommended_qty == 39  # 54 - 15
