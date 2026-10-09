"""Build a MarketEnvironment for the fresh IRS from zero curves.

Single-curve setup: one ``QuantLibZeroCurve`` serves as both the discount and
the forecast curve of its currency, which is the confirmed TC1 configuration.
The helper checks that the curve's reference date equals the pricing date and
does not add curves for any other currency.

Typed curve input through ``MarketDataRequest`` is not wired yet (open item OI-5).
"""

from __future__ import annotations

from datetime import date

from core.interfaces.base import MarketEnvironment
from core.types.value_objects import PricingDate
from market.curves.irs_zero_curve import QuantLibZeroCurve


def build_single_curve_irs_environment(
    pricing_date: date,
    curve: QuantLibZeroCurve,
) -> MarketEnvironment:
    """Discount and forecast on the same curve, keyed by the curve's currency."""
    if not isinstance(curve, QuantLibZeroCurve):
        raise TypeError("curve must be a QuantLibZeroCurve from build_zero_curve()")
    if curve.market_data.reference_date != pricing_date:
        raise ValueError(
            f"curve reference date {curve.market_data.reference_date.isoformat()} does not "
            f"match pricing date {pricing_date.isoformat()}"
        )
    currency = curve.market_data.currency
    return MarketEnvironment(
        pricing_date=PricingDate(pricing_date),
        discount_curves={currency: curve.handle},
        forecast_curves={currency: curve.handle},
    )
