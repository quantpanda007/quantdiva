"""Registry adapter that exposes the fresh IRS implementation to PricingService.

``FreshOISInstrument`` is registered as instrument type ``"ois"``. It parses an
explicit parameter set into typed domain objects and, at build time, assembles
the swap with the existing fresh IRS builders (schedule translation, fixed and
floating legs, ``ql.Swap`` assembly). It is independent of the legacy
``"irs"`` instrument in ``instruments/rates/interest_rate_swap.py``.

Rules:
* every parameter is required, unknown keys are rejected, nothing is defaulted;
* rates and spreads are decimals (0.05, 0.001), never percentages or bp;
* the projection curve is ``market_env.forecast_curves[currency]``; if it is
  missing the build fails, there is no fallback to another curve;
* the pricing engine is attached by the caller (PricingService); this class
  does not choose a discount curve.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Mapping, Optional, Tuple

import QuantLib as ql

from core.enums.definitions import AssetClass, DayCountConvention, Frequency, InstrumentType
from core.interfaces.base import BaseInstrument, MarketEnvironment
from core.types.value_objects import Money, TradeId
from instruments.rates.irs.domain import IRSLegKind, IRSLegTerms, ObservationConventions
from instruments.rates.irs.fixed_leg import build_fixed_leg
from instruments.rates.irs.floating_leg import build_floating_leg
from instruments.rates.irs.instrument import QuantLibIRSInstrument, assemble_quantlib_irs
from instruments.rates.irs.quantlib_schedule import translate_leg_schedule
from instruments.rates.irs.schedule import CouponPeriod, LegSchedule
from registry import instrument_registry


class InvalidIRSParameters(ValueError):
    """Raised when request parameters are missing, unknown or malformed."""


class MissingIRSCurve(KeyError):
    """Raised when a required curve is absent from the market environment."""


_DAY_COUNTS = {
    "ACT/360": DayCountConvention.ACT_360,
    "ACT/365": DayCountConvention.ACT_365,
    "30/360": DayCountConvention.THIRTY_360,
}
_PAYMENT_FREQUENCIES = {
    "annual": Frequency.ANNUAL,
    "semiannual": Frequency.SEMIANNUAL,
    "quarterly": Frequency.QUARTERLY,
    "monthly": Frequency.MONTHLY,
}
_RESET_FREQUENCIES = {"daily": Frequency.DAILY}
_FIXED_SIDES = ("pay", "receive")

_TOP_KEYS = frozenset(
    {
        "trade_id",
        "currency",
        "valuation_date",
        "effective_date",
        "maturity_date",
        "fixed_leg_side",
        "fixed_leg",
        "floating_leg",
    }
)
_FIXED_KEYS = frozenset({"day_count", "payment_frequency", "fixed_rate", "periods"})
_FLOATING_KEYS = frozenset(
    {
        "day_count",
        "payment_frequency",
        "benchmark",
        "benchmark_tenor",
        "spread",
        "leverage",
        "reset_frequency",
        "observation",
        "periods",
    }
)
_OBSERVATION_KEYS = frozenset(
    {"lookback_days", "cutoff_days", "reset_timing", "compounding", "lookback_type"}
)
_PERIOD_KEYS = frozenset({"accrual_start", "accrual_end", "payment_date", "notional"})


def _require_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidIRSParameters(f"{path} must be a mapping")
    return value


def _check_keys(value: Mapping[str, Any], expected: frozenset, path: str) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        raise InvalidIRSParameters(f"{path}: missing required keys {missing}")
    if unknown:
        raise InvalidIRSParameters(f"{path}: unknown keys {unknown}")


def _date(value: Any, path: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise InvalidIRSParameters(f"{path}: invalid ISO date {value!r}") from exc


def _decimal(value: Any, path: str) -> Decimal:
    if isinstance(value, bool):
        raise InvalidIRSParameters(f"{path}: must be a number")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except Exception as exc:  # decimal.InvalidOperation and friends
        raise InvalidIRSParameters(f"{path}: must be a number, got {value!r}") from exc
    if not result.is_finite():
        raise InvalidIRSParameters(f"{path}: must be finite")
    return result


def _decimal_rate(value: Any, path: str) -> Decimal:
    result = _decimal(value, path)
    if abs(result) >= 1:
        raise InvalidIRSParameters(f"{path}: {result} looks like a percentage; use a decimal")
    return result


def _int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidIRSParameters(f"{path}: must be an integer, got {value!r}")
    return value


def _choice(value: Any, choices: Mapping[str, Any], path: str) -> Any:
    key = value if isinstance(value, str) else None
    if key is None or key not in choices:
        raise InvalidIRSParameters(f"{path}: {value!r} is not one of {sorted(choices)}")
    return choices[key]


def _non_empty_str(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidIRSParameters(f"{path}: must be a non-empty string")
    return value.strip()


def _periods(value: Any, currency: str, path: str) -> Tuple[CouponPeriod, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise InvalidIRSParameters(f"{path}: must be a non-empty list")
    periods = []
    for i, raw in enumerate(value):
        item_path = f"{path}[{i}]"
        row = _require_mapping(raw, item_path)
        _check_keys(row, _PERIOD_KEYS, item_path)
        notional = _decimal(row["notional"], f"{item_path}.notional")
        if notional <= 0:
            raise InvalidIRSParameters(f"{item_path}.notional: must be positive")
        periods.append(
            CouponPeriod(
                accrual_start=_date(row["accrual_start"], f"{item_path}.accrual_start"),
                accrual_end=_date(row["accrual_end"], f"{item_path}.accrual_end"),
                payment_date=_date(row["payment_date"], f"{item_path}.payment_date"),
                notional=Money(notional, currency),
            )
        )
    return tuple(periods)


@dataclass(frozen=True)
class FreshOISTrade:
    """Typed, validated inputs for one fixed-vs-overnight swap."""

    trade_id: str
    currency: str
    valuation_date: date
    effective_date: date
    maturity_date: date
    fixed_leg_side: str
    fixed_terms: IRSLegTerms
    floating_terms: IRSLegTerms
    fixed_periods: Tuple[CouponPeriod, ...]
    floating_periods: Tuple[CouponPeriod, ...]

    def __post_init__(self) -> None:
        if self.fixed_leg_side not in _FIXED_SIDES:
            raise InvalidIRSParameters(f"fixed_leg_side must be one of {_FIXED_SIDES}")
        if self.fixed_terms.kind is not IRSLegKind.FIXED:
            raise InvalidIRSParameters("fixed_terms must describe a fixed leg")
        if self.floating_terms.kind is not IRSLegKind.FLOATING:
            raise InvalidIRSParameters("floating_terms must describe a floating leg")
        if not self.effective_date < self.maturity_date:
            raise InvalidIRSParameters("effective_date must be before maturity_date")
        for name, periods in (("fixed", self.fixed_periods), ("floating", self.floating_periods)):
            if periods[0].accrual_start != self.effective_date:
                raise InvalidIRSParameters(f"{name} periods must start on the effective_date")
            if periods[-1].accrual_end != self.maturity_date:
                raise InvalidIRSParameters(f"{name} periods must end on the maturity_date")

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "FreshOISTrade":
        params = _require_mapping(params, "params")
        _check_keys(params, _TOP_KEYS, "params")
        currency = _non_empty_str(params["currency"], "currency").upper()

        fixed = _require_mapping(params["fixed_leg"], "fixed_leg")
        _check_keys(fixed, _FIXED_KEYS, "fixed_leg")
        fixed_periods = _periods(fixed["periods"], currency, "fixed_leg.periods")
        fixed_terms = IRSLegTerms(
            kind=IRSLegKind.FIXED,
            payment_frequency=_choice(
                fixed["payment_frequency"], _PAYMENT_FREQUENCIES, "fixed_leg.payment_frequency"
            ),
            day_count=_choice(fixed["day_count"], _DAY_COUNTS, "fixed_leg.day_count"),
            original_notional=fixed_periods[0].notional,
            fixed_coupon_rate=_decimal_rate(fixed["fixed_rate"], "fixed_leg.fixed_rate"),
        )

        floating = _require_mapping(params["floating_leg"], "floating_leg")
        _check_keys(floating, _FLOATING_KEYS, "floating_leg")
        observation = _require_mapping(floating["observation"], "floating_leg.observation")
        _check_keys(observation, _OBSERVATION_KEYS, "floating_leg.observation")
        floating_periods = _periods(floating["periods"], currency, "floating_leg.periods")
        floating_terms = IRSLegTerms(
            kind=IRSLegKind.FLOATING,
            payment_frequency=_choice(
                floating["payment_frequency"],
                _PAYMENT_FREQUENCIES,
                "floating_leg.payment_frequency",
            ),
            day_count=_choice(floating["day_count"], _DAY_COUNTS, "floating_leg.day_count"),
            original_notional=floating_periods[0].notional,
            benchmark=_non_empty_str(floating["benchmark"], "floating_leg.benchmark"),
            benchmark_tenor=_non_empty_str(
                floating["benchmark_tenor"], "floating_leg.benchmark_tenor"
            ),
            floating_spread_rate=_decimal_rate(floating["spread"], "floating_leg.spread"),
            floating_leverage=_decimal(floating["leverage"], "floating_leg.leverage"),
            reset_frequency=_choice(
                floating["reset_frequency"], _RESET_FREQUENCIES, "floating_leg.reset_frequency"
            ),
            observation=ObservationConventions(
                lookback_days=_int(
                    observation["lookback_days"], "floating_leg.observation.lookback_days"
                ),
                cutoff_days=_int(
                    observation["cutoff_days"], "floating_leg.observation.cutoff_days"
                ),
                reset_timing=_non_empty_str(
                    observation["reset_timing"], "floating_leg.observation.reset_timing"
                ),
                compounding=_non_empty_str(
                    observation["compounding"], "floating_leg.observation.compounding"
                ),
                lookback_type=_non_empty_str(
                    observation["lookback_type"], "floating_leg.observation.lookback_type"
                ),
            ),
        )

        return cls(
            trade_id=_non_empty_str(params["trade_id"], "trade_id"),
            currency=currency,
            valuation_date=_date(params["valuation_date"], "valuation_date"),
            effective_date=_date(params["effective_date"], "effective_date"),
            maturity_date=_date(params["maturity_date"], "maturity_date"),
            fixed_leg_side=_non_empty_str(params["fixed_leg_side"], "fixed_leg_side").lower(),
            fixed_terms=fixed_terms,
            floating_terms=floating_terms,
            fixed_periods=fixed_periods,
            floating_periods=floating_periods,
        )


@instrument_registry.register_decorator(InstrumentType.OIS.value)
class FreshOISInstrument(BaseInstrument):
    """Fresh fixed-vs-overnight swap, priced by the ``("ois", "discounting")`` engine."""

    def __init__(self, trade: FreshOISTrade) -> None:
        if not isinstance(trade, FreshOISTrade):
            raise TypeError("FreshOISInstrument requires a FreshOISTrade; use from_dict(params)")
        self._trade = trade
        self._last_built: Optional[QuantLibIRSInstrument] = None

    # --- construction ------------------------------------------------------

    @classmethod
    def from_dict(cls, params: Mapping[str, Any]) -> "FreshOISInstrument":
        return cls(FreshOISTrade.from_params(params))

    @property
    def trade(self) -> FreshOISTrade:
        return self._trade

    # --- BaseInstrument ----------------------------------------------------

    def build(self, market_env: MarketEnvironment) -> ql.Swap:
        currency = self._trade.currency
        forecast = market_env.forecast_curves.get(currency)
        if forecast is None:
            raise MissingIRSCurve(
                f"no forecast curve for {currency}; available: {sorted(market_env.forecast_curves)}"
            )

        fixed_schedule = translate_leg_schedule(
            LegSchedule(periods=self._trade.fixed_periods, principal_repayments=())
        )
        floating_schedule = translate_leg_schedule(
            LegSchedule(periods=self._trade.floating_periods, principal_repayments=())
        )
        fixed = build_fixed_leg(self._trade.fixed_terms, fixed_schedule)
        floating = build_floating_leg(
            self._trade.floating_terms, floating_schedule, currency, forwarding_curve=forecast
        )
        if self._trade.fixed_leg_side == "pay":
            built = assemble_quantlib_irs(fixed, floating)
        else:
            built = assemble_quantlib_irs(floating, fixed)
        self._last_built = built
        return built.quantlib_instrument

    def asset_class(self) -> AssetClass:
        return AssetClass.RATES

    def instrument_type(self) -> InstrumentType:
        return InstrumentType.OIS

    def trade_id(self) -> TradeId:
        return TradeId(self._trade.trade_id)

    def currency(self) -> str:
        return self._trade.currency

    def maturity(self) -> date:
        return self._trade.maturity_date

    # --- results -----------------------------------------------------------

    @property
    def last_built(self) -> QuantLibIRSInstrument:
        if self._last_built is None:
            raise RuntimeError("instrument has not been built yet")
        return self._last_built

    def leg_npvs(self) -> Dict[str, float]:
        """Signed leg NPVs of the last-built swap (paid leg negative)."""
        built = self.last_built
        swap = built.quantlib_instrument
        fixed_index = 0 if self._trade.fixed_leg_side == "pay" else 1
        return {
            "fixed": swap.legNPV(fixed_index),
            "floating": swap.legNPV(1 - fixed_index),
        }
