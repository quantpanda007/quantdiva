"""
Analytical FX Forward Engine.

Pure closed-form pricer — no stochastic model, no vol.

    F   = S × exp((r_d - r_f) × T)
    DF  = exp(-r_d × T)
    NPV = Notional × (F - K) × DF × sign

sign = +1 if direction == 'buy'  (long foreign ccy)
sign = -1 if direction == 'sell' (short foreign ccy)

No Black-Scholes, no N(d1)/N(d2), no vol dependency.
"""

from __future__ import annotations

import math
from datetime import date

import QuantLib as ql

from core.interfaces.base import BaseEngine, BaseInstrument, MarketEnvironment, PricingResult
from registry import engine_registry


class FXForwardAnalyticEngine(BaseEngine):
    """Closed-form FX forward pricer."""

    def price(
        self,
        instrument: BaseInstrument,
        market_env: MarketEnvironment,
        **kwargs,
    ) -> PricingResult:
        import time
        t0 = time.time()

        # --- Extract instrument fields ---
        ccy_pair     = getattr(instrument, "ccy_pair", "USDINR")
        strike       = float(getattr(instrument, "strike", 0))
        notional     = float(getattr(instrument, "notional", 1_000_000))
        direction    = str(getattr(instrument, "direction", "sell")).lower()
        delivery     = getattr(instrument, "delivery_date", None)

        sign = 1.0 if direction in ("buy", "b") else -1.0

        # --- Pricing date ---
        pricing_date = market_env.pricing_date.to_date()

        if delivery is None or delivery <= pricing_date:
            return PricingResult(
                npv=0.0,
                currency=ccy_pair[3:] if len(ccy_pair) == 6 else "INR",
                model="analytical",
                engine="analytic",
                diagnostics={"status": "expired", "elapsed_seconds": 0.0},
            )

        T = (delivery - pricing_date).days / 365.0

        # --- Extract rates ---
        r_d = self._extract_rate(market_env, ccy_pair, domestic=True)
        r_f = self._extract_rate(market_env, ccy_pair, domestic=False)

        # --- Extract spot ---
        spot = market_env.spot_prices.get(ccy_pair, 0.0)
        if not spot:
            raise ValueError(f"No spot price found for {ccy_pair}")

        # --- Pure forward formula ---
        F   = spot * math.exp((r_d - r_f) * T)
        DF  = math.exp(-r_d * T)
        npv = notional * (F - strike) * DF * sign

        elapsed = time.time() - t0

        foreign_ccy  = ccy_pair[:3] if len(ccy_pair) == 6 else "USD"
        domestic_ccy = ccy_pair[3:] if len(ccy_pair) == 6 else "INR"

        return PricingResult(
            npv=npv,
            currency=domestic_ccy,
            model="analytical",
            engine="analytic",
            diagnostics={
                "elapsed_seconds": elapsed,
                "spot": spot,
                "forward_rate": round(F, 6),
                "discount_factor": round(DF, 6),
                "domestic_rate": r_d,
                "foreign_rate": r_f,
                "T": round(T, 6),
                "strike": strike,
                "notional": notional,
                "direction": direction,
                "sign": sign,
            },
        )

    def _extract_rate(
        self,
        market_env: MarketEnvironment,
        ccy_pair: str,
        domestic: bool,
    ) -> float:
        """
        Extract domestic (INR) or foreign (USD) rate from discount curves.
        Falls back to 0.0 if not found — respects user-entered zero rates.
        """
        if len(ccy_pair) == 6:
            key = ccy_pair[3:] if domestic else ccy_pair[:3]
        else:
            key = ccy_pair

        curve_handle = market_env.discount_curves.get(key)
        if curve_handle is None:
            return 0.0

        try:
            ql_date = market_env.pricing_date.to_ql()
            # Read the continuously compounded zero rate at 1Y
            dc = ql.Actual365Fixed()
            ref = curve_handle.referenceDate()
            target = ref + ql.Period(1, ql.Years)
            rate = curve_handle.zeroRate(target, dc, ql.Continuous).rate()
            return float(rate)
        except Exception:
            return 0.0


# --- Registration ---
engine_registry.register(("fx_forward", "analytic"), FXForwardAnalyticEngine)