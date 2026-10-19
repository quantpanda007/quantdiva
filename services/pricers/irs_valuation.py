"""Input-driven valuation of a fresh IRS from a trade document and a market-data
document.

Pipeline (no pricing logic of its own):

    trade document  -> instrument_registry[type].from_dict(params)  (strict validation)
    market document -> parse_market_snapshot -> resolve_market_environment
    PricingService.price(instrument, environment, "analytical", "discounting")
    irs_cashflow_rows(instrument.last_built, environment.discount_curves[currency])

Checks made here, before pricing:
* the trade's valuation_date equals the market data's valuation_date;
* the market data assigns discount and forecast curves for the trade currency;
* the trade's floating benchmark maps (strictly) to the forecast curve's benchmark.

QuantLib's evaluation date is restored after pricing. Bloomberg comparison is not
part of valuation.

Trade document::

    {"schema_version": 1, "instrument_type": "ois", "params": {...FreshOISTrade params...}}
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Dict, Mapping, Tuple

import QuantLib as ql

from instruments.rates.irs.cashflows import (
    IRSCashflowRow,
    SettledCashflow,
    irs_cashflow_rows,
    settled_cashflows,
)
from instruments.rates.irs.pricing_instrument import FreshOISInstrument
from market.curves.irs_fixings import overnight_fixings_applied
from market.curves.irs_market_snapshot import (
    InvalidMarketData,
    parse_market_snapshot,
    resolve_market_environment,
)
from registry import instrument_registry
from services.pricers.pricing_service import PricingService

TRADE_SCHEMA_VERSION = 1
MODEL = "analytical"
ENGINE = "discounting"

# Trade floating benchmark -> curve benchmark it must be projected on (strict).
BENCHMARK_CURVES = {"SOFRRATE": "SOFR", "SF0006M": "SARON", "MUTKCALM": "TONA",
                    "IRSWOF": "MIBOR"}

_TRADE_KEYS = frozenset({"schema_version", "instrument_type", "params"})


class InvalidTradeDocument(ValueError):
    """The trade document is missing, malformed or of an unsupported type."""


class IRSValuationError(ValueError):
    """Trade and market data are individually valid but cannot be used together."""


@dataclass(frozen=True)
class IRSValuation:
    trade_id: str
    instrument_type: str
    currency: str
    valuation_date: date
    npv: float
    fixed_leg_npv: float
    floating_leg_npv: float
    cashflows: Tuple[IRSCashflowRow, ...]
    discount_curve_id: str
    forecast_curve_id: str
    model: str
    engine: str
    # Coupons paying on or before the valuation date: excluded, as by the engine.
    settled: Tuple[SettledCashflow, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """JSON-ready dictionary (dates as ISO strings)."""

        def plain(value: Any) -> Any:
            return value.isoformat() if isinstance(value, date) else value

        result = {key: plain(value) for key, value in asdict(self).items()
                  if key not in ("cashflows", "settled")}
        for name in ("cashflows", "settled"):
            result[name] = [
                {key: plain(value) for key, value in asdict(row).items()}
                for row in getattr(self, name)
            ]
        return result


def parse_trade_document(document: Any) -> Tuple[str, Mapping[str, Any]]:
    """Return (instrument_type, params) from a trade document."""
    if not isinstance(document, Mapping):
        raise InvalidTradeDocument("trade document must be an object")
    missing = sorted(_TRADE_KEYS - set(document))
    unknown = sorted(set(document) - _TRADE_KEYS)
    if missing:
        raise InvalidTradeDocument(f"trade document: missing required keys {missing}")
    if unknown:
        raise InvalidTradeDocument(f"trade document: unknown keys {unknown}")
    schema_version = document["schema_version"]
    # bool is an int subclass and 1.0 == 1, so check the type explicitly.
    if type(schema_version) is not int or schema_version != TRADE_SCHEMA_VERSION:
        raise InvalidTradeDocument(
            f"trade document: unsupported schema_version {document['schema_version']!r}; "
            f"expected {TRADE_SCHEMA_VERSION}"
        )
    instrument_type = document["instrument_type"]
    if not isinstance(instrument_type, str) or not instrument_type:
        raise InvalidTradeDocument("trade document: instrument_type must be a non-empty string")
    if not isinstance(document["params"], Mapping):
        raise InvalidTradeDocument("trade document: params must be an object")
    return instrument_type, document["params"]


def build_trade(document: Any) -> FreshOISInstrument:
    """Construct the instrument through the registry; validation errors propagate."""
    instrument_type, params = parse_trade_document(document)
    instrument_class = instrument_registry.get_or_none(instrument_type)
    if instrument_class is not FreshOISInstrument:
        raise InvalidTradeDocument(
            f"instrument_type {instrument_type!r} is not supported by the input-driven IRS "
            "workflow; supported: ['ois']"
        )
    return FreshOISInstrument.from_dict(params)


def price_irs(trade_document: Any, market_document: Any) -> IRSValuation:
    """Validate both documents, build the environment and price through PricingService."""
    instrument = build_trade(trade_document)
    snapshot = parse_market_snapshot(market_document)
    trade = instrument.trade

    if trade.valuation_date != snapshot.valuation_date:
        raise IRSValuationError(
            f"trade valuation_date {trade.valuation_date.isoformat()} does not match market "
            f"data valuation_date {snapshot.valuation_date.isoformat()}"
        )
    currency = instrument.currency()
    assignment = snapshot.assignment(currency)

    benchmark = trade.floating_terms.benchmark
    if benchmark not in BENCHMARK_CURVES:
        raise IRSValuationError(
            f"floating benchmark {benchmark!r} has no curve-benchmark mapping; "
            f"supported: {sorted(BENCHMARK_CURVES)}"
        )
    forecast_benchmark = snapshot.curves[assignment.forecast_curve_id].market_data.benchmark
    if forecast_benchmark != BENCHMARK_CURVES[benchmark]:
        raise IRSValuationError(
            f"floating benchmark {benchmark!r} must be projected on a "
            f"{BENCHMARK_CURVES[benchmark]!r} curve, but the {currency} forecast curve "
            f"{assignment.forecast_curve_id!r} is {forecast_benchmark!r}"
        )

    resolved = resolve_market_environment(snapshot)
    environment = resolved.environment

    previous = ql.Settings.instance().evaluationDate
    try:
        # Overnight fixings (market data) are in QuantLib's index history only while this
        # trade is priced and its cashflows read; the previous history is restored.
        with overnight_fixings_applied(environment.fixings):
            result = PricingService().price(
                instrument=instrument,
                market_env=environment,
                model_type=MODEL,
                engine_type=ENGINE,
            )
            legs = instrument.leg_npvs()
            # Read while the pricing evaluation date is still set; same curve as the engine.
            cashflows = irs_cashflow_rows(
                instrument.last_built, environment.discount_curves[currency]
            )
            settled = settled_cashflows(
                instrument.last_built, ql.Settings.instance().evaluationDate
            )
    finally:
        ql.Settings.instance().evaluationDate = previous

    return IRSValuation(
        trade_id=str(instrument.trade_id()),
        instrument_type=instrument.instrument_type().value,
        currency=currency,
        valuation_date=snapshot.valuation_date,
        npv=result.npv,
        fixed_leg_npv=legs["fixed"],
        floating_leg_npv=legs["floating"],
        cashflows=cashflows,
        discount_curve_id=assignment.discount_curve_id,
        forecast_curve_id=assignment.forecast_curve_id,
        model=result.model_used,
        engine=result.engine_used,
        settled=settled,
    )


__all__ = [
    "BENCHMARK_CURVES",
    "IRSValuation",
    "IRSValuationError",
    "InvalidMarketData",
    "InvalidTradeDocument",
    "build_trade",
    "parse_trade_document",
    "price_irs",
]
