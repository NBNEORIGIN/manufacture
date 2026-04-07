"""
Unit tests for the Newsvendor restock algorithm.
Run: python manage.py test restock.tests.test_newsvendor
"""
import math
import pytest

from restock.newsvendor import NewsvendorInput, NewsvendorResult, calculate_restock_qty


def test_zero_velocity_returns_zero():
    """Items with near-zero sales get 0 recommendation."""
    inp = NewsvendorInput(
        units_sold_30d=0,
        days_of_supply_amazon=30.0,
        alert='',
        price=9.99,
        margin=0.40,
    )
    result = calculate_restock_qty(inp)
    assert result.recommended_qty == 0
    assert result.confidence == pytest.approx(0.2)
    assert 'Very low velocity' in result.notes


def test_out_of_stock_with_margin_applies_safety_stock():
    """Out-of-stock item with known margin should get safety stock applied."""
    inp = NewsvendorInput(
        units_sold_30d=50,
        days_of_supply_amazon=0.0,
        alert='out_of_stock',
        price=12.99,
        margin=0.35,
        lead_time_days=7,
        review_period_days=30,
        cv=0.4,
        target_service_level=0.90,
    )
    result = calculate_restock_qty(inp)
    assert result.recommended_qty > 0
    assert result.safety_stock > 0
    assert 'safety stock added' in result.notes
    # Cu = price * margin, Co = price * storage * horizon
    # With low margin (0.35) and 37-day horizon, Co can exceed Cu — CR < 0.5 is valid
    assert 0 < result.critical_ratio < 1


def test_no_margin_uses_fallback_ratio():
    """Without margin data, 3:1 Cu/Co ratio gives CR = 0.75."""
    inp = NewsvendorInput(
        units_sold_30d=30,
        days_of_supply_amazon=10.0,
        alert='reorder_now',
        price=9.99,
        margin=None,
    )
    result = calculate_restock_qty(inp)
    assert result.critical_ratio == pytest.approx(0.75)
    assert 'no margin data' in result.notes
    # 30 units sold → not low velocity; no margin → 0.8; days_of_supply present → 1.0
    assert result.confidence == pytest.approx(0.8)


def test_normal_case_with_margin():
    """Healthy item with margin and decent velocity — sensible recommendation."""
    inp = NewsvendorInput(
        units_sold_30d=100,
        days_of_supply_amazon=14.0,
        alert='',
        price=14.99,
        margin=0.45,
        lead_time_days=7,
        review_period_days=30,
        cv=0.4,
    )
    result = calculate_restock_qty(inp)
    # Mean demand = (100/30) * 37 ≈ 123 units
    # With CR > 0.5 and z > 0, base_qty > mu
    assert result.recommended_qty > 100
    assert result.safety_stock == 0  # no out_of_stock alert
    assert result.confidence == pytest.approx(1.0)
    assert result.mean_demand == pytest.approx((100 / 30) * 37, rel=0.01)


def test_reorder_now_without_margin():
    """Reorder-now alert without margin — gets safety stock via 3:1 fallback."""
    inp = NewsvendorInput(
        units_sold_30d=20,
        days_of_supply_amazon=5.0,
        alert='reorder_now',
        price=7.99,
        margin=None,
    )
    result = calculate_restock_qty(inp)
    assert result.recommended_qty > 0
    assert result.safety_stock > 0


def test_low_velocity_degrades_confidence():
    """Low-selling items have reduced confidence."""
    inp = NewsvendorInput(
        units_sold_30d=3,
        days_of_supply_amazon=None,
        alert='',
        price=9.99,
        margin=None,
    )
    result = calculate_restock_qty(inp)
    # 0.5 (low sales) * 0.8 (no margin) * 0.9 (no days-of-supply) = 0.36
    assert result.confidence == pytest.approx(0.36)


def test_norm_ppf_boundary_values():
    """Internal _norm_ppf implementation is sane at key percentiles."""
    from restock.newsvendor import _norm_ppf
    assert _norm_ppf(0.5) == pytest.approx(0.0, abs=1e-4)
    assert _norm_ppf(0.90) == pytest.approx(1.2816, rel=0.01)
    assert _norm_ppf(0.75) == pytest.approx(0.6745, rel=0.01)
    assert _norm_ppf(0.95) == pytest.approx(1.6449, rel=0.01)
