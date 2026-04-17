"""
FBA Restock quantity calculation.

Formula: max(0, 90_day_demand - fba_total)
  90_day_demand  = units_sold_30d * 3
  fba_total      = units_total (Amazon's "Inventory Supply at FBA":
                   available + inbound + reserved + researching)

If we already hold stock equal to or greater than 90-day demand, recommend 0.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class NewsvendorInput:
    units_sold_30d: int
    days_of_supply_amazon: Optional[float]
    alert: str
    price: float
    margin: Optional[float] = None
    lead_time_days: int = 7
    review_period_days: int = 30
    cv: float = 0.4
    target_service_level: float = 0.90
    fba_storage_cost_per_unit_per_day: float = 0.02
    units_available: int = 0
    units_inbound: int = 0
    units_reserved: int = 0
    units_total: int = 0  # Amazon's FBA total (available + inbound + reserved + researching)


@dataclass
class NewsvendorResult:
    recommended_qty: int
    base_qty: float
    safety_stock: int
    critical_ratio: float
    mean_demand: float
    std_demand: float
    confidence: float
    notes: str


def calculate_restock_qty(inp: NewsvendorInput) -> NewsvendorResult:
    """
    Recommended send quantity = max(0, 90d demand - fba_total).

    90d demand is derived from 30-day units sold x 3.
    fba_total is Amazon's "Inventory Supply at FBA" which includes
    available + inbound + reserved + researching units. This matches
    the total shown on Amazon's FBA Restock Report, not the lower
    "on-hand" from Manage My Inventory.
    """
    demand_90d = inp.units_sold_30d * 3

    # Use units_total (Amazon's FBA total) if available, otherwise
    # fall back to available + inbound + reserved.
    fba_total = inp.units_total
    if fba_total == 0 and (inp.units_available or inp.units_inbound):
        fba_total = inp.units_available + inp.units_inbound + inp.units_reserved

    recommended = max(0, demand_90d - fba_total)

    notes_parts = [f'90d demand {demand_90d} \u2212 FBA total {fba_total} = {recommended}']
    if fba_total >= demand_90d and demand_90d > 0:
        notes_parts = [f'sufficient stock: {fba_total} at FBA covers {demand_90d} 90d demand']
    elif demand_90d == 0:
        notes_parts = ['zero velocity \u2014 no demand in last 30d']

    confidence = 1.0 if inp.units_sold_30d >= 5 else 0.5

    return NewsvendorResult(
        recommended_qty=recommended,
        base_qty=float(demand_90d),
        safety_stock=0,
        critical_ratio=0.0,
        mean_demand=float(demand_90d / 90) if demand_90d else 0.0,
        std_demand=0.0,
        confidence=confidence,
        notes='; '.join(notes_parts),
    )
