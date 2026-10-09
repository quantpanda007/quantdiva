"""Guard: the runtime QuantLib must be the version pinned by the project.

IRS valuations depend on QuantLib release behaviour (e.g. holiday-start overnight
accrual changed in 1.43). A different runtime version must fail loudly rather
than silently shift results. To upgrade: change both pins, then rerun the IRS
regression tests and review every difference.
"""

from __future__ import annotations

import re
from pathlib import Path

import QuantLib as ql

ROOT = Path(__file__).resolve().parents[3]


def _pyproject_pin() -> str:
    # Regex rather than tomllib so the guard also runs on Python 3.10 (requires-python).
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    pins = re.findall(r'^\s*"QuantLib\s*==\s*([0-9][0-9.]*)"\s*,', text, re.MULTILINE)
    assert len(pins) == 1, f"expected exactly one QuantLib== pin, found {pins}"
    return pins[0]


def _environment_pin() -> str:
    text = (ROOT / "environment.yml").read_text(encoding="utf-8")
    pins = re.findall(r"^\s*-\s*quantlib-python\s*==\s*([0-9][0-9.]*)\s*$", text, re.MULTILINE)
    assert len(pins) == 1, f"expected exactly one quantlib-python== pin, found {pins}"
    return pins[0]


def test_dependency_pins_agree():
    assert _pyproject_pin() == _environment_pin() == "1.43"


def test_runtime_quantlib_matches_pin():
    assert ql.__version__ == _pyproject_pin(), (
        f"QuantLib {ql.__version__} is installed but the project pins {_pyproject_pin()}; "
        "recreate the environment from environment.yml / pyproject.toml"
    )
