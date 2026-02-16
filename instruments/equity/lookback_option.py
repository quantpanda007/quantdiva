"""
Lookback Option instrument — Fixed and Floating strike.

Lookback options depend on the extremum (max or min) of the underlying
price over the life of the option.

Fixed Strike Lookback:
    Call: max(S_max - K, 0)     — payoff on running maximum
    Put:  max(K - S_min, 0)     — payoff on running minimum

Floating Strike Lookback:
    Call: S(T) - S_min          — buy at the lowest price seen
    Put:  S_max - S(T)          — sell at the highest price seen

Monitoring:
    Continuous: theoretical, uses analytic formulas
    Discrete:   monitor at specific dates (more realistic, requires MC)

For in-progress options, the current running max/min can be provided.

Usage:
    from instruments.equity.lookback_option import LookbackOption, LookbackStrikeType

    # Floating-strike lookback call: buy at the minimum
    opt = LookbackOption(
        _trade_id="LB-001",
        underlying="AAPL",
        expiry=date(2026, 6, 15),
        option_type=OptionType.CALL,
        strike_type=LookbackStrikeType.FLOATING,
    )

    # Fixed-strike lookback put: payoff on running minimum
    opt = LookbackOption(
        _trade_id="LB-002",
        underlying="SPX",
        strike=5000.0,
        expiry=date(2026, 6, 15),
        option_type=OptionType.PUT,
        strike_type=LookbackStrikeType.FIXED,
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any, Dict, Optional

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
# Lookback strike type
# ---------------------------------------------------------------------------

class LookbackStrikeType(str, Enum):
    """Fixed or floating strike for lookback options."""
    FIXED = "fixed"
    FLOATING = "floating"


# ---------------------------------------------------------------------------
# Lookback Option
# ---------------------------------------------------------------------------

@instrument_registry.register_decorator("lookback_option", overwrite=True)
@dataclass
class LookbackOption(BaseInstrument):
    """
    Lookback option — fixed or floating strike.

    Attributes:
        _trade_id:        Unique trade identifier
        underlying:       Underlying asset code
        strike:           Strike price (used for fixed-strike only)
        expiry:           Expiry date
        option_type:      CALL or PUT
        strike_type:      FIXED or FLOATING
        current_max:      Running maximum of spot seen so far (for in-progress options)
        current_min:      Running minimum of spot seen so far (for in-progress options)
        notional:         Contract multiplier
        _currency:        Settlement currency
    """

    _trade_id: str = ""
    underlying: str = ""
    strike: float = 0.0
    expiry: date = None
    option_type: OptionType = OptionType.CALL
    strike_type: LookbackStrikeType = LookbackStrikeType.FLOATING
    current_max: Optional[float] = None
    current_min: Optional[float] = None
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
        return InstrumentType.LOOKBACK_OPTION

    def currency(self) -> str:
        return self._currency

    def maturity(self) -> date:
        return self.expiry

    # -------------------------------------------------------------------
    # Build QuantLib instrument
    # -------------------------------------------------------------------

    def build(self, market_env: MarketEnvironment) -> ql.Instrument:
        """
        Construct a QuantLib lookback option.

        Floating strike → ContinuousFloatingLookbackOption
        Fixed strike    → ContinuousFixedLookbackOption

        These are continuous monitoring versions suitable for analytic pricing.
        For discrete monitoring, use MC engine directly.
        """
        try:
            self._validate(market_env)

            # Exercise
            exercise = ExerciseBuilder.european(self.expiry)

            spot = market_env.spot_prices.get(self.underlying, 100.0)

            if self.strike_type == LookbackStrikeType.FLOATING:
                return self._build_floating(exercise, spot)
            else:
                return self._build_fixed(exercise, spot)

        except InstrumentBuildError:
            raise
        except Exception as e:
            raise InstrumentBuildError(
                f"Failed to build LookbackOption '{self._trade_id}': {e}"
            ) from e

    def _build_floating(self, exercise: ql.Exercise, spot: float) -> ql.ContinuousFloatingLookbackOption:
        """
        Build floating-strike lookback.

        Call: S(T) - S_min  → minmax = current running minimum
        Put:  S_max - S(T)  → minmax = current running maximum
        """
        # QuantLib floating lookback payoff
        ql_type = ql.Option.Call if self.option_type == OptionType.CALL else ql.Option.Put
        payoff = ql.FloatingTypePayoff(ql_type)

        # Running extremum
        if self.option_type == OptionType.CALL:
            # Need running minimum
            minmax = self.current_min if self.current_min is not None else spot
        else:
            # Need running maximum
            minmax = self.current_max if self.current_max is not None else spot

        return ql.ContinuousFloatingLookbackOption(minmax, payoff, exercise)

    def _build_fixed(self, exercise: ql.Exercise, spot: float) -> ql.ContinuousFixedLookbackOption:
        """
        Build fixed-strike lookback.

        Call: max(S_max - K, 0)  → minmax = current running maximum
        Put:  max(K - S_min, 0)  → minmax = current running minimum
        """
        payoff = PayoffBuilder.plain_vanilla(self.option_type, self.strike)

        # Running extremum
        if self.option_type == OptionType.CALL:
            # Need running maximum
            minmax = self.current_max if self.current_max is not None else spot
        else:
            # Need running minimum
            minmax = self.current_min if self.current_min is not None else spot

        return ql.ContinuousFixedLookbackOption(minmax, payoff, exercise)

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
        if self.strike_type == LookbackStrikeType.FIXED and self.strike <= 0:
            raise InstrumentBuildError(
                f"strike must be positive for fixed-strike lookback, got {self.strike}"
            )

        spot = market_env.spot_prices.get(self.underlying)
        if spot is not None:
            if self.current_min is not None and self.current_min > spot:
                raise InstrumentBuildError(
                    f"current_min ({self.current_min}) cannot be above "
                    f"current spot ({spot})"
                )
            if self.current_max is not None and self.current_max < spot:
                raise InstrumentBuildError(
                    f"current_max ({self.current_max}) cannot be below "
                    f"current spot ({spot})"
                )

    # -------------------------------------------------------------------
    # Properties
    # -------------------------------------------------------------------

    @property
    def is_fixed_strike(self) -> bool:
        return self.strike_type == LookbackStrikeType.FIXED

    @property
    def is_floating_strike(self) -> bool:
        return self.strike_type == LookbackStrikeType.FLOATING

    # -------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update({
            "underlying": self.underlying,
            "strike": self.strike,
            "option_type": self.option_type.value,
            "strike_type": self.strike_type.value,
            "current_max": self.current_max,
            "current_min": self.current_min,
            "notional": self.notional,
        })
        return base

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> LookbackOption:
        def parse_date(d):
            if d is None:
                return None
            if isinstance(d, date):
                return d
            return date.fromisoformat(str(d))

        return cls(
            _trade_id=data["trade_id"],
            underlying=data["underlying"],
            strike=float(data.get("strike", 0.0)),
            expiry=parse_date(data.get("expiry") or data.get("maturity")),
            option_type=OptionType(data["option_type"]),
            strike_type=LookbackStrikeType(data.get("strike_type", "floating")),
            current_max=data.get("current_max"),
            current_min=data.get("current_min"),
            notional=float(data.get("notional", 1.0)),
            _currency=data.get("currency", "USD"),
        )

    def __repr__(self) -> str:
        extremum = ""
        if self.current_max is not None:
            extremum += f" max={self.current_max}"
        if self.current_min is not None:
            extremum += f" min={self.current_min}"
        return (
            f"LookbackOption("
            f"id={self._trade_id}, "
            f"{self.strike_type.value}-strike "
            f"{self.option_type.value.upper()} "
            f"{self.underlying} "
            f"{'K=' + str(self.strike) + ' ' if self.is_fixed_strike else ''}"
            f"exp={self.expiry}"
            f"{extremum}"
            f")"
        )