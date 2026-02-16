"""
Engine Comparison Utility.

Prices the same instrument across all compatible engines and reports:
- NPV from each engine
- Greeks from each engine (where available)
- Differences vs a reference engine (typically analytic)
- Convergence ranking
- Timing comparison

This is critical for:
- Validating new engine implementations
- Checking numerical accuracy
- Performance benchmarking
- Audit trail: prove that MC/FD converge to analytic

Usage:
    from services.comparison.engine_comparator import EngineComparator

    comp = EngineComparator()
    report = comp.compare(
        instrument=option,
        market_env=env,
        model_type="black_scholes",
    )
    report.print_summary()
    report.to_dataframe()
    report.to_csv("comparison_results.csv")

    # Compare specific engines only
    report = comp.compare(
        instrument=option,
        market_env=env,
        model_type="black_scholes",
        engine_types=["analytic", "finite_difference", "monte_carlo"],
    )

    # Compare with custom engine params
    report = comp.compare(
        instrument=option,
        market_env=env,
        model_type="black_scholes",
        engine_configs={
            "analytic": {},
            "finite_difference": {"time_steps": 500, "spot_steps": 1000},
            "monte_carlo": {"num_paths": 200_000, "time_steps": 500},
            "mc_american": {"num_paths": 100_000, "poly_degree": 5},
            "binomial": {"steps": 1000, "tree_type": "crr"},
        },
    )
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.enums.definitions import EngineType, InstrumentType, ModelType
from core.interfaces.base import BaseInstrument, MarketEnvironment
from registry import engine_registry, model_registry
from services.pricers.pricing_service import PricingService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Single engine result
# ---------------------------------------------------------------------------

@dataclass
class EngineResult:
    """Result from a single engine run."""
    engine_type: str
    npv: float
    greeks: Dict[str, Optional[float]] = field(default_factory=dict)
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    elapsed_seconds: float = 0.0
    error: Optional[str] = None  # None if successful

    @property
    def succeeded(self) -> bool:
        return self.error is None


# ---------------------------------------------------------------------------
# Comparison report
# ---------------------------------------------------------------------------

@dataclass
class ComparisonReport:
    """
    Full comparison report across engines.

    Attributes:
        trade_id:        Instrument trade ID
        instrument_type: Instrument type
        model_type:      Model used for all engines
        reference_engine: Engine used as reference (typically analytic)
        results:         List of EngineResult
    """

    trade_id: str = ""
    instrument_type: str = ""
    model_type: str = ""
    reference_engine: str = ""
    results: List[EngineResult] = field(default_factory=list)

    # -------------------------------------------------------------------
    # Analysis
    # -------------------------------------------------------------------

    @property
    def reference_npv(self) -> Optional[float]:
        """NPV from the reference engine."""
        for r in self.results:
            if r.engine_type == self.reference_engine and r.succeeded:
                return r.npv
        return None

    def differences(self) -> List[Dict[str, Any]]:
        """Compute differences vs reference engine."""
        ref = self.reference_npv
        if ref is None:
            return []

        diffs = []
        for r in self.results:
            if not r.succeeded:
                diffs.append({
                    "engine": r.engine_type,
                    "npv": None,
                    "abs_diff": None,
                    "rel_diff_pct": None,
                    "rel_diff_bps": None,
                    "elapsed_ms": round(r.elapsed_seconds * 1000, 2),
                    "error": r.error,
                })
                continue

            abs_diff = r.npv - ref
            rel_diff = abs_diff / ref if abs(ref) > 1e-10 else 0.0

            diffs.append({
                "engine": r.engine_type,
                "npv": round(r.npv, 8),
                "abs_diff": round(abs_diff, 8),
                "rel_diff_pct": round(rel_diff * 100, 6),
                "rel_diff_bps": round(rel_diff * 10000, 2),
                "elapsed_ms": round(r.elapsed_seconds * 1000, 2),
                "error": None,
            })

        return diffs

    def greeks_comparison(self) -> List[Dict[str, Any]]:
        """Compare Greeks across engines."""
        all_greek_names = set()
        for r in self.results:
            if r.succeeded and r.greeks:
                all_greek_names.update(r.greeks.keys())

        if not all_greek_names:
            return []

        rows = []
        for greek in sorted(all_greek_names):
            row = {"greek": greek}
            for r in self.results:
                if r.succeeded and r.greeks:
                    val = r.greeks.get(greek)
                    row[r.engine_type] = round(val, 8) if val is not None else None
                else:
                    row[r.engine_type] = None
            rows.append(row)

        return rows

    # -------------------------------------------------------------------
    # Display
    # -------------------------------------------------------------------

    def print_summary(self) -> None:
        """Print a formatted comparison summary."""
        print(f"\n{'='*80}")
        print(f"Engine Comparison: {self.trade_id}")
        print(f"Instrument: {self.instrument_type} | Model: {self.model_type}")
        print(f"Reference: {self.reference_engine}")
        print(f"{'='*80}")

        ref = self.reference_npv
        if ref is not None:
            print(f"Reference NPV: {ref:.8f}")
        print()

        # NPV comparison
        print(f"{'Engine':<25} {'NPV':>14} {'Diff':>12} {'Diff(bps)':>10} {'Time(ms)':>10} {'Status':>8}")
        print(f"{'-'*25} {'-'*14} {'-'*12} {'-'*10} {'-'*10} {'-'*8}")

        for d in self.differences():
            if d["error"]:
                print(f"{d['engine']:<25} {'FAILED':>14} {'':>12} {'':>10} {d['elapsed_ms']:>10.2f} {'✗':>8}")
            else:
                is_ref = d["engine"] == self.reference_engine
                status = "ref" if is_ref else "✓"
                print(
                    f"{d['engine']:<25} "
                    f"{d['npv']:>14.8f} "
                    f"{d['abs_diff']:>12.8f} "
                    f"{d['rel_diff_bps']:>10.2f} "
                    f"{d['elapsed_ms']:>10.2f} "
                    f"{status:>8}"
                )

        # Greeks comparison
        greeks = self.greeks_comparison()
        if greeks:
            print(f"\n{'Greeks Comparison':}")
            engines = [r.engine_type for r in self.results if r.succeeded]
            header = f"{'Greek':<10}" + "".join(f"{e:>18}" for e in engines)
            print(header)
            print("-" * len(header))
            for row in greeks:
                line = f"{row['greek']:<10}"
                for e in engines:
                    val = row.get(e)
                    line += f"{val:>18.8f}" if val is not None else f"{'N/A':>18}"
                print(line)

        print(f"{'='*80}\n")

    def to_dataframe(self):
        """Convert to pandas DataFrame."""
        import pandas as pd
        return pd.DataFrame(self.differences())

    def to_csv(self, filepath: str) -> None:
        """Export comparison to CSV."""
        df = self.to_dataframe()
        df.to_csv(filepath, index=False)
        logger.info(f"Comparison exported to {filepath}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "instrument_type": self.instrument_type,
            "model_type": self.model_type,
            "reference_engine": self.reference_engine,
            "reference_npv": self.reference_npv,
            "results": self.differences(),
            "greeks": self.greeks_comparison(),
        }


# ---------------------------------------------------------------------------
# Engine discovery
# ---------------------------------------------------------------------------

def discover_compatible_engines(
    instrument_type: str,
    model_type: str = None,
) -> List[str]:
    """
    Discover all registered engines compatible with an instrument type.

    Looks up the engine registry for all keys matching the instrument type.
    """
    compatible = []
    for key in engine_registry.keys():
        if isinstance(key, tuple) and len(key) == 2:
            inst, eng = key
            if inst == instrument_type:
                compatible.append(eng)
    return compatible


# ---------------------------------------------------------------------------
# Engine Comparator
# ---------------------------------------------------------------------------

@dataclass
class EngineComparator:
    """
    Compares pricing results across multiple engines.

    Automatically discovers compatible engines or uses a specified list.
    Prices the same instrument with each engine and produces a
    ComparisonReport with differences, Greeks, and timing.
    """

    pricing_service: PricingService = field(default_factory=PricingService)
    reference_engine: str = "analytic"  # default reference

    def compare(
        self,
        instrument: BaseInstrument,
        market_env: MarketEnvironment,
        model_type: str = "black_scholes",
        engine_types: Optional[List[str]] = None,
        engine_configs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> ComparisonReport:
        """
        Compare an instrument across multiple engines.

        Args:
            instrument:     The instrument to price
            market_env:     Market data environment
            model_type:     Model to use for all engines
            engine_types:   Specific engines to compare. If None, auto-discovers.
            engine_configs: Per-engine parameters. Key = engine_type, value = params dict.

        Returns:
            ComparisonReport with all results
        """
        inst_type = instrument.instrument_type().value
        engine_configs = engine_configs or {}

        # Discover engines
        if engine_types is None:
            engine_types = discover_compatible_engines(inst_type)
            if not engine_types:
                logger.warning(f"No engines found for {inst_type}")

        # Determine reference engine
        ref = self.reference_engine
        if ref not in engine_types and engine_types:
            ref = engine_types[0]

        report = ComparisonReport(
            trade_id=str(instrument.trade_id()),
            instrument_type=inst_type,
            model_type=model_type,
            reference_engine=ref,
        )

        logger.info(
            f"Comparing {len(engine_types)} engines for {instrument.trade_id()}: "
            f"{engine_types}"
        )

        # Price with each engine
        for eng_type in engine_types:
            params = engine_configs.get(eng_type, {})
            result = self._price_with_engine(
                instrument, market_env, model_type, eng_type, params
            )
            report.results.append(result)

        return report

    def compare_convergence(
        self,
        instrument: BaseInstrument,
        market_env: MarketEnvironment,
        model_type: str = "black_scholes",
        engine_type: str = "finite_difference",
        param_name: str = "spot_steps",
        param_values: List[Any] = None,
        base_params: Optional[Dict[str, Any]] = None,
    ) -> ComparisonReport:
        """
        Convergence study: price with one engine at multiple param values.

        Useful for studying how FD grid size, MC paths, or binomial steps
        affect accuracy.

        Args:
            instrument:   Instrument to price
            market_env:   Market data
            model_type:   Model
            engine_type:  Engine to study
            param_name:   Parameter to vary (e.g., "spot_steps", "num_paths")
            param_values: Values to test
            base_params:  Base engine parameters

        Returns:
            ComparisonReport with one result per param value
        """
        base_params = base_params or {}
        if param_values is None:
            param_values = [50, 100, 200, 500, 1000]

        report = ComparisonReport(
            trade_id=str(instrument.trade_id()),
            instrument_type=instrument.instrument_type().value,
            model_type=model_type,
            reference_engine=f"{engine_type}_{param_name}={param_values[-1]}",
        )

        # First, get analytic reference if available
        try:
            ref_result = self._price_with_engine(
                instrument, market_env, model_type, "analytic", {}
            )
            ref_result.engine_type = "analytic (reference)"
            report.results.append(ref_result)
            report.reference_engine = "analytic (reference)"
        except Exception:
            pass

        # Run at each param value
        for val in param_values:
            params = {**base_params, param_name: val}
            label = f"{engine_type}_{param_name}={val}"

            result = self._price_with_engine(
                instrument, market_env, model_type, engine_type, params
            )
            result.engine_type = label
            report.results.append(result)

        return report

    def _price_with_engine(
        self,
        instrument: BaseInstrument,
        market_env: MarketEnvironment,
        model_type: str,
        engine_type: str,
        engine_params: Dict[str, Any],
    ) -> EngineResult:
        """Price with a single engine, capturing all diagnostics."""
        t0 = time.perf_counter()

        try:
            pricing_result = self.pricing_service.price(
                instrument=instrument,
                market_env=market_env,
                model_type=model_type,
                engine_type=engine_type,
                engine_params=engine_params,
            )

            elapsed = time.perf_counter() - t0

            # Extract Greeks if available
            greeks = {}
            diag = pricing_result.diagnostics or {}

            # Try to get Greeks from FD diagnostics
            if "fd_greeks" in diag:
                greeks.update(diag["fd_greeks"])

            # Try to get Greeks from MC diagnostics
            if "mc_greeks" in diag:
                greeks.update(diag["mc_greeks"])

            # Try QuantLib built-in Greeks
            if not greeks:
                try:
                    market_env.set_evaluation_date()
                    ModelClass = model_registry.get(model_type)
                    model = ModelClass()
                    if hasattr(model, "underlying") and hasattr(instrument, "underlying"):
                        model.underlying = instrument.underlying

                    EngineClass = engine_registry.get(
                        (instrument.instrument_type().value, engine_type)
                    )
                    engine_instance = EngineClass(**{
                        k: v for k, v in engine_params.items()
                        if hasattr(EngineClass, k)
                    }) if engine_params else EngineClass()

                    ql_engine = engine_instance.build(model, market_env)
                    ql_inst = instrument.build(market_env)
                    ql_inst.setPricingEngine(ql_engine)

                    for greek_name in ["delta", "gamma", "vega", "theta", "rho"]:
                        try:
                            val = getattr(ql_inst, greek_name)()
                            if greek_name == "vega":
                                val = val / 100.0
                            elif greek_name == "rho":
                                val = val / 100.0
                            greeks[greek_name] = float(val)
                        except Exception:
                            pass
                except Exception:
                    pass

            return EngineResult(
                engine_type=engine_type,
                npv=pricing_result.npv,
                greeks=greeks,
                diagnostics={
                    k: v for k, v in diag.items()
                    if k not in ("mc_result_ref", "fd_result_ref")
                },
                elapsed_seconds=elapsed,
            )

        except Exception as e:
            elapsed = time.perf_counter() - t0
            logger.warning(f"Engine '{engine_type}' failed: {e}")
            return EngineResult(
                engine_type=engine_type,
                npv=float("nan"),
                elapsed_seconds=elapsed,
                error=str(e),
            )


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

def quick_compare(
    instrument: BaseInstrument,
    market_env: MarketEnvironment,
    model_type: str = "black_scholes",
) -> None:
    """
    Quick comparison — discover all engines and print summary.

    Usage:
        quick_compare(option, market_env)
    """
    comp = EngineComparator()
    report = comp.compare(instrument, market_env, model_type)
    report.print_summary()


def convergence_study(
    instrument: BaseInstrument,
    market_env: MarketEnvironment,
    engine_type: str = "finite_difference",
    param_name: str = "spot_steps",
    param_values: List[Any] = None,
) -> None:
    """
    Quick convergence study — print results.

    Usage:
        convergence_study(option, market_env, "finite_difference", "spot_steps", [50, 100, 200, 500])
    """
    comp = EngineComparator()
    report = comp.compare_convergence(
        instrument, market_env,
        engine_type=engine_type,
        param_name=param_name,
        param_values=param_values,
    )
    report.print_summary()