"""
Binomial tree pricing engines — European, American, and Bermudan.

Tree methods are the workhorse for American/Bermudan options where
no closed-form solution exists. At each node the tree checks whether
early exercise is optimal.

Supported tree types:
- CRR (Cox-Ross-Rubinstein) — default, most common
- JR (Jarrow-Rudd) — equal probability tree
- Tian — moment-matching tree
- LR (Leisen-Reimer) — converges faster, odd steps recommended
- Joshi4 — 4th-order convergence

Usage:
    from engines.lattice.binomial_engine import BinomialEngine

    # Default CRR tree with 500 steps
    engine = BinomialEngine(steps=500, tree_type="crr")
    ql_engine = engine.build(model, market_env)

    # LR tree (faster convergence)
    engine = BinomialEngine(steps=501, tree_type="lr")  # odd steps for LR
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import QuantLib as ql

from core.enums.definitions import EngineType, InstrumentType, ModelType
from core.exceptions.errors import EngineError, IncompatibleEngineError
from core.interfaces.base import BaseEngine, BaseModel, MarketEnvironment
from registry import engine_registry


# ---------------------------------------------------------------------------
# Tree type mapping
# ---------------------------------------------------------------------------

# Maps our string names to QuantLib tree builder class names.
# These are used as the first argument to ql.BinomialVanillaEngine.
TREE_TYPES = {
    "crr": "CoxRossRubinstein",
    "cox_ross_rubinstein": "CoxRossRubinstein",
    "jr": "JarrowRudd",
    "jarrow_rudd": "JarrowRudd",
    "tian": "Tian",
    "lr": "LeisenReimer",
    "leisen_reimer": "LeisenReimer",
    "joshi4": "Joshi4",
}


# ---------------------------------------------------------------------------
# Binomial Engine
# ---------------------------------------------------------------------------

@engine_registry.register_decorator(
    (InstrumentType.VANILLA_OPTION.value, EngineType.BINOMIAL.value), overwrite=True
)
@dataclass
class BinomialEngine(BaseEngine):
    """
    Binomial tree engine for vanilla options.

    Handles European, American, and Bermudan exercise naturally —
    the tree checks early exercise at each node.

    Attributes:
        steps:      Number of tree steps (higher = more accurate, slower).
                    Recommended: 200-1000. For LR, use odd numbers.
        tree_type:  Tree algorithm: "crr", "jr", "tian", "lr", "joshi4"

    Convergence behavior:
        - CRR: oscillates, converges as O(1/N)
        - LR: smooth convergence, O(1/N^2) with odd steps
        - Tian: similar to CRR but better moment matching
        - Joshi4: O(1/N^4) — fastest convergence but more complex

    Performance:
        - 100 steps:  ~1ms   (rough estimate)
        - 500 steps:  ~10ms  (good for single trades)
        - 1000 steps: ~50ms  (production quality)
        - 5000 steps: ~1s    (benchmark quality)
    """

    steps: int = 500
    tree_type: str = "crr"

    def engine_type(self) -> EngineType:
        return EngineType.BINOMIAL

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.VANILLA_OPTION]

    def supported_models(self) -> List[ModelType]:
        return [ModelType.BLACK_SCHOLES]

    def build(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        **kwargs,
    ) -> ql.PricingEngine:
        """
        Build a QuantLib BinomialVanillaEngine.

        The engine works for European, American, AND Bermudan options —
        QuantLib's binomial engine automatically handles the exercise
        type based on the option's exercise object.
        """
        if model.model_type() != ModelType.BLACK_SCHOLES:
            raise IncompatibleEngineError(
                f"BinomialEngine requires BLACK_SCHOLES model, "
                f"got {model.model_type()}"
            )

        # Resolve tree type
        tree_name = TREE_TYPES.get(self.tree_type.lower())
        if tree_name is None:
            raise EngineError(
                f"Unknown tree type: '{self.tree_type}'. "
                f"Available: {list(TREE_TYPES.keys())}"
            )

        # Warn about even steps for LR
        if tree_name == "LeisenReimer" and self.steps % 2 == 0:
            import logging
            logging.getLogger(__name__).warning(
                f"LeisenReimer tree works best with odd step count. "
                f"Got {self.steps}, consider {self.steps + 1}."
            )

        # Build process
        process = model.build_process(market_env)

        # Build engine using QuantLib's string-based tree selector
        engine = ql.BinomialVanillaEngine(process, tree_name, self.steps)
        return engine

    def __repr__(self) -> str:
        return f"BinomialEngine(steps={self.steps}, tree={self.tree_type})"


# ---------------------------------------------------------------------------
# Also register under a more explicit key for American
# ---------------------------------------------------------------------------

@engine_registry.register_decorator(
    (InstrumentType.VANILLA_OPTION.value, "binomial_american"), overwrite=True
)
@dataclass
class BinomialAmericanEngine(BinomialEngine):
    """
    Convenience alias — BinomialEngine with defaults tuned for American options.

    Uses CRR tree with 800 steps for good accuracy.
    """
    steps: int = 800
    tree_type: str = "crr"


@engine_registry.register_decorator(
    (InstrumentType.VANILLA_OPTION.value, "binomial_bermudan"), overwrite=True
)
@dataclass
class BinomialBermudanEngine(BinomialEngine):
    """
    Convenience alias — BinomialEngine with defaults tuned for Bermudan options.

    Uses Tian tree with 800 steps.
    Note: QuantLib's binomial engine handles Bermudan exercise dates
    automatically based on the option's BermudanExercise object.
    """
    steps: int = 800
    tree_type: str = "tian"
