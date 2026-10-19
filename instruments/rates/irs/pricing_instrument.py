"""Registry adapter that exposes the fresh IRS implementation to PricingService.

``FreshOISInstrument`` is registered as instrument type ``"ois"``. It parses an
explicit parameter set into typed domain objects and, at build time, assembles
the swap with the existing fresh IRS builders (schedule translation, fixed and
floating legs, ``ql.Swap`` assembly). It is independent of the legacy
``"irs"`` instrument in ``instruments/rates/interest_rate_swap.py``.

Rules:
* every parameter is required, unknown keys are rejected, nothing is defaulted;
* rates and spreads are decimals (0.05, 0.001), never percentages or bp;
* ``maturity_date`` is the contractual (unadjusted) maturity and is stored as
  given. Each leg's final accrual end must equal that date adjusted with the
  leg's own ``accrual_date_adjustment`` (calendar and business-day convention);
  the first accrual start must equal ``effective_date`` exactly. This "start
  exact, end adjusted" rule is provisional, taken from Bloomberg TC1, TC3 and TC4
  (open item OI-8). The check is one-way: an already-adjusted date supplied as
  ``maturity_date`` also passes, because adjusting a business day leaves it
  unchanged;
* the adjustment is used for validation only. Coupons are still built from the
  explicit period dates, so it cannot change a price;
* the floating leg is either daily-compounded overnight (``reset_frequency``
  "daily", with ``observation``) or a term-rate IBOR-fallback leg (``reset_frequency``
  "semiannual", with ``term_rate`` and explicit ``resets`` per period; see
  ``instruments.rates.irs.term_rate_leg``). Resets are trade inputs: no reset
  schedule is generated, and each reset date is checked against the fixing calendar;
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

from core.enums.definitions import (
    AssetClass,
    BusinessDayConvention,
    DayCountConvention,
    Frequency,
    InstrumentType,
)
from core.interfaces.base import BaseInstrument, MarketEnvironment
from core.types.value_objects import Money, TradeId
from instruments.rates.irs.domain import IRSLegKind, IRSLegTerms, ObservationConventions
from instruments.rates.irs.fixed_leg import build_fixed_leg
from instruments.rates.irs.floating_leg import build_floating_leg
from instruments.rates.irs.instrument import QuantLibIRSInstrument, assemble_quantlib_irs
from instruments.rates.irs.quantlib_schedule import translate_leg_schedule
from instruments.rates.irs.schedule import CouponPeriod, LegSchedule
from instruments.rates.irs.term_rate_leg import (
    CONTRACTUAL_ACCRUAL,
    DEFAULT_OBSERVATION_METHOD,
    OBSERVATION_METHODS,
    TERM_BENCHMARKS,
    FallbackTermBenchmark,
    TermRateLegSpec,
    TermRateReset,
    build_term_rate_floating_leg,
)
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
# Term-rate (IBOR-fallback) legs: resets are explicit trade inputs, see term_rate_leg.
_TERM_RESET_FREQUENCIES = {"semiannual": Frequency.SEMIANNUAL}
_TERM_COMPOUNDING = ("flat", "none")
_FIXED_SIDES = ("pay", "receive")

# Bloomberg calendar codes. "FD" is taken to be the US Federal Reserve calendar
# (assumption, OI-8). "SZ" is QuantLib's Switzerland calendar (its only market);
# it reproduces every TC7 accrual and payment date. "JN" -> ql.Japan and "RB" ->
# ql.India (NSE): the INR and JPY OIS bootstraps on these calendars reproduce
# Bloomberg's TC5/TC8/TC9 and TC6/TC10 discount factors (OI-15, OI-16); not
# SME-confirmed. Other codes are rejected.
_CALENDARS = {
    "FD": lambda: ql.UnitedStates(ql.UnitedStates.FederalReserve),
    "SZ": ql.Switzerland,
    "JN": ql.Japan,
    "RB": ql.India,
}
# Fixing calendars for term-rate resets. "EN" (England) is QuantLib's UnitedKingdom
# settlement calendar: TC7's 27-Aug-2027 reset is one London business day before
# 31-Aug-2027 (30-Aug-2027 is a UK bank holiday but a Swiss business day).
_FIXING_CALENDARS = {
    "EN": ql.UnitedKingdom,
    "SZ": ql.Switzerland,
    "RB": ql.India,
}
_BUSINESS_DAY_CONVENTIONS = {convention.value: convention for convention in BusinessDayConvention}
_QL_BUSINESS_DAY_CONVENTIONS = {
    BusinessDayConvention.FOLLOWING: ql.Following,
    BusinessDayConvention.MODIFIED_FOLLOWING: ql.ModifiedFollowing,
    BusinessDayConvention.PRECEDING: ql.Preceding,
    BusinessDayConvention.MODIFIED_PRECEDING: ql.ModifiedPreceding,
    BusinessDayConvention.UNADJUSTED: ql.Unadjusted,
}

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
_FIXED_KEYS = frozenset(
    {"day_count", "payment_frequency", "fixed_rate", "accrual_date_adjustment", "periods"}
)
_FLOATING_KEYS = frozenset(
    {
        "day_count",
        "accrual_date_adjustment",
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
_TERM_FLOATING_KEYS = (_FLOATING_KEYS - {"observation"}) | {"term_rate"}
_TERM_RATE_KEYS = frozenset({"compounding", "fixing_calendar", "fixing_days"})
# Optional: observation-date method of an RFR-fallback benchmark (term_rate_leg); absent
# means the existing reset-date fallback (Method B).
_TERM_RATE_OPTIONAL_KEYS = frozenset({"observation_dates"})
_RESET_KEYS = frozenset({"reset_date", "start", "end"})
_OBSERVATION_KEYS = frozenset(
    {"lookback_days", "cutoff_days", "reset_timing", "compounding", "lookback_type"}
)
_PERIOD_KEYS = frozenset({"accrual_start", "accrual_end", "payment_date", "notional"})
_ADJUSTMENT_KEYS = frozenset({"calendar", "business_day_convention"})


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
class AccrualDateAdjustment:
    """Calendar and business-day convention used to adjust a leg's accrual dates.

    Used only to check the final accrual end against the contractual maturity.
    """

    calendar: str
    business_day_convention: BusinessDayConvention

    def __post_init__(self) -> None:
        if self.calendar not in _CALENDARS:
            raise InvalidIRSParameters(
                f"calendar {self.calendar!r} is not supported; supported: {sorted(_CALENDARS)}"
            )
        if not isinstance(self.business_day_convention, BusinessDayConvention):
            raise InvalidIRSParameters("business_day_convention must be a BusinessDayConvention")

    def adjust(self, value: date) -> date:
        calendar = _CALENDARS[self.calendar]()
        adjusted = calendar.adjust(
            ql.Date(value.day, value.month, value.year),
            _QL_BUSINESS_DAY_CONVENTIONS[self.business_day_convention],
        )
        return date(adjusted.year(), adjusted.month(), adjusted.dayOfMonth())

    def describe(self) -> str:
        return f"{self.business_day_convention.value}, calendar {self.calendar}"


def _adjustment(value: Any, path: str) -> AccrualDateAdjustment:
    row = _require_mapping(value, path)
    _check_keys(row, _ADJUSTMENT_KEYS, path)
    calendar = row["calendar"]
    if not isinstance(calendar, str) or calendar not in _CALENDARS:
        raise InvalidIRSParameters(
            f"{path}.calendar: {calendar!r} is not supported; supported: {sorted(_CALENDARS)}"
        )
    return AccrualDateAdjustment(
        calendar=calendar,
        business_day_convention=_choice(
            row["business_day_convention"],
            _BUSINESS_DAY_CONVENTIONS,
            f"{path}.business_day_convention",
        ),
    )


def _term_rate_floating(
    floating: Mapping[str, Any], currency: str
) -> Tuple[IRSLegTerms, Tuple[CouponPeriod, ...], TermRateLegSpec]:
    """Parse a term-rate (IBOR-fallback) floating leg with explicit resets."""
    _check_keys(floating, _TERM_FLOATING_KEYS, "floating_leg")
    benchmark_name = _non_empty_str(floating["benchmark"], "floating_leg.benchmark")
    benchmark = TERM_BENCHMARKS.get(benchmark_name)
    if benchmark is None:
        raise InvalidIRSParameters(
            f"floating_leg.benchmark: {benchmark_name!r} has no term-rate definition; "
            f"supported: {sorted(TERM_BENCHMARKS)}"
        )
    tenor = _non_empty_str(floating["benchmark_tenor"], "floating_leg.benchmark_tenor")
    if tenor != benchmark.tenor or currency != benchmark.currency:
        raise InvalidIRSParameters(
            f"floating_leg: {benchmark_name} is a {benchmark.currency} {benchmark.tenor} "
            f"benchmark, not {currency} {tenor}"
        )
    term = _require_mapping(floating["term_rate"], "floating_leg.term_rate")
    _check_keys({k: v for k, v in term.items() if k not in _TERM_RATE_OPTIONAL_KEYS},
                _TERM_RATE_KEYS, "floating_leg.term_rate")
    observation_method = DEFAULT_OBSERVATION_METHOD
    if "observation_dates" in term:
        observation_method = _non_empty_str(
            term["observation_dates"], "floating_leg.term_rate.observation_dates")
        if observation_method not in OBSERVATION_METHODS:
            raise InvalidIRSParameters(
                f"floating_leg.term_rate.observation_dates: {observation_method!r} is not one "
                f"of {sorted(OBSERVATION_METHODS)}")
        if (observation_method == CONTRACTUAL_ACCRUAL
                and not isinstance(benchmark, FallbackTermBenchmark)):
            raise InvalidIRSParameters(
                f"floating_leg.term_rate.observation_dates: {CONTRACTUAL_ACCRUAL!r} applies "
                f"to RFR-fallback benchmarks only, not {benchmark_name}")
    compounding = _non_empty_str(term["compounding"], "floating_leg.term_rate.compounding")
    if compounding not in _TERM_COMPOUNDING:
        raise InvalidIRSParameters(
            f"floating_leg.term_rate.compounding: {compounding!r} is not one of "
            f"{list(_TERM_COMPOUNDING)}"
        )
    fixing_code = _non_empty_str(term["fixing_calendar"], "floating_leg.term_rate.fixing_calendar")
    if fixing_code not in _FIXING_CALENDARS:
        raise InvalidIRSParameters(
            f"floating_leg.term_rate.fixing_calendar: {fixing_code!r} is not supported; "
            f"supported: {sorted(_FIXING_CALENDARS)}"
        )
    fixing_calendar = _FIXING_CALENDARS[fixing_code]()
    fixing_days = _int(term["fixing_days"], "floating_leg.term_rate.fixing_days")
    if fixing_days < 0:
        raise InvalidIRSParameters("floating_leg.term_rate.fixing_days: cannot be negative")

    raw_periods = floating["periods"]
    if not isinstance(raw_periods, (list, tuple)) or not raw_periods:
        raise InvalidIRSParameters("floating_leg.periods: must be a non-empty list")
    plain_rows, resets = [], []
    for i, raw in enumerate(raw_periods):
        path = f"floating_leg.periods[{i}]"
        row = _require_mapping(raw, path)
        _check_keys(row, _PERIOD_KEYS | {"resets"}, path)
        plain_rows.append({key: row[key] for key in _PERIOD_KEYS})
        if not isinstance(row["resets"], (list, tuple)) or not row["resets"]:
            raise InvalidIRSParameters(f"{path}.resets: must be a non-empty list")
        period_resets = []
        for j, raw_reset in enumerate(row["resets"]):
            reset_path = f"{path}.resets[{j}]"
            reset_row = _require_mapping(raw_reset, reset_path)
            _check_keys(reset_row, _RESET_KEYS, reset_path)
            reset = TermRateReset(
                reset_date=_date(reset_row["reset_date"], f"{reset_path}.reset_date"),
                start=_date(reset_row["start"], f"{reset_path}.start"),
                end=_date(reset_row["end"], f"{reset_path}.end"),
            )
            if not reset.start < reset.end:
                raise InvalidIRSParameters(f"{reset_path}: start must be before end")
            # A reset fixes in advance (on or before its sub-period start) on a fixing-
            # calendar business day. Its rate period starts a benchmark-defined lag after
            # the reset date (term_rate_leg.rate_period_start), so a reset may also fix an
            # earlier rate period than the sub-period it applies to (TC2) or be shared by
            # consecutive sub-periods (TC9).
            fixing = ql.Date(reset.reset_date.day, reset.reset_date.month, reset.reset_date.year)
            if not fixing_calendar.isBusinessDay(fixing):
                raise InvalidIRSParameters(
                    f"{reset_path}.reset_date {reset.reset_date.isoformat()} is not a "
                    f"{fixing_code} business day"
                )
            if reset.reset_date > reset.start:
                raise InvalidIRSParameters(
                    f"{reset_path}.reset_date {reset.reset_date.isoformat()} is after the "
                    f"sub-period start {reset.start.isoformat()} (resets fix in advance)"
                )
            period_resets.append(reset)
        resets.append(tuple(period_resets))
    periods = _periods(plain_rows, currency, "floating_leg.periods")
    for i, (period, period_resets) in enumerate(zip(periods, resets)):
        path = f"floating_leg.periods[{i}].resets"
        bounds = [period_resets[0].start] + [r.end for r in period_resets]
        if bounds[0] != period.accrual_start or bounds[-1] != period.accrual_end or any(
            a.end != b.start for a, b in zip(period_resets, period_resets[1:])
        ):
            raise InvalidIRSParameters(
                f"{path}: sub-periods must run contiguously from accrual_start "
                f"{period.accrual_start.isoformat()} to accrual_end "
                f"{period.accrual_end.isoformat()}"
            )
        if compounding == "none" and len(period_resets) != 1:
            raise InvalidIRSParameters(
                f"{path}: compounding 'none' allows one reset per period, got "
                f"{len(period_resets)}"
            )
    leverage = _decimal(floating["leverage"], "floating_leg.leverage")
    if leverage != 1:
        raise InvalidIRSParameters("floating_leg.leverage: term-rate legs support 1 only")
    terms = IRSLegTerms(
        kind=IRSLegKind.FLOATING,
        payment_frequency=_choice(
            floating["payment_frequency"], _PAYMENT_FREQUENCIES, "floating_leg.payment_frequency"
        ),
        day_count=_choice(floating["day_count"], _DAY_COUNTS, "floating_leg.day_count"),
        original_notional=periods[0].notional,
        benchmark=benchmark_name,
        benchmark_tenor=tenor,
        floating_spread_rate=_decimal_rate(floating["spread"], "floating_leg.spread"),
        floating_leverage=leverage,
        reset_frequency=_choice(
            floating["reset_frequency"], _TERM_RESET_FREQUENCIES, "floating_leg.reset_frequency"
        ),
    )
    spec = TermRateLegSpec(
        benchmark=benchmark,
        compounding=compounding,
        fixing_calendar_code=fixing_code,
        fixing_calendar=fixing_calendar,
        fixing_days=fixing_days,
        resets=tuple(resets),
        observation_method=observation_method,
    )
    return terms, periods, spec


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
    fixed_date_adjustment: AccrualDateAdjustment
    floating_date_adjustment: AccrualDateAdjustment
    # Set only for a term-rate (IBOR-fallback) floating leg; None for an overnight leg.
    floating_term_rate: Optional[TermRateLegSpec] = None

    def __post_init__(self) -> None:
        if self.fixed_leg_side not in _FIXED_SIDES:
            raise InvalidIRSParameters(f"fixed_leg_side must be one of {_FIXED_SIDES}")
        if self.fixed_terms.kind is not IRSLegKind.FIXED:
            raise InvalidIRSParameters("fixed_terms must describe a fixed leg")
        if self.floating_terms.kind is not IRSLegKind.FLOATING:
            raise InvalidIRSParameters("floating_terms must describe a floating leg")
        if not self.effective_date < self.maturity_date:
            raise InvalidIRSParameters("effective_date must be before maturity_date")
        legs = (
            ("fixed", self.fixed_periods, self.fixed_date_adjustment),
            ("floating", self.floating_periods, self.floating_date_adjustment),
        )
        for name, periods, adjustment in legs:
            if not isinstance(adjustment, AccrualDateAdjustment):
                raise InvalidIRSParameters(f"{name} leg requires an AccrualDateAdjustment")
            # Start exact: the first accrual start is the effective date, unadjusted.
            if periods[0].accrual_start != self.effective_date:
                raise InvalidIRSParameters(
                    f"{name} periods must start on the effective_date "
                    f"{self.effective_date.isoformat()} (unadjusted); first accrual_start is "
                    f"{periods[0].accrual_start.isoformat()}"
                )
            # End adjusted: compare with the adjusted maturity; maturity_date itself
            # is left as supplied.
            expected_end = adjustment.adjust(self.maturity_date)
            if periods[-1].accrual_end != expected_end:
                raise InvalidIRSParameters(
                    f"{name} periods must end on the maturity_date "
                    f"{self.maturity_date.isoformat()} adjusted ({adjustment.describe()}), "
                    f"i.e. {expected_end.isoformat()}; final accrual_end is "
                    f"{periods[-1].accrual_end.isoformat()}"
                )

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
        term_rate = None
        if floating.get("reset_frequency") in _TERM_RESET_FREQUENCIES:
            floating_terms, floating_periods, term_rate = _term_rate_floating(floating, currency)
        else:
            floating_terms, floating_periods = _overnight_floating(floating, currency)

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
            fixed_date_adjustment=_adjustment(
                fixed["accrual_date_adjustment"], "fixed_leg.accrual_date_adjustment"
            ),
            floating_date_adjustment=_adjustment(
                floating["accrual_date_adjustment"], "floating_leg.accrual_date_adjustment"
            ),
            floating_term_rate=term_rate,
        )


def _overnight_floating(
    floating: Mapping[str, Any], currency: str
) -> Tuple[IRSLegTerms, Tuple[CouponPeriod, ...]]:
    """Parse a daily-compounded overnight floating leg (the original schema)."""
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
    return floating_terms, floating_periods


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
        if self._trade.floating_term_rate is not None:
            spec = self._trade.floating_term_rate
            floating = build_term_rate_floating_leg(
                self._trade.floating_terms,
                floating_schedule,
                spec,
                forecast,
                fixings=(market_env.fixings or {}).get(spec.benchmark.name, {}),
            )
        else:
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
