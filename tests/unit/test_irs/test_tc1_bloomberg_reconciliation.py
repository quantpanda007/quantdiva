"""TC1 reconciliation against Bloomberg: recorded baseline and documented differences.

This is a monitoring test, not a validation claim. It does three things:

1. Pins Optima's current TC1 outputs (the "recorded baseline") so any change in
   curve construction, coupon pricing or QuantLib behaviour is detected.
2. Asserts Period 1 against Bloomberg within Bloomberg's display precision.
3. Records the known, unexplained Bloomberg differences explicitly, each tied to
   an open item in docs/IRS_OPEN_ITEMS.md. Nothing is tuned to close them.

Bloomberg values are read from tests/fixtures/bloomberg_irs/references/TC1.json.
The Optima baseline was recorded on 09-Oct-2026 with QuantLib 1.43, Optima's
production leg/swap/engine builders, and the production zero-curve builder fed
from market_data/2026-03-31/USD/2026-03-31-USD-SOFR-zero.json
(lookback 0 from the Bloomberg source; cutoff kept as metadata, lockoutDays=0).

If a baseline assertion fails, do not edit the numbers to make it pass: find the
cause, decide whether the change is intended, and update this file and
docs/IRS_OPEN_ITEMS.md together.
"""

from __future__ import annotations

import pytest

# --- Recorded Optima baseline (QuantLib 1.43) ---------------------------------
BASELINE = {
    "floating_p1_rate_pct": 3.7854551860800054,
    "floating_p2_rate_pct": 3.639707547099463,
    "floating_p1_amount": 20174.373111147495,
    "floating_p2_amount": 4983.366249903682,
    "p1_discount_factor": 0.9583057566822694,
    "p2_discount_factor": 0.9410945591947374,
    "fixed_p1_amount": 26647.22222222227,
    "fixed_p2_amount": 6845.833333333344,
    "fixed_leg_npv": -31978.762958301282,
    "floating_leg_npv": 24023.036754127665,
    "npv": -7955.726204173618,
}
BASELINE_TOLERANCE = {
    "rate_pct": 1e-9,
    "amount": 1e-6,
    "discount_factor": 1e-12,
    "npv": 1e-6,
}

# --- Bloomberg display precision ---------------------------------------------
COUPON_DISPLAY_TOL_PCT = 1e-4  # 0.01 bp; coupons shown to 5 dp of a percent
DF_DISPLAY_TOL = 5e-7  # DFs shown to 6 dp
PAYMENT_TOL = 0.05  # 5-dp coupon band (+/-$0.027) plus zero-rate input rounding

# --- Documented open differences (Optima baseline minus Bloomberg) -------------
# OI-1: 30-Nov-2027 discount factor. Optima's linear zero rate there is
# 0.016 bp below the Bloomberg-implied rate; the DF is 2.6e-6 higher. It acts
# almost entirely through the Period 2 coupon. Pending Bloomberg curve-490
# member list and full-precision zero/DF at 30-Nov-2027.
KNOWN_DIFFERENCES = {
    "p2_discount_factor": (+2.56e-6, 1e-8),
    "floating_p2_rate_pct": (-0.0005425, 1e-6),  # -0.054 bp
    "floating_p2_amount": (-0.7438, 1e-3),
    "floating_leg_npv": (-0.7032, 1e-3),  # the ~$0.70 floating-leg gap
    "fixed_leg_npv": (-0.0230, 1e-3),  # DF effect plus Bloomberg display rounding
    "npv": (-0.7262, 1e-3),
}
# Bands the open differences must stay inside until OI-1 is resolved.
OPEN_ITEM_BANDS = {
    "p2_discount_factor": 5e-6,
    "floating_p2_rate_pct": 1e-3,  # 0.1 bp
    "floating_p2_amount": 1.0,
    "floating_leg_npv": 1.0,
    "fixed_leg_npv": 0.10,
    "npv": 1.0,
}


def _tolerance_for(metric: str) -> float:
    for suffix, tolerance in BASELINE_TOLERANCE.items():
        if metric.endswith(suffix):
            return tolerance
    raise KeyError(metric)


@pytest.fixture(scope="module")
def optima(tc1_valuation) -> dict:
    floating, fixed = tc1_valuation["floating"], tc1_valuation["fixed"]
    return {
        "floating_p1_rate_pct": floating[0]["rate_pct"],
        "floating_p2_rate_pct": floating[1]["rate_pct"],
        "floating_p1_amount": floating[0]["amount"],
        "floating_p2_amount": floating[1]["amount"],
        "p1_discount_factor": floating[0]["discount_factor"],
        "p2_discount_factor": floating[1]["discount_factor"],
        "fixed_p1_amount": fixed[0]["amount"],
        "fixed_p2_amount": fixed[1]["amount"],
        "fixed_leg_npv": tc1_valuation["fixed_leg_npv"],
        "floating_leg_npv": tc1_valuation["floating_leg_npv"],
        "npv": tc1_valuation["npv"],
    }


@pytest.fixture(scope="module")
def bloomberg(tc1_documents) -> dict:
    _, _, reference = tc1_documents
    sections = reference["source_oracle_sections"]
    floating = sections["cashflow_leg_2"]["cashflows"]
    fixed = sections["cashflow_leg_1"]["cashflows"]
    outputs = {item["name"]: item["value"] for item in reference["outputs"]}
    return {
        "floating_p1_rate_pct": floating[0]["equivalent_coupon"],
        "floating_p2_rate_pct": floating[1]["equivalent_coupon"],
        "floating_p1_amount": floating[0]["payment"],
        "floating_p2_amount": floating[1]["payment"],
        "p1_discount_factor": floating[0]["discount_factor"],
        "p2_discount_factor": floating[1]["discount_factor"],
        # Bloomberg shows the paid fixed leg with a negative sign.
        "fixed_p1_amount": -fixed[0]["payment"],
        "fixed_p2_amount": -fixed[1]["payment"],
        "fixed_leg_npv": outputs["fixed_leg_npv"],
        "floating_leg_npv": outputs["floating_leg_npv"],
        "npv": outputs["total_npv"],
    }


# 1. Recorded baseline -----------------------------------------------------------


@pytest.mark.parametrize("metric", sorted(BASELINE))
def test_optima_matches_recorded_baseline(optima, metric):
    assert optima[metric] == pytest.approx(BASELINE[metric], abs=_tolerance_for(metric))


def test_baseline_conventions_are_the_recorded_ones(tc1_valuation):
    assert tc1_valuation["lookback_days"] == 0  # from the Bloomberg source (OI-3)
    assert tc1_valuation["lockout_days"] == 0  # cutoff not mapped (OI-2)


# 2. Reconciled with Bloomberg ----------------------------------------------------


def test_period1_coupon_reconciles(optima, bloomberg):
    assert optima["floating_p1_rate_pct"] == pytest.approx(
        bloomberg["floating_p1_rate_pct"], abs=COUPON_DISPLAY_TOL_PCT
    )


def test_period1_payment_reconciles(optima, bloomberg):
    assert optima["floating_p1_amount"] == pytest.approx(
        bloomberg["floating_p1_amount"], abs=PAYMENT_TOL
    )


def test_period1_discount_factor_reconciles(optima, bloomberg):
    assert optima["p1_discount_factor"] == pytest.approx(
        bloomberg["p1_discount_factor"], abs=DF_DISPLAY_TOL
    )


@pytest.mark.parametrize("metric", ["fixed_p1_amount", "fixed_p2_amount"])
def test_fixed_cashflows_reconcile(optima, bloomberg, metric):
    assert optima[metric] == pytest.approx(bloomberg[metric], abs=0.005)


# 3. Documented open differences (OI-1) ------------------------------------------


@pytest.mark.parametrize("metric", sorted(KNOWN_DIFFERENCES))
def test_open_difference_is_the_documented_one(optima, bloomberg, metric):
    expected, tolerance = KNOWN_DIFFERENCES[metric]
    assert optima[metric] - bloomberg[metric] == pytest.approx(expected, abs=tolerance)


@pytest.mark.parametrize("metric", sorted(OPEN_ITEM_BANDS))
def test_open_difference_stays_inside_its_band(optima, bloomberg, metric):
    assert abs(optima[metric] - bloomberg[metric]) <= OPEN_ITEM_BANDS[metric]


def test_floating_leg_gap_comes_from_period2_projection(optima, bloomberg):
    """OI-1 attribution: Period 2 payment difference, not discounting, drives it."""
    p2_payment_effect = (
        optima["floating_p2_amount"] - bloomberg["floating_p2_amount"]
    ) * bloomberg["p2_discount_factor"]
    total_gap = optima["floating_leg_npv"] - bloomberg["floating_leg_npv"]
    assert p2_payment_effect == pytest.approx(-0.70, abs=0.01)
    assert abs(total_gap - p2_payment_effect) < 0.05
