"""Assemble prebuilt IRS coupon legs into a native QuantLib swap instrument.

This layer consumes leg builders' outputs. It does not generate schedules,
rebuild coupons, construct curves, attach an engine, or value the instrument.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

import QuantLib as ql

from instruments.rates.irs.fixed_leg import QuantLibFixedLeg
from instruments.rates.irs.floating_leg import QuantLibFloatingLeg


QuantLibIRSLeg = Union[QuantLibFixedLeg, QuantLibFloatingLeg]


class UnsupportedIRSInstrumentLegs(ValueError):
    """Raised when the supplied legs do not form a fixed/floating IRS."""


@dataclass(frozen=True)
class QuantLibIRSInstrument:
    """Native QuantLib swap with explicit Pay/Receive leg sidecars."""

    quantlib_instrument: ql.Swap
    pay_leg: QuantLibIRSLeg
    receive_leg: QuantLibIRSLeg


def assemble_quantlib_irs(
    pay_leg: QuantLibIRSLeg,
    receive_leg: QuantLibIRSLeg,
) -> QuantLibIRSInstrument:
    """Assemble the already-built Pay and Receive coupon legs.

    QuantLib 1.41's ``OvernightIndexedSwap`` constructors generate their own
    fixed and overnight legs from schedules and conventions; there is no
    overload accepting existing ``ql.Leg`` objects. ``ql.Swap`` accepts those
    independent native legs directly and preserves their explicit cashflows.
    A floating leg remains composed of QuantLib overnight indexed coupons.
    """
    legs_are_fixed_float = (
        isinstance(pay_leg, QuantLibFixedLeg)
        and isinstance(receive_leg, QuantLibFloatingLeg)
    ) or (
        isinstance(pay_leg, QuantLibFloatingLeg)
        and isinstance(receive_leg, QuantLibFixedLeg)
    )
    if not legs_are_fixed_float:
        raise UnsupportedIRSInstrumentLegs(
            "IRS assembly requires one QuantLib fixed leg and one QuantLib floating leg"
        )

    ql_legs = ql.LegVector()
    ql_legs.append(pay_leg.quantlib_leg)
    ql_legs.append(receive_leg.quantlib_leg)
    payer_flags = ql.BoolVector()
    payer_flags.append(True)
    payer_flags.append(False)

    instrument = ql.Swap(ql_legs, payer_flags)
    return QuantLibIRSInstrument(
        quantlib_instrument=instrument,
        pay_leg=pay_leg,
        receive_leg=receive_leg,
    )
