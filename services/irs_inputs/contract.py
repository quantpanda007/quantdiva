"""Source-independent IRS input contract (no Excel, no UI, no pricing).

Two representations, both plain Python data:

1. **Trade inputs** (``TradeInputs``): the analyst-facing fields, keyed by section, in
   analyst units and labels: rates in percent, spreads in basis points, enumerations as the
   workbook's labels ("Modified Following", "Exclude Spread", ...). Dates are ``date``
   objects or ISO strings; numbers are ``int``/``float``/``Decimal`` or numeric strings;
   a field that was left empty is ``None``. The Excel reader produces this; a UI adapter
   would produce the same dictionary.

2. **Normalized trade** (``NormalizedIRSTrade``): the output of the normalizer. It holds the
   existing engine trade document (``{"schema_version": 1, "instrument_type": "ois",
   "params": {...}}``, the schema of ``instruments.rates.irs.pricing_instrument``, engine
   units: decimal rates and spreads) and a ``MarketDataRequest`` naming the market data the
   inputs refer to. This is what the pricing orchestration consumes.

Keys of ``TradeInputs`` (every key must be present; unused optional values are ``None``)::

    trade:        trade_id, currency, notional, effective_date, maturity_date, valuation_date
    fixed_leg:    direction, rate_percent, payment_frequency, day_count,
                  business_day_convention, calendar
    floating_leg: direction, benchmark, index_tenor, spread_bp, leverage, reset_frequency,
                  payment_frequency, day_count, business_day_convention, calendar,
                  rate_timing, lookback_days, lookback_type, rate_cutoff_days, compounding,
                  spread_treatment
    notional:     principal_exchange, amortisation_type,
                  schedule: [ {period, accrual_start, accrual_end, payment_date, notional,
                               amortisation_percent, amortisation_amount, action}, ... ]
    market_data:  curve, snapshot_folder, curve_source_file, fixings_source_file,
                  reference_date, interpolation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Mapping, Optional, Tuple

TradeInputs = Mapping[str, Any]

SECTION_KEYS: Dict[str, Tuple[str, ...]] = {
    "trade": ("trade_id", "currency", "notional", "effective_date", "maturity_date",
              "valuation_date"),
    "fixed_leg": ("direction", "rate_percent", "payment_frequency", "day_count",
                  "business_day_convention", "calendar"),
    "floating_leg": ("direction", "benchmark", "index_tenor", "spread_bp", "leverage",
                     "reset_frequency", "payment_frequency", "day_count",
                     "business_day_convention", "calendar", "rate_timing", "lookback_days",
                     "lookback_type", "rate_cutoff_days", "compounding", "spread_treatment"),
    "notional": ("principal_exchange", "amortisation_type", "schedule"),
    "market_data": ("curve", "snapshot_folder", "curve_source_file", "fixings_source_file",
                    "reference_date", "interpolation"),
}
SCHEDULE_ROW_KEYS: Tuple[str, ...] = ("period", "accrual_start", "accrual_end", "payment_date",
                                      "notional", "amortisation_percent",
                                      "amortisation_amount", "action")


class InputValidationError(ValueError):
    """The trade inputs are missing, invalid or not supported. ``issues`` lists every
    problem found, each prefixed with the field path (e.g. ``floating_leg.spread_bp``)."""

    def __init__(self, issues: List[str], source: str = "trade inputs"):
        self.issues = list(issues)
        self.source = source
        lines = "\n".join(f"  - {issue}" for issue in self.issues)
        super().__init__(f"{source}: {len(self.issues)} problem(s)\n{lines}")


@dataclass(frozen=True)
class MarketDataRequest:
    """The market data the inputs refer to, checked against what the existing resolver
    selects and against the prepared snapshot. Nothing here selects or changes a curve."""

    valuation_date: date
    currency: str
    curve_benchmark: str                 # e.g. "SOFR" (curve, not trade, benchmark)
    curve_file: str                      # prepared snapshot file name
    fixings_file: Optional[str]          # dated fixings file name, if stated
    reference_date: Optional[date]       # stated curve reference date, if any
    interpolation: Optional[str]         # stated snapshot interpolation (engine label)


@dataclass(frozen=True)
class NormalizedIRSTrade:
    trade_document: Dict[str, Any]       # engine schema, schema_version 1, instrument "ois"
    market: MarketDataRequest
    notes: Tuple[str, ...] = field(default_factory=tuple)
