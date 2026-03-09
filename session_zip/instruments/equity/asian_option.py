"""
Asian Option instrument — Arithmetic and Geometric averaging.

Asian options pay based on the average price of the underlying
over a period, rather than the terminal price.

Average types:
    Arithmetic: avg = (1/N) * Σ S(t_i)       — most traded, no closed form
    Geometric:  avg = (Π S(t_i))^(1/N)        — closed-form exists (Kemna-Vorst)

Strike types:
    Fixed strike:    payoff = max(avg - K, 0)   for call
    Floating strike: payoff = max(S(T) - avg, 0) for call

Averaging:
    Discrete:   average over specific fixing dates
    Continuous:  average over entire period (theoretical, approximated)

Usage:
    from instruments.equity.asian_option import AsianOption
    from core.enums.definitions import OptionType

    # Arithmetic fixed-strike Asian call with monthly fixings
    opt = AsianOption(
        _trade_id="ASIAN-001",
        underlying="AAPL",
        strike=150.0,
        expiry=date(2026, 6, 15),
        option_type=OptionType.CALL,
        average_type=AverageType.ARITHMETIC,
        strike_type=StrikeType.FIXED,
        averaging_start=date(2025, 6, 15),
        fixing_frequency="monthly",
    )

    # Geometric floating-strike Asian put with explicit fixing dates
    opt = AsianOption(
        _trade_id="ASIAN-002",
        underlying="SPX",
        strike=0.0,  # ignored for floating strike
        expiry=date(2026, 6, 15),
        option_type=OptionType.PUT,
        average_type=AverageType.GEOMETRIC,
        strike_type=StrikeType.FLOATING,
        fixing_dates=[date(2026, 1, 15), date(2026, 2, 15), ...],
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Dict, List, Optional

import QuantLib as ql

from core.enums.definitions import (
    AssetClass,
    InstrumentType,
    OptionType,
)
from core.exceptions.errors import InstrumentBuildError
from core.interfaces.base import BaseInstrument, MarketEnvironment
from core.types.value_objects import TradeId
from instruments.common.payoffs import PayoffBuilder
from instruments.common.exercise import ExerciseBuilder
from registry import instrument_registry


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AverageType(str, Enum):
    """Type of averaging."""
    ARITHMETIC = "arithmetic"
    GEOMETRIC = "geometric"


class StrikeType(str, Enum):
    """Fixed or floating strike."""
    FIXED = "fixed"
    FLOATING = "floating"


# ---------------------------------------------------------------------------
# QuantLib mappings
# ---------------------------------------------------------------------------

_AVERAGE_TYPE_MAP = {
    AverageType.ARITHMETIC: ql.Average.Arithmetic,
    AverageType.GEOMETRIC: ql.Average.Geometric,
}


# ---------------------------------------------------------------------------
# Fixing date generation
# ---------------------------------------------------------------------------

def generate_fixing_dates(
    start: date,
    end: date,
    frequency: str = "monthly",
) -> List[date]:
    """
    Generate fixing dates between start and end (inclusive).

    Frequencies: daily, weekly, monthly, quarterly.
    """
    from dateutil.rrule import rrule, DAILY, WEEKLY, MONTHLY
    from dateutil.rrule import MO

    freq_map = {
        "daily": DAILY,
        "weekly": WEEKLY,
        "monthly": MONTHLY,
    }

    if frequency == "quarterly":
        # Generate monthly then take every 3rd
        all_dates = list(rrule(MONTHLY, dtstart=start, until=end))
        dates = all_dates[::3]
    elif frequency in freq_map:
        dates = list(rrule(freq_map[frequency], dtstart=start, until=end))
    else:
        raise ValueError(
            f"Unknown fixing frequency: '{frequency}'. "
            f"Use: daily, weekly, monthly, quarterly."
        )

    # Convert to date objects and ensure end date is included
    result = [d.date() if hasattr(d, 'date') else d for d in dates]
    if result and result[-1] < end:
        result.append(end)
    return result


# ---------------------------------------------------------------------------
# Asian Option
# ---------------------------------------------------------------------------

@instrument_registry.register_decorator("asian_option", overwrite=True)
@dataclass
class AsianOption(BaseInstrument):
    """
    Asian option — average price or average strike.

    Attributes:
        _trade_id:          Unique trade identifier
        underlying:         Underlying asset code
        strike:             Strike price (ignored for floating strike)
        expiry:             Expiry date
        option_type:        CALL or PUT
        average_type:       ARITHMETIC or GEOMETRIC
        strike_type:        FIXED or FLOATING
        averaging_start:    Start date for averaging period
        fixing_dates:       Explicit list of fixing dates (overrides frequency)
        fixing_frequency:   "daily", "weekly", "monthly", "quarterly"
        past_fixings:       Already observed fixings (for in-progress Asians)
        running_accumulator: Running sum (arithmetic) or product (geometric)
                             of past fixings
        notional:           Contract multiplier
        _currency:          Settlement currency
    """

    _trade_id: str = ""
    underlying: str = ""
    strike: float = 0.0
    expiry: date = None
    option_type: OptionType = OptionType.CALL
    average_type: AverageType = AverageType.ARITHMETIC
    strike_type: StrikeType = StrikeType.FIXED
    averaging_start: Optional[date] = None
    fixing_dates: Optional[List[date]] = None
    fixing_frequency: str = "monthly"
    past_fixings: Optional[List[float]] = None
    running_accumulator: float = 0.0
    notional: float = 1.0
    _currency: str = "USD"

    # -------------------------------------------------------------------
    # BaseInstrument interface
    # -------------------------------------------------------------------

    def trade_id(self) -> TradeId:
        return TradeId(self._trade_id)

    def asset_class(self) -> AssetClass:
        return AssetClass.EQUITY

    def instrument_type(self) -> InstrumentType:
        return InstrumentType.ASIAN_OPTION

    def currency(self) -> str:
        return self._currency

    def maturity(self) -> date:
        return self.expiry

    # -------------------------------------------------------------------
    # Build QuantLib instrument
    # -------------------------------------------------------------------

    def build(self, market_env: MarketEnvironment) -> ql.DiscreteAveragingAsianOption:
        """
        Construct a QuantLib DiscreteAveragingAsianOption.

        QuantLib requires:
        - Average type (Arithmetic/Geometric)
        - Running accumulator and past fixings count
        - Future fixing dates
        - Payoff and exercise
        """
        try:
            self._validate(market_env)

            # 1. Payoff
            payoff = PayoffBuilder.plain_vanilla(self.option_type, self.strike)

            # 2. Exercise (European — Asians are not early-exercised)
            exercise = ExerciseBuilder.european(self.expiry)

            # 3. Average type
            ql_avg_type = _AVERAGE_TYPE_MAP[self.average_type]

            # 4. Fixing dates
            all_fixings = self._resolve_fixing_dates(market_env)
            pricing_date = market_env.pricing_date.value

            # Separate past and future fixings
            future_fixings = [d for d in all_fixings if d > pricing_date]
            past_fixing_dates = [d for d in all_fixings if d <= pricing_date]

            # Past fixings count and running accumulator
            past_count = len(past_fixing_dates)
            if self.past_fixings:
                past_count = len(self.past_fixings)

            running_acc = self.running_accumulator

            # For geometric, running accumulator must be positive (multiplicative)
            # Default: 1.0 for geometric (identity element), 0.0 for arithmetic
            if self.past_fixings and running_acc in (0.0, 1.0):
                if self.average_type == AverageType.ARITHMETIC:
                    running_acc = sum(self.past_fixings)
                else:
                    import math
                    running_acc = math.prod(self.past_fixings) if self.past_fixings else 1.0
            elif not self.past_fixings and self.average_type == AverageType.GEOMETRIC:
                # No past fixings — geometric needs 1.0 (multiplicative identity)
                if running_acc == 0.0:
                    running_acc = 1.0

            # Convert future fixing dates to QuantLib
            ql_future_dates = [
                ql.Date(d.day, d.month, d.year) for d in future_fixings
            ]

            if not ql_future_dates:
                raise InstrumentBuildError(
                    "No future fixing dates — option may have already expired "
                    "or averaging period hasn't started."
                )

            # 5. Build option
            option = ql.DiscreteAveragingAsianOption(
                ql_avg_type,
                running_acc,
                past_count,
                ql_future_dates,
                payoff,
                exercise,
            )

            return option

        except InstrumentBuildError:
            raise
        except Exception as e:
            raise InstrumentBuildError(
                f"Failed to build AsianOption '{self._trade_id}': {e}"
            ) from e

    # -------------------------------------------------------------------
    # Fixing date resolution
    # -------------------------------------------------------------------

    def _resolve_fixing_dates(self, market_env: MarketEnvironment) -> List[date]:
        """Resolve fixing dates from explicit list or frequency."""
        if self.fixing_dates:
            return sorted(self.fixing_dates)

        # Generate from frequency
        start = self.averaging_start
        if start is None:
            # Default: start 1 year before expiry
            start = date(self.expiry.year - 1, self.expiry.month, self.expiry.day)

        return generate_fixing_dates(start, self.expiry, self.fixing_frequency)

    # -------------------------------------------------------------------
    # Validation
    # -------------------------------------------------------------------

    def _validate(self, market_env: MarketEnvironment) -> None:
        if not self._trade_id:
            raise InstrumentBuildError("trade_id is required")
        if not self.underlying:
            raise InstrumentBuildError("underlying is required")
        if self.expiry is None:
            raise InstrumentBuildError("expiry is required")
        if self.strike_type == StrikeType.FIXED and self.strike <= 0:
            raise InstrumentBuildError(
                f"strike must be positive for fixed-strike Asian, got {self.strike}"
            )

    # -------------------------------------------------------------------
    # Properties
    # -------------------------------------------------------------------

    @property
    def is_arithmetic(self) -> bool:
        return self.average_type == AverageType.ARITHMETIC

    @property
    def is_geometric(self) -> bool:
        return self.average_type == AverageType.GEOMETRIC

    @property
    def is_fixed_strike(self) -> bool:
        return self.strike_type == StrikeType.FIXED

    @property
    def is_floating_strike(self) -> bool:
        return self.strike_type == StrikeType.FLOATING

    @property
    def total_fixings(self) -> int:
        """Total number of fixing dates (past + future)."""
        if self.fixing_dates:
            return len(self.fixing_dates)
        return 0  # unknown until build() resolves dates

    # -------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update({
            "underlying": self.underlying,
            "strike": self.strike,
            "option_type": self.option_type.value,
            "average_type": self.average_type.value,
            "strike_type": self.strike_type.value,
            "averaging_start": self.averaging_start.isoformat() if self.averaging_start else None,
            "fixing_dates": [d.isoformat() for d in self.fixing_dates] if self.fixing_dates else None,
            "fixing_frequency": self.fixing_frequency,
            "past_fixings": self.past_fixings,
            "running_accumulator": self.running_accumulator,
            "notional": self.notional,
        })
        return base

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AsianOption:
        def parse_date(d):
            if d is None:
                return None
            if isinstance(d, date):
                return d
            return date.fromisoformat(str(d))

        fixing_dates = None
        if data.get("fixing_dates"):
            fixing_dates = [parse_date(d) for d in data["fixing_dates"]]

        return cls(
            _trade_id=data["trade_id"],
            underlying=data["underlying"],
            strike=float(data.get("strike", 0.0)),
            expiry=parse_date(data.get("expiry") or data.get("maturity")),
            option_type=OptionType(data["option_type"]),
            average_type=AverageType(data.get("average_type", "arithmetic")),
            strike_type=StrikeType(data.get("strike_type", "fixed")),
            averaging_start=parse_date(data.get("averaging_start")),
            fixing_dates=fixing_dates,
            fixing_frequency=data.get("fixing_frequency", "monthly"),
            past_fixings=data.get("past_fixings"),
            running_accumulator=float(data.get("running_accumulator", 0.0)),
            notional=float(data.get("notional", 1.0)),
            _currency=data.get("currency", "USD"),
        )

    # -------------------------------------------------------------------
    # Display
    # -------------------------------------------------------------------

    def __repr__(self) -> str:
        n_fix = len(self.fixing_dates) if self.fixing_dates else f"freq={self.fixing_frequency}"
        return (
            f"AsianOption("
            f"id={self._trade_id}, "
            f"{self.average_type.value} "
            f"{self.strike_type.value}-strike "
            f"{self.option_type.value.upper()} "
            f"{self.underlying} "
            f"K={self.strike} "
            f"fixings={n_fix} "
            f"exp={self.expiry}"
            f")"
        )