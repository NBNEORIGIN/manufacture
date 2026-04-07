"""
Integration tests for the restock pipeline.

Tests the full chain: parse CSV → Newsvendor → assert recommendations.
Does NOT require a running database or SP-API credentials.
Run: python manage.py test restock.tests.test_integration
"""
import pytest
from restock.parser import parse_restock_csv
from restock.newsvendor import NewsvendorInput, calculate_restock_qty

# Minimal CSV fixture representing a GB restock report
SAMPLE_CSV = b"""Country,Product Name,FNSKU,Merchant SKU,ASIN,Condition,Supplier,Supplier part no.,Currency code,Price,Sales last 30 days,Units Sold Last 30 Days,Total Units,Inbound,Available,FC transfer,FC Processing,Customer Order,Unfulfillable,Working,Shipped,Receiving,Fulfilled by,Total Days of Supply (including units from open shipments),Days of Supply at Amazon Fulfillment Network,Alert,Recommended replenishment qty,Recommended ship date,Unit storage size
United Kingdom,Wooden Push Sign DONALD,X00123,OD001209UK,B01EXAMPLE1,New,,,GBP,9.99,245.00,24,0,0,0,0,0,0,0,0,0,0,Amazon,0,0,out_of_stock,227,04/07/2026,Small
United Kingdom,Metal Plate SAVILLE,X00124,OD045085UK,B01EXAMPLE2,New,,,GBP,12.99,180.00,18,5,10,5,0,0,0,0,0,0,0,Amazon,15,10,reorder_now,18,07/07/2026,Small
United Kingdom,Acrylic Plaque DICK,X00125,OD009033UK,B01EXAMPLE3,New,,,GBP,8.99,30.00,3,20,0,20,0,0,0,0,0,0,0,Amazon,200,200,,0,,Small
United Kingdom,Garden Stake TOM,X00126,M0045UKALL,B01EXAMPLE4,New,,,GBP,11.99,0,0,50,0,50,0,0,0,0,0,0,0,Amazon,0,0,,0,,Small
United Kingdom,Large Panel STALIN,X00127,OD088002UK,B01EXAMPLE5,New,,,GBP,24.99,120.00,12,2,0,2,0,0,0,0,0,0,0,Amazon,5,5,reorder_now,150,05/07/2026,Large
United States,US Product,X00200,OD001209US,B02EXAMPLE1,New,,,USD,12.99,100.00,10,0,0,0,0,0,0,0,0,0,0,Amazon,0,0,out_of_stock,100,04/07/2026,Small
"""


def test_parse_csv_all_rows():
    """Parser extracts all rows from the CSV."""
    rows = parse_restock_csv(SAMPLE_CSV)
    # Both GB and US rows included when no filter
    assert len(rows) == 6


def test_parse_csv_filter_marketplace():
    """Filter to GB only."""
    rows = parse_restock_csv(SAMPLE_CSV, filter_marketplace='GB')
    assert len(rows) == 5
    assert all(r['marketplace'] == 'GB' for r in rows)


def test_parse_csv_filter_us():
    """Filter to US only."""
    rows = parse_restock_csv(SAMPLE_CSV, filter_marketplace='US')
    assert len(rows) == 1
    assert rows[0]['marketplace'] == 'US'


def test_out_of_stock_newsvendor_recommends_qty():
    """Out-of-stock items with sales data get a positive recommendation."""
    rows = parse_restock_csv(SAMPLE_CSV, filter_marketplace='GB')
    out_of_stock = [r for r in rows if r['alert'] == 'out_of_stock']
    assert len(out_of_stock) >= 1

    for row in out_of_stock:
        inp = NewsvendorInput(
            units_sold_30d=row['units_sold_30d'],
            days_of_supply_amazon=row['days_of_supply_amazon'],
            alert=row['alert'],
            price=row.get('price') or 9.99,
            margin=0.35,
        )
        result = calculate_restock_qty(inp)
        assert result.recommended_qty > 0, (
            f"Out-of-stock item {row['merchant_sku']} should get qty > 0"
        )
        assert result.safety_stock > 0


def test_zero_velocity_returns_zero_recommendation():
    """Items with 0 sales in 30 days get 0 recommendation."""
    rows = parse_restock_csv(SAMPLE_CSV, filter_marketplace='GB')
    zero_velocity = [r for r in rows if r['units_sold_30d'] == 0]
    assert len(zero_velocity) >= 1

    for row in zero_velocity:
        inp = NewsvendorInput(
            units_sold_30d=0,
            days_of_supply_amazon=row['days_of_supply_amazon'],
            alert=row['alert'],
            price=row.get('price') or 9.99,
        )
        result = calculate_restock_qty(inp)
        assert result.recommended_qty == 0


def test_date_parsing():
    """Ship dates are parsed correctly."""
    rows = parse_restock_csv(SAMPLE_CSV, filter_marketplace='GB')
    dated = [r for r in rows if r['amazon_ship_date']]
    assert len(dated) >= 1
    from datetime import date
    assert isinstance(dated[0]['amazon_ship_date'], date)


def test_alert_normalisation():
    """Alert values are lower-cased and underscored."""
    rows = parse_restock_csv(SAMPLE_CSV, filter_marketplace='GB')
    alerts = {r['alert'] for r in rows if r['alert']}
    for a in alerts:
        assert a == a.lower()
        assert ' ' not in a


def test_reorder_now_safety_stock():
    """Reorder-now items get safety stock in Newsvendor calculation."""
    rows = parse_restock_csv(SAMPLE_CSV, filter_marketplace='GB')
    reorder = [r for r in rows if r['alert'] == 'reorder_now']
    assert len(reorder) >= 1

    for row in reorder:
        inp = NewsvendorInput(
            units_sold_30d=row['units_sold_30d'],
            days_of_supply_amazon=row['days_of_supply_amazon'],
            alert=row['alert'],
            price=row.get('price') or 9.99,
            margin=0.30,
        )
        result = calculate_restock_qty(inp)
        assert result.safety_stock > 0
