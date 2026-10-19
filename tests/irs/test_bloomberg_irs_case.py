import json
from pathlib import Path


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "bloomberg_irs_case.json"
)


def test_bloomberg_irs_fixture_is_structurally_complete():
    case = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert case["case_id"] == "SLLSL9RR"
    trade = case["trade"]
    assert trade["trade_id"] == "SLLSL9RR"
    assert trade["currency"] == "USD"
    assert trade["notional"] == {"amount": 530000, "currency": "USD"}
    assert trade["effective_date"] == "2026-05-31"
    assert trade["maturity_date"] == "2027-11-30"

    fixed = trade["fixed_leg"]
    assert fixed["direction"] == "payer"
    assert fixed["rate_percent"] == 5.0
    assert fixed["payment_frequency"] == "Annual"
    assert fixed["day_count"] == "ACT/360"

    floating = trade["floating_leg"]
    assert floating["direction"] == "receiver"
    assert floating["index"] == "SOFR"
    assert floating["index_tenor"] == "1D"
    assert floating["reset_frequency"] == "Daily"
    assert floating["payment_frequency"] == "Annual"
    assert floating["day_count"] == "ACT/360"
    assert floating["spread_bps"] == 10
    assert floating["leverage"] == 1.0

    conventions = case["conventions"]
    assert conventions["rate_cutoff_days"] == 1
    assert conventions["lookback_days"] == 1
    assert conventions["days_before_type"] == "Lookback"
    assert conventions["reset_type"] == "In Arrears"
    assert conventions["compounding"] == "ExcludeSprd"
    assert conventions["business_day_convention"] == {
        "source_label": "Mod Roll",
        "normalized_name": "Modified Following",
    }
    assert conventions["schedule_generation"] == "Backward"
    assert trade["principal_exchange"] == "Never"

    amortization = trade["amortization"]
    assert amortization["reduction_percent"] == 50
    assert amortization["reduction_amount"] == 265000
    assert amortization["remaining_notional"] == 265000
    schedule = amortization["schedule"]
    assert schedule[0] == {
        "period_start": "2026-05-31",
        "period_end": "2027-05-28",
        "notional": 530000,
        "currency": "USD",
    }
    assert schedule[1] == {
        "period_start": "2027-05-28",
        "period_end": "2027-11-30",
        "notional": 265000,
        "currency": "USD",
    }
    assert amortization["reduction_between_coupon_periods"] == {
        "date": "2027-05-28",
        "from_notional": 530000,
        "to_notional": 265000,
    }
    assert "subsequent periods" in amortization["coupon_notional_rule"]

    market = case["market_environment"]
    assert market["curve_date"] == "2026-03-31"
    assert market["reference_date"] == "2026-03-31"
    assert market["valuation_date"] == "2026-03-31"
    assert case["source"]["market_data_sheet"] == "490-USDSOFR"
    assert "Simple forward rate" in case["source"]["market_data_columns"]["Market Rate"]

    points = market["market_data_points"]
    assert len(points) == 20
    assert all(
        set(point) == {"date", "market_rate", "discount_factor"}
        for point in points
    )
    assert all(
        isinstance(point["market_rate"], (int, float))
        and isinstance(point["discount_factor"], (int, float))
        for point in points
    )

    prohibited_result_fields = {
        "npv",
        "pv",
        "pv01",
        "dv01",
        "cashflow_amounts",
        "equivalent_coupon",
    }
    assert not prohibited_result_fields.intersection(case)
