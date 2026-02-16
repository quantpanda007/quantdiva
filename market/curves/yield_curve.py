"""
Yield curve construction utilities.

Provides builders for common curve types:
- Flat curves (for testing)
- Bootstrapped deposit + swap curves
- OIS curves
- Convenience market environment builder
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

import QuantLib as ql

from core.types.value_objects import PricingDate, Tenor


# ---------------------------------------------------------------------------
# Flat Curve (testing / quick pricing)
# ---------------------------------------------------------------------------

def build_flat_curve(
    pricing_date: PricingDate,
    rate: float,
    day_count: ql.DayCounter = ql.Actual365Fixed(),
) -> ql.YieldTermStructureHandle:
    """Build a flat yield curve — useful for testing."""
    ql_date = pricing_date.to_ql()
    flat_curve = ql.FlatForward(ql_date, rate, day_count)
    return ql.YieldTermStructureHandle(flat_curve)


def build_flat_vol(
    pricing_date: PricingDate,
    vol: float,
    day_count: ql.DayCounter = ql.Actual365Fixed(),
) -> ql.BlackVolTermStructureHandle:
    """Build a flat Black vol surface — useful for testing."""
    ql_date = pricing_date.to_ql()
    flat_vol = ql.BlackConstantVol(ql_date, ql.NullCalendar(), vol, day_count)
    return ql.BlackVolTermStructureHandle(flat_vol)


# ---------------------------------------------------------------------------
# Bootstrapped Curve Builder
# ---------------------------------------------------------------------------

@dataclass
class CurveDefinition:
    """Defines the instruments used to bootstrap a yield curve."""
    currency: str
    pricing_date: PricingDate
    calendar: ql.Calendar = None
    day_count: ql.DayCounter = None
    settlement_days: int = 2

    # Market quotes: list of (tenor_str, rate) tuples
    deposits: List[Tuple[str, float]] = field(default_factory=list)
    futures: List[Tuple[date, float]] = field(default_factory=list)
    swaps: List[Tuple[str, float]] = field(default_factory=list)

    def __post_init__(self):
        if self.calendar is None:
            cal_map = {
                "USD": ql.UnitedStates(ql.UnitedStates.GovernmentBond),
                "EUR": ql.TARGET(),
                "GBP": ql.UnitedKingdom(),
                "JPY": ql.Japan(),
            }
            self.calendar = cal_map.get(self.currency, ql.NullCalendar())

        if self.day_count is None:
            dc_map = {"USD": ql.Actual360(), "EUR": ql.Actual360(), "GBP": ql.Actual365Fixed()}
            self.day_count = dc_map.get(self.currency, ql.Actual360())


class YieldCurveBuilder:
    """Bootstraps a yield curve from deposit, futures, and swap quotes."""

    def build(self, definition: CurveDefinition) -> ql.YieldTermStructureHandle:
        """Bootstrap curve from the definition."""
        ql_date = definition.pricing_date.to_ql()
        ql.Settings.instance().evaluationDate = ql_date

        helpers = []

        # Deposit rate helpers
        for tenor_str, rate in definition.deposits:
            tenor = Tenor(tenor_str).to_ql_period()
            helpers.append(
                ql.DepositRateHelper(
                    ql.QuoteHandle(ql.SimpleQuote(rate)),
                    tenor,
                    definition.settlement_days,
                    definition.calendar,
                    ql.ModifiedFollowing,
                    True,
                    definition.day_count,
                )
            )

        # Swap rate helpers
        ibor_index = self._get_ibor_index(definition)
        for tenor_str, rate in definition.swaps:
            tenor = Tenor(tenor_str).to_ql_period()
            helpers.append(
                ql.SwapRateHelper(
                    ql.QuoteHandle(ql.SimpleQuote(rate)),
                    tenor,
                    definition.calendar,
                    ql.Annual,
                    ql.ModifiedFollowing,
                    definition.day_count,
                    ibor_index,
                )
            )

        if not helpers:
            raise ValueError("No rate helpers provided for curve bootstrapping")

        curve = ql.PiecewiseLogCubicDiscount(ql_date, helpers, definition.day_count)
        curve.enableExtrapolation()
        return ql.YieldTermStructureHandle(curve)

    def _get_ibor_index(self, definition: CurveDefinition) -> ql.IborIndex:
        index_map = {
            "USD": lambda: ql.USDLibor(ql.Period(3, ql.Months)),
            "EUR": lambda: ql.Euribor(ql.Period(6, ql.Months)),
            "GBP": lambda: ql.GBPLibor(ql.Period(6, ql.Months)),
        }
        factory = index_map.get(definition.currency)
        if factory:
            return factory()
        return ql.USDLibor(ql.Period(3, ql.Months))


# ---------------------------------------------------------------------------
# Convenience: Quick Market Environment for Testing
# ---------------------------------------------------------------------------

def build_test_market_env(
    pricing_date: Optional[PricingDate] = None,
    spot: float = 100.0,
    rate: float = 0.05,
    vol: float = 0.20,
    div_yield: float = 0.02,
    underlying: str = "TEST",
) -> "MarketEnvironment":
    """
    Build a simple market environment for testing/notebooks.

    Returns a MarketEnvironment with flat curves and constant vol.
    """
    from core.interfaces.base import MarketEnvironment

    if pricing_date is None:
        pricing_date = PricingDate.today()

    ql_date = pricing_date.to_ql()
    ql.Settings.instance().evaluationDate = ql_date

    discount = build_flat_curve(pricing_date, rate)
    vol_surface = build_flat_vol(pricing_date, vol)
    div_curve = ql.YieldTermStructureHandle(
        ql.FlatForward(ql_date, div_yield, ql.Actual365Fixed())
    )

    return MarketEnvironment(
        pricing_date=pricing_date,
        discount_curves={"USD": discount, underlying: discount},
        forecast_curves={"USD": discount},
        vol_surfaces={underlying: vol_surface},
        spot_prices={underlying: spot},
        dividend_curves={f"{underlying}_div": div_curve},
    )


# ---------------------------------------------------------------------------
# Bootstrapped USD Curve from Market Data
# ---------------------------------------------------------------------------

def build_usd_curve(
    pricing_date: PricingDate,
    deposit_rates: Dict[str, float],
    swap_rates: Dict[str, float],
) -> ql.YieldTermStructureHandle:
    """
    Build a USD yield curve from deposit and swap rates.

    Args:
        pricing_date: Valuation date
        deposit_rates: {"1M": 0.05, "3M": 0.051, ...}
        swap_rates: {"2Y": 0.045, "5Y": 0.042, "10Y": 0.04, ...}
    """
    definition = CurveDefinition(
        currency="USD",
        pricing_date=pricing_date,
        deposits=list(deposit_rates.items()),
        swaps=list(swap_rates.items()),
    )
    builder = YieldCurveBuilder()
    return builder.build(definition)
