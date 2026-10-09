"""Domain types for the fresh IRS implementation."""

from instruments.rates.irs.domain import (
    IRSLegTerms,
    IRSLegKind,
    IRSTrade,
    ObservationConventions,
    PrincipalRepayment,
)
from instruments.rates.irs.schedule import (
    CouponPeriod,
    LegSchedule,
    RepaymentTreatment,
    ScheduleDirection,
    ScheduleGeneration,
    generate_leg_schedule,
)
from instruments.rates.irs.quantlib_schedule import (
    QuantLibIRSSchedules,
    QuantLibLegSchedule,
    translate_irs_schedules,
    translate_leg_schedule,
)
from instruments.rates.irs.fixed_leg import QuantLibFixedLeg, build_fixed_leg
from instruments.rates.irs.floating_leg import (
    CouponObservationDates,
    FloatingObservationMapping,
    FloatingObservationSchedule,
    QuantLibFloatingLeg,
    UnsupportedBenchmarkMapping,
    build_floating_index,
    build_floating_leg,
)

__all__ = [
    "IRSLegTerms",
    "IRSLegKind",
    "IRSTrade",
    "ObservationConventions",
    "PrincipalRepayment",
    "CouponPeriod",
    "LegSchedule",
    "RepaymentTreatment",
    "ScheduleDirection",
    "ScheduleGeneration",
    "generate_leg_schedule",
    "QuantLibIRSSchedules",
    "QuantLibLegSchedule",
    "translate_irs_schedules",
    "translate_leg_schedule",
    "QuantLibFixedLeg",
    "build_fixed_leg",
    "FloatingObservationMapping",
    "CouponObservationDates",
    "FloatingObservationSchedule",
    "QuantLibFloatingLeg",
    "UnsupportedBenchmarkMapping",
    "build_floating_index",
    "build_floating_leg",
]
