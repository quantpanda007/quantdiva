"""
Central registry system for the pricing platform.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Generic, List, Optional, Tuple, Type, TypeVar

from core.exceptions.errors import (
    DuplicateRegistrationError,
    NotRegisteredError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Generic Registry
# ---------------------------------------------------------------------------

class Registry(Generic[T]):
    """
    Generic registry that maps keys to classes/factories.
    """

    def __init__(self, name: str):
        self.name = name
        self._store: Dict[Any, T] = {}

    def register(self, key: Any, value: T, overwrite: bool = False) -> None:
        """Register an item under the given key."""
        if key in self._store:
            existing = self._store[key]

            # Safe re-import (pytest/module reload)
            if existing is value:
                return

            if not overwrite:
                raise DuplicateRegistrationError(
                    f"[{self.name}] Key '{key}' already registered with "
                    f"{existing}. Cannot register {value} without overwrite=True."
                )

        self._store[key] = value
        logger.debug(f"[{self.name}] Registered: {key} → {value}")

    def register_decorator(self, key: Any, overwrite: bool = False) -> Callable:
        """Decorator form of register."""
        def decorator(cls: T) -> T:
            self.register(key, cls, overwrite=overwrite)
            return cls
        return decorator

    def get(self, key: Any) -> T:
        """Lookup a registered item."""
        if key not in self._store:
            available = list(self._store.keys())
            raise NotRegisteredError(
                f"[{self.name}] Key '{key}' not registered. Available: {available}"
            )
        return self._store[key]

    def get_or_none(self, key: Any) -> Optional[T]:
        return self._store.get(key)

    def has(self, key: Any) -> bool:
        return key in self._store

    def keys(self) -> List[Any]:
        return list(self._store.keys())

    def items(self) -> List[Tuple[Any, T]]:
        return list(self._store.items())

    def __contains__(self, key: Any) -> bool:
        return key in self._store

    def __len__(self) -> int:
        return len(self._store)

    def __repr__(self) -> str:
        return f"Registry('{self.name}', entries={len(self._store)})"


# ---------------------------------------------------------------------------
# Pricer Configuration Object  ← ⭐ THIS WAS MISSING
# ---------------------------------------------------------------------------

class PricerConfig:
    """
    Maps an instrument type to its default model and engine.
    """

    def __init__(
        self,
        instrument_type: str,
        model_type: str,
        engine_type: str,
        engine_params: Optional[Dict[str, Any]] = None,
    ):
        self.instrument_type = instrument_type
        self.model_type = model_type
        self.engine_type = engine_type
        self.engine_params = engine_params or {}

    def __repr__(self) -> str:
        return (
            f"PricerConfig({self.instrument_type} → "
            f"model={self.model_type}, engine={self.engine_type})"
        )


# ---------------------------------------------------------------------------
# Singleton Registry Instances
# ---------------------------------------------------------------------------

instrument_registry: Registry[Type] = Registry("InstrumentRegistry")
engine_registry: Registry[Type] = Registry("EngineRegistry")
model_registry: Registry[Type] = Registry("ModelRegistry")
pricer_config_registry: Registry[PricerConfig] = Registry("PricerConfigRegistry")
curve_registry: Registry[Type] = Registry("CurveRegistry")
calibrator_registry: Registry[Type] = Registry("CalibratorRegistry")
