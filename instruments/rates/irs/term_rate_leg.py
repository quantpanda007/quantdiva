"""Term-rate floating legs: each payment period carries explicit resets (reset date and
sub-period dates are trade inputs; no reset schedule is generated), and each reset
rate is a term benchmark whose rate period starts a benchmark-defined lag after the
reset date. Two benchmark kinds:

* ``FallbackTermBenchmark`` (CHF ``SF0006M``, TC2/TC7): the IBOR fallback

    compounded RFR over the IBOR period [s, s + tenor], s = reset date + fixing days
    on the trade's fixing calendar, with an observation shift of ``shift_days``
    business days, plus a fixed spread adjustment,

  projected with QuantLib's overnight-indexed coupon;
* ``ProjectedTermBenchmark`` (INR ``IRSWOF`` 6M, TC5/TC8/TC9): the simple forward
  rate over [s, s + tenor], s = reset date + spot lag on the benchmark calendar.

A reset whose rate period starts before the evaluation date is a historical fixing:
its value must be supplied (market-data fixings for the benchmark); it is never
projected.
Within a payment period the sub-period amounts are combined by ISDA flat
compounding (the spread is not compounded):

    A_1 = N (r_1 + s) t_1
    A_k = N (r_k + s) t_k + (A_1 + ... + A_{k-1}) r_k t_k

and the payment is sum(A_k). It is represented as a ``ql.FixedRateCoupon`` whose
rate is the equivalent coupon sum(A_k) / (N t), so the coupon amount equals
sum(A_k). The rates are therefore computed when the leg is built: a later
change to the forecast curve needs a rebuild (``FreshOISInstrument.build``
rebuilds on every pricing call).

Status of the conventions (see ``TERM_BENCHMARKS``):
* flat compounding and the equivalent-coupon definition are confirmed by
  Bloomberg's TC7 payments (re-export of 14-Oct-2026);
* the fallback definition is PROVISIONAL: it reproduces the TC7 Resets tab within
  0.2 bp on the supplied CHF curve but has not been confirmed by the SME.

Observation windows that start before the evaluation date need the historical fixing
of the reset (see above); without it the leg is rejected rather than projected.

Observation-date method of a fallback benchmark (``TermRateLegSpec.observation_method``,
trade input ``floating_leg.term_rate.observation_dates``):

* ``"reset_date_fallback"`` (Method B, the default when the trade does not say): the
  IBOR period [reset + fixing days, + tenor Modified Following] observed with the
  benchmark's observation shift, as above. Unchanged existing behaviour.
* ``"contractual_accrual"`` (Method A): SARON observed over the reset sub-period's own
  contractual dates [start, end], with no observation shift; the reset date and the IBOR
  tenor do not set the window. PROVISIONAL operational choice (14-Oct-2026), not a
  Bloomberg- or SME-confirmed convention; the trade data contains no observation-shift
  term and the user chose no shift (docs/IRS_OPEN_ITEMS.md OI-17).

Both methods use the same compounding (QuantLib overnight-indexed coupon, compounded),
the same RFR fixings (QuantLib index history) and the same spread adjustment; only the
observation dates differ.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Callable, Mapping, Optional, Tuple, Union

import QuantLib as ql

from instruments.rates.irs.domain import IRSLegTerms
from instruments.rates.irs.floating_leg import QuantLibFloatingLeg, _day_counter
from instruments.rates.irs.quantlib_schedule import QuantLibLegSchedule


class UnsupportedTermRateLeg(ValueError):
    """The term-rate leg uses a benchmark or feature that is not implemented."""


class TermRateFixingRequired(UnsupportedTermRateLeg):
    """A fallback observation window starts before the evaluation date."""


@dataclass(frozen=True)
class FallbackTermBenchmark:
    """An IBOR term benchmark replaced by a compounded-RFR fallback."""

    name: str
    tenor: str
    currency: str
    rfr: str  # benchmark of the curve that projects the RFR (snapshot ``benchmark``)
    rfr_index: Callable[[ql.YieldTermStructureHandle], ql.OvernightIndex]
    period_calendar: Callable[[], ql.Calendar]
    shift_days: int
    spread_adjustment: Decimal
    status: str


@dataclass(frozen=True)
class ProjectedTermBenchmark:
    """A term benchmark projected as a simple forward rate on the forecast curve."""

    name: str
    tenor: str
    currency: str
    rfr: str  # benchmark of the curve it is projected on (snapshot ``benchmark``)
    calendar: Callable[[], ql.Calendar]
    spot_lag: int  # business days from the reset date to the rate-period start
    day_counter: Callable[[], ql.DayCounter]
    status: str
    shift_days: int = 0
    spread_adjustment: Decimal = Decimal("0")


TermBenchmark = Union[FallbackTermBenchmark, ProjectedTermBenchmark]

# Observation-date methods for fallback benchmarks (see the module docstring).
RESET_DATE_FALLBACK = "reset_date_fallback"  # Method B: existing behaviour, the default
CONTRACTUAL_ACCRUAL = "contractual_accrual"  # Method A: provisional operational choice
OBSERVATION_METHODS = {
    RESET_DATE_FALLBACK: "B",
    CONTRACTUAL_ACCRUAL: "A",
}
DEFAULT_OBSERVATION_METHOD = RESET_DATE_FALLBACK
CONTRACTUAL_ACCRUAL_SHIFT_DAYS = 0  # user decision 14-Oct-2026: no observation shift

TERM_BENCHMARKS = {
    "SF0006M": FallbackTermBenchmark(
        name="SF0006M",
        tenor="6M",
        currency="CHF",
        rfr="SARON",
        rfr_index=ql.Saron,
        period_calendar=ql.Switzerland,
        shift_days=2,
        spread_adjustment=Decimal("0.000741"),
        status=(
            "PROVISIONAL: CHF LIBOR 6M fallback = SARON compounded over the 6M period "
            "starting on the sub-period start (Modified Following, Swiss calendar), "
            "2-business-day observation shift, plus the published 6M spread adjustment "
            "0.0741%. IBOR period starts 1 fixing-calendar business day after the reset "
            "date (TC2: P2-P8 observation windows end on Bloomberg's effective reset dates; "
            "P1 differs by one day, OI-11). "
            "Inclusion of the 0.0741% is settled; window and shift not SME-confirmed."
        ),
    ),
    "IRSWOF": ProjectedTermBenchmark(
        name="IRSWOF",
        tenor="6M",
        currency="INR",
        rfr="MIBOR",
        calendar=ql.India,
        spot_lag=2,
        day_counter=ql.Actual365Fixed,
        status=(
            "PROVISIONAL: simple ACT/365F forward over [reset + 2 India business days, "
            "+6M Modified Following] on the INR OIS curve. Reproduces Bloomberg's TC8/TC9 "
            "6M resets within 0.3 bp (two exactly); short final stubs and TC9's first reset "
            "differ (unresolved). Index definition not SME-confirmed."
        ),
    ),
}


@dataclass(frozen=True)
class TermRateReset:
    """One reset inside a payment period (trade input)."""

    reset_date: date
    start: date
    end: date


@dataclass(frozen=True)
class TermRateLegSpec:
    """Leg-level term-rate inputs."""

    benchmark: TermBenchmark
    compounding: str  # "flat", or "none" when every period has a single reset
    fixing_calendar_code: str
    fixing_calendar: ql.Calendar
    fixing_days: int
    resets: Tuple[Tuple[TermRateReset, ...], ...]  # one tuple per payment period
    observation_method: str = DEFAULT_OBSERVATION_METHOD


@dataclass(frozen=True)
class ResetDetail:
    reset_date: date
    start: date
    end: date
    rate_start: date  # start of the benchmark's rate period (from the reset date)
    ibor_period_end: date
    observation_start: date
    observation_end: date
    rfr_compounded_rate: float
    spread_adjustment: float
    reset_rate: float  # benchmark rate = projected rate + spread adjustment, or the fixing
    accrual_fraction: float
    amount: float  # flat-compounded amount for this sub-period
    source: str = "projected"  # "projected" or "fixing" (historical, from market data)
    observation_method: str = DEFAULT_OBSERVATION_METHOD
    observation_rule: str = ""  # how the observation dates were derived (diagnostics)


@dataclass(frozen=True)
class TermRatePeriodDetail:
    resets: Tuple[ResetDetail, ...]
    equivalent_rate: float  # payment / (notional x period accrual fraction)


@dataclass(frozen=True)
class QuantLibTermRateFloatingLeg(QuantLibFloatingLeg):
    """Floating leg of fixed-rate coupons carrying the computed equivalent rates."""

    spec: TermRateLegSpec
    period_details: Tuple[TermRatePeriodDetail, ...]


def _ql(value: date) -> ql.Date:
    return ql.Date(value.day, value.month, value.year)


def _py(value: ql.Date) -> date:
    return date(value.year(), value.month(), value.dayOfMonth())


def flat_compounded_amount(
    notional: float, rates: Tuple[float, ...], fractions: Tuple[float, ...], spread: float
) -> Tuple[float, Tuple[float, ...]]:
    """ISDA flat compounding; returns (total, per-sub-period amounts)."""
    if len(rates) != len(fractions) or not rates:
        raise ValueError("flat compounding needs one rate per sub-period")
    amounts = []
    accumulated = 0.0
    for rate, fraction in zip(rates, fractions):
        amount = notional * (rate + spread) * fraction + accumulated * rate * fraction
        amounts.append(amount)
        accumulated += amount
    return accumulated, tuple(amounts)


def compounded_rfr(
    benchmark: FallbackTermBenchmark,
    forecast_curve: ql.YieldTermStructureHandle,
    begin: ql.Date,
    end: ql.Date,
    shift_days: int,
    label: str,
) -> float:
    """Compounded RFR over the period [begin, end) observed ``shift_days`` RFR business
    days earlier (observation shift). Shared by both observation-date methods: past
    observations use the RFR's QuantLib index history (market-data fixings applied during
    pricing), later ones are projected."""
    index = benchmark.rfr_index(forecast_curve)
    coupon = ql.OvernightIndexedCoupon(
        end, 1.0, begin, end, index, 1.0, 0.0, ql.Date(), ql.Date(), ql.Actual360(), False,
        ql.RateAveraging.Compound, shift_days, 0, True, False,
    )
    coupon.setPricer(ql.CompoundingOvernightIndexedCouponPricer())
    observation_start = benchmark.period_calendar().advance(begin, -shift_days, ql.Days)
    try:
        return coupon.rate()
    except RuntimeError as exc:
        raise TermRateFixingRequired(
            f"{benchmark.name} {label} observes {benchmark.rfr} from "
            f"{observation_start.ISO()}, before the evaluation date "
            f"{ql.Settings.instance().evaluationDate.ISO()}; historical fixings are "
            f"required ({benchmark.rfr} {observation_start.ISO()} onwards): {exc}"
        ) from exc


def fallback_rate(
    benchmark: FallbackTermBenchmark,
    forecast_curve: ql.YieldTermStructureHandle,
    start: date,
) -> Tuple[float, date, date, date]:
    """Method B (reset-date fallback): (compounded RFR, IBOR period end, observation
    start, observation end) for the IBOR period starting on ``start``."""
    calendar = benchmark.period_calendar()
    begin = _ql(start)
    end = calendar.advance(begin, ql.Period(benchmark.tenor), ql.ModifiedFollowing)
    observation_start = calendar.advance(begin, -benchmark.shift_days, ql.Days)
    observation_end = calendar.advance(end, -benchmark.shift_days, ql.Days)
    rate = compounded_rfr(benchmark, forecast_curve, begin, end, benchmark.shift_days,
                          f"reset starting {start.isoformat()}")
    return rate, _py(end), _py(observation_start), _py(observation_end)


def contractual_accrual_rate(
    benchmark: FallbackTermBenchmark,
    forecast_curve: ql.YieldTermStructureHandle,
    start: date,
    end: date,
) -> Tuple[float, date, date]:
    """Method A (contractual accrual): (compounded RFR, observation start, observation
    end) over the contractual sub-period [start, end], no observation shift."""
    shift = CONTRACTUAL_ACCRUAL_SHIFT_DAYS
    calendar = benchmark.period_calendar()
    begin, finish = _ql(start), _ql(end)
    rate = compounded_rfr(benchmark, forecast_curve, begin, finish, shift,
                          f"contractual period {start.isoformat()} -> {end.isoformat()}")
    return (rate, _py(calendar.advance(begin, -shift, ql.Days)),
            _py(calendar.advance(finish, -shift, ql.Days)))


def observation_rule(spec: TermRateLegSpec) -> str:
    """Plain-language derivation of the observation dates (diagnostics)."""
    bm = spec.benchmark
    if not isinstance(bm, FallbackTermBenchmark):
        return (f"rate period = reset + {bm.spot_lag} {bm.name} calendar business days, "
                f"+{bm.tenor} Modified Following")
    calendar = bm.period_calendar().name()
    if spec.observation_method == CONTRACTUAL_ACCRUAL:
        return (f"Method A (contractual_accrual, PROVISIONAL): {bm.rfr} observed over the "
                f"contractual sub-period [start, end) as given (already adjusted Modified "
                f"Following on the accrual calendar), observation shift "
                f"{CONTRACTUAL_ACCRUAL_SHIFT_DAYS} days; reset date not used; {bm.rfr} "
                f"calendar {calendar}")
    return (f"Method B (reset_date_fallback): IBOR start = reset + {spec.fixing_days} "
            f"{spec.fixing_calendar_code} business day(s); IBOR end = start + {bm.tenor} "
            f"Modified Following ({calendar}); observation = IBOR dates - {bm.shift_days} "
            f"{calendar} business days")


def rate_period_start(spec: TermRateLegSpec, reset_date: date) -> date:
    """Start of the benchmark's rate period for a reset (a business-day lag after it)."""
    bm = spec.benchmark
    if isinstance(bm, FallbackTermBenchmark):
        calendar, lag = spec.fixing_calendar, spec.fixing_days
    else:
        calendar, lag = bm.calendar(), bm.spot_lag
    return _py(calendar.advance(_ql(reset_date), lag, ql.Days))


def projected_term_rate(
    benchmark: ProjectedTermBenchmark,
    forecast_curve: ql.YieldTermStructureHandle,
    start: date,
) -> Tuple[float, date]:
    """(simple forward rate over [start, start + tenor], end) on the forecast curve."""
    calendar = benchmark.calendar()
    begin = _ql(start)
    end = calendar.advance(begin, ql.Period(benchmark.tenor), ql.ModifiedFollowing)
    if begin < ql.Settings.instance().evaluationDate:
        raise TermRateFixingRequired(
            f"{benchmark.name} rate period starting {start.isoformat()} begins before the "
            f"evaluation date {ql.Settings.instance().evaluationDate.ISO()}; a historical "
            "fixing is required"
        )
    dc = benchmark.day_counter()
    rate = (forecast_curve.discount(begin) / forecast_curve.discount(end) - 1.0) / dc.yearFraction(
        begin, end
    )
    return rate, _py(end)


def _reset_rate(spec: TermRateLegSpec, forecast_curve, reset: TermRateReset,
                fixings: Mapping[date, float]):
    """(rate excl. adjustment, adjustment, rate_start, ibor_end, obs_start, obs_end, source)."""
    bm = spec.benchmark
    adjustment = float(bm.spread_adjustment)
    if spec.observation_method == CONTRACTUAL_ACCRUAL:
        # Method A: no IBOR period; the benchmark's reset-date fixings (defined for the
        # IBOR period) do not apply. Past observations come from the RFR fixings.
        try:
            rfr, obs_start, obs_end = contractual_accrual_rate(
                bm, forecast_curve, reset.start, reset.end)
        except TermRateFixingRequired as exc:
            raise TermRateFixingRequired(
                f"{exc}; supply {bm.rfr} daily fixings (market-data fixings.{bm.rfr}) for "
                f"the contractual period {reset.start.isoformat()} -> {reset.end.isoformat()}"
            ) from exc
        return rfr, adjustment, reset.start, None, obs_start, obs_end, "projected"
    start = rate_period_start(spec, reset.reset_date)
    fixing = fixings.get(reset.reset_date)
    evaluation = _py(ql.Settings.instance().evaluationDate)
    if fixing is not None and reset.reset_date <= evaluation:
        return float(fixing) - adjustment, adjustment, start, None, None, None, "fixing"
    try:
        if isinstance(bm, FallbackTermBenchmark):
            rfr, ibor_end, obs_start, obs_end = fallback_rate(bm, forecast_curve, start)
        else:
            rfr, ibor_end = projected_term_rate(bm, forecast_curve, start)
            obs_start, obs_end = start, ibor_end
    except TermRateFixingRequired as exc:
        need = (f"{bm.rfr} daily fixings (market-data fixings.{bm.rfr})"
                if isinstance(bm, FallbackTermBenchmark)
                else f"the {bm.name} fixing (market-data fixings.{bm.name})")
        raise TermRateFixingRequired(
            f"{exc}; supply {need} for reset {reset.reset_date.isoformat()}"
        ) from exc
    return rfr, adjustment, start, ibor_end, obs_start, obs_end, "projected"


def build_term_rate_floating_leg(
    terms: IRSLegTerms,
    contractual_schedule: QuantLibLegSchedule,
    spec: TermRateLegSpec,
    forecast_curve: ql.YieldTermStructureHandle,
    fixings: Optional[Mapping[date, float]] = None,
) -> QuantLibTermRateFloatingLeg:
    """Build the leg from the explicit resets; inputs are validated at parse time.
    ``fixings`` (reset date -> benchmark rate incl. any spread adjustment, decimal) are
    used for resets on or before the evaluation date."""
    fixings = fixings or {}
    if spec.observation_method not in OBSERVATION_METHODS:
        raise UnsupportedTermRateLeg(
            f"observation method {spec.observation_method!r}; supported: "
            f"{sorted(OBSERVATION_METHODS)}")
    if (spec.observation_method == CONTRACTUAL_ACCRUAL
            and not isinstance(spec.benchmark, FallbackTermBenchmark)):
        raise UnsupportedTermRateLeg(
            f"observation method {CONTRACTUAL_ACCRUAL!r} applies to RFR-fallback benchmarks "
            f"only, not {spec.benchmark.name}")
    rule = observation_rule(spec)
    if terms.floating_leverage != 1:
        raise UnsupportedTermRateLeg("term-rate legs support leverage 1 only")
    periods = contractual_schedule.periods
    if len(spec.resets) != len(periods):
        raise UnsupportedTermRateLeg(
            f"{len(spec.resets)} reset lists for {len(periods)} payment periods"
        )
    day_counter = _day_counter(terms.day_count)
    spread = float(terms.floating_spread_rate)
    coupons, details = [], []
    for period, resets in zip(periods, spec.resets):
        notional = float(period.notional.amount)
        rates, fractions, partial = [], [], []
        for reset in resets:
            rfr, adjustment, rate_start, ibor_end, obs_start, obs_end, source = _reset_rate(
                spec, forecast_curve, reset, fixings
            )
            rates.append(rfr + adjustment)
            fractions.append(day_counter.yearFraction(_ql(reset.start), _ql(reset.end)))
            partial.append((reset, rate_start, ibor_end, obs_start, obs_end, rfr, adjustment,
                            source))
        total, amounts = flat_compounded_amount(notional, tuple(rates), tuple(fractions), spread)
        start, end = _ql(period.accrual_start), _ql(period.accrual_end)
        period_fraction = day_counter.yearFraction(start, end)
        equivalent = total / (notional * period_fraction)
        coupons.append(
            ql.FixedRateCoupon(
                _ql(period.payment_date), notional, equivalent, day_counter, start, end
            )
        )
        details.append(
            TermRatePeriodDetail(
                resets=tuple(
                    ResetDetail(
                        reset_date=r.reset_date, start=r.start, end=r.end,
                        rate_start=rate_start, ibor_period_end=ibor_end,
                        observation_start=obs_start, observation_end=obs_end,
                        rfr_compounded_rate=rfr, spread_adjustment=adjustment, reset_rate=rate,
                        accrual_fraction=fraction, amount=amount, source=source,
                        observation_method=spec.observation_method, observation_rule=rule,
                    )
                    for (r, rate_start, ibor_end, obs_start, obs_end, rfr, adjustment, source),
                    rate, fraction, amount in zip(partial, rates, fractions, amounts)
                ),
                equivalent_rate=equivalent,
            )
        )
    quantlib_leg = ql.Leg(coupons)
    return QuantLibTermRateFloatingLeg(
        quantlib_leg=quantlib_leg,
        coupons=tuple(ql.as_fixed_rate_coupon(c) for c in quantlib_leg),
        index=None,
        terms=terms,
        contractual_schedule=contractual_schedule,
        observation_settings=None,
        observation_schedule=None,
        spec=spec,
        period_details=tuple(details),
    )
