"""QuantLib discounting-engine attachment for the fresh IRS instrument."""

from __future__ import annotations

from dataclasses import dataclass

import QuantLib as ql

from instruments.rates.irs.instrument import QuantLibIRSInstrument
from market.curves.irs_market_data import QuantLibDiscountCurve


@dataclass(frozen=True)
class AttachedDiscountingEngine:
    """Discounting engine attached to a QuantLib IRS swap."""

    instrument: QuantLibIRSInstrument
    quantlib_engine: ql.DiscountingSwapEngine
    discount_curve: ql.YieldTermStructureHandle


def attach_discounting_engine(
    instrument: QuantLibIRSInstrument,
    discount_curve: QuantLibDiscountCurve,
) -> AttachedDiscountingEngine:
    """Attach QuantLib cashflow discounting with the dedicated discount curve."""
    engine = ql.DiscountingSwapEngine(discount_curve.handle)
    instrument.quantlib_instrument.setPricingEngine(engine)
    return AttachedDiscountingEngine(
        instrument=instrument,
        quantlib_engine=engine,
        discount_curve=discount_curve.handle,
    )
