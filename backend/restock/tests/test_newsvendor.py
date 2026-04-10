"""
Unit tests for the simplified restock quantity calculator.

The module is named newsvendor.py for historical reasons — the original
implementation was a proper newsvendor model with critical ratio, safety
stock, and margin-weighted confidence. The current production implementation
has been deliberately simplified to:

    recommended_qty = max(0, (units_sold_30d * 3) - (units_available + units_inbound))

with a binary confidence (1.0 if velocity >= 5/30d, else 0.5) and
safety_stock / critical_ratio stubbed to 0 / 0.0.

These tests assert the CURRENT production behaviour. They replace an earlier
test suite that targeted the richer model and had rotted into drift.

Run: pytest restock/tests/test_newsvendor.py
"""

import pytest

from restock.newsvendor import (
    NewsvendorInput,
    NewsvendorResult,
    calculate_restock_qty,
)


# --------------------------------------------------------------------------- #
# Core formula: max(0, 90d demand - on_hand)                                  #
# --------------------------------------------------------------------------- #


def test_zero_velocity_returns_zero():
    """No sales in last 30d → no restock."""
    inp = NewsvendorInput(
        units_sold_30d=0,
        days_of_supply_amazon=30.0,
        alert='',
        price=9.99,
        margin=0.40,
    )
    result = calculate_restock_qty(inp)
    assert result.recommended_qty == 0
    assert result.base_qty == 0.0
    assert 'zero velocity' in result.notes


def test_empty_stock_recommends_full_90d_demand():
    """Out of stock entirely → recommend 3x the monthly velocity."""
    inp = NewsvendorInput(
        units_sold_30d=50,
        days_of_supply_amazon=0.0,
        alert='out_of_stock',
        price=12.99,
        margin=0.35,
        units_available=0,
        units_inbound=0,
    )
    result = calculate_restock_qty(inp)
    assert result.recommended_qty == 150  # 50 * 3 - 0
    assert result.base_qty == 150.0


def test_partial_on_hand_is_subtracted():
    """On-hand available + inbound reduces the recommendation."""
    inp = NewsvendorInput(
        units_sold_30d=30,
        days_of_supply_amazon=10.0,
        alert='reorder_now',
        price=9.99,
        margin=None,
        units_available=20,
        units_inbound=10,
    )
    result = calculate_restock_qty(inp)
    # 30 * 3 = 90 demand, on_hand = 30, recommended = 60
    assert result.recommended_qty == 60
    assert result.base_qty == 90.0


def test_sufficient_stock_recommends_zero():
    """If on-hand already covers 90-day demand, recommend nothing."""
    inp = NewsvendorInput(
        units_sold_30d=10,
        days_of_supply_amazon=90.0,
        alert='',
        price=9.99,
        margin=0.40,
        units_available=50,
        units_inbound=0,
    )
    result = calculate_restock_qty(inp)
    # 10 * 3 = 30 demand, 50 on-hand → 0 recommended
    assert result.recommended_qty == 0
    assert 'sufficient stock' in result.notes


def test_inbound_counts_toward_on_hand():
    """Inbound shipments count as on-hand for the deficit calculation."""
    inp = NewsvendorInput(
        units_sold_30d=40,
        days_of_supply_amazon=5.0,
        alert='out_of_stock',
        price=9.99,
        margin=None,
        units_available=0,
        units_inbound=120,  # already enough to cover 40*3 = 120
    )
    result = calculate_restock_qty(inp)
    assert result.recommended_qty == 0


# --------------------------------------------------------------------------- #
# Confidence — binary threshold at 5 units/30d                                #
# --------------------------------------------------------------------------- #


def test_high_velocity_gives_full_confidence():
    inp = NewsvendorInput(
        units_sold_30d=100,
        days_of_supply_amazon=14.0,
        alert='',
        price=14.99,
        margin=0.45,
    )
    result = calculate_restock_qty(inp)
    assert result.confidence == pytest.approx(1.0)


def test_velocity_at_threshold_gives_full_confidence():
    """Exactly 5 units in 30d → confidence 1.0 (threshold is >= 5)."""
    inp = NewsvendorInput(
        units_sold_30d=5,
        days_of_supply_amazon=None,
        alert='',
        price=9.99,
        margin=None,
    )
    result = calculate_restock_qty(inp)
    assert result.confidence == pytest.approx(1.0)


def test_low_velocity_gives_half_confidence():
    inp = NewsvendorInput(
        units_sold_30d=3,
        days_of_supply_amazon=None,
        alert='',
        price=9.99,
        margin=None,
    )
    result = calculate_restock_qty(inp)
    assert result.confidence == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# Stubbed fields — safety_stock and critical_ratio are always 0 in the       #
# current implementation. Documented here so a future reinstate is caught.   #
# --------------------------------------------------------------------------- #


def test_safety_stock_is_always_zero():
    """
    The current simplified model does not compute safety stock.
    If this test starts failing it means someone reinstated the richer
    newsvendor model — update this test and the related tests accordingly.
    """
    inp = NewsvendorInput(
        units_sold_30d=50,
        days_of_supply_amazon=0.0,
        alert='out_of_stock',
        price=12.99,
        margin=0.35,
    )
    result = calculate_restock_qty(inp)
    assert result.safety_stock == 0


def test_critical_ratio_is_always_zero():
    """See test_safety_stock_is_always_zero — same caveat."""
    inp = NewsvendorInput(
        units_sold_30d=50,
        days_of_supply_amazon=0.0,
        alert='out_of_stock',
        price=12.99,
        margin=0.35,
    )
    result = calculate_restock_qty(inp)
    assert result.critical_ratio == 0.0


# --------------------------------------------------------------------------- #
# Notes field — what the UI surfaces                                          #
# --------------------------------------------------------------------------- #


class TestNotesField:
    def test_normal_notes_show_formula(self):
        inp = NewsvendorInput(
            units_sold_30d=20,
            days_of_supply_amazon=10.0,
            alert='',
            price=9.99,
            margin=None,
            units_available=5,
            units_inbound=0,
        )
        result = calculate_restock_qty(inp)
        assert 'demand 60' in result.notes  # 20 * 3
        assert 'on-hand 5' in result.notes
        assert '55' in result.notes  # 60 - 5

    def test_sufficient_notes_override_normal(self):
        inp = NewsvendorInput(
            units_sold_30d=5,
            days_of_supply_amazon=60.0,
            alert='',
            price=9.99,
            margin=None,
            units_available=30,
            units_inbound=0,
        )
        result = calculate_restock_qty(inp)
        assert 'sufficient stock' in result.notes
        assert '30' in result.notes  # on-hand

    def test_zero_velocity_notes(self):
        inp = NewsvendorInput(
            units_sold_30d=0,
            days_of_supply_amazon=None,
            alert='',
            price=9.99,
            margin=None,
        )
        result = calculate_restock_qty(inp)
        assert 'zero velocity' in result.notes


# --------------------------------------------------------------------------- #
# Mean demand — sanity check                                                  #
# --------------------------------------------------------------------------- #


def test_mean_demand_is_per_day():
    """mean_demand should be (90d demand / 90) = daily units, roughly."""
    inp = NewsvendorInput(
        units_sold_30d=90,
        days_of_supply_amazon=20.0,
        alert='',
        price=9.99,
        margin=None,
    )
    result = calculate_restock_qty(inp)
    # demand_90d = 270; mean_demand = 270/90 = 3.0
    assert result.mean_demand == pytest.approx(3.0)


def test_mean_demand_zero_for_zero_velocity():
    inp = NewsvendorInput(
        units_sold_30d=0,
        days_of_supply_amazon=None,
        alert='',
        price=9.99,
        margin=None,
    )
    result = calculate_restock_qty(inp)
    assert result.mean_demand == 0.0
