"""
Interest Rate Swap instrument wrapper.

Covers:
- Fixed vs Float IRS
- Basis swaps (placeholder)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Optional

import QuantLib as ql

from core.enums.definitions import (
    AssetClass,
    Currency,
    DayCountConvention,
    Frequency,
    InstrumentType,
    TradeDirection,
)
from core.exceptions.errors import InstrumentBuildError
from core.interfaces.base import BaseInstrument, MarketEnvironment
from core.types.value_objects import PricingDate, TradeId
from registry import instrument_registry


@instrument_registry.register_decorator(InstrumentType.IRS.value)
@dataclass
class InterestRateSwap(BaseInstrument):
    """Fixed vs Float Interest Rate Swap."""

    _trade_id: str
    notional: float
    _currency: str = "USD"
    start_date: date = None
    end_date: date = None
    fixed_rate: float = 0.0
    fixed_leg_frequency: str = "semiannual"
    float_leg_frequency: str = "quarterly"
    fixed_day_count: str = "30/360"
    float_day_count: str = "ACT/360"
    direction: str = "pay"  # pay = pay fixed, receive = receive fixed
    float_index_tenor: str = "3M"
    float_index: str = "IBOR"
    float_spread: float = 0.0
    leverage: float = 1.0
    lookback_days: int = 0
    rate_cutoff_days: int = 0
    reset_type: str = ""
    compounding: str = ""
    business_day_convention: str = "Modified Following"
    schedule_generation: str = "Forward"
    principal_exchange: str = "Never"
    amortization: Optional[Dict[str, Any]] = None

    def trade_id(self) -> TradeId:
        return TradeId(self._trade_id)

    def asset_class(self) -> AssetClass:
        return AssetClass.RATES

    def instrument_type(self) -> InstrumentType:
        return InstrumentType.IRS

    def currency(self) -> str:
        return self._currency

    def maturity(self) -> date:
        return self.end_date

    def build(self, market_env: MarketEnvironment) -> ql.Instrument:
        try:
            market_env.set_evaluation_date()

            if self.float_index.strip().upper() in {"SOFR", "SOFRRATE"}:
                return self._build_sofr_ois(market_env)

            ql_start = ql.Date(self.start_date.day, self.start_date.month, self.start_date.year)
            ql_end = ql.Date(self.end_date.day, self.end_date.month, self.end_date.year)

            # Calendar & conventions
            calendar = self._get_calendar()
            bdc = ql.ModifiedFollowing

            # Frequencies
            freq_map = {
                "annual": ql.Annual, "semiannual": ql.Semiannual,
                "quarterly": ql.Quarterly, "monthly": ql.Monthly,
            }
            fixed_freq = freq_map.get(self.fixed_leg_frequency, ql.Semiannual)
            float_freq = freq_map.get(self.float_leg_frequency, ql.Quarterly)

            # Day counts
            dc_map = {
                "ACT/360": ql.Actual360(), "ACT/365": ql.Actual365Fixed(),
                "30/360": ql.Thirty360(ql.Thirty360.BondBasis),
                "ACT/ACT": ql.ActualActual(ql.ActualActual.ISDA),
            }
            fixed_dc = dc_map.get(self.fixed_day_count, ql.Thirty360(ql.Thirty360.BondBasis))
            float_dc = dc_map.get(self.float_day_count, ql.Actual360())

            # Schedules
            fixed_schedule = ql.Schedule(
                ql_start, ql_end, ql.Period(fixed_freq),
                calendar, bdc, bdc, ql.DateGeneration.Forward, False,
            )
            float_schedule = ql.Schedule(
                ql_start, ql_end, ql.Period(float_freq),
                calendar, bdc, bdc, ql.DateGeneration.Forward, False,
            )

            # Float index
            index = self._get_ibor_index(market_env)

            # Add past fixings — QuantLib requires fixings for all past
            # floating leg reset dates. Use the flat rate from the curve.
            eval_date = ql.Settings.instance().evaluationDate
            flat_rate = market_env.discount_curves.get(
                self._currency,
                list(market_env.discount_curves.values())[0] if market_env.discount_curves else None,
            )
            if flat_rate:
                fixing_rate = flat_rate.zeroRate(
                    0.25, ql.Continuous, ql.Annual
                ).rate()
            else:
                fixing_rate = self.fixed_rate

            # Add fixings for all past dates
            for i in range(len(float_schedule) - 1):
                reset_date = index.fixingDate(float_schedule[i])
                if reset_date < eval_date:
                    try:
                        index.addFixing(reset_date, fixing_rate)
                    except RuntimeError:
                        pass  # Fixing already added

            # Swap type
            swap_type = ql.VanillaSwap.Payer if self.direction == "pay" else ql.VanillaSwap.Receiver

            swap = ql.VanillaSwap(
                swap_type,
                self.notional,
                fixed_schedule,
                self.fixed_rate,
                fixed_dc,
                float_schedule,
                index,
                0.0,  # spread
                float_dc,
            )

            return swap

        except Exception as e:
            raise InstrumentBuildError(f"Failed to build IRS {self._trade_id}: {e}") from e

    def _build_sofr_ois(self, market_env: MarketEnvironment) -> ql.OvernightIndexedSwap:
        """Build a SOFR OIS while leaving the existing IBOR path unchanged."""
        if self.leverage != 1.0:
            raise ValueError("SOFR OIS construction currently supports unit leverage only")

        freq_map = {
            "annual": ql.Annual,
            "semiannual": ql.Semiannual,
            "quarterly": ql.Quarterly,
            "monthly": ql.Monthly,
        }
        fixed_frequency = freq_map.get(self.fixed_leg_frequency.lower())
        float_frequency = freq_map.get(self.float_leg_frequency.lower())
        if fixed_frequency is None or float_frequency is None:
            raise ValueError("Unsupported SOFR OIS payment frequency")
        if fixed_frequency != float_frequency:
            raise ValueError("SOFR OIS fixed and floating payment frequencies must match")

        day_count_map = {
            "ACT/360": ql.Actual360(),
            "ACT/365": ql.Actual365Fixed(),
            "30/360": ql.Thirty360(ql.Thirty360.BondBasis),
            "ACT/ACT": ql.ActualActual(ql.ActualActual.ISDA),
        }
        fixed_day_count = day_count_map.get(self.fixed_day_count.upper())
        if fixed_day_count is None:
            raise ValueError(f"Unsupported fixed-leg day count: {self.fixed_day_count}")
        if self.float_day_count.upper() != "ACT/360":
            raise ValueError("SOFR floating-leg day count is determined by the SOFR index (ACT/360)")

        calendar = self._get_sofr_calendar()
        convention = self._get_business_day_convention()
        generation = self._get_date_generation()
        ql_start = ql.Date(self.start_date.day, self.start_date.month, self.start_date.year)
        ql_end = ql.Date(self.end_date.day, self.end_date.month, self.end_date.year)
        amortization_schedule = (
            self.amortization.get("schedule") if self.amortization else None
        )
        if amortization_schedule:
            notionals = [float(period["notional"]) for period in amortization_schedule]

            # Amortization schedule boundaries are explicit instrument inputs.
            # Use them as the accrual DateVector so the effective date can stay
            # unadjusted while intermediate and payment dates follow the
            # supplied schedule. Payment-date adjustment is applied separately
            # by the OIS leg using `convention` and `calendar` below.
            accrual_dates = [
                self._to_ql_date(amortization_schedule[0]["period_start"])
            ] + [
                self._to_ql_date(period["period_end"])
                for period in amortization_schedule
            ]
            if accrual_dates[0] != ql_start or accrual_dates[-1] != ql_end:
                raise ValueError(
                    "SOFR amortization schedule must start at the effective date "
                    "and end at the maturity date"
                )
            if any(
                accrual_dates[i] != self._to_ql_date(
                    amortization_schedule[i]["period_start"]
                )
                for i in range(1, len(amortization_schedule))
            ):
                raise ValueError("SOFR amortization schedule periods must be contiguous")
            if any(
                accrual_dates[i] >= accrual_dates[i + 1]
                for i in range(len(accrual_dates) - 1)
            ):
                raise ValueError("SOFR accrual schedule dates must be increasing")

            schedule = ql.Schedule(
                accrual_dates,
                calendar,
                ql.Unadjusted,
                convention,
                ql.Period(fixed_frequency),
                generation,
                False,
            )
        else:
            schedule = ql.Schedule(
                ql_start,
                ql_end,
                ql.Period(fixed_frequency),
                calendar,
                convention,
                convention,
                generation,
                False,
            )
            notionals = [self.notional] * (len(schedule) - 1)

        periods = len(schedule) - 1
        if len(notionals) != periods:
            raise ValueError(
                f"SOFR OIS needs one notional per coupon period ({periods}); "
                f"received {len(notionals)}"
            )

        forecast = market_env.forecast_curves.get(self._currency)
        if forecast is None:
            forecast = market_env.discount_curves.get(self._currency)
        if forecast is None:
            forecast = ql.YieldTermStructureHandle()
        index = ql.Sofr(forecast)

        direction = self.direction.strip().lower()
        swap_type = (
            ql.OvernightIndexedSwap.Payer
            if direction in {"pay", "payer", "pay_fixed"}
            else ql.OvernightIndexedSwap.Receiver
        )
        averaging = self._get_averaging_method()

        # The QuantLib OIS constructor creates overnight coupons in arrears.
        # Its standard OvernightLeg also keeps the spread outside daily
        # compounding (compoundSpreadDaily=False).
        return ql.OvernightIndexedSwap(
            swap_type,
            notionals,
            schedule,
            self.fixed_rate,
            fixed_day_count,
            index,
            self.float_spread,
            0,
            convention,
            calendar,
            False,
            averaging,
            self.lookback_days,
            self.rate_cutoff_days,
            False,
        )

    def _get_business_day_convention(self) -> ql.BusinessDayConvention:
        convention = self.business_day_convention.strip().lower().replace("_", " ")
        convention_map = {
            "following": ql.Following,
            "modified following": ql.ModifiedFollowing,
            "mod roll": ql.ModifiedFollowing,
            "preceding": ql.Preceding,
            "modified preceding": ql.ModifiedPreceding,
        }
        if convention not in convention_map:
            raise ValueError(f"Unsupported business-day convention: {self.business_day_convention}")
        return convention_map[convention]

    def _get_sofr_calendar(self) -> ql.Calendar:
        """Return SOFR market calendar without changing the legacy IBOR path."""
        if self._currency == "USD":
            return ql.UnitedStates(ql.UnitedStates.FederalReserve)
        return self._get_calendar()

    @staticmethod
    def _to_ql_date(value: Any) -> ql.Date:
        """Convert an amortization boundary represented as date or ISO string."""
        if isinstance(value, ql.Date):
            return value
        parsed = value if isinstance(value, date) else date.fromisoformat(str(value))
        return ql.Date(parsed.day, parsed.month, parsed.year)

    def _get_date_generation(self) -> ql.DateGeneration.Rule:
        generation = self.schedule_generation.strip().lower()
        generation_map = {
            "forward": ql.DateGeneration.Forward,
            "backward": ql.DateGeneration.Backward,
        }
        if generation not in generation_map:
            raise ValueError(f"Unsupported schedule generation rule: {self.schedule_generation}")
        return generation_map[generation]

    def _get_averaging_method(self) -> ql.RateAveraging.Type:
        compounding = self.compounding.strip().lower()
        if compounding in {"excludesprd", "compound", "compounded"}:
            return ql.RateAveraging.Compound
        if compounding == "simple":
            return ql.RateAveraging.Simple
        raise ValueError(f"Unsupported SOFR compounding convention: {self.compounding}")

    def _get_calendar(self) -> ql.Calendar:
        cal_map = {
            "USD": ql.UnitedStates(ql.UnitedStates.GovernmentBond),
            "EUR": ql.TARGET(),
            "GBP": ql.UnitedKingdom(),
            "JPY": ql.Japan(),
        }
        return cal_map.get(self._currency, ql.NullCalendar())

    def _get_ibor_index(self, market_env: MarketEnvironment) -> ql.IborIndex:
        """Get IBOR index with forwarding curve."""
        forecast = market_env.forecast_curves.get(
            self._currency,
            market_env.discount_curves.get(self._currency),
        )

        tenor_map = {"1M": ql.Period(1, ql.Months), "3M": ql.Period(3, ql.Months), "6M": ql.Period(6, ql.Months)}
        tenor = tenor_map.get(self.float_index_tenor, ql.Period(3, ql.Months))

        if self._currency == "USD":
            return ql.USDLibor(tenor, forecast)
        elif self._currency == "EUR":
            return ql.Euribor(tenor, forecast)
        elif self._currency == "GBP":
            return ql.GBPLibor(tenor, forecast)
        else:
            return ql.USDLibor(tenor, forecast)

    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "notional": self.notional,
            "fixed_rate": self.fixed_rate,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "direction": self.direction,
            "float_index": self.float_index,
            "float_index_tenor": self.float_index_tenor,
            "float_spread": self.float_spread,
            "leverage": self.leverage,
            "lookback_days": self.lookback_days,
            "rate_cutoff_days": self.rate_cutoff_days,
            "reset_type": self.reset_type,
            "compounding": self.compounding,
            "business_day_convention": self.business_day_convention,
            "schedule_generation": self.schedule_generation,
            "principal_exchange": self.principal_exchange,
            "amortization": self.amortization,
        })
        return base

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> InterestRateSwap:
        """Deserialize from dictionary."""
        def parse_date(d):
            if d is None:
                return None
            if isinstance(d, date):
                return d
            return date.fromisoformat(str(d))

        return cls(
            _trade_id=data.get("trade_id", "IRS-001"),
            notional=float(data.get("notional", 1_000_000)),
            _currency=data.get("currency", "USD"),
            start_date=parse_date(data.get("start_date")),
            end_date=parse_date(data.get("end_date")),
            fixed_rate=float(data.get("fixed_rate", 0.0)),
            fixed_leg_frequency=data.get("fixed_leg_frequency", "semiannual"),
            float_leg_frequency=data.get("float_leg_frequency", "quarterly"),
            fixed_day_count=data.get("fixed_day_count", "30/360"),
            float_day_count=data.get("float_day_count", "ACT/360"),
            direction=data.get("direction", "pay"),
            float_index_tenor=data.get("float_index_tenor", "3M"),
            float_index=data.get("float_index", "IBOR"),
            float_spread=float(data.get("float_spread", 0.0)),
            leverage=float(data.get("leverage", 1.0)),
            lookback_days=int(data.get("lookback_days", 0)),
            rate_cutoff_days=int(data.get("rate_cutoff_days", 0)),
            reset_type=data.get("reset_type", ""),
            compounding=data.get("compounding", ""),
            business_day_convention=data.get(
                "business_day_convention", "Modified Following"
            ),
            schedule_generation=data.get("schedule_generation", "Forward"),
            principal_exchange=data.get("principal_exchange", "Never"),
            amortization=data.get("amortization"),
        )
