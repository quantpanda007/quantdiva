"""
Registry endpoints — discover available instruments, models, engines, scenarios.

These are the metadata endpoints that tell the frontend what the platform can do.
Adding a new product/model/engine automatically appears here.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel

from registry import instrument_registry, model_registry, engine_registry
from services.risk.scenario_engine import PREDEFINED_SCENARIOS

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class InstrumentTypeInfo(BaseModel):
    type: str
    class_name: str


class ModelInfo(BaseModel):
    type: str
    class_name: str


class EngineInfo(BaseModel):
    instrument_type: str
    engine_type: str
    class_name: str


class ScenarioInfo(BaseModel):
    key: str
    name: str
    description: str
    shocks: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/instruments", response_model=List[InstrumentTypeInfo])
def list_instruments():
    """List all registered instrument types."""
    results = []
    for key in sorted(instrument_registry.keys()):
        cls = instrument_registry.get(key)
        results.append(InstrumentTypeInfo(
            type=key,
            class_name=cls.__name__ if cls else "unknown",
        ))
    return results


@router.get("/models", response_model=List[ModelInfo])
def list_models():
    """List all registered models."""
    results = []
    for key in sorted(model_registry.keys()):
        cls = model_registry.get(key)
        results.append(ModelInfo(
            type=key,
            class_name=cls.__name__ if cls else "unknown",
        ))
    return results


@router.get("/engines", response_model=List[EngineInfo])
def list_engines():
    """List all registered engines with instrument compatibility."""
    results = []
    for key in sorted(engine_registry.keys(), key=str):
        cls = engine_registry.get(key)
        if isinstance(key, tuple) and len(key) == 2:
            inst_type, eng_type = key
        else:
            inst_type, eng_type = str(key), "unknown"

        results.append(EngineInfo(
            instrument_type=inst_type,
            engine_type=eng_type,
            class_name=cls.__name__ if cls else "unknown",
        ))
    return results


@router.get("/engines/compatibility")
def engine_compatibility():
    """
    Engine compatibility matrix.

    Returns a map of instrument_type → [compatible engine types].
    This is the key metadata for the frontend to know which
    engines to offer for a given instrument.
    """
    compat: Dict[str, List[str]] = {}
    for key in engine_registry.keys():
        if isinstance(key, tuple) and len(key) == 2:
            inst_type, eng_type = key
            if inst_type not in compat:
                compat[inst_type] = []
            compat[inst_type].append(eng_type)

    return compat


@router.get("/scenarios", response_model=List[ScenarioInfo])
def list_scenarios():
    """List all predefined stress scenarios."""
    results = []
    for key, scenario in PREDEFINED_SCENARIOS.items():
        results.append(ScenarioInfo(
            key=key,
            name=scenario.name,
            description=scenario.description or "",
            shocks=[
                {
                    "risk_factor": s.risk_factor,
                    "shock_type": s.shock_type,
                    "value": s.value,
                    "underlying": s.underlying,
                }
                for s in scenario.shocks
            ],
        ))
    return results


@router.get("/schema/{instrument_type}")
def instrument_schema(instrument_type: str):
    """
    Get the parameter schema for a specific instrument type.

    Returns field names, types, and defaults.
    Useful for the frontend to dynamically build forms.
    """
    cls = instrument_registry.get(instrument_type)
    if cls is None:
        return {"error": f"Unknown instrument type: '{instrument_type}'"}

    import inspect
    import dataclasses

    fields = {}
    if dataclasses.is_dataclass(cls):
        for f in dataclasses.fields(cls):
            field_type = str(f.type).replace("typing.", "")
            default = None
            if f.default is not dataclasses.MISSING:
                default = f.default
            elif f.default_factory is not dataclasses.MISSING:
                default = "factory"

            fields[f.name] = {
                "type": field_type,
                "default": default,
                "required": f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING,
            }
    else:
        sig = inspect.signature(cls)
        for name, param in sig.parameters.items():
            fields[name] = {
                "type": str(param.annotation) if param.annotation != inspect.Parameter.empty else "Any",
                "default": param.default if param.default != inspect.Parameter.empty else None,
                "required": param.default == inspect.Parameter.empty,
            }

    return {
        "instrument_type": instrument_type,
        "class_name": cls.__name__,
        "fields": fields,
    }