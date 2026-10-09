"""Market-data snapshot for the fresh IRS: parse a document and resolve it to a
``MarketEnvironment``.

A snapshot is plain data (observations, explicit conventions and curve
assignments) for one valuation date. It holds no QuantLib objects; curves are
built from it with the production ``build_zero_curve``. This module does not read
files: callers pass the decoded JSON document.

Document (every key required unless stated; unknown keys are rejected)::

    {
      "schema_version": 1,
      "valuation_date": "2026-03-31",
      "provenance": "free text",
      "curves": {
        "<curve id>": {
          "currency": "USD", "benchmark": "SOFR", "reference_date": "2026-03-31",
          "conventions": {
            "calendar": "US-SOFR", "spot_lag_days": 2,
            "business_day_convention": "modified_following", "end_of_month": false,
            "day_count": "ACT/365F", "compounding": "continuous",
            "interpolation": "linear_zero", "front_extrapolation": "flat_first_zero",
            "allow_extrapolation": false, "discount_factor_check_tolerance": 1e-6
          },
          "observations": [
            {"tenor": "1W", "zero_rate": 0.0370182, "discount_factor": 0.999088}
          ]
        }
      },
      "assignments": {"USD": {"discount": "<curve id>", "forecast": "<curve id>"}}
    }

* ``schema_version`` must be the integer 1 (not ``true`` or ``1.0``).
* ``discount_factor`` in an observation is optional; when present it must be a
  number (``null`` is rejected) and is only a consistency check on the derived
  pillar date (see ``build_zero_curve``).
* Each currency may be assigned once; keys that differ only in case (``"usd"``
  and ``"USD"``) are rejected.
* Discount and forecast assignments may name different curves.
* Every curve's reference date must equal the valuation date.
* A currency without an assignment has no curves: nothing falls back to another
  currency's curve or to flat test curves.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Mapping, Tuple

import QuantLib as ql

from core.enums.definitions import BusinessDayConvention
from core.interfaces.base import MarketEnvironment
from core.types.value_objects import PricingDate
from market.curves.irs_zero_curve import (
    QuantLibZeroCurve,
    ZeroCurveConventions,
    ZeroCurveMarketData,
    ZeroCurveObservation,
    build_zero_curve,
)

SCHEMA_VERSION = 1


class InvalidMarketData(ValueError):
    """The market-data document is missing, malformed or unsupported."""


class MissingCurveAssignment(InvalidMarketData):
    """No discount/forecast curve assignment exists for a requested currency."""


# Optima calendar names (strict; anything else is rejected).
_CALENDARS = {
    "US-SOFR": lambda: ql.UnitedStates(ql.UnitedStates.SOFR),
    "US-FED": lambda: ql.UnitedStates(ql.UnitedStates.FederalReserve),
}
_DAY_COUNTS = {
    "ACT/365F": ql.Actual365Fixed,
    "ACT/360": ql.Actual360,
}
_COMPOUNDING = {"continuous": ql.Continuous}
_BUSINESS_DAY_CONVENTIONS = {
    BusinessDayConvention.FOLLOWING.value: ql.Following,
    BusinessDayConvention.MODIFIED_FOLLOWING.value: ql.ModifiedFollowing,
    BusinessDayConvention.PRECEDING.value: ql.Preceding,
    BusinessDayConvention.MODIFIED_PRECEDING.value: ql.ModifiedPreceding,
    BusinessDayConvention.UNADJUSTED.value: ql.Unadjusted,
}

_TOP_KEYS = frozenset({"schema_version", "valuation_date", "provenance", "curves", "assignments"})
_CURVE_KEYS = frozenset({"currency", "benchmark", "reference_date", "conventions", "observations"})
_CONVENTION_KEYS = frozenset(
    {
        "calendar",
        "spot_lag_days",
        "business_day_convention",
        "end_of_month",
        "day_count",
        "compounding",
        "interpolation",
        "front_extrapolation",
        "allow_extrapolation",
        "discount_factor_check_tolerance",
    }
)
_OBSERVATION_KEYS = frozenset({"tenor", "zero_rate"})
_OBSERVATION_OPTIONAL_KEYS = frozenset({"discount_factor"})
_ASSIGNMENT_KEYS = frozenset({"discount", "forecast"})


# --- parsing helpers -----------------------------------------------------------------


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidMarketData(f"{path} must be an object")
    return value


def _keys(value: Mapping[str, Any], required: frozenset, path: str,
          optional: frozenset = frozenset()) -> None:
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required - optional)
    if missing:
        raise InvalidMarketData(f"{path}: missing required keys {missing}")
    if unknown:
        raise InvalidMarketData(f"{path}: unknown keys {unknown}")


def _date(value: Any, path: str) -> date:
    if not isinstance(value, str):
        raise InvalidMarketData(f"{path}: expected an ISO date string, got {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidMarketData(f"{path}: invalid ISO date {value!r}") from exc


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidMarketData(f"{path}: must be a non-empty string")
    return value.strip()


def _choice(value: Any, choices: Mapping[str, Any], path: str) -> Any:
    if not isinstance(value, str) or value not in choices:
        raise InvalidMarketData(f"{path}: {value!r} is not one of {sorted(choices)}")
    return choices[value]


def _bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise InvalidMarketData(f"{path}: must be true or false, got {value!r}")
    return value


def _int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidMarketData(f"{path}: must be an integer, got {value!r}")
    return value


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidMarketData(f"{path}: must be a number, got {value!r}")
    if not math.isfinite(value):
        raise InvalidMarketData(f"{path}: must be finite")
    return value


# --- typed snapshot ---------------------------------------------------------------------


@dataclass(frozen=True)
class CurveSpec:
    """One curve's observations and conventions, ready for ``build_zero_curve``."""

    curve_id: str
    market_data: ZeroCurveMarketData
    conventions: ZeroCurveConventions


@dataclass(frozen=True)
class CurveAssignment:
    currency: str
    discount_curve_id: str
    forecast_curve_id: str


@dataclass(frozen=True)
class MarketSnapshot:
    valuation_date: date
    provenance: str
    curves: Mapping[str, CurveSpec]
    assignments: Mapping[str, CurveAssignment]

    def assignment(self, currency: str) -> CurveAssignment:
        try:
            return self.assignments[currency]
        except KeyError:
            raise MissingCurveAssignment(
                f"market data has no curve assignment for {currency}; "
                f"assigned currencies: {sorted(self.assignments)}"
            ) from None


def _conventions(value: Any, path: str) -> ZeroCurveConventions:
    row = _mapping(value, path)
    _keys(row, _CONVENTION_KEYS, path)
    try:
        return ZeroCurveConventions(
            calendar=_choice(row["calendar"], _CALENDARS, f"{path}.calendar")(),
            spot_lag_days=_int(row["spot_lag_days"], f"{path}.spot_lag_days"),
            business_day_convention=_choice(
                row["business_day_convention"],
                _BUSINESS_DAY_CONVENTIONS,
                f"{path}.business_day_convention",
            ),
            end_of_month=_bool(row["end_of_month"], f"{path}.end_of_month"),
            day_counter=_choice(row["day_count"], _DAY_COUNTS, f"{path}.day_count")(),
            compounding=_choice(row["compounding"], _COMPOUNDING, f"{path}.compounding"),
            interpolation=_string(row["interpolation"], f"{path}.interpolation"),
            front_extrapolation=_string(
                row["front_extrapolation"], f"{path}.front_extrapolation"
            ),
            allow_extrapolation=_bool(
                row["allow_extrapolation"], f"{path}.allow_extrapolation"
            ),
            discount_factor_tolerance=_number(
                row["discount_factor_check_tolerance"],
                f"{path}.discount_factor_check_tolerance",
            ),
        )
    except InvalidMarketData:
        raise
    except (ValueError, TypeError) as exc:  # rejected by ZeroCurveConventions
        raise InvalidMarketData(f"{path}: {exc}") from exc


def _observations(value: Any, path: str) -> Tuple[ZeroCurveObservation, ...]:
    if not isinstance(value, list) or not value:
        raise InvalidMarketData(f"{path}: must be a non-empty list")
    observations = []
    for i, raw in enumerate(value):
        item_path = f"{path}[{i}]"
        row = _mapping(raw, item_path)
        _keys(row, _OBSERVATION_KEYS, item_path, _OBSERVATION_OPTIONAL_KEYS)
        # The key is optional; when present its value must be a valid number
        # (an explicit null is rejected, not read as "absent").
        discount_factor = (
            _number(row["discount_factor"], f"{item_path}.discount_factor")
            if "discount_factor" in row
            else None
        )
        try:
            observations.append(
                ZeroCurveObservation(
                    tenor=_string(row["tenor"], f"{item_path}.tenor"),
                    zero_rate=_number(row["zero_rate"], f"{item_path}.zero_rate"),
                    discount_factor=discount_factor,
                )
            )
        except InvalidMarketData:
            raise
        except ValueError as exc:  # rejected by ZeroCurveObservation
            raise InvalidMarketData(f"{item_path}: {exc}") from exc
    return tuple(observations)


def parse_market_snapshot(document: Any) -> MarketSnapshot:
    """Validate a market-data document and return the typed snapshot."""
    top = _mapping(document, "market data")
    _keys(top, _TOP_KEYS, "market data")
    schema_version = top["schema_version"]
    # bool is an int subclass and 1.0 == 1, so check the type explicitly.
    if type(schema_version) is not int or schema_version != SCHEMA_VERSION:
        raise InvalidMarketData(
            f"market data: unsupported schema_version {top['schema_version']!r}; "
            f"expected {SCHEMA_VERSION}"
        )
    valuation_date = _date(top["valuation_date"], "valuation_date")
    provenance = _string(top["provenance"], "provenance")

    curves_doc = _mapping(top["curves"], "curves")
    if not curves_doc:
        raise InvalidMarketData("curves: at least one curve is required")
    curves: Dict[str, CurveSpec] = {}
    for curve_id, raw in curves_doc.items():
        path = f"curves.{curve_id}"
        row = _mapping(raw, path)
        _keys(row, _CURVE_KEYS, path)
        reference_date = _date(row["reference_date"], f"{path}.reference_date")
        if reference_date != valuation_date:
            raise InvalidMarketData(
                f"{path}.reference_date {reference_date.isoformat()} does not match "
                f"valuation_date {valuation_date.isoformat()}"
            )
        try:
            market_data = ZeroCurveMarketData(
                reference_date=reference_date,
                currency=_string(row["currency"], f"{path}.currency"),
                benchmark=_string(row["benchmark"], f"{path}.benchmark"),
                observations=_observations(row["observations"], f"{path}.observations"),
            )
        except InvalidMarketData:
            raise
        except ValueError as exc:
            raise InvalidMarketData(f"{path}: {exc}") from exc
        curves[curve_id] = CurveSpec(
            curve_id=curve_id,
            market_data=market_data,
            conventions=_conventions(row["conventions"], f"{path}.conventions"),
        )

    assignments_doc = _mapping(top["assignments"], "assignments")
    if not assignments_doc:
        raise InvalidMarketData("assignments: at least one currency assignment is required")
    assignments: Dict[str, CurveAssignment] = {}
    seen_keys: Dict[str, str] = {}
    for currency_key, raw in assignments_doc.items():
        currency = _string(currency_key, "assignments key").upper()
        if currency in seen_keys:
            raise InvalidMarketData(
                f"assignments: keys {seen_keys[currency]!r} and {currency_key!r} both name "
                f"{currency}; each currency may be assigned once"
            )
        seen_keys[currency] = currency_key
        path = f"assignments.{currency}"
        row = _mapping(raw, path)
        _keys(row, _ASSIGNMENT_KEYS, path)
        ids = {}
        for role in ("discount", "forecast"):
            curve_id = _string(row[role], f"{path}.{role}")
            if curve_id not in curves:
                raise InvalidMarketData(
                    f"{path}.{role}: unknown curve {curve_id!r}; available: {sorted(curves)}"
                )
            if curves[curve_id].market_data.currency != currency:
                raise InvalidMarketData(
                    f"{path}.{role}: curve {curve_id!r} is a "
                    f"{curves[curve_id].market_data.currency} curve, not {currency}"
                )
            ids[role] = curve_id
        assignments[currency] = CurveAssignment(
            currency=currency,
            discount_curve_id=ids["discount"],
            forecast_curve_id=ids["forecast"],
        )

    return MarketSnapshot(
        valuation_date=valuation_date,
        provenance=provenance,
        curves=curves,
        assignments=assignments,
    )


# --- resolution ----------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedMarket:
    """The configured environment plus the built curves it was assembled from."""

    snapshot: MarketSnapshot
    environment: MarketEnvironment
    curves: Mapping[str, QuantLibZeroCurve]


def resolve_market_environment(snapshot: MarketSnapshot) -> ResolvedMarket:
    """Build every assigned curve once and assemble the ``MarketEnvironment``.

    ``discount_curves[ccy]`` and ``forecast_curves[ccy]`` hold exactly the assigned
    curves; no other entries exist.
    """
    needed = sorted(
        {a.discount_curve_id for a in snapshot.assignments.values()}
        | {a.forecast_curve_id for a in snapshot.assignments.values()}
    )
    built: Dict[str, QuantLibZeroCurve] = {}
    for curve_id in needed:
        spec = snapshot.curves[curve_id]
        try:
            built[curve_id] = build_zero_curve(spec.market_data, spec.conventions)
        except ValueError as exc:  # inconsistent DFs, bad tenors, unsupported conventions
            raise InvalidMarketData(f"curves.{curve_id}: {exc}") from exc
    environment = MarketEnvironment(
        pricing_date=PricingDate(snapshot.valuation_date),
        discount_curves={
            ccy: built[a.discount_curve_id].handle for ccy, a in snapshot.assignments.items()
        },
        forecast_curves={
            ccy: built[a.forecast_curve_id].handle for ccy, a in snapshot.assignments.items()
        },
    )
    return ResolvedMarket(snapshot=snapshot, environment=environment, curves=built)
