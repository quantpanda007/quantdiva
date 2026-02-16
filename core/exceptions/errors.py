"""
Domain-specific exception hierarchy for the pricing platform.

Organized by subsystem so error handling can be targeted.
"""


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class PricingPlatformError(Exception):
    """Root exception for the entire platform."""
    pass


# ---------------------------------------------------------------------------
# Instrument Errors
# ---------------------------------------------------------------------------

class InstrumentError(PricingPlatformError):
    """Base for instrument-related errors."""
    pass


class InstrumentBuildError(InstrumentError):
    """Failed to construct QuantLib instrument."""
    pass


class UnsupportedInstrumentError(InstrumentError):
    """Instrument type not recognized or not implemented."""
    pass


# ---------------------------------------------------------------------------
# Engine Errors
# ---------------------------------------------------------------------------

class EngineError(PricingPlatformError):
    """Base for pricing engine errors."""
    pass


class EngineNotFoundError(EngineError):
    """No engine registered for this instrument/model combination."""
    pass


class EngineConvergenceError(EngineError):
    """Numerical engine failed to converge."""
    pass


class IncompatibleEngineError(EngineError):
    """Engine does not support the given instrument or model."""
    pass


# ---------------------------------------------------------------------------
# Model Errors
# ---------------------------------------------------------------------------

class ModelError(PricingPlatformError):
    """Base for model errors."""
    pass


class CalibrationError(ModelError):
    """Model calibration failed."""
    def __init__(self, message: str, residuals: dict = None):
        super().__init__(message)
        self.residuals = residuals or {}


class InvalidParameterError(ModelError):
    """Model parameters are out of valid range."""
    pass


# ---------------------------------------------------------------------------
# Market Data Errors
# ---------------------------------------------------------------------------

class MarketDataError(PricingPlatformError):
    """Base for market data errors."""
    pass


class MissingMarketDataError(MarketDataError):
    """Required market data not found."""
    def __init__(self, data_type: str, key: str):
        super().__init__(f"Missing {data_type}: {key}")
        self.data_type = data_type
        self.key = key


class StaleMarketDataError(MarketDataError):
    """Market data is too old for the requested pricing date."""
    pass


class CurveBootstrapError(MarketDataError):
    """Curve bootstrapping failed."""
    pass


# ---------------------------------------------------------------------------
# Pricing Errors
# ---------------------------------------------------------------------------

class PricingError(PricingPlatformError):
    """A pricing request failed."""
    pass


class DispatchError(PricingError):
    """Could not dispatch pricing request to appropriate pricer."""
    pass


# ---------------------------------------------------------------------------
# Data / Repository Errors
# ---------------------------------------------------------------------------

class DataError(PricingPlatformError):
    """Base for data access errors."""
    pass


class EntityNotFoundError(DataError):
    """Requested entity does not exist."""
    def __init__(self, entity_type: str, entity_id: str):
        super().__init__(f"{entity_type} not found: {entity_id}")
        self.entity_type = entity_type
        self.entity_id = entity_id


class DataIntegrityError(DataError):
    """Data consistency violation."""
    pass


# ---------------------------------------------------------------------------
# Configuration Errors
# ---------------------------------------------------------------------------

class ConfigurationError(PricingPlatformError):
    """Invalid or missing configuration."""
    pass


# ---------------------------------------------------------------------------
# Registry Errors
# ---------------------------------------------------------------------------

class RegistryError(PricingPlatformError):
    """Base for registry errors."""
    pass


class DuplicateRegistrationError(RegistryError):
    """Attempted to register the same key twice."""
    pass


class NotRegisteredError(RegistryError):
    """Requested item not found in registry."""
    pass
