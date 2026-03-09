"""
Barrier Option instrument — Up/Down × In/Out with rebate.

Barrier options are path-dependent: the option is activated (knocked-in)
or extinguished (knocked-out) if the underlying crosses a barrier level.

Types:
    UpIn:    Option activates when spot rises above barrier
    UpOut:   Option dies when spot rises above barrier
    DownIn:  Option activates when spot falls below barrier
    DownOut: Option dies when spot falls below barrier

Rebate:
    A cash amount paid to the holder when the option is knocked out
    (for Out barriers) or at expiry if never knocked in (for In barriers).

Parity relations:
    UpIn + UpOut = Vanilla     (same strike, expiry)
    DownIn + DownOut = Vanilla

Usage:
    from instruments.equity.barrier_option import BarrierOption
    from core.enums.definitions import OptionType, ExerciseType, BarrierType

    # Down-and-Out Call: dies if spot drops below 80
    opt = BarrierOption(
        _trade_id="BAR-001",
        underlying="AAPL",
        strike=100.0,
        expiry=date(2026, 6, 15),
        option_type=OptionType.CALL,
        barrier_type=BarrierType.DOWN_OUT,
        barrier_level=80.0,
        rebate=0.0,
    )

    # Up-and-In Put with rebate: activates if spot rises above 120
    opt = BarrierOption(
        _trade_id="BAR-002",
        underlying="SPX",
        strike=100.0,
        expiry=date(2026, 6, 15),
        option_type=OptionType.PUT,
        barrier_type=BarrierType.UP_IN,
        barrier_level=120.0,
        rebate=5.0,
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Optional

import QuantLib as ql

from core.enums.definitions import (
    AssetClass,
    BarrierType,
    ExerciseType,
    InstrumentType,
    OptionType,
)
from core.exceptions.errors import InstrumentBuildError
from core.interfaces.base import BaseInstrument, MarketEnvironment
from core.types.value_objects import TradeId
from instruments.common.exercise import ExerciseBuilder
from instruments.common.payoffs import PayoffBuilder
from registry import instrument_registry


# ---------------------------------------------------------------------------
# QuantLib barrier type mapping
# ---------------------------------------------------------------------------

_BARRIER_TYPE_MAP = {
    BarrierType.UP_IN: ql.Barrier.UpIn,
    BarrierType.UP_OUT: ql.Barrier.UpOut,
    BarrierType.DOWN_IN: ql.Barrier.DownIn,
    BarrierType.DOWN_OUT: ql.Barrier.DownOut,
}


# ---------------------------------------------------------------------------
# Barrier Option
# ---------------------------------------------------------------------------

@instrument_registry.register_decorator(
    InstrumentType.BARRIER_OPTION.value, overwrite=True
)
@dataclass
class BarrierOption(BaseInstrument):
    """
    Barrier option — knock-in or knock-out with optional rebate.

    Supports European exercise only for analytic pricing.
    American/Bermudan barriers can be priced via FD or MC engines.

    Attributes:
        _trade_id:       Unique trade identifier
        underlying:      Underlying asset code
        strike:          Strike price
        expiry:          Expiry date
        option_type:     CALL or PUT
        barrier_type:    UP_IN, UP_OUT, DOWN_IN, DOWN_OUT
        barrier_level:   Barrier trigger level
        rebate:          Cash rebate paid on knock-out (Out) or at expiry
                         if never knocked in (In). Default: 0.0
        exercise_type:   EUROPEAN (default). AMERICAN for FD/MC pricing.
        exercise_start:  First exercise date (American only)
        notional:        Contract multiplier
        _currency:       Settlement currency
    """

    _trade_id: str = ""
    underlying: str = ""
    strike: float = 0.0
    expiry: date = None
    option_type: OptionType = OptionType.CALL
    barrier_type: BarrierType = BarrierType.DOWN_OUT
    barrier_level: float = 0.0
    rebate: float = 0.0
    exercise_type: ExerciseType = ExerciseType.EUROPEAN
    exercise_start: Optional[date] = None
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
        return InstrumentType.BARRIER_OPTION

    def currency(self) -> str:
        return self._currency

    def maturity(self) -> date:
        return self.expiry

    # -------------------------------------------------------------------
    # Build QuantLib instrument
    # -------------------------------------------------------------------

    def build(self, market_env: MarketEnvironment) -> ql.BarrierOption:
        """
        Construct a QuantLib BarrierOption.

        Returns ql.BarrierOption with payoff, exercise, barrier type,
        barrier level, and rebate. Engine must be set separately.
        """
        try:
            self._validate(market_env)

            # 1. Payoff
            payoff = PayoffBuilder.plain_vanilla(self.option_type, self.strike)

            # 2. Exercise
            exercise = ExerciseBuilder.build(
                exercise_type=self.exercise_type,
                expiry=self.expiry,
                start=self.exercise_start or market_env.pricing_date.value,
            )

            # 3. Barrier type
            ql_barrier_type = _BARRIER_TYPE_MAP.get(self.barrier_type)
            if ql_barrier_type is None:
                raise InstrumentBuildError(
                    f"Unknown barrier type: {self.barrier_type}. "
                    f"Use: {list(_BARRIER_TYPE_MAP.keys())}"
                )

            # 4. Build option
            option = ql.BarrierOption(
                ql_barrier_type,
                self.barrier_level,
                self.rebate,
                payoff,
                exercise,
            )

            return option

        except InstrumentBuildError:
            raise
        except Exception as e:
            raise InstrumentBuildError(
                f"Failed to build BarrierOption '{self._trade_id}': {e}"
            ) from e

    # -------------------------------------------------------------------
    # Validation
    # -------------------------------------------------------------------

    def _validate(self, market_env: MarketEnvironment) -> None:
        """Validate barrier option parameters."""
        if not self._trade_id:
            raise InstrumentBuildError("trade_id is required")
        if not self.underlying:
            raise InstrumentBuildError("underlying is required")
        if self.strike <= 0:
            raise InstrumentBuildError(f"strike must be positive, got {self.strike}")
        if self.expiry is None:
            raise InstrumentBuildError("expiry is required")
        if self.barrier_level <= 0:
            raise InstrumentBuildError(
                f"barrier_level must be positive, got {self.barrier_level}"
            )
        if self.rebate < 0:
            raise InstrumentBuildError(
                f"rebate must be non-negative, got {self.rebate}"
            )

        spot = market_env.spot_prices.get(self.underlying)

        # Validate barrier level vs spot for consistency
        if spot is not None:
            if self.barrier_type in (BarrierType.UP_IN, BarrierType.UP_OUT):
                if self.barrier_level <= spot:
                    raise InstrumentBuildError(
                        f"Up barrier ({self.barrier_level}) must be above "
                        f"current spot ({spot}). "
                        f"For barriers below spot, use DOWN_IN or DOWN_OUT."
                    )
            elif self.barrier_type in (BarrierType.DOWN_IN, BarrierType.DOWN_OUT):
                if self.barrier_level >= spot:
                    raise InstrumentBuildError(
                        f"Down barrier ({self.barrier_level}) must be below "
                        f"current spot ({spot}). "
                        f"For barriers above spot, use UP_IN or UP_OUT."
                    )

    # -------------------------------------------------------------------
    # Properties
    # -------------------------------------------------------------------

    @property
    def is_knock_in(self) -> bool:
        """True if this is a knock-in barrier."""
        return self.barrier_type in (BarrierType.UP_IN, BarrierType.DOWN_IN)

    @property
    def is_knock_out(self) -> bool:
        """True if this is a knock-out barrier."""
        return self.barrier_type in (BarrierType.UP_OUT, BarrierType.DOWN_OUT)

    @property
    def is_up(self) -> bool:
        """True if barrier is above spot."""
        return self.barrier_type in (BarrierType.UP_IN, BarrierType.UP_OUT)

    @property
    def is_down(self) -> bool:
        """True if barrier is below spot."""
        return self.barrier_type in (BarrierType.DOWN_IN, BarrierType.DOWN_OUT)

    # -------------------------------------------------------------------
    # Parity
    # -------------------------------------------------------------------

    def parity_counterpart(self) -> BarrierOption:
        """
        Return the parity counterpart of this barrier option.

        UpIn + UpOut = Vanilla  →  counterpart of UpIn is UpOut
        DownIn + DownOut = Vanilla  →  counterpart of DownIn is DownOut

        Useful for checking: barrier_in_price + barrier_out_price ≈ vanilla_price
        """
        parity_map = {
            BarrierType.UP_IN: BarrierType.UP_OUT,
            BarrierType.UP_OUT: BarrierType.UP_IN,
            BarrierType.DOWN_IN: BarrierType.DOWN_OUT,
            BarrierType.DOWN_OUT: BarrierType.DOWN_IN,
        }

        return BarrierOption(
            _trade_id=f"{self._trade_id}-parity",
            underlying=self.underlying,
            strike=self.strike,
            expiry=self.expiry,
            option_type=self.option_type,
            barrier_type=parity_map[self.barrier_type],
            barrier_level=self.barrier_level,
            rebate=self.rebate,
            exercise_type=self.exercise_type,
            exercise_start=self.exercise_start,
            notional=self.notional,
            _currency=self._currency,
        )

    # -------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update({
            "underlying": self.underlying,
            "strike": self.strike,
            "option_type": self.option_type.value,
            "barrier_type": self.barrier_type.value,
            "barrier_level": self.barrier_level,
            "rebate": self.rebate,
            "exercise_type": self.exercise_type.value,
            "exercise_start": self.exercise_start.isoformat() if self.exercise_start else None,
            "notional": self.notional,
        })
        return base

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BarrierOption:
        def parse_date(d):
            if d is None:
                return None
            if isinstance(d, date):
                return d
            return date.fromisoformat(str(d))

        return cls(
            _trade_id=data["trade_id"],
            underlying=data["underlying"],
            strike=float(data["strike"]),
            expiry=parse_date(data.get("expiry") or data.get("maturity")),
            option_type=OptionType(data["option_type"]),
            barrier_type=BarrierType(data["barrier_type"]),
            barrier_level=float(data["barrier_level"]),
            rebate=float(data.get("rebate", 0.0)),
            exercise_type=ExerciseType(data.get("exercise_type", "european")),
            exercise_start=parse_date(data.get("exercise_start")),
            notional=float(data.get("notional", 1.0)),
            _currency=data.get("currency", "USD"),
        )

    # -------------------------------------------------------------------
    # Display
    # -------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"BarrierOption("
            f"id={self._trade_id}, "
            f"{self.barrier_type.value} "
            f"{self.option_type.value.upper()} "
            f"{self.underlying} "
            f"K={self.strike} "
            f"B={self.barrier_level} "
            f"exp={self.expiry}"
            f"{f' rebate={self.rebate}' if self.rebate > 0 else ''}"
            f")"
        )