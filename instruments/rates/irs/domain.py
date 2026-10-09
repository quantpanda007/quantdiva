"""Immutable contractual inputs for a fresh, QuantLib-native IRS implementation.

These objects deliberately contain no QuantLib objects or valuation behavior. They
store contractual leg terms and dated repayment amounts for later schedule,
instrument, model, and engine layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional, Tuple, Union

from core.enums.definitions import DayCountConvention, Frequency
from core.types.value_objects import Money


DecimalLike = Union[Decimal, int, float, str]


class IRSLegKind(str, Enum):
    FIXED = "fixed"
    FLOATING = "floating"


def _as_decimal(value: DecimalLike) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass(frozen=True)
class PrincipalRepayment:
    """A dated principal-repayment amount; it does not imply principal exchange."""

    payment_date: date
    amount: Money


@dataclass(frozen=True)
class ObservationConventions:
    """Explicit floating observation inputs, retained without interpreting them."""

    lookback_days: Optional[int] = None
    cutoff_days: Optional[int] = None
    reset_timing: Optional[str] = None
    compounding: Optional[str] = None
    lookback_type: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("lookback_days", "cutoff_days"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative")


@dataclass(frozen=True)
class IRSLegTerms:
    """Terms for one independently configured fixed or floating IRS leg."""

    kind: IRSLegKind
    payment_frequency: Frequency
    day_count: DayCountConvention
    original_notional: Money
    principal_repayments: Tuple[PrincipalRepayment, ...] = ()
    fixed_coupon_rate: Optional[DecimalLike] = None
    benchmark: Optional[str] = None
    benchmark_tenor: Optional[str] = None
    floating_spread_rate: Optional[DecimalLike] = None
    floating_leverage: Optional[DecimalLike] = None
    reset_frequency: Optional[Frequency] = None
    observation: Optional[ObservationConventions] = None

    def __post_init__(self) -> None:
        kind = IRSLegKind(self.kind)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "principal_repayments", tuple(self.principal_repayments))

        if self.fixed_coupon_rate is not None:
            object.__setattr__(self, "fixed_coupon_rate", _as_decimal(self.fixed_coupon_rate))
        if self.floating_spread_rate is not None:
            object.__setattr__(self, "floating_spread_rate", _as_decimal(self.floating_spread_rate))
        if self.floating_leverage is not None:
            object.__setattr__(self, "floating_leverage", _as_decimal(self.floating_leverage))

        if kind is IRSLegKind.FIXED:
            if self.fixed_coupon_rate is None:
                raise ValueError("fixed_coupon_rate is required for a fixed leg")
            if any(
                value is not None
                for value in (
                    self.benchmark,
                    self.benchmark_tenor,
                    self.floating_spread_rate,
                    self.floating_leverage,
                    self.reset_frequency,
                    self.observation,
                )
            ):
                raise ValueError("floating terms cannot be set on a fixed leg")
        else:
            required = {
                "benchmark": self.benchmark,
                "benchmark_tenor": self.benchmark_tenor,
                "floating_spread_rate": self.floating_spread_rate,
                "floating_leverage": self.floating_leverage,
                "reset_frequency": self.reset_frequency,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise ValueError(f"floating leg requires {', '.join(missing)}")
            if self.fixed_coupon_rate is not None:
                raise ValueError("fixed_coupon_rate cannot be set on a floating leg")


@dataclass(frozen=True)
class IRSTrade:
    """Contractual IRS trade inputs, independent of valuation implementation."""

    trade_id: str
    currency: str
    valuation_date: date
    effective_date: date
    maturity_date: date
    pay_leg: IRSLegTerms
    receive_leg: IRSLegTerms
    principal_exchange: str

