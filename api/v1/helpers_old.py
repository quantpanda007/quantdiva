"""
Shared helpers for API endpoints.

Converts API request objects into domain objects (instruments, market envs).
All instrument-agnostic — uses the registry to resolve types.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

import QuantLib as ql

from core.interfaces.base import BaseInstrument, MarketEnvironment
from core.types.value_objects import PricingDate
from market.curves.yield_curve import build_test_market_env
from registry import instrument_registry

from api.v1.schemas import InstrumentRequest, MarketDataRequest


# ---------------------------------------------------------------------------
# Instrument builder
# ---------------------------------------------------------------------------

def build_instrument_from_request(req: InstrumentRequest) -> BaseInstrument:
    """
    Build a domain instrument from an API request.

    Uses the instrument registry to resolve the class by type string,
    then calls from_dict() with the params.
    """
    InstrumentClass = instrument_registry.get(req.type)
    if InstrumentClass is None:
        raise ValueError(
            f"Unknown instrument type: '{req.type}'. "
            f"Registered types: {instrument_registry.keys()}"
        )

    # Normalize params: ensure trade_id is present
    params = dict(req.params)
    if "trade_id" not in params:
        params["trade_id"] = params.get("_trade_id", f"API-{req.type}-001")

    # Try from_dict first (handles type conversions)
    if hasattr(InstrumentClass, "from_dict"):
        try:
            return InstrumentClass.from_dict(params)
        except Exception:
            pass

    # Fallback: direct construction with underscore prefix mapping
    constructor_params = {}
    for k, v in params.items():
        # Map trade_id → _trade_id, currency → _currency
        if k == "trade_id":
            constructor_params["_trade_id"] = v
        elif k == "currency":
            constructor_params["_currency"] = v
        else:
            constructor_params[k] = v

    # Parse date strings
    for date_field in ["expiry", "exercise_start", "averaging_start",
                       "start_date", "end_date", "issue_date", "maturity_date",
                       "expiry_date", "swap_start", "swap_end", "delivery_date"]:
        if date_field in constructor_params and isinstance(constructor_params[date_field], str):
            constructor_params[date_field] = date.fromisoformat(constructor_params[date_field])

    # Parse fixing dates list
    if "fixing_dates" in constructor_params and constructor_params["fixing_dates"]:
        constructor_params["fixing_dates"] = [
            date.fromisoformat(d) if isinstance(d, str) else d
            for d in constructor_params["fixing_dates"]
        ]

    # Parse enum strings
    from core.enums.definitions import OptionType, ExerciseType, BarrierType
    enum_map = {
        "option_type": OptionType,
        "exercise_type": ExerciseType,
        "barrier_type": BarrierType,
    }
    for field_name, enum_cls in enum_map.items():
        if field_name in constructor_params and isinstance(constructor_params[field_name], str):
            try:
                constructor_params[field_name] = enum_cls(constructor_params[field_name])
            except ValueError:
                pass

    # Handle instrument-specific enums
    if req.type == "digital_option" and "digital_type" in constructor_params:
        from instruments.equity.digital_option import DigitalType
        if isinstance(constructor_params["digital_type"], str):
            constructor_params["digital_type"] = DigitalType(constructor_params["digital_type"])

    if req.type == "asian_option":
        from instruments.equity.asian_option import AverageType, StrikeType
        if "average_type" in constructor_params and isinstance(constructor_params["average_type"], str):
            constructor_params["average_type"] = AverageType(constructor_params["average_type"])
        if "strike_type" in constructor_params and isinstance(constructor_params["strike_type"], str):
            constructor_params["strike_type"] = StrikeType(constructor_params["strike_type"])

    if req.type == "lookback_option" and "strike_type" in constructor_params:
        from instruments.equity.lookback_option import LookbackStrikeType
        if isinstance(constructor_params["strike_type"], str):
            constructor_params["strike_type"] = LookbackStrikeType(constructor_params["strike_type"])

    # Filter to valid constructor params
    import inspect
    valid_params = set(inspect.signature(InstrumentClass).parameters.keys())
    filtered = {k: v for k, v in constructor_params.items() if k in valid_params}

    return InstrumentClass(**filtered)


def build_instruments_from_request(reqs: List[InstrumentRequest]) -> List[BaseInstrument]:
    """Build multiple instruments."""
    return [build_instrument_from_request(r) for r in reqs]


# ---------------------------------------------------------------------------
# Market environment builder
# ---------------------------------------------------------------------------

def build_market_env_from_request(
    req: MarketDataRequest,
    underlying: str = None,
) -> MarketEnvironment:
    """
    Build a MarketEnvironment from an API request.

    If underlying is specified, builds for that specific underlying.
    Otherwise builds for the first underlying in the request.
    """
    pricing_date = PricingDate(date.fromisoformat(req.pricing_date))

    if not req.underlyings:
        raise ValueError("At least one underlying is required in market_data")

    if underlying is None or underlying.strip() == "":
        underlying = list(req.underlyings.keys())[0]

    und_data = req.underlyings.get(underlying)
    if und_data is None:
        raise ValueError(
            f"No market data for underlying '{underlying}'. "
            f"Available: {list(req.underlyings.keys())}"
        )

    return build_test_market_env(
        pricing_date=pricing_date,
        spot=und_data.spot,
        rate=req.rate,
        vol=und_data.vol,
        div_yield=und_data.div_yield,
        underlying=underlying,
    )


def build_multi_underlying_env(req: MarketDataRequest) -> Dict[str, MarketEnvironment]:
    """Build market environments for all underlyings."""
    envs = {}
    for und in req.underlyings:
        envs[und] = build_market_env_from_request(req, underlying=und)
    return envs
