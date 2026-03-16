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

    For FX instruments (ccy pair underlyings like USDINR):
    - Builds separate domestic and foreign discount curves
    - Foreign rate comes from req.foreign_rate or und_data.div_yield
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

    # Resolve domestic rate: rate_curve takes priority over flat rate
    domestic_rate = req.rate
    if req.rate_curve and len(req.rate_curve) > 0:
        domestic_rate = req.rate_curve[0].get("rate", req.rate)

    # Resolve foreign rate: explicit foreign_rate > div_yield > default
    foreign_rate = req.foreign_rate if req.foreign_rate is not None else und_data.div_yield

    # Check if this is an FX underlying (6-char ccy pair like USDINR)
    is_fx = len(underlying) == 6 and underlying.isalpha()

    if is_fx and foreign_rate is not None:
        # Build FX-specific market environment with separate curves
        return _build_fx_market_env(
            pricing_date=pricing_date,
            spot=und_data.spot,
            domestic_rate=domestic_rate,
            foreign_rate=foreign_rate,
            vol=und_data.vol,
            ccy_pair=underlying,
        )
    else:
        # Standard equity/rates market environment
        return build_test_market_env(
            pricing_date=pricing_date,
            spot=und_data.spot,
            rate=domestic_rate,
            vol=und_data.vol,
            div_yield=und_data.div_yield,
            underlying=underlying,
        )


def _build_fx_market_env(
    pricing_date: PricingDate,
    spot: float,
    domestic_rate: float,
    foreign_rate: float,
    vol: float,
    ccy_pair: str,
) -> MarketEnvironment:
    """
    Build a MarketEnvironment with separate domestic and foreign curves.

    For USDINR: domestic=INR, foreign=USD.
    Creates discount curves keyed by currency code so fx_forward's
    _extract_rate("INR") and _extract_foreign_rate("USD") find them.
    """
    from market.curves.yield_curve import build_flat_curve, build_flat_vol

    foreign_ccy = ccy_pair[:3]   # e.g., USD
    domestic_ccy = ccy_pair[3:6]  # e.g., INR

    ql_date = pricing_date.to_ql()
    ql.Settings.instance().evaluationDate = ql_date

    # Separate curves for each currency
    domestic_curve = build_flat_curve(pricing_date, domestic_rate)
    foreign_curve = build_flat_curve(pricing_date, foreign_rate)
    vol_surface = build_flat_vol(pricing_date, vol)

    # Also create a div_yield curve for BSM-style compatibility (FX options)
    div_curve = ql.YieldTermStructureHandle(
        ql.FlatForward(ql_date, foreign_rate, ql.Actual365Fixed())
    )

    return MarketEnvironment(
        pricing_date=pricing_date,
        discount_curves={
            domestic_ccy: domestic_curve,   # INR curve at 6.5%
            foreign_ccy: foreign_curve,     # USD curve at 4.5%
            ccy_pair: domestic_curve,        # USDINR → domestic (for BSM compat)
            "USD": foreign_curve,            # Fallback key
        },
        forecast_curves={
            domestic_ccy: domestic_curve,
            foreign_ccy: foreign_curve,
        },
        vol_surfaces={ccy_pair: vol_surface},
        spot_prices={ccy_pair: spot},
        dividend_curves={f"{ccy_pair}_div": div_curve},
    )


def build_multi_underlying_env(req: MarketDataRequest) -> Dict[str, MarketEnvironment]:
    """Build market environments for all underlyings."""
    envs = {}
    for und in req.underlyings:
        envs[und] = build_market_env_from_request(req, underlying=und)
    return envs
