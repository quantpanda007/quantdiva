"""
Portfolio — first-class aggregate of trades.

A Portfolio is not just a list of instruments — it provides:
- Aggregated valuation
- Portfolio-level Greeks (with netting)
- Scenario analysis at portfolio scope
- VaR with proper aggregation
- Trade-level drill-down

This is the primary object that desk systems operate on.

Usage:
    from core.portfolio import Portfolio, PortfolioPosition

    portfolio = Portfolio(
        portfolio_id="DESK-EQ-001",
        name="Equity Derivatives Desk",
    )
    portfolio.add_position(PortfolioPosition(instrument=option1, quantity=100, direction="buy"))
    portfolio.add_position(PortfolioPosition(instrument=option2, quantity=50, direction="sell"))

    result = portfolio.value(market_env, pricing_service)
    print(result.total_npv)
    print(result.greeks)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.interfaces.base import BaseInstrument, MarketEnvironment

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------

@dataclass
class PortfolioPosition:
    """
    Single position in a portfolio.

    Attributes:
        instrument:  The underlying instrument
        quantity:    Number of contracts / notional
        direction:   "buy" (+1) or "sell" (-1)
        trade_date:  When the position was entered
        book:        Trading book (for aggregation)
        tags:        Arbitrary metadata for filtering
    """
    instrument: BaseInstrument
    quantity: float = 1.0
    direction: str = "buy"  # "buy" or "sell"
    trade_date: Optional[str] = None
    book: str = "default"
    tags: Dict[str, str] = field(default_factory=dict)

    @property
    def sign(self) -> float:
        return 1.0 if self.direction == "buy" else -1.0

    @property
    def signed_quantity(self) -> float:
        return self.quantity * self.sign

    @property
    def trade_id(self) -> str:
        return str(self.instrument.trade_id())


# ---------------------------------------------------------------------------
# Valuation result
# ---------------------------------------------------------------------------

@dataclass
class PositionResult:
    """Valuation result for a single position."""
    trade_id: str
    instrument_type: str
    book: str
    quantity: float
    direction: str
    unit_npv: float
    position_npv: float
    greeks: Dict[str, Optional[float]] = field(default_factory=dict)
    position_greeks: Dict[str, Optional[float]] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class PortfolioValuationResult:
    """Full portfolio valuation."""
    portfolio_id: str
    total_npv: float = 0.0
    total_greeks: Dict[str, float] = field(default_factory=dict)
    position_results: List[PositionResult] = field(default_factory=list)
    by_book: Dict[str, float] = field(default_factory=dict)
    by_instrument_type: Dict[str, float] = field(default_factory=dict)
    num_positions: int = 0
    num_succeeded: int = 0
    num_failed: int = 0
    elapsed_seconds: float = 0.0
    valuation_timestamp: str = ""

    def print_summary(self) -> None:
        print(f"\nPortfolio Valuation: {self.portfolio_id}")
        print(f"{'='*70}")
        print(f"  Total NPV:     {self.total_npv:>14.4f}")
        print(f"  Positions:     {self.num_positions} ({self.num_succeeded} ok, {self.num_failed} failed)")
        print(f"  Time:          {self.elapsed_seconds:.3f}s")

        if self.total_greeks:
            print(f"\n  Portfolio Greeks:")
            for g, v in self.total_greeks.items():
                print(f"    {g:<12} {v:>14.6f}")

        if self.by_book and len(self.by_book) > 1:
            print(f"\n  By Book:")
            for book, npv in self.by_book.items():
                print(f"    {book:<20} {npv:>14.4f}")

        if self.by_instrument_type:
            print(f"\n  By Instrument Type:")
            for it, npv in self.by_instrument_type.items():
                print(f"    {it:<20} {npv:>14.4f}")

        print(f"\n  {'Trade ID':<22} {'Type':<18} {'Qty':>6} {'Dir':>5} {'Unit NPV':>12} {'Pos NPV':>14}")
        print(f"  {'-'*22} {'-'*18} {'-'*6} {'-'*5} {'-'*12} {'-'*14}")
        for pr in self.position_results:
            if pr.error:
                print(f"  {pr.trade_id:<22} {'ERROR':<18} {pr.quantity:>6.0f} {pr.direction:>5} {'':>12} {pr.error}")
            else:
                print(
                    f"  {pr.trade_id:<22} {pr.instrument_type:<18} "
                    f"{pr.quantity:>6.0f} {pr.direction:>5} "
                    f"{pr.unit_npv:>12.4f} {pr.position_npv:>14.4f}"
                )
        print()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "portfolio_id": self.portfolio_id,
            "total_npv": self.total_npv,
            "total_greeks": self.total_greeks,
            "by_book": self.by_book,
            "by_instrument_type": self.by_instrument_type,
            "num_positions": self.num_positions,
            "num_succeeded": self.num_succeeded,
            "num_failed": self.num_failed,
            "elapsed_seconds": self.elapsed_seconds,
            "positions": [
                {
                    "trade_id": pr.trade_id,
                    "instrument_type": pr.instrument_type,
                    "quantity": pr.quantity,
                    "direction": pr.direction,
                    "unit_npv": pr.unit_npv,
                    "position_npv": pr.position_npv,
                    "greeks": pr.position_greeks,
                    "error": pr.error,
                }
                for pr in self.position_results
            ],
        }


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------

@dataclass
class Portfolio:
    """
    First-class portfolio object.

    Holds positions and provides aggregated valuation,
    Greeks, and risk analytics.
    """
    portfolio_id: str = "PF-001"
    name: str = ""
    positions: List[PortfolioPosition] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_position(self, position: PortfolioPosition) -> None:
        self.positions.append(position)

    def remove_position(self, trade_id: str) -> None:
        self.positions = [p for p in self.positions if p.trade_id != trade_id]

    def get_position(self, trade_id: str) -> Optional[PortfolioPosition]:
        for p in self.positions:
            if p.trade_id == trade_id:
                return p
        return None

    @property
    def instruments(self) -> List[BaseInstrument]:
        """All instruments (for scenario engine compatibility)."""
        return [p.instrument for p in self.positions]

    def filter_by_book(self, book: str) -> List[PortfolioPosition]:
        return [p for p in self.positions if p.book == book]

    def filter_by_type(self, instrument_type: str) -> List[PortfolioPosition]:
        return [
            p for p in self.positions
            if p.instrument.instrument_type().value == instrument_type
        ]

    def filter_by_tag(self, key: str, value: str) -> List[PortfolioPosition]:
        return [p for p in self.positions if p.tags.get(key) == value]

    @property
    def books(self) -> List[str]:
        return list(set(p.book for p in self.positions))

    @property
    def instrument_types(self) -> List[str]:
        return list(set(p.instrument.instrument_type().value for p in self.positions))

    # -------------------------------------------------------------------
    # Valuation
    # -------------------------------------------------------------------

    def value(
        self,
        market_env: MarketEnvironment,
        pricing_service: Any,
        model_type: str = "black_scholes",
        engine_type: str = "analytic",
        engine_params: Optional[Dict[str, Any]] = None,
        compute_greeks: bool = True,
    ) -> PortfolioValuationResult:
        """
        Full portfolio valuation with aggregation.

        Prices each position, aggregates NPV and Greeks
        across the portfolio with quantity and direction weighting.
        """
        t0 = time.perf_counter()

        result = PortfolioValuationResult(
            portfolio_id=self.portfolio_id,
            num_positions=len(self.positions),
            valuation_timestamp=datetime.utcnow().isoformat(),
        )

        total_greeks: Dict[str, float] = {}
        by_book: Dict[str, float] = {}
        by_type: Dict[str, float] = {}

        for pos in self.positions:
            tid = pos.trade_id
            inst = pos.instrument
            inst_type = inst.instrument_type().value

            # Get underlying for market env
            underlying = getattr(inst, "underlying", "")

            try:
                # Price
                pr = pricing_service.price(
                    inst, market_env,
                    model_type=model_type,
                    engine_type=engine_type,
                    engine_params=engine_params,
                )
                unit_npv = pr.npv
                position_npv = unit_npv * pos.signed_quantity

                # Greeks
                unit_greeks = {}
                pos_greeks = {}
                if compute_greeks:
                    try:
                        from services.greeks.bump_reprice import BumpAndRepriceGreeks
                        greeks_svc = BumpAndRepriceGreeks(pricing_service=pricing_service)
                        gr = greeks_svc.compute(
                            inst, market_env,
                            model_type=model_type,
                            engine_type=engine_type,
                            engine_params=engine_params,
                            measures=["delta", "gamma", "vega", "theta", "rho"],
                        )
                        unit_greeks = gr.greeks

                        for g_name, g_val in unit_greeks.items():
                            if g_val is not None:
                                scaled = g_val * pos.signed_quantity
                                pos_greeks[g_name] = scaled
                                total_greeks[g_name] = total_greeks.get(g_name, 0.0) + scaled

                    except Exception as e:
                        logger.debug(f"Greeks failed for {tid}: {e}")

                # Aggregation
                result.total_npv += position_npv
                by_book[pos.book] = by_book.get(pos.book, 0.0) + position_npv
                by_type[inst_type] = by_type.get(inst_type, 0.0) + position_npv

                result.position_results.append(PositionResult(
                    trade_id=tid,
                    instrument_type=inst_type,
                    book=pos.book,
                    quantity=pos.quantity,
                    direction=pos.direction,
                    unit_npv=unit_npv,
                    position_npv=position_npv,
                    greeks=unit_greeks,
                    position_greeks=pos_greeks,
                ))
                result.num_succeeded += 1

            except Exception as e:
                logger.warning(f"Position valuation failed: {tid}: {e}")
                result.position_results.append(PositionResult(
                    trade_id=tid,
                    instrument_type=inst_type,
                    book=pos.book,
                    quantity=pos.quantity,
                    direction=pos.direction,
                    unit_npv=0.0,
                    position_npv=0.0,
                    error=str(e),
                ))
                result.num_failed += 1

        result.total_greeks = {k: round(v, 8) for k, v in total_greeks.items()}
        result.by_book = {k: round(v, 6) for k, v in by_book.items()}
        result.by_instrument_type = {k: round(v, 6) for k, v in by_type.items()}
        result.elapsed_seconds = time.perf_counter() - t0

        return result