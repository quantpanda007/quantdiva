"""Integrity inventory for the immutable Bloomberg IRS source/oracle fixtures."""

import hashlib
import json
from pathlib import Path

import pytest  # noqa: E402

# Validation-phase test (reads Bloomberg fixtures): excluded from the default run;
# run with `pytest -m validation`.
pytestmark = pytest.mark.validation


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests/fixtures/bloomberg_irs"
CASE_IDS = {f"TC{i}" for i in range(1, 11)}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_all_ten_bloomberg_sources_cases_and_references_exist():
    manifest = _json(FIXTURE_ROOT / "source_manifest.json")
    assert set(manifest["cases"]) == CASE_IDS
    for folder in ("source", "cases", "references"):
        found = {path.stem for path in (FIXTURE_ROOT / folder).glob("TC*.json")}
        assert found == CASE_IDS


def test_raw_sources_are_valid_hash_preserved_and_have_expected_sections():
    manifest = _json(FIXTURE_ROOT / "source_manifest.json")
    for case_id in sorted(CASE_IDS):
        source_path = FIXTURE_ROOT / "source" / f"{case_id}.json"
        raw = source_path.read_bytes()
        source = json.loads(raw)
        number = int(case_id[2:])

        assert hashlib.sha256(raw).hexdigest() == manifest["cases"][case_id]["sha256"]
        if number <= 5:
            assert source.keys() >= {
                "trade", "leg_1", "leg_2", "additional_detail", "cashflow",
                "cashflow_leg_1", "cashflow_leg_2", "valuation_results", "risk",
            }
        elif number <= 9:
            assert source.keys() == {"trade"}
            assert source["trade"].keys() >= {
                "legs", "additional_detail", "valuation_results", "cashflows"
            }
            assert source["trade"]["legs"].keys() >= {"fixed", "floating"}
        else:
            assert source.keys() >= {
                "trade", "fixed_leg", "floating_leg", "amortization_schedule",
                "valuation", "leg_valuation", "net_cashflows",
                "fixed_leg_cashflows", "floating_leg_cashflows",
            }


def test_references_retain_source_valuation_and_cashflow_sections():
    for number in range(1, 11):
        case_id = f"TC{number}"
        source = _json(FIXTURE_ROOT / "source" / f"{case_id}.json")
        case = _json(FIXTURE_ROOT / "cases" / f"{case_id}.json")
        reference = _json(FIXTURE_ROOT / "references" / f"{case_id}.json")
        oracle = reference["source_oracle_sections"]

        assert case["case_id"] == reference["case_id"] == case_id
        assert reference["trade_id"] == _trade_id(number, source)
        assert oracle
        if number <= 5:
            assert {"cashflow", "cashflow_leg_1", "cashflow_leg_2", "valuation_results"} <= set(oracle)
            assert oracle["cashflow"]["npv"] == source["cashflow"]["npv"]
            assert "npv" in oracle["valuation_results"]
            assert oracle["cashflow_leg_1"]["cashflows"] == source["cashflow_leg_1"]["cashflows"]
            assert oracle["cashflow_leg_2"]["cashflows"] == source["cashflow_leg_2"]["cashflows"]
            assert oracle["valuation_results"] == source["valuation_results"]
            assert len(oracle["cashflow"]["net"]) == len(source["cashflow"]["net"])
        elif number <= 9:
            trade = source["trade"]
            assert {"valuation_results", "cashflows"} <= set(oracle)
            assert "npv" in oracle["valuation_results"]
            assert "net_npv" in oracle["cashflows"]
            assert oracle["valuation_results"] == trade["valuation_results"]
            assert oracle["cashflows"] == trade["cashflows"]
            assert len(oracle["cashflows"]["net_cashflows"]) == len(
                trade["cashflows"]["net_cashflows"]
            )
        else:
            assert "trade_npv" in oracle["valuation"]
            for key in (
                "valuation", "leg_valuation", "net_cashflows",
                "fixed_leg_cashflows", "floating_leg_cashflows",
            ):
                assert oracle[key] == source[key]


def _trade_id(number: int, source: dict) -> str:
    if number == 10:
        return source["trade"]["trade_id"]
    if number <= 5:
        return source["trade"]["swap_id"]
    return source["trade"]["swap_id"]
