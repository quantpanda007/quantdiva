"""
Digital (Binary) Option instrument — Cash-or-Nothing and Asset-or-Nothing.

Digital options have discontinuous payoffs at expiry:

Cash-or-Nothing:
    Call: pays fixed cash amount Q if S(T) > K, else 0
    Put:  pays fixed cash amount Q if S(T) < K, else 0

Asset-or-Nothing:
    Call: pays S(T) if S(T) > K, else 0
    Put:  pays S(T) if S(T) < K, else 0

These are building blocks for structured products and are also
useful for replicating other payoffs:
    Vanilla Call = Asset-or-Nothing Call - K × Cash-or-Nothing Call

Usage:
    from instruments.equity.digital_option import DigitalOption
    from core.enums.definitions import OptionType, DigitalType

    # Cash-or-Nothing Call: pays $10 if AAPL > 150 at expiry
    opt = DigitalOption(
        _trade_id="DIG-001",
        underlying="AAPL",
        strike=150.0,
        expiry=date(2026, 6, 15),
        option_type=OptionType.CALL,
        digital_type=DigitalType.CASH_OR_NOTHING,
        cash_payoff=10.0,
    )

    # Asset-or-Nothing Put: pays S(T) if SPX < 5000 at expiry
    opt = DigitalOption(
        _trade_id="DIG-002",
        underlying="SPX",
        strike=5000.0,
        expiry=date(2026, 6, 15),
        option_type=OptionType.PUT,
        digital_type=DigitalType.ASSET_OR_NOTHING,
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
# Digital type enum (if not already in core/enums)
# ---------------------------------------------------------------------------

class DigitalType(str, Enum):
    """Type of digital payoff."""
    CASH_OR_NOTHING = "cash_or_nothing"
    ASSET_OR_NOTHING = "asset_or_nothing"


# ---------------------------------------------------------------------------
# Digital Option
# ---------------------------------------------------------------------------

@instrument_registry.register_decorator("digital_option", overwrite=True)
@dataclass
class DigitalOption(BaseInstrument):
    """
    Digital (binary) option — Cash-or-Nothing or Asset-or-Nothing.

    European exercise only (digitals are not typically exercised early).

    Attributes:
        _trade_id:      Unique trade identifier
        underlying:     Underlying asset code
        strike:         Strike / trigger level
        expiry:         Expiry date
        option_type:    CALL or PUT
        digital_type:   CASH_OR_NOTHING or ASSET_OR_NOTHING
        cash_payoff:    Fixed cash amount for Cash-or-Nothing (default: 1.0)
        notional:       Contract multiplier
        _currency:      Settlement currency
    """

    _trade_id: str = ""
    underlying: str = ""
    strike: float = 0.0
    expiry: date = None
    option_type: OptionType = OptionType.CALL
    digital_type: DigitalType = DigitalType.CASH_OR_NOTHING
    cash_payoff: float = 1.0
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
        return InstrumentType.DIGITAL_OPTION

    def currency(self) -> str:
        return self._currency

    def maturity(self) -> date:
        return self.expiry

    # -------------------------------------------------------------------
    # Build QuantLib instrument
    # -------------------------------------------------------------------

    def build(self, market_env: MarketEnvironment) -> ql.VanillaOption:
        """
        Construct a QuantLib VanillaOption with digital payoff.

        QuantLib models digitals as VanillaOption with a special payoff
        (CashOrNothingPayoff or AssetOrNothingPayoff), not as a
        separate instrument class.
        """
        try:
            self._validate()

            # 1. Build payoff (digital-specific)
            payoff = self._build_payoff()

            # 2. Exercise (European only for digitals)
            exercise = ExerciseBuilder.european(self.expiry)

            # 3. Build as VanillaOption with digital payoff
            option = ql.VanillaOption(payoff, exercise)
            return option

        except InstrumentBuildError:
            raise
        except Exception as e:
            raise InstrumentBuildError(
                f"Failed to build DigitalOption '{self._trade_id}': {e}"
            ) from e

    def _build_payoff(self) -> ql.Payoff:
        """Build the appropriate digital payoff."""
        if self.digital_type == DigitalType.CASH_OR_NOTHING:
            return PayoffBuilder.cash_or_nothing(
                self.option_type, self.strike, self.cash_payoff
            )
        elif self.digital_type == DigitalType.ASSET_OR_NOTHING:
            return PayoffBuilder.asset_or_nothing(
                self.option_type, self.strike
            )
        else:
            raise InstrumentBuildError(
                f"Unknown digital type: {self.digital_type}. "
                f"Use CASH_OR_NOTHING or ASSET_OR_NOTHING."
            )

    # -------------------------------------------------------------------
    # Validation
    # -------------------------------------------------------------------

    def _validate(self) -> None:
        if not self._trade_id:
            raise InstrumentBuildError("trade_id is required")
        if not self.underlying:
            raise InstrumentBuildError("underlying is required")
        if self.strike <= 0:
            raise InstrumentBuildError(f"strike must be positive, got {self.strike}")
        if self.expiry is None:
            raise InstrumentBuildError("expiry is required")
        if self.digital_type == DigitalType.CASH_OR_NOTHING and self.cash_payoff <= 0:
            raise InstrumentBuildError(
                f"cash_payoff must be positive for Cash-or-Nothing, "
                f"got {self.cash_payoff}"
            )

    # -------------------------------------------------------------------
    # Analytic price (for quick reference / testing)
    # -------------------------------------------------------------------

    @staticmethod
    def analytic_price_cash_or_nothing(
        spot: float,
        strike: float,
        T: float,
        rate: float,
        div_yield: float,
        vol: float,
        cash_payoff: float,
        is_call: bool,
    ) -> float:
        """
        Closed-form BSM price for Cash-or-Nothing digital.

        Call: Q * exp(-rT) * N(d2)
        Put:  Q * exp(-rT) * N(-d2)

        where d2 = [ln(S/K) + (r - q - σ²/2)T] / (σ√T)
        """
        import numpy as np
        from scipy.stats import norm

        if T <= 0 or vol <= 0:
            if is_call:
                return cash_payoff * np.exp(-rate * T) if spot > strike else 0.0
            else:
                return cash_payoff * np.exp(-rate * T) if spot < strike else 0.0

        d2 = (
            (np.log(spot / strike) + (rate - div_yield - 0.5 * vol ** 2) * T)
            / (vol * np.sqrt(T))
        )

        if is_call:
            return cash_payoff * np.exp(-rate * T) * norm.cdf(d2)
        else:
            return cash_payoff * np.exp(-rate * T) * norm.cdf(-d2)

    @staticmethod
    def analytic_price_asset_or_nothing(
        spot: float,
        strike: float,
        T: float,
        rate: float,
        div_yield: float,
        vol: float,
        is_call: bool,
    ) -> float:
        """
        Closed-form BSM price for Asset-or-Nothing digital.

        Call: S * exp(-qT) * N(d1)
        Put:  S * exp(-qT) * N(-d1)

        where d1 = [ln(S/K) + (r - q + σ²/2)T] / (σ√T)
        """
        import numpy as np
        from scipy.stats import norm

        if T <= 0 or vol <= 0:
            if is_call:
                return spot * np.exp(-div_yield * T) if spot > strike else 0.0
            else:
                return spot * np.exp(-div_yield * T) if spot < strike else 0.0

        d1 = (
            (np.log(spot / strike) + (rate - div_yield + 0.5 * vol ** 2) * T)
            / (vol * np.sqrt(T))
        )

        if is_call:
            return spot * np.exp(-div_yield * T) * norm.cdf(d1)
        else:
            return spot * np.exp(-div_yield * T) * norm.cdf(-d1)

    # -------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update({
            "underlying": self.underlying,
            "strike": self.strike,
            "option_type": self.option_type.value,
            "digital_type": self.digital_type.value,
            "cash_payoff": self.cash_payoff,
            "notional": self.notional,
        })
        return base

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DigitalOption:
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
            digital_type=DigitalType(data.get("digital_type", "cash_or_nothing")),
            cash_payoff=float(data.get("cash_payoff", 1.0)),
            notional=float(data.get("notional", 1.0)),
            _currency=data.get("currency", "USD"),
        )

    # -------------------------------------------------------------------
    # Display
    # -------------------------------------------------------------------

    def __repr__(self) -> str:
        payoff_str = (
            f"Q={self.cash_payoff}"
            if self.digital_type == DigitalType.CASH_OR_NOTHING
            else "asset"
        )
        return (
            f"DigitalOption("
            f"id={self._trade_id}, "
            f"{self.digital_type.value} "
            f"{self.option_type.value.upper()} "
            f"{self.underlying} "
            f"K={self.strike} "
            f"[{payoff_str}] "
            f"exp={self.expiry}"
            f")"
        )