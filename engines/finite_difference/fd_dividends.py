"""
Discrete dividend support for Finite Difference engines.

In QuantLib, discrete dividends are modeled as:
- Known cash dividends at specific dates → jump in spot at ex-div
- Proportional dividends → spot scaled by (1 - yield) at ex-div

For American single-stock options, discrete dividends are critical:
the early exercise boundary has kinks at ex-div dates.

QuantLib approach:
- FdBlackScholesVanillaEngine accepts dividend schedule via the
  DividendVanillaOption instrument (not the regular VanillaOption)
- Or use the escrow dividend model (spot adjusted upfront)

Usage:
    from engines.finite_difference.fd_dividends import (
        DividendSchedule, DividendEntry, build_dividend_option,
    )

    divs = DividendSchedule()
    divs.add_cash(date(2025, 6, 15), amount=1.50)
    divs.add_cash(date(2025, 12, 15), amount=1.50)

    option = build_dividend_option(payoff, exercise, divs)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

import QuantLib as ql

logger = logging.getLogger(__name__)


@dataclass
class DividendEntry:
    """Single dividend payment."""
    ex_date: date
    amount: float
    is_proportional: bool = False  # True = proportional yield, False = cash

    def to_ql_date(self) -> ql.Date:
        return ql.Date(self.ex_date.day, self.ex_date.month, self.ex_date.year)


@dataclass
class DividendSchedule:
    """
    Schedule of discrete dividends.

    Supports:
    - Cash dividends: fixed dollar amount on ex-date
    - Proportional dividends: percentage of spot on ex-date
    - Mixed: combination of both
    """
    entries: List[DividendEntry] = field(default_factory=list)

    def add_cash(self, ex_date: date, amount: float) -> None:
        """Add a cash dividend."""
        self.entries.append(DividendEntry(ex_date=ex_date, amount=amount, is_proportional=False))

    def add_proportional(self, ex_date: date, yield_pct: float) -> None:
        """Add a proportional dividend (yield as decimal, e.g., 0.02 for 2%)."""
        self.entries.append(DividendEntry(ex_date=ex_date, amount=yield_pct, is_proportional=True))

    def sorted_entries(self) -> List[DividendEntry]:
        """Return entries sorted by ex-date."""
        return sorted(self.entries, key=lambda d: d.ex_date)

    def filter_future(self, as_of: date) -> DividendSchedule:
        """Return new schedule with only future dividends."""
        future = DividendSchedule()
        future.entries = [d for d in self.entries if d.ex_date > as_of]
        return future

    def total_cash(self) -> float:
        """Sum of all cash dividends."""
        return sum(d.amount for d in self.entries if not d.is_proportional)

    def to_ql_vector(self) -> tuple:
        """
        Convert to QuantLib dividend vectors for DividendVanillaOption.

        Returns:
            (dividend_dates: list[ql.Date], dividend_amounts: list[float])
        """
        sorted_divs = self.sorted_entries()
        dates = []
        amounts = []
        for d in sorted_divs:
            dates.append(d.to_ql_date())
            amounts.append(d.amount)
        return dates, amounts

    def is_empty(self) -> bool:
        return len(self.entries) == 0

    def __len__(self) -> int:
        return len(self.entries)

    def __repr__(self) -> str:
        if not self.entries:
            return "DividendSchedule(empty)"
        total = self.total_cash()
        return f"DividendSchedule({len(self.entries)} divs, total_cash={total:.2f})"


# ---------------------------------------------------------------------------
# Build dividend option
# ---------------------------------------------------------------------------

def build_dividend_option(
    payoff: ql.Payoff,
    exercise: ql.Exercise,
    dividend_schedule: DividendSchedule,
) -> ql.DividendVanillaOption:
    """
    Build a QuantLib DividendVanillaOption with discrete dividend schedule.

    This is required for FD pricing with discrete dividends.
    Regular VanillaOption only supports continuous dividend yield.

    Args:
        payoff: ql.PlainVanillaPayoff (or other)
        exercise: ql.Exercise (European, American, or Bermudan)
        dividend_schedule: discrete dividend entries

    Returns:
        ql.DividendVanillaOption
    """
    sorted_divs = dividend_schedule.sorted_entries()

    div_dates = [d.to_ql_date() for d in sorted_divs]
    div_amounts = [d.amount for d in sorted_divs]

    option = ql.DividendVanillaOption(payoff, exercise, div_dates, div_amounts)
    return option


# ---------------------------------------------------------------------------
# Escrowed dividend model (alternative approach)
# ---------------------------------------------------------------------------

def compute_escrowed_spot(
    spot: float,
    rate: float,
    dividend_schedule: DividendSchedule,
    pricing_date: date,
) -> float:
    """
    Compute escrowed (adjusted) spot price for the dividend model.

    S_adj = S - PV(future dividends)

    This is an alternative to DividendVanillaOption:
    reduce the spot upfront by PV of known dividends,
    then price as if no dividends.

    Less accurate than explicit dividend handling for American options
    (misses early exercise around ex-div dates) but simpler.

    Args:
        spot: current spot price
        rate: risk-free rate (continuous)
        dividend_schedule: future dividends
        pricing_date: valuation date

    Returns:
        Adjusted spot price
    """
    pv_divs = 0.0
    for d in dividend_schedule.sorted_entries():
        if d.ex_date > pricing_date and not d.is_proportional:
            T = (d.ex_date - pricing_date).days / 365.0
            pv_divs += d.amount * np.exp(-rate * T)

    import numpy as np
    adjusted = spot - pv_divs
    if adjusted <= 0:
        logger.warning(
            f"Escrowed spot is non-positive: {adjusted:.4f} "
            f"(spot={spot}, PV(divs)={pv_divs:.4f}). "
            f"Dividends may be too large relative to spot."
        )
        adjusted = max(adjusted, 0.01)

    return adjusted
