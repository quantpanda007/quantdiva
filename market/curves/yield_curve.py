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


# PROVISIONAL SOFR market-data interpretation (not SME-confirmed).
# Keep the assumptions centralized so the scale and interval accrual can be
# updated without changing the curve-building API if the SME clarifies them.
_PROVISIONAL_SIMPLE_FORWARD_RATE_DIVISOR = 100.0
_PROVISIONAL_SIMPLE_FORWARD_DAY_COUNT = ql.Actual360()


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
    # Direct dated discount-factor observations: [(pillar date, DF), ...].
    discount_factors: List[Tuple[date, float]] = field(default_factory=list)
    # Dated simple forwards: [(interval end date, displayed market rate), ...].
    # The provisional interval interpretation is centralized in the builder.
    forward_rates: List[Tuple[date, float]] = field(default_factory=list)

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
        """Build a direct DF curve, simple-forward projection curve, or bootstrap."""
        ql_date = definition.pricing_date.to_ql()
        ql.Settings.instance().evaluationDate = ql_date

        if definition.forward_rates:
            if (
                definition.discount_factors
                or definition.deposits
                or definition.futures
                or definition.swaps
            ):
                raise ValueError(
                    "Simple forward observations cannot be mixed with other curve inputs"
                )
            dates, factors = self._discount_factors_from_simple_forwards(
                ql_date, definition.forward_rates
            )
            curve = ql.DiscountCurve(dates, factors, definition.day_count)
            curve.enableExtrapolation()
            return ql.YieldTermStructureHandle(curve)

        if definition.discount_factors:
            if definition.deposits or definition.futures or definition.swaps:
                raise ValueError(
                    "Direct discount factors cannot be mixed with curve rate quotes"
                )

            # DiscountCurve takes discount factors directly. Include the
            # reference-date anchor required by QuantLib; no rate conversion
            # or rate-helper bootstrap is involved.
            dated_factors = []
            for pillar_date, discount_factor in definition.discount_factors:
                if isinstance(pillar_date, date):
                    ql_pillar = ql.Date(
                        pillar_date.day, pillar_date.month, pillar_date.year
                    )
                else:
                    ql_pillar = pillar_date
                dated_factors.append((ql_pillar, float(discount_factor)))

            reference_factors = [
                factor for pillar, factor in dated_factors if pillar == ql_date
            ]
            if reference_factors and any(factor != 1.0 for factor in reference_factors):
                raise ValueError("Reference-date discount factor must equal 1.0")
            if not reference_factors:
                dated_factors.append((ql_date, 1.0))

            dated_factors.sort(key=lambda item: item[0].serialNumber())
            dates = [pillar for pillar, _ in dated_factors]
            factors = [factor for _, factor in dated_factors]
            if len(set(dates)) != len(dates):
                raise ValueError("Discount-factor pillar dates must be unique")
            if any(factor <= 0.0 for factor in factors):
                raise ValueError("Discount factors must be positive")

            curve = ql.DiscountCurve(dates, factors, definition.day_count)
            curve.enableExtrapolation()
            return ql.YieldTermStructureHandle(curve)

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

    @staticmethod
    def _discount_factors_from_simple_forwards(
        reference_date: ql.Date,
        forward_rates: List[Tuple[date, float]],
    ) -> Tuple[List[ql.Date], List[float]]:
        """Convert provisional dated simple forwards to cumulative discount factors.

        Under the current provisional convention, each quote date ends its
        accrual interval: the first interval begins on the reference date and
        later intervals begin on the previous quote date. Displayed rates are
        percentages and Actual/360 supplies the simple accrual fraction.
        """
        dates = [reference_date]
        factors = [1.0]
        previous_date = reference_date
        previous_factor = 1.0

        for pillar_date, displayed_rate in forward_rates:
            if isinstance(pillar_date, date):
                ql_pillar = ql.Date(
                    pillar_date.day, pillar_date.month, pillar_date.year
                )
            else:
                ql_pillar = pillar_date
            if ql_pillar <= previous_date:
                raise ValueError(
                    "Simple-forward quote dates must be strictly increasing "
                    "after the reference date"
                )

            rate = float(displayed_rate) / _PROVISIONAL_SIMPLE_FORWARD_RATE_DIVISOR
            tau = _PROVISIONAL_SIMPLE_FORWARD_DAY_COUNT.yearFraction(
                previous_date, ql_pillar
            )
            denominator = 1.0 + rate * tau
            if denominator <= 0.0:
                raise ValueError(
                    "Simple-forward quote implies a non-positive discount factor"
                )

            previous_factor /= denominator
            dates.append(ql_pillar)
            factors.append(previous_factor)
            previous_date = ql_pillar

        return dates, factors

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
