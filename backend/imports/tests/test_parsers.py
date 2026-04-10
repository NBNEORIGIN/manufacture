"""
Tests for backend/imports/parsers.py — pure-function CSV/TSV parsers.

These are unit tests; no DB required. Every parser must:
  * handle both comma and tab delimiters
  * cope with utf-8-sig BOMs (handled upstream in the view but the parser
    should not choke on stray whitespace)
  * tolerate the column-name variants we've actually seen from Seller Central
  * skip rows missing their primary key instead of raising
  * return {'items': [...], 'errors': [...], 'report_type': '<type>'}

No production code changes in this file — only tests.
"""

from __future__ import annotations

from imports.parsers import (
    PARSERS,
    clean_int,
    clean_str,
    detect_delimiter,
    detect_report_type,
    parse_fba_inventory,
    parse_restock_inventory,
    parse_sales_traffic,
    parse_zenstores,
)


# --------------------------------------------------------------------------- #
# Low-level helpers                                                           #
# --------------------------------------------------------------------------- #


class TestCleanInt:
    def test_blank_returns_zero(self):
        assert clean_int('') == 0
        assert clean_int(None) == 0

    def test_plain_integer(self):
        assert clean_int('42') == 42

    def test_strips_commas_in_thousands(self):
        assert clean_int('1,234') == 1234
        assert clean_int('12,345,678') == 12345678

    def test_accepts_decimal_strings(self):
        assert clean_int('42.0') == 42
        assert clean_int('42.9') == 42  # truncates, not rounds

    def test_garbage_returns_zero(self):
        assert clean_int('n/a') == 0
        assert clean_int('—') == 0


class TestCleanStr:
    def test_strips_whitespace(self):
        assert clean_str('  hello  ') == 'hello'

    def test_none_returns_empty(self):
        assert clean_str(None) == ''
        assert clean_str('') == ''


class TestDetectDelimiter:
    def test_tab_detected(self):
        assert detect_delimiter('a\tb\tc\n1\t2\t3') == '\t'

    def test_comma_default(self):
        assert detect_delimiter('a,b,c\n1,2,3') == ','

    def test_empty_input_defaults_to_comma(self):
        assert detect_delimiter('') == ','


# --------------------------------------------------------------------------- #
# FBA Inventory parser                                                        #
# --------------------------------------------------------------------------- #


class TestParseFBAInventory:
    def test_canonical_columns(self):
        csv_content = (
            'sku,asin,fnsku,product-name,afn-fulfillable-quantity\n'
            'NBNE-A-UK,B0001ASIN,X000A,Widget A,12\n'
            'NBNE-B-UK,B0002ASIN,X000B,Widget B,0\n'
        )
        parsed = parse_fba_inventory(csv_content)
        assert parsed['report_type'] == 'fba_inventory'
        assert len(parsed['items']) == 2
        assert parsed['items'][0] == {
            'sku': 'NBNE-A-UK',
            'asin': 'B0001ASIN',
            'fnsku': 'X000A',
            'fba_quantity': 12,
        }
        assert parsed['items'][1]['fba_quantity'] == 0

    def test_tab_delimited(self):
        content = (
            'sku\tasin\tfnsku\tafn-fulfillable-quantity\n'
            'NBNE-A-UK\tB0001ASIN\tX000A\t7\n'
        )
        parsed = parse_fba_inventory(content)
        assert len(parsed['items']) == 1
        assert parsed['items'][0]['fba_quantity'] == 7

    def test_alternate_column_headers(self):
        # seller-sku instead of sku, Fulfillable Quantity instead of afn-*
        csv_content = (
            'seller-sku,ASIN,FNSKU,Fulfillable Quantity\n'
            'NBNE-A-UK,B0001ASIN,X000A,42\n'
        )
        parsed = parse_fba_inventory(csv_content)
        assert parsed['items'][0]['sku'] == 'NBNE-A-UK'
        assert parsed['items'][0]['asin'] == 'B0001ASIN'
        assert parsed['items'][0]['fba_quantity'] == 42

    def test_rows_without_sku_are_skipped(self):
        csv_content = (
            'sku,asin,afn-fulfillable-quantity\n'
            ',B0001ASIN,12\n'
            'NBNE-B-UK,B0002ASIN,5\n'
        )
        parsed = parse_fba_inventory(csv_content)
        assert len(parsed['items']) == 1
        assert parsed['items'][0]['sku'] == 'NBNE-B-UK'

    def test_empty_file(self):
        parsed = parse_fba_inventory('')
        assert parsed['items'] == []
        assert parsed['errors'] == []

    def test_header_only(self):
        parsed = parse_fba_inventory('sku,asin,afn-fulfillable-quantity\n')
        assert parsed['items'] == []

    def test_comma_thousand_separator_in_quantity(self):
        csv_content = (
            'sku,afn-fulfillable-quantity\n'
            '"NBNE-A-UK","1,250"\n'
        )
        parsed = parse_fba_inventory(csv_content)
        assert parsed['items'][0]['fba_quantity'] == 1250


# --------------------------------------------------------------------------- #
# Sales & Traffic parser                                                      #
# --------------------------------------------------------------------------- #


class TestParseSalesTraffic:
    def test_canonical_columns(self):
        csv_content = (
            'SKU,Sessions,Units Ordered\n'
            'NBNE-A-UK,123,8\n'
            'NBNE-B-UK,45,0\n'
        )
        parsed = parse_sales_traffic(csv_content)
        assert parsed['report_type'] == 'sales_traffic'
        assert len(parsed['items']) == 2
        assert parsed['items'][0] == {
            'sku': 'NBNE-A-UK',
            'units_ordered': 8,
            'sessions': 123,
        }

    def test_lowercase_units_ordered(self):
        csv_content = (
            'sku,sessions,units-ordered\n'
            'NBNE-A-UK,10,3\n'
        )
        parsed = parse_sales_traffic(csv_content)
        assert parsed['items'][0]['units_ordered'] == 3
        assert parsed['items'][0]['sessions'] == 10

    def test_skus_without_sku_are_skipped(self):
        csv_content = (
            'SKU,Units Ordered\n'
            ',5\n'
            'NBNE-B-UK,2\n'
        )
        parsed = parse_sales_traffic(csv_content)
        assert len(parsed['items']) == 1
        assert parsed['items'][0]['sku'] == 'NBNE-B-UK'


# --------------------------------------------------------------------------- #
# Restock Inventory parser                                                    #
# --------------------------------------------------------------------------- #


class TestParseRestockInventory:
    def test_canonical_columns(self):
        csv_content = (
            'SKU,ASIN,Available,Recommended restock qty\n'
            'NBNE-A-UK,B0001ASIN,15,30\n'
            'NBNE-B-UK,B0002ASIN,0,50\n'
        )
        parsed = parse_restock_inventory(csv_content)
        assert parsed['report_type'] == 'restock'
        assert len(parsed['items']) == 2
        assert parsed['items'][0] == {
            'sku': 'NBNE-A-UK',
            'asin': 'B0001ASIN',
            'available': 15,
            'restock_quantity': 30,
        }

    def test_alternate_column_names(self):
        # Merchant SKU + Recommended Order Quantity variant
        csv_content = (
            'Merchant SKU,ASIN,available,Recommended Order Quantity\n'
            'NBNE-A-UK,B0001ASIN,7,12\n'
        )
        parsed = parse_restock_inventory(csv_content)
        assert parsed['items'][0]['sku'] == 'NBNE-A-UK'
        assert parsed['items'][0]['restock_quantity'] == 12


# --------------------------------------------------------------------------- #
# Zenstores parser                                                            #
# --------------------------------------------------------------------------- #


class TestParseZenstores:
    def test_canonical_columns(self):
        csv_content = (
            'Order ID,Status,Date,Channel,First name,Last name,'
            'Lineitem name,Lineitem SKU,Lineitem quantity,Flags\n'
            '123-45-67,Pending,2026-04-10,AmazonOD,Jane,Smith,'
            'Gorgeous Sign,NBNE-A-UK,2,Urgent\n'
        )
        parsed = parse_zenstores(csv_content)
        assert parsed['report_type'] == 'zenstores'
        assert len(parsed['items']) == 1
        item = parsed['items'][0]
        assert item['order_id'] == '123-45-67'
        assert item['sku'] == 'NBNE-A-UK'
        assert item['quantity'] == 2
        assert item['flags'] == 'Urgent'
        assert item['channel'] == 'AmazonOD'
        assert item['customer_name'] == 'Jane Smith'
        assert item['description'] == 'Gorgeous Sign'

    def test_missing_order_id_skipped(self):
        csv_content = (
            'Order ID,Lineitem SKU,Lineitem quantity\n'
            ',NBNE-A-UK,1\n'
            '123-45-67,NBNE-B-UK,3\n'
        )
        parsed = parse_zenstores(csv_content)
        assert len(parsed['items']) == 1
        assert parsed['items'][0]['order_id'] == '123-45-67'

    def test_missing_sku_skipped(self):
        csv_content = (
            'Order ID,Lineitem SKU,Lineitem quantity\n'
            '123-45-67,,1\n'
        )
        parsed = parse_zenstores(csv_content)
        assert parsed['items'] == []

    def test_quantity_defaults_to_one_when_blank(self):
        csv_content = (
            'Order ID,Lineitem SKU,Lineitem quantity\n'
            '123-45-67,NBNE-A-UK,\n'
        )
        parsed = parse_zenstores(csv_content)
        assert parsed['items'][0]['quantity'] == 1

    def test_customer_name_strips_when_both_blank(self):
        csv_content = (
            'Order ID,Lineitem SKU,Lineitem quantity,First name,Last name\n'
            '123-45-67,NBNE-A-UK,1,,\n'
        )
        parsed = parse_zenstores(csv_content)
        assert parsed['items'][0]['customer_name'] == ''


# --------------------------------------------------------------------------- #
# Report type detection                                                       #
# --------------------------------------------------------------------------- #


class TestDetectReportType:
    def test_fba_inventory_by_fulfillable_column(self):
        assert detect_report_type('sku,afn-fulfillable-quantity\n1,2') == 'fba_inventory'
        assert detect_report_type('sku,Fulfillable Quantity\n1,2') == 'fba_inventory'

    def test_sales_traffic_by_units_ordered(self):
        assert detect_report_type('SKU,Units Ordered\n1,2') == 'sales_traffic'
        assert detect_report_type('sku,units-ordered\n1,2') == 'sales_traffic'

    def test_restock_by_recommended_restock(self):
        assert detect_report_type('SKU,Recommended restock qty\n1,2') == 'restock'

    def test_zenstores_requires_both_columns(self):
        assert (
            detect_report_type('Order ID,Lineitem SKU\n1,2') == 'zenstores'
        )
        # Only one of the two columns — not enough to classify
        assert detect_report_type('Order ID,Name\n1,2') is None
        assert detect_report_type('Lineitem SKU,Name\n1,2') is None

    def test_unknown_format_returns_none(self):
        assert detect_report_type('foo,bar,baz\n1,2,3') is None
        assert detect_report_type('') is None


# --------------------------------------------------------------------------- #
# Parser registry                                                             #
# --------------------------------------------------------------------------- #


class TestParserRegistry:
    def test_all_four_report_types_registered(self):
        assert set(PARSERS.keys()) == {
            'fba_inventory',
            'sales_traffic',
            'restock',
            'zenstores',
        }

    def test_every_parser_returns_standard_shape(self):
        for name, fn in PARSERS.items():
            result = fn('')
            assert 'items' in result
            assert 'errors' in result
            assert 'report_type' in result
            assert result['report_type'] == name
