"""
Exercise builders — factory for constructing QuantLib exercise objects.

Handles:
- European: single exercise date at expiry
- American: continuous exercise from start to expiry
- Bermudan: discrete set of exercise dates

Usage:
    from instruments.common.exercise import ExerciseBuilder

    ex = ExerciseBuilder.european(expiry=date(2026, 6, 15))
    ex = ExerciseBuilder.american(start=date(2025, 1, 15), expiry=date(2026, 6, 15))
    ex = ExerciseBuilder.bermudan(dates=[date(2025,6,15), date(2025,12,15), date(2026,6,15)])
    ex = ExerciseBuilder.bermudan_from_schedule(
             start=date(2025,1,15), expiry=date(2026,6,15), frequency="quarterly"
         )
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional, Union

import QuantLib as ql

from core.enums.definitions import ExerciseType


class ExerciseBuilder:
    """
    Factory for QuantLib exercise objects.
    
    All methods are static. Accepts Python date objects and converts
    to QuantLib dates internally.
    """

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

    @staticmethod
    def _to_ql_date(d: date) -> ql.Date:
        """Convert Python date to QuantLib Date."""
        return ql.Date(d.day, d.month, d.year)

    @staticmethod
    def _to_ql_dates(dates: List[date]) -> List[ql.Date]:
        """Convert list of Python dates to QuantLib Dates."""
        return [ExerciseBuilder._to_ql_date(d) for d in sorted(dates)]

    # -------------------------------------------------------------------
    # Exercise types
    # -------------------------------------------------------------------

    @staticmethod
    def european(expiry: date) -> ql.EuropeanExercise:
        """
        European exercise — can only exercise at expiry.

        Args:
            expiry: The single exercise date.
        """
        return ql.EuropeanExercise(ExerciseBuilder._to_ql_date(expiry))

    @staticmethod
    def american(
        expiry: date,
        start: Optional[date] = None,
    ) -> ql.AmericanExercise:
        """
        American exercise — can exercise any time from start to expiry.

        Args:
            expiry: Last possible exercise date.
            start: First possible exercise date. If None, uses today.
        """
        ql_expiry = ExerciseBuilder._to_ql_date(expiry)
        if start is not None:
            ql_start = ExerciseBuilder._to_ql_date(start)
            return ql.AmericanExercise(ql_start, ql_expiry)
        else:
            return ql.AmericanExercise(ql_expiry)

    @staticmethod
    def bermudan(dates: List[date]) -> ql.BermudanExercise:
        """
        Bermudan exercise — can exercise on specific discrete dates.

        Args:
            dates: List of allowed exercise dates (will be sorted).
                   Must have at least 2 dates.

        Raises:
            ValueError: If fewer than 2 dates provided.
        """
        if len(dates) < 2:
            raise ValueError(
                f"Bermudan exercise requires at least 2 dates, got {len(dates)}. "
                f"Use european() for single-date exercise."
            )
        ql_dates = ExerciseBuilder._to_ql_dates(dates)
        return ql.BermudanExercise(ql_dates)

    @staticmethod
    def bermudan_from_schedule(
        start: date,
        expiry: date,
        frequency: str = "quarterly",
        calendar: Optional[ql.Calendar] = None,
    ) -> ql.BermudanExercise:
        """
        Bermudan exercise from a regular schedule.

        Generates exercise dates at regular intervals between start and expiry.

        Args:
            start: First possible exercise date.
            expiry: Last possible exercise date.
            frequency: "monthly", "quarterly", "semiannual", "annual"
            calendar: QuantLib calendar for date adjustment. Default: NullCalendar.

        Example:
            # Quarterly exercise dates for 2 years
            ex = ExerciseBuilder.bermudan_from_schedule(
                start=date(2025, 3, 15),
                expiry=date(2027, 3, 15),
                frequency="quarterly",
            )
            # Generates: 2025-03-15, 2025-06-15, 2025-09-15, ..., 2027-03-15
        """
        if calendar is None:
            calendar = ql.NullCalendar()

        freq_map = {
            "monthly": ql.Monthly,
            "quarterly": ql.Quarterly,
            "semiannual": ql.Semiannual,
            "annual": ql.Annual,
        }
        ql_freq = freq_map.get(frequency.lower())
        if ql_freq is None:
            raise ValueError(
                f"Unknown frequency: {frequency}. "
                f"Use: {list(freq_map.keys())}"
            )

        ql_start = ExerciseBuilder._to_ql_date(start)
        ql_expiry = ExerciseBuilder._to_ql_date(expiry)

        schedule = ql.Schedule(
            ql_start,
            ql_expiry,
            ql.Period(ql_freq),
            calendar,
            ql.ModifiedFollowing,
            ql.ModifiedFollowing,
            ql.DateGeneration.Forward,
            False,
        )

        # Extract dates from schedule (skip first if it's the start date)
        exercise_dates = list(schedule)[1:]  # skip the effective date
        if len(exercise_dates) < 2:
            raise ValueError(
                f"Schedule generated fewer than 2 exercise dates. "
                f"Check start/expiry/frequency: {start} to {expiry}, {frequency}."
            )

        return ql.BermudanExercise(exercise_dates)

    # -------------------------------------------------------------------
    # Convenience: from enum + params
    # -------------------------------------------------------------------

    @staticmethod
    def build(
        exercise_type: Union[ExerciseType, str],
        expiry: date,
        start: Optional[date] = None,
        bermudan_dates: Optional[List[date]] = None,
        bermudan_frequency: Optional[str] = None,
        calendar: Optional[ql.Calendar] = None,
    ) -> ql.Exercise:
        """
        Universal builder — dispatches to the right exercise type.

        Args:
            exercise_type: "european", "american", "bermudan" or ExerciseType enum
            expiry: Expiry / last exercise date
            start: First exercise date (American/Bermudan)
            bermudan_dates: Explicit list of exercise dates (Bermudan)
            bermudan_frequency: Generate dates from schedule (Bermudan)
            calendar: For schedule generation

        Examples:
            ExerciseBuilder.build("european", expiry=date(2026, 6, 15))
            ExerciseBuilder.build("american", expiry=date(2026, 6, 15), start=date(2025, 1, 1))
            ExerciseBuilder.build("bermudan", expiry=date(2026, 6, 15),
                                  bermudan_dates=[date(2025,6,15), date(2025,12,15), date(2026,6,15)])
            ExerciseBuilder.build("bermudan", expiry=date(2027, 3, 15),
                                  start=date(2025, 3, 15), bermudan_frequency="quarterly")
        """
        # Normalize to string
        if isinstance(exercise_type, ExerciseType):
            ex_str = exercise_type.value
        else:
            ex_str = exercise_type.strip().lower()

        if ex_str == "european":
            return ExerciseBuilder.european(expiry)

        elif ex_str == "american":
            return ExerciseBuilder.american(expiry, start)

        elif ex_str == "bermudan":
            if bermudan_dates:
                return ExerciseBuilder.bermudan(bermudan_dates)
            elif bermudan_frequency and start:
                return ExerciseBuilder.bermudan_from_schedule(
                    start, expiry, bermudan_frequency, calendar
                )
            else:
                raise ValueError(
                    "Bermudan exercise requires either 'bermudan_dates' (explicit list) "
                    "or 'start' + 'bermudan_frequency' (schedule-based)."
                )

        else:
            raise ValueError(
                f"Unknown exercise type: {ex_str}. "
                f"Use: 'european', 'american', 'bermudan'."
            )

    # -------------------------------------------------------------------
    # Convenience: from dict (API/config-driven)
    # -------------------------------------------------------------------

    @staticmethod
    def from_dict(config: dict) -> ql.Exercise:
        """
        Build exercise from a configuration dictionary.

        Examples:
            {"type": "european", "expiry": "2026-06-15"}
            {"type": "american", "expiry": "2026-06-15", "start": "2025-01-15"}
            {"type": "bermudan", "expiry": "2027-03-15", "start": "2025-03-15", "frequency": "quarterly"}
            {"type": "bermudan", "dates": ["2025-06-15", "2025-12-15", "2026-06-15"]}
        """
        from datetime import date as date_type

        def parse_date(d) -> date_type:
            if isinstance(d, date_type):
                return d
            return date_type.fromisoformat(str(d))

        ex_type = config.get("type", "european")
        expiry = parse_date(config["expiry"])
        start = parse_date(config["start"]) if "start" in config else None
        bermudan_dates = [parse_date(d) for d in config["dates"]] if "dates" in config else None
        frequency = config.get("frequency")

        return ExerciseBuilder.build(
            exercise_type=ex_type,
            expiry=expiry,
            start=start,
            bermudan_dates=bermudan_dates,
            bermudan_frequency=frequency,
        )
