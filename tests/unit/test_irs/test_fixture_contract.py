"""Parsing checks for the separated Bloomberg IRS fixture contract."""

import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from core.enums.definitions import DayCountConvention, Frequency
from core.types.value_objects import Money
from instruments.rates.irs.domain import (
    IRSLegTerms,
    IRSTrade,
    ObservationConventions,
    PrincipalRepayment,
)
from market.curves.irs_market_data import (
    DiscountCurveMarketData,
    DiscountFactorObservation,
    IRSMarketData,
    SimpleForwardCurveMarketData,
    SimpleForwardObservation,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CASE_PATH = REPOSITORY_ROOT / "tests/fixtures/bloomberg_irs/cases/TC1.json"
MARKET_DATA_PATH = (
    REPOSITORY_ROOT / "market_data/2026-03-31/USD/market_data.json"
)
REFERENCE_PATH = (
    REPOSITORY_ROOT / "tests/fixtures/bloomberg_irs/references/TC1.json"
)
IRS_FIXTURE_ROOT = REPOSITORY_ROOT / "tests/fixtures/bloomberg_irs"


def _frequency(value: str) -> Frequency:
    return {
        "Annual": Frequency.ANNUAL,
        "Semiannual": Frequency.SEMIANNUAL,
        "Quarterly": Frequency.QUARTERLY,
        "Monthly": Frequency.MONTHLY,
        "Weekly": Frequency.WEEKLY,
        "Daily": Frequency.DAILY,
        "Once": Frequency.ONCE,
    }[value]


def _day_count(value: str) -> DayCountConvention:
    return {
        "ACT/360": DayCountConvention.ACT_360,
        "ACT/365": DayCountConvention.ACT_365,
        "ACT/ACT": DayCountConvention.ACT_ACT,
        "30/360": DayCountConvention.THIRTY_360,
    }[value]


def _money(value: dict) -> Money:
    return Money(Decimal(str(value["amount"])), value["currency"])


def _leg(leg: dict) -> IRSLegTerms:
    repayments = tuple(
        PrincipalRepayment(
            payment_date=date.fromisoformat(item["payment_date"]),
            amount=_money(item["amount"]),
        )
        for item in leg["principal_repayments"]
    )
    shared = {
        "kind": leg["kind"],
        "payment_frequency": _frequency(leg["payment_frequency"]),
        "day_count": _day_count(leg["day_count"]),
        "original_notional": _money(leg["original_notional"]),
        "principal_repayments": repayments,
    }
    if leg["kind"] == "fixed":
        # The fixture stores the rate as a percentage; the domain stores a
        # normalized decimal rate.
        return IRSLegTerms(
            **shared,
            fixed_coupon_rate=Decimal(str(leg["fixed_coupon"]["value"])) / 100,
        )

    spread = leg["floating_spread"]
    observation_data = leg["observation"]
    return IRSLegTerms(
        **shared,
        benchmark=leg["benchmark"],
        benchmark_tenor=leg["benchmark_tenor"],
        # The fixture stores bps; the domain stores a normalized decimal rate.
        floating_spread_rate=Decimal(str(spread["value"])) / 10000,
        floating_leverage=Decimal(str(leg["leverage"])),
        reset_frequency=_frequency(leg["reset_frequency"]),
        observation=ObservationConventions(
            lookback_days=observation_data["lookback_days"],
            cutoff_days=observation_data["cutoff_days"],
            reset_timing=observation_data["reset_timing"],
            compounding=observation_data["compounding"],
            lookback_type=observation_data["lookback_type"],
        ),
    )


def test_tc1_case_and_market_data_parse_into_existing_domain_objects():
    case = json.loads(CASE_PATH.read_text(encoding="utf-8"))
    market_data = json.loads(MARKET_DATA_PATH.read_text(encoding="utf-8"))
    trade_data = case["trade"]

    trade = IRSTrade(
        trade_id=trade_data["trade_id"],
        currency=trade_data["currency"],
        valuation_date=date.fromisoformat(trade_data["valuation_date"]),
        effective_date=date.fromisoformat(trade_data["effective_date"]),
        maturity_date=date.fromisoformat(trade_data["maturity_date"]),
        pay_leg=_leg(trade_data["pay_leg"]),
        receive_leg=_leg(trade_data["receive_leg"]),
        principal_exchange=trade_data["principal_exchange"],
    )

    observations = market_data["observations"]
    irs_market = IRSMarketData(
        discount_curve=DiscountCurveMarketData(
            reference_date=date.fromisoformat(market_data["reference_date"]),
            currency=market_data["currency"],
            observations=tuple(
                DiscountFactorObservation(
                    date.fromisoformat(point["date"]),
                    Decimal(str(point["discount_factor"])),
                )
                for point in observations
            ),
        ),
        projection_curve=SimpleForwardCurveMarketData(
            reference_date=date.fromisoformat(market_data["reference_date"]),
            currency=market_data["currency"],
            benchmark=market_data["benchmark"],
            observations=tuple(
                SimpleForwardObservation(
                    date.fromisoformat(point["date"]),
                    Decimal(str(point["market_rate"])),
                )
                for point in observations
            ),
        ),
    )

    assert trade.trade_id == "SLLSL9RR"
    assert trade.pay_leg.fixed_coupon_rate == Decimal("0.05")
    assert trade.receive_leg.floating_spread_rate == Decimal("0.001")
    assert trade.receive_leg.benchmark == "SOFR"
    assert trade.pay_leg.principal_repayments == trade.receive_leg.principal_repayments
    assert irs_market.discount_curve.reference_date == date(2026, 3, 31)
    assert len(irs_market.discount_curve.observations) == 20
    assert len(irs_market.projection_curve.observations) == 20
    assert [item.rate for item in irs_market.projection_curve.observations] == [
        Decimal(str(item["market_rate"])) for item in observations
    ]
    assert [item.discount_factor for item in irs_market.discount_curve.observations] == [
        Decimal(str(item["discount_factor"])) for item in observations
    ]


def test_tc1_reference_fixture_is_separate_and_contains_only_existing_outputs():
    reference = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))

    assert reference["trade_id"] == "SLLSL9RR"
    assert {item["name"]: item["value"] for item in reference["outputs"]} == {
        "fixed_leg_npv": -31978.74,
        "floating_leg_npv": 24023.74,
        "total_npv": -7955.0,
    }
    assert all(item["unit_status"] == "not_stated" for item in reference["outputs"])


def _source_trade_id(case_id: str, source: dict) -> str:
    if case_id == "TC10":
        return source["trade"]["trade_id"]
    return source["trade"]["swap_id"]


def _expected_oracle_sections(case_id: str, source: dict) -> dict:
    number = int(case_id[2:])
    if number == 1:
        sections = {
            key: source[key]
            for key in (
                "cashflow",
                "cashflow_leg_1",
                "cashflow_leg_2",
                "valuation_results",
                "risk",
            )
        }
        sections["leg_1_market"] = source["leg_1"]["market"]
        sections["leg_2_market"] = source["leg_2"]["market"]
        return sections
    if number <= 5:
        return {
            "leg_1_market": source["leg_1"]["market"],
            "leg_2_market": source["leg_2"]["market"],
            **{
                key: source[key]
                for key in (
                    "cashflow",
                    "cashflow_leg_1",
                    "cashflow_leg_2",
                    "valuation_results",
                    "risk",
                )
            },
        }
    if number <= 9:
        trade = source["trade"]
        return {
            "leg_valuation_metrics": {
                leg_name: {
                    key: leg[key]
                    for key in ("npv", "accrued", "premium", "dv01")
                    if key in leg
                }
                for leg_name, leg in trade["legs"].items()
            },
            "valuation_results": trade["valuation_results"],
            "cashflows": trade["cashflows"],
        }
    return {
        key: source[key]
        for key in (
            "valuation",
            "leg_valuation",
            "net_cashflows",
            "fixed_leg_cashflows",
            "floating_leg_cashflows",
        )
    }


def _expected_input_sections(case_id: str, source: dict) -> dict:
    number = int(case_id[2:])
    if number == 1:
        return {}
    if number <= 5:
        leg_1 = dict(source["leg_1"])
        leg_2 = dict(source["leg_2"])
        market_curve_references = {}
        for leg_name, leg in (("leg_1", leg_1), ("leg_2", leg_2)):
            market = leg.pop("market", {})
            curve_names = {key: value for key, value in market.items() if key.endswith("_curve")}
            if curve_names:
                market_curve_references[leg_name] = curve_names
        return {
            "trade": source["trade"],
            "leg_1": leg_1,
            "leg_2": leg_2,
            "additional_detail": source["additional_detail"],
            "market_curve_references": market_curve_references,
        }
    if number <= 9:
        trade = json.loads(json.dumps(source["trade"]))
        trade.pop("valuation_results", None)
        trade.pop("cashflows", None)
        for leg in trade.get("legs", {}).values():
            for key in ("npv", "accrued", "premium", "dv01"):
                leg.pop(key, None)
        return {"trade": trade}
    keys = (
        "trade", "fixed_leg", "floating_leg", "amortization_schedule",
        "additional_details", "fee_schedule", "market_data",
    )
    return {key: source[key] for key in keys if key in source}


def test_tc1_to_tc10_sources_cases_and_references_are_complete_and_untransformed():
    manifest_path = IRS_FIXTURE_ROOT / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert set(manifest["cases"]) == {f"TC{i}" for i in range(1, 11)}

    for number in range(1, 11):
        case_id = f"TC{number}"
        source_path = IRS_FIXTURE_ROOT / "source" / f"{case_id}.json"
        case_path = IRS_FIXTURE_ROOT / "cases" / f"{case_id}.json"
        reference_path = IRS_FIXTURE_ROOT / "references" / f"{case_id}.json"

        source_bytes = source_path.read_bytes()
        source = json.loads(source_bytes)
        case = json.loads(case_path.read_text(encoding="utf-8"))
        reference = json.loads(reference_path.read_text(encoding="utf-8"))
        source_trade_id = _source_trade_id(case_id, source)

        assert case["case_id"] == reference["case_id"] == case_id
        assert reference["trade_id"] == source_trade_id
        assert manifest["cases"][case_id]["trade_id"] == source_trade_id
        assert hashlib.sha256(source_bytes).hexdigest() == manifest["cases"][case_id]["sha256"]
        assert reference["source_oracle_sections"] == _expected_oracle_sections(case_id, source)
        assert reference["source_oracle_sections"]

        if number == 1:
            assert source.keys() >= {
                "trade", "leg_1", "leg_2", "additional_detail", "cashflow",
                "cashflow_leg_1", "cashflow_leg_2", "valuation_results", "risk",
            }
            # This is the canonicalized domain-facing case. The immutable raw
            # source above retains the residual 10^3 leg-amortization values.
            assert case["trade"]["notional"]["amount"] == 530000
            assert case["trade"]["pay_leg"]["original_notional"]["amount"] == 530000
            assert case["trade"]["receive_leg"]["original_notional"]["amount"] == 530000
            assert case["trade"]["receive_leg"]["benchmark"] == "SOFR"
            assert case["trade"]["amortization_source"]["period_notionals"][1]["notional"] == 265000
            assert case["schedule_inputs"]["pay_leg"]["explicit_accrual_boundaries"] == [
                "2026-05-31", "2027-05-28", "2027-11-30"
            ]
        elif number <= 5:
            assert case["input_sections"] == _expected_input_sections(case_id, source)
            assert case["input_sections"].keys() >= {
                "trade", "leg_1", "leg_2", "additional_detail"
            }
            assert "market" not in case["input_sections"]["leg_1"]
            assert "market" not in case["input_sections"]["leg_2"]
        elif number <= 9:
            assert case["input_sections"] == _expected_input_sections(case_id, source)
            assert case["input_sections"]["trade"].keys() >= {
                "swap_id", "legs", "additional_detail"
            }
            assert "valuation_results" not in case["input_sections"]["trade"]
            assert "cashflows" not in case["input_sections"]["trade"]
        else:
            assert case["input_sections"] == _expected_input_sections(case_id, source)
            assert case["input_sections"].keys() >= {
                "trade", "fixed_leg", "floating_leg", "amortization_schedule"
            }
            assert "valuation" not in case["input_sections"]
