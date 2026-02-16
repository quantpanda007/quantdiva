"""
Unified Vanilla Option instrument — European, American, and Bermudan.

This replaces the earlier vanilla_option.py with a single class that
handles all three exercise types cleanly.

Usage:
    from instruments.equity.vanilla_option import VanillaOption
    from core.enums.definitions import OptionType, ExerciseType

    # European
    opt = VanillaOption(
        trade_id="OPT-001", underlying="AAPL", strike=150.0,
        expiry=date(2026, 6, 15), option_type=OptionType.CALL,
        exercise_type=ExerciseType.EUROPEAN,
    )

    # American
    opt = VanillaOption(
        trade_id="OPT-002", underlying="AAPL", strike=150.0,
        expiry=date(2026, 6, 15), option_type=OptionType.PUT,
        exercise_type=ExerciseType.AMERICAN,
        exercise_start=date(2025, 6, 15),
    )

    # Bermudan with explicit dates
    opt = VanillaOption(
        trade_id="OPT-003", underlying="SPX", strike=5000.0,
        expiry=date(2027, 3, 15), option_type=OptionType.CALL,
        exercise_type=ExerciseType.BERMUDAN,
        bermudan_dates=[date(2025,9,15), date(2026,3,15), date(2026,9,15), date(2027,3,15)],
    )

    # Bermudan with schedule
    opt = VanillaOption(
        trade_id="OPT-004", underlying="SPX", strike=5000.0,
        expiry=date(2027, 3, 15), option_type=OptionType.CALL,
        exercise_type=ExerciseType.BERMUDAN,
        exercise_start=date(2025, 3, 15),
        bermudan_frequency="quarterly",
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Any, List, Optional

import QuantLib as ql

from core.enums.definitions import (
    AssetClass,
    ExerciseType,
    InstrumentType,
    OptionType,
)
from core.exceptions.errors import InstrumentBuildError
from core.interfaces.base import BaseInstrument, MarketEnvironment
from core.types.value_objects import TradeId
from instruments.common.payoffs import PayoffBuilder
from instruments.common.exercise import ExerciseBuilder
from registry import instrument_registry


@instrument_registry.register_decorator(
    InstrumentType.VANILLA_OPTION.value, overwrite=True
)
@dataclass
class VanillaOption(BaseInstrument):
    """
    Vanilla equity option supporting European, American, and Bermudan exercise.

    Builds a QuantLib VanillaOption with the appropriate payoff and exercise.
    The pricing engine is NOT set here — that's the engine's job.

    Attributes:
        _trade_id:          Unique trade identifier
        underlying:         Underlying asset code (e.g., "AAPL", "SPX")
        strike:             Strike price
        expiry:             Expiry / last exercise date
        option_type:        CALL or PUT
        exercise_type:      EUROPEAN, AMERICAN, or BERMUDAN
        exercise_start:     First exercise date (American/Bermudan). Defaults to pricing date.
        bermudan_dates:     Explicit list of exercise dates (Bermudan only)
        bermudan_frequency: Schedule-based exercise: "monthly"/"quarterly"/"semiannual"/"annual"
        notional:           Number of contracts / notional multiplier
        _currency:          Settlement currency
    """

    _trade_id: str = ""
    underlying: str = ""
    strike: float = 0.0
    expiry: date = None
    option_type: OptionType = OptionType.CALL
    exercise_type: ExerciseType = ExerciseType.EUROPEAN
    exercise_start: Optional[date] = None
    bermudan_dates: Optional[List[date]] = None
    bermudan_frequency: Optional[str] = None
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
        return InstrumentType.VANILLA_OPTION

    def currency(self) -> str:
        return self._currency

    def maturity(self) -> date:
        return self.expiry

    # -------------------------------------------------------------------
    # Build QuantLib instrument
    # -------------------------------------------------------------------

    def build(self, market_env: MarketEnvironment) -> ql.VanillaOption:
        """
        Construct the QuantLib VanillaOption.

        Returns a ql.VanillaOption (or ql.DividendVanillaOption if needed).
        The engine must be set separately after calling this.
        """
        try:
            self._validate()

            # 1. Build payoff
            payoff = PayoffBuilder.plain_vanilla(self.option_type, self.strike)

            # 2. Build exercise
            exercise = self._build_exercise(market_env)

            # 3. Construct QuantLib option
            option = ql.VanillaOption(payoff, exercise)
            return option

        except InstrumentBuildError:
            raise
        except Exception as e:
            raise InstrumentBuildError(
                f"Failed to build VanillaOption '{self._trade_id}': {e}"
            ) from e

    # -------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------

    def _validate(self) -> None:
        """Validate instrument parameters before building."""
        if not self._trade_id:
            raise InstrumentBuildError("trade_id is required")
        if not self.underlying:
            raise InstrumentBuildError("underlying is required")
        if self.strike <= 0:
            raise InstrumentBuildError(f"strike must be positive, got {self.strike}")
        if self.expiry is None:
            raise InstrumentBuildError("expiry is required")
        if self.exercise_type == ExerciseType.BERMUDAN:
            if not self.bermudan_dates and not self.bermudan_frequency:
                raise InstrumentBuildError(
                    "Bermudan exercise requires either 'bermudan_dates' or "
                    "'bermudan_frequency' (with 'exercise_start')."
                )
            if self.bermudan_frequency and not self.exercise_start:
                raise InstrumentBuildError(
                    "Bermudan schedule-based exercise requires 'exercise_start'."
                )

    def _build_exercise(self, market_env: MarketEnvironment) -> ql.Exercise:
        """Build the appropriate QuantLib exercise object."""
        start = self.exercise_start or market_env.pricing_date.value

        return ExerciseBuilder.build(
            exercise_type=self.exercise_type,
            expiry=self.expiry,
            start=start,
            bermudan_dates=self.bermudan_dates,
            bermudan_frequency=self.bermudan_frequency,
        )

    # -------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for storage/API."""
        base = super().to_dict()
        base.update({
            "underlying": self.underlying,
            "strike": self.strike,
            "option_type": self.option_type.value,
            "exercise_type": self.exercise_type.value,
            "exercise_start": self.exercise_start.isoformat() if self.exercise_start else None,
            "bermudan_dates": [d.isoformat() for d in self.bermudan_dates] if self.bermudan_dates else None,
            "bermudan_frequency": self.bermudan_frequency,
            "notional": self.notional,
        })
        return base

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> VanillaOption:
        """Deserialize from dictionary."""
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
            expiry=parse_date(data["expiry"]) if "expiry" in data else parse_date(data.get("maturity")),
            option_type=OptionType(data["option_type"]),
            exercise_type=ExerciseType(data.get("exercise_type", "european")),
            exercise_start=parse_date(data.get("exercise_start")),
            bermudan_dates=[parse_date(d) for d in data["bermudan_dates"]] if data.get("bermudan_dates") else None,
            bermudan_frequency=data.get("bermudan_frequency"),
            notional=float(data.get("notional", 1.0)),
            _currency=data.get("currency", "USD"),
        )

    # -------------------------------------------------------------------
    # Display
    # -------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"VanillaOption("
            f"id={self._trade_id}, "
            f"{self.option_type.value.upper()} "
            f"{self.underlying} "
            f"K={self.strike} "
            f"exp={self.expiry} "
            f"[{self.exercise_type.value}]"
            f")"
        )
