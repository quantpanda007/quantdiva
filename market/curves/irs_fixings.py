"""Historical and valuation-date fixings for the fresh IRS.

Fixings are market data (``fixings`` section of a market snapshot): index name ->
{fixing date: rate (decimal)}, each series with its provenance. Two consumers:

* overnight legs read fixings from QuantLib's global index history, so
  ``overnight_fixings_applied`` adds them for the duration of one pricing and then
  restores the previous history exactly (the audit checks QuantLib's shared state);
* term-rate legs receive their benchmark's fixings directly
  (``build_term_rate_floating_leg(..., fixings=...)``); nothing global is touched.

A fixing is never inferred: a coupon that needs one that is not supplied fails.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from typing import Callable, Dict, Iterator, Mapping

import QuantLib as ql

# Market-snapshot fixing names of overnight indexes -> QuantLib index factory.
OVERNIGHT_FIXING_INDEXES: Dict[str, Callable[[], ql.OvernightIndex]] = {
    "SOFR": ql.Sofr,
    "SARON": ql.Saron,
    "TONA": ql.Tonar,
}


def _ql(value: date) -> ql.Date:
    return ql.Date(value.day, value.month, value.year)


@contextmanager
def overnight_fixings_applied(fixings: Mapping[str, Mapping[date, float]]) -> Iterator[None]:
    """Add the overnight fixings to QuantLib's index history; restore it afterwards.
    (Reading an index's time series registers its name with QuantLib's index manager;
    the audit reads the monitored indexes first for the same reason.)"""
    saved = []
    try:
        for name, series in sorted((fixings or {}).items()):
            factory = OVERNIGHT_FIXING_INDEXES.get(name)
            if factory is None or not series:
                continue
            index = factory()
            history = index.timeSeries()
            saved.append((index, list(history.dates()), list(history.values())))
            dates = sorted(series)
            index.addFixings([_ql(d) for d in dates], [float(series[d]) for d in dates], True)
        yield
    finally:
        for index, dates, values in reversed(saved):
            index.clearFixings()
            if dates:
                index.addFixings(dates, values, True)
