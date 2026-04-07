"""
Newsvendor algorithm for FBA restock quantity optimisation.

Theory: The Newsvendor model solves the single-period inventory problem under
demand uncertainty. It answers: how many units should NBNE send to FBA, given
uncertain demand and asymmetric costs of over/under-stocking?

Critical ratio: CR = Cu / (Cu + Co)
  Cu = cost of under-stocking (lost sale + lost margin)
  Co = cost of over-stocking (FBA storage fees, opportunity cost)

Optimal quantity: Q* = F_inv(CR, mu, sigma) where F_inv is the inverse normal CDF.
"""
import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class NewsvendorInput:
    units_sold_30d: int
    days_of_supply_amazon: Optional[float]
    alert: str
    price: float
    margin: Optional[float] = None          # 0–1 fraction, from Manufacture Product
    lead_time_days: int = 7
    review_period_days: int = 30
    cv: float = 0.4                         # coefficient of variation (demand volatility)
    target_service_level: float = 0.90
    fba_storage_cost_per_unit_per_day: float = 0.02
    units_available: int = 0
    units_inbound: int = 0


@dataclass
class NewsvendorResult:
    recommended_qty: int
    base_qty: float
    safety_stock: int
    critical_ratio: float
    mean_demand: float
    std_demand: float
    confidence: float                       # 0–1
    notes: str


def _norm_ppf(p: float) -> float:
    """
    Percent-point function (inverse CDF) for N(0,1).
    Rational approximation — accurate to ~1e-4 for 0.001 < p < 0.999.
    Avoids scipy dependency.
    """
    if p <= 0.0:
        return -8.0
    if p >= 1.0:
        return 8.0
    if p == 0.5:
        return 0.0

    sign = 1.0 if p > 0.5 else -1.0
    q = p if p < 0.5 else 1.0 - p

    t = math.sqrt(-2.0 * math.log(q))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    num = c0 + c1 * t + c2 * t ** 2
    den = 1.0 + d1 * t + d2 * t ** 2 + d3 * t ** 3
    return sign * (t - num / den)


def calculate_restock_qty(inp: NewsvendorInput) -> NewsvendorResult:
    """
    Compute Newsvendor-optimal FBA restock quantity for one NBNE SKU.

    Confidence degrades when:
    - Sales velocity is very low (<1 unit / 30 days) — unreliable data
    - CV is defaulted (no historical sigma available)
    - M-number not resolved (no margin data)
    """
    notes_parts: list[str] = []

    daily_demand = inp.units_sold_30d / 30.0
    horizon = inp.lead_time_days + inp.review_period_days
    mu = daily_demand * horizon
    sigma = mu * inp.cv

    # Gate 1: DoS already covers the entire horizon — no replenishment needed
    if (inp.days_of_supply_amazon is not None
            and inp.days_of_supply_amazon >= horizon
            and inp.alert not in ('out_of_stock', 'reorder_now')):
        return NewsvendorResult(
            recommended_qty=0,
            base_qty=0.0,
            safety_stock=0,
            critical_ratio=0.0,
            mean_demand=mu,
            std_demand=sigma,
            confidence=0.9,
            notes=f'DoS {inp.days_of_supply_amazon:.0f}d >= horizon {horizon}d — sufficient stock.',
        )

    if mu < 0.5:
        return NewsvendorResult(
            recommended_qty=0,
            base_qty=0.0,
            safety_stock=0,
            critical_ratio=0.0,
            mean_demand=mu,
            std_demand=sigma,
            confidence=0.2,
            notes='Very low velocity (<0.5 units/horizon). Defer to Amazon recommendation.',
        )

    if inp.margin is not None:
        cu = inp.price * inp.margin
        co = inp.price * inp.fba_storage_cost_per_unit_per_day * horizon
        notes_parts.append(f'margin data available ({inp.margin:.0%})')
    else:
        cu = 3.0
        co = 1.0
        notes_parts.append('no margin data — using 3:1 Cu/Co ratio')

    critical_ratio = cu / (cu + co)
    z = _norm_ppf(critical_ratio)
    base_qty = mu + z * sigma

    safety_stock = 0
    if inp.alert in ('out_of_stock', 'reorder_now'):
        z_ss = _norm_ppf(inp.target_service_level)
        safety_stock = int(math.ceil(z_ss * sigma * math.sqrt(inp.lead_time_days)))
        notes_parts.append(f'safety stock added ({safety_stock} units) — alert: {inp.alert}')

    recommended = max(0, int(math.ceil(base_qty)) + safety_stock)

    # Gate 2: subtract inventory already at FBA / in transit
    on_hand = inp.units_available + inp.units_inbound
    recommended = max(0, recommended - on_hand)
    if on_hand > 0 and recommended == 0:
        notes_parts.append(f'net 0 after subtracting {on_hand} on-hand units')

    confidence = 1.0
    if inp.units_sold_30d < 5:
        confidence *= 0.5
    if inp.margin is None:
        confidence *= 0.8
    if inp.days_of_supply_amazon is None:
        confidence *= 0.9

    return NewsvendorResult(
        recommended_qty=recommended,
        base_qty=base_qty,
        safety_stock=safety_stock,
        critical_ratio=critical_ratio,
        mean_demand=mu,
        std_demand=sigma,
        confidence=round(confidence, 2),
        notes='; '.join(notes_parts),
    )
