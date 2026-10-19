"""Curated evidence register for the ten-case IRS reconciliation report.

This module holds judgements, not calculations. Every Optima number in the report is
computed by the production path (``scripts.irs_case_audit``); every Bloomberg number is
read from the reference fixtures, except the supplementary references below, whose
source is stated. What lives here:

* ``SUPPLEMENTARY_BLOOMBERG_REFERENCES``: Bloomberg values that are not in the fixtures
  (TC7 Resets tab). Inspection references only; never pricing inputs.
* ``FINDINGS``: the classification of each material discrepancy, with the evidence and
  the open item (docs/IRS_OPEN_ITEMS.md) that tracks it.
* ``EVIDENCE_REQUESTS``: the minimum additional Bloomberg or SME evidence needed to
  separate the remaining explanations. No request asks for data already in the
  repository or for an instruction the SME has already given.
* ``BLOCKER_ACTIONS``: the minimum next action for each blocker code.

The report checks this register against the run: an out-of-tolerance cashflow without a
finding is reported as "Unresolved - not yet investigated", never as explained.
Bloomberg-derived content: keep local (OI-6).
"""

from __future__ import annotations

from typing import Any, Dict, List

CLASSIFICATIONS = {
    "Explained": "Supported by reproduced calculations and source evidence.",
    "Likely explanation": "Supported by evidence but not yet conclusively verified.",
    "Unresolved": "More than one plausible explanation remains.",
    "Blocked": "Insufficient data or unsupported production capability prevents a "
    "meaningful comparison.",
    "Not comparable": "The Bloomberg and Optima values are different measures or scopes.",
}
NOT_INVESTIGATED = "Unresolved - not yet investigated"

# --- Bloomberg values not held in the fixtures --------------------------------------------

SUPPLEMENTARY_BLOOMBERG_REFERENCES: Dict[str, Dict[str, Any]] = {
    "TC7": {
        "source": "SWPM Resets tab screenshot, 13-Oct-2026 (also pinned in "
        "tests/unit/test_irs/test_irs_tc7_term_rate.py::RESETS_TAB_PCT). SME, 14-Oct-2026: "
        "provided for inspection; not Optima inputs; latest_index is not used to determine "
        "them.",
        "reset_rate_pct": {"2026-08-28": 0.21366, "2027-02-25": 0.33654, "2027-08-27": 0.28763},
    },
}

# --- case descriptions ------------------------------------------------------------------------

# Qualitative features only; the trade structure in the report is generated from the
# Bloomberg source terms (scripts.irs_case_audit.read_terms).
CASE_NOTES: Dict[str, str] = {
    "TC1": "Forward-starting; annual first period and a short second period; amortising.",
    "TC2": "Amortising; quarterly payments on SF0006M (SARON fallback). Priced with Method A "
    "(SARON over the contractual accrual dates, no observation shift): a PROVISIONAL "
    "operational default, not Bloomberg- or SME-confirmed (OI-17). Method B (reset date + 1 "
    "EN business day, 6M IBOR period, 2-day shift; OI-11) is preserved and compared.",
    "TC3": "Forward-starting; amortising; short final stub ending on an adjusted Sunday "
    "maturity.",
    "TC4": "Seasoned: started 01-Jan-2026; Period 1 pays on the valuation date (settled) and "
    "the next floating period starts on it (needs the 31-Mar-2026 SOFR fixing).",
    "TC5": "Forward-starting INR IRSWOF 6M: annual payment with semiannual sub-resets (flat "
    "compounding); short final period.",
    "TC6": "Forward-starting JPY TONA overnight, daily compounding; whole-yen amounts.",
    "TC7": "Forward-starting CHF term-rate fallback leg: semiannual resets in advance, annual "
    "payment, flat compounding; amortising; second period is a single 11-month reset.",
    "TC8": "Seasoned INR IRSWOF 6M: first period in progress at the valuation date (historical "
    "reset 27-Feb-2026); short final period.",
    "TC9": "Forward-starting INR IRSWOF 6M: quarterly payments sharing semiannual resets; "
    "3-month first and 2-month last reset periods.",
    "TC10": "JPY TONA overnight; first floating period starts on the valuation date (needs the "
    "31-Mar-2026 TONA fixing); whole-yen amounts.",
}

# --- findings ---------------------------------------------------------------------------------
# ``match``: (leg, payment_date) of the cashflow rows the finding covers; None = trade level.

_STUB = ("Bloomberg's IRSWOF rate for every reset period shorter than 6M is 23-39 bp below "
         "the 6M forward that reproduces its full 6M resets (TC5 P2 3M: -22.8 bp; TC8 P3 33 "
         "days: -23.2 bp; TC9 P1 3M: -38.8 bp; TC9 P8 2M: -28.2 bp; all six full 6M resets "
         "within 0.3 bp). Not explained by a stub-length forward (still 10-24 bp off) or by "
         "the supplied DF curve (worse). Mechanism unknown (OI-15, R6).")

FINDINGS: Dict[str, List[Dict[str, Any]]] = {
    "TC1": [
        {
            "id": "TC1-F1",
            "match": [("floating", "2027-11-30"), ("fixed", "2027-11-30")],
            "classification": "Unresolved",
            "categories": ["curve construction, pillar selection or interpolation"],
            "statement": "Period 2: coupon -0.054 bp and DF +2.6e-6 vs Bloomberg; floating PV "
            "about -0.68.",
            "evidence": "Period 1 and the 28-May-2027 DF reconcile within display precision. "
            "Bloomberg's own Period 2 coupon and DF are mutually consistent. Input rounding "
            "ruled out (<= 1e-7 in DF). Every tested alternative interpolation breaks the "
            "28-May-2027 control. Remaining hypotheses: curve members between 18M and 2Y not "
            "in the export, a segment-specific convention, an untested interpolation or time "
            "basis, node placement or member payment lag.",
            "open_item": "OI-1",
        },
        {
            "id": "TC1-F2",
            "match": None,
            "classification": "Not comparable",
            "categories": ["rounding and displayed precision"],
            "statement": "Bloomberg's cashflow notional column (530,000,000) is 1,000x the "
            "payment scale; payments are consistent with 530,000.",
            "evidence": "Bloomberg fixed payments / (notional x rate x days) = 0.001 for every "
            "row (audit data-quality check). Notionals are not compared on this case.",
            "open_item": None,
        },
        {
            "id": "TC1-F3",
            "match": None,
            "classification": "Explained",
            "categories": ["observation windows and business-day calendars",
                           "reset/fixing treatment"],
            "statement": "Lookback and rate cutoff are not causes of the TC1 differences.",
            "evidence": "Production reads lookback 0 from the Bloomberg source, and Period 1 "
            "reconciles with it (-0.0005 bp); the case fixture's lookback 1 would move Period 1 "
            "by +0.045 bp, outside display precision (OI-3, fixture unchanged). Rate cutoff 1 "
            "day vs lockout 0 differs by about 0.001 bp on TC1; on the JPY trades (TC6, TC10) "
            "mapping the cutoff to a lockout makes every coupon slightly worse, so the "
            "unmapped treatment is kept (OI-2).",
            "open_item": "OI-2, OI-3",
        },
    ],
    "TC2": [
        {
            "id": "TC2-F1",
            "match": None,
            "classification": "Explained",
            "categories": ["reset/fixing treatment", "fallback methodology and spread adjustment"],
            "statement": "Method B (reset_date_fallback, OI-11): each quarterly coupon is "
            "the SF0006M fallback fixed at the source reset date, its 6M rate period starting "
            "1 EN business day later. Not the configured method since 14-Oct-2026 (OI-17); "
            "computed alongside Method A for comparison.",
            "evidence": "With the production fallback on the SME CHF curve, periods P2-P8 "
            "have observation windows ending exactly on Bloomberg's effective reset dates "
            "(P1 differs by one day, TC2-F2), and their rates match Bloomberg's coupons "
            "(minus the 10 bp "
            "margin) within 0.15 bp (-0.14 to +0.03 bp; Bloomberg shows the coupon to 0.01 bp, "
            "so these are small projection residuals of the same order as TC7's, OI-13). P1 "
            "cannot be priced: its window starts 29-Jan-2026, before the valuation date "
            "(TC2-B1).",
            "open_item": "OI-11",
        },
        {
            "id": "TC2-F2",
            "match": None,
            "classification": "Unresolved",
            "categories": ["reset/fixing treatment", "date generation and business-day rules"],
            "statement": "Method B, P1 observation end: the rule gives Thu 30-Jul-2026; "
            "Bloomberg's effective reset date is Wed 29-Jul-2026 (one Swiss business day "
            "earlier). The production convention is not changed to force a match.",
            "evidence": "Reset Fri 30-Jan-2026 + 1 EN business day = IBOR start Mon "
            "02-Feb-2026; + 6M = Sun 02-Aug, Modified Following -> Mon 03-Aug-2026; "
            "observation window 29-Jan-2026 -> 30-Jul-2026 (each end - 2 Swiss business "
            "days). P1 is the only TC2 period whose 6M end rolls forward over a weekend into "
            "the next month; a Modified Preceding roll would give 29-Jul but is untested as a "
            "general rule. Affects a future observation date only, not the historical-fixing "
            "requirement (R3). Evidence needed: R8.",
            "open_item": "OI-11",
        },
        {
            "id": "TC2-F3",
            "match": [("floating", d) for d in (
                "2026-07-31", "2026-10-30", "2027-01-29", "2027-04-30", "2027-07-30",
                "2027-10-29", "2028-01-31", "2028-02-29")],
            "classification": "Unresolved",
            "categories": ["reset/fixing treatment", "fallback methodology and spread adjustment"],
            "statement": "Method A (configured, provisional): NPV -153.3732 vs Bloomberg "
            "-158.91 (+5.537); every floating coupon differs from Bloomberg's (-5.51 to +6.92 "
            "bp); no Method A observation end equals Bloomberg's effective reset date.",
            "evidence": "Method A observes SARON over the contractual accrual dates with no "
            "shift (an operational assumption: the trade data has no observation-shift term). "
            "On the same curve, fixings and 0.0741% adjustment, Method B reproduces "
            "Bloomberg's P2-P8 coupons within 0.14 bp and its observation ends match "
            "Bloomberg's effective reset dates for P2-P8; it cannot price P1 without SARON "
            "29-Jan -> 30-Mar-2026 (R3). Over P2-P8 the floating PV is A 60.3475, B 55.0119, "
            "Bloomberg 55.18. Neither method is tuned. Which convention applies is for "
            "management/SME (R9).",
            "open_item": "OI-17",
        },
        {
            "id": "TC2-F4",
            "match": [("fixed", d) for d in ("2026-10-30", "2027-10-29", "2028-01-31",
                                             "2028-02-29")],
            "classification": "Unresolved",
            "categories": ["curve construction, pillar selection or interpolation"],
            "statement": "CHF SARON curve discount factors differ from Bloomberg's at four "
            "payment dates by 5.5e-7 to 8.4e-6 (PV effect at most 0.003 each).",
            "evidence": "Fixed-leg amounts match exactly; the difference is discounting only "
            "and is the same under both observation methods. Same SME CHF curve as TC7; cause "
            "not investigated.",
            "open_item": "OI-11",
        },
    ],
    "TC3": [
        {
            "id": "TC3-F1",
            "match": [("floating", "2027-11-30"), ("fixed", "2027-11-30")],
            "classification": "Unresolved",
            "categories": ["curve construction, pillar selection or interpolation"],
            "statement": "Period 3 (same dates as TC1 Period 2): coupon -0.054 bp, DF "
            "+2.56e-6; floating PV about -1.01.",
            "evidence": "Compounded SOFR is identical to TC1 Period 2 once the spread is "
            "removed: one curve difference seen in two trades (OI-1).",
            "open_item": "OI-1",
        },
        {
            "id": "TC3-F2",
            "match": [("floating", "2028-04-28"), ("fixed", "2028-04-28")],
            "classification": "Unresolved",
            "categories": ["curve construction, pillar selection or interpolation"],
            "statement": "Period 4: coupon +0.217 bp, DF -5.3e-6; floating PV about +1.64.",
            "evidence": "First TC case using the curve beyond the 2Y pillar; Periods 1-2 and "
            "all fixed amounts reconcile, so amortisation, spread and stub handling are not "
            "the source. Opposite sign to OI-1; it nets against Period 3 in the leg total.",
            "open_item": "OI-7",
        },
    ],
    "TC4": [
        {
            "id": "TC4-F1",
            "match": None,
            "classification": "Explained",
            "categories": ["valuation-date treatment of seasoned cashflows"],
            "statement": "Period 1 (fixed and floating) pays on the valuation date and is "
            "settled: excluded, exactly as the engine and Bloomberg's cashflow table exclude it.",
            "evidence": "Production cashflow extraction now excludes cashflows paying on or "
            "before the valuation date and lists them as settled (OI-10). The remaining rows "
            "sum exactly to the engine NPV.",
            "open_item": "OI-10",
        },
        {
            "id": "TC4-F2",
            "match": None,
            "classification": "Explained",
            "categories": ["reset/fixing treatment", "historical fixings"],
            "statement": "The 31-Mar-2026 SOFR fixing (3.68%) is applied from market data; "
            "TC4 then reconciles: NPV +0.0033 vs Bloomberg, every cashflow within tolerance.",
            "evidence": "SOFR for 31-Mar-2026 is 3.68% (published 01-Apr-2026; "
            "examples/irs/fixings_2026-03-31.json states the source), equal to the source "
            "latest_index. Without it Optima projects 3.651% and the 30-Jun-2026 payment is "
            "-0.59. The fixing is public market data, not a Bloomberg output; confirm the value "
            "against the NY Fed release (R4).",
            "open_item": "OI-10",
        },
    ],
    "TC5": [
        {
            "id": "TC5-F1",
            "match": [("floating", "2027-09-30")],
            "classification": "Unresolved",
            "categories": ["reset/fixing treatment", "schedule generation and stub periods"],
            "statement": "Period 2 (3-month final period, reset 29-Jun-2027): Optima index "
            "6.7417% vs Bloomberg 6.5137% (equivalent coupon minus 1%): +2,154.84 payment, "
            "+1,963.31 NPV, the whole TC5 difference.",
            "evidence": _STUB + " Bloomberg's row also shows effective reset date 30-Dec-2026, "
            "which is Period 1's sub-reset date, not 29-Jun-2027.",
            "open_item": "OI-15",
        },
        {
            "id": "TC5-F2",
            "match": None,
            "classification": "Explained",
            "categories": ["compounding and day-count conventions"],
            "statement": "Period 1 (annual, two semiannual sub-resets, flat compounding) "
            "reproduces Bloomberg's payment to the cent (559,485.34).",
            "evidence": "Sub-reset period 31-Dec-2026 (Forward EOM roll, the source roll "
            "convention), fixing 30-Dec-2026 (= the effective reset date Bloomberg shows). Both "
            "resets projected by the provisional IRSWOF rule (OI-15).",
            "open_item": "OI-15",
        },
    ],
    "TC6": [
        {
            "id": "TC6-F1",
            "match": [("fixed", "2027-07-30"), ("fixed", "2028-01-31")],
            "classification": "Explained",
            "categories": ["rounding and displayed precision"],
            "statement": "Fixed payments -24,266.67 and -12,333.33 vs Bloomberg -24,266 and "
            "-12,333: Bloomberg shows whole-yen amounts, truncated.",
            "evidence": "Notional x 1% x days/365 gives the Optima amounts exactly; every JPY "
            "fixed row in TC6 and TC10 differs only by the fractional yen.",
            "open_item": "OI-16",
        },
        {
            "id": "TC6-F2",
            "match": [("floating", "2027-01-29"), ("floating", "2027-07-30"),
                      ("floating", "2028-01-31")],
            "classification": "Unresolved",
            "categories": ["curve construction, pillar selection or interpolation",
                           "rounding and displayed precision"],
            "statement": "Floating coupons within -0.0005 / -0.0155 / -0.0076 bp; payments "
            "+0.29 / -2.84 / -0.36 yen (Bloomberg shows whole yen).",
            "evidence": "The JPY curve reproduces Bloomberg's DFs within 1.0e-6 (OI-16). "
            "Mapping the 1-day rate cutoff to a lockout makes all three coupons worse. The "
            "largest residual is in the 12M-18M segment that contains the 15M pillar.",
            "open_item": "OI-16",
        },
    ],
    "TC7": [
        {
            "id": "TC7-F1",
            "match": [("floating", "2027-08-31")],
            "classification": "Unresolved",
            "categories": ["fallback methodology and spread adjustment",
                           "curve construction, pillar selection or interpolation"],
            "statement": "Payment 1: -0.14 + -0.14 NPV from projected resets -0.054 bp "
            "(28-Aug-2026) and -0.052 bp (25-Feb-2027) vs the Resets tab.",
            "evidence": "Optima projected the reset rates itself from the SME's CHF SARON "
            "curve; they were not trade inputs. Bloomberg's resets in the production "
            "flat-compounding function reproduce Bloomberg's payments, so the mechanics are "
            "confirmed. The first-reset gap fell from -0.18 to -0.054 bp when the rate period "
            "start was derived from the reset date (28-Aug + 1 EN business day = 01-Sep-2026, "
            "31-Aug-2026 being a UK holiday; the rule fits TC2 P2-P8, P1 differs by one "
            "day). latest_index "
            "is not used (SME). The remaining gaps equal 2.7e-6 / 2.6e-6 in the DF ratios of "
            "the windows (R1).",
            "open_item": "OI-12, OI-13",
        },
        {
            "id": "TC7-F2",
            "match": [("floating", "2028-07-31")],
            "classification": "Unresolved",
            "categories": ["fallback methodology and spread adjustment",
                           "curve construction, pillar selection or interpolation"],
            "statement": "Payment 2: -0.03, from the projected 27-Aug-2027 reset (-0.014 bp); "
            "DF -2.3e-6 (OI-14).",
            "evidence": "Same projection question as TC7-F1. The DF difference changes this "
            "PV by under 0.001.",
            "open_item": "OI-13, OI-14",
        },
        {
            "id": "TC7-F3",
            "match": [("fixed", "2028-07-31")],
            "classification": "Unresolved",
            "categories": ["curve construction, pillar selection or interpolation"],
            "statement": "31-Jul-2028 DF -2.3e-6 (outside the 5e-7 display band); fixed-leg PV "
            "effect about +0.0005, about +0.0003 net of the floating payment on the same date.",
            "evidence": "Between the 2Y and 3Y pillars; the pillars reproduce curve 234 within "
            "about +/-0.02 bp, so the residual is in the interpolation between them. "
            "Immaterial to NPV; investigation first (OI-14).",
            "open_item": "OI-14",
        },
    ],
    "TC8": [
        {
            "id": "TC8-F1",
            "match": [("floating", "2027-03-31")],
            "classification": "Unresolved",
            "categories": ["reset/fixing treatment", "schedule generation and stub periods"],
            "statement": "Period 3 (33-day final period, reset 25-Feb-2027): Optima 6.5906% vs "
            "Bloomberg 6.35906%: +313.97 payment, +295.52 NPV, the whole TC8 difference.",
            "evidence": _STUB + " With Bloomberg's three resets, the production payment "
            "calculation reproduces Bloomberg's NPV within 0.05.",
            "open_item": "OI-15",
        },
        {
            "id": "TC8-F2",
            "match": None,
            "classification": "Explained",
            "categories": ["historical fixings"],
            "statement": "Period 1 (in progress at the valuation date) uses the historical "
            "IRSWOF fixing of 27-Feb-2026 (5.36%) from market data; payment matches Bloomberg "
            "to the cent. Period 2 (projected) matches to the cent.",
            "evidence": "The fixing value comes from the TC8 trade record (provenance in "
            "examples/irs/fixings_2026-03-31.json); it is not independently sourced (R7).",
            "open_item": "OI-10, OI-15",
        },
    ],
    "TC9": [
        {
            "id": "TC9-F1",
            "match": [("floating", "2026-09-30")],
            "classification": "Unresolved",
            "categories": ["reset/fixing treatment", "schedule generation and stub periods"],
            "statement": "Period 1 (3-month first reset period, reset 29-Jun-2026): Optima "
            "6.1301% vs Bloomberg 5.74185% (= source latest_index): +1,859.35 payment, "
            "+1,806.61 NPV.",
            "evidence": _STUB + " Bloomberg's value equals the trade's latest_index; the SME's "
            "latest_index statement concerns TC7 and is not applied here; no override is used.",
            "open_item": "OI-15",
        },
        {
            "id": "TC9-F2",
            "match": [("floating", "2028-05-31")],
            "classification": "Unresolved",
            "categories": ["reset/fixing treatment", "schedule generation and stub periods"],
            "statement": "Period 8 (2-month final reset period, reset 30-Mar-2028): +28.2 bp, "
            "+111.91 payment, +97.48 NPV.",
            "evidence": _STUB,
            "open_item": "OI-15",
        },
        {
            "id": "TC9-F3",
            "match": [("floating", "2026-12-31"), ("floating", "2027-03-31"),
                      ("floating", "2027-06-30"), ("floating", "2027-09-30")],
            "classification": "Unresolved",
            "categories": ["reset/fixing treatment",
                           "curve construction, pillar selection or interpolation"],
            "statement": "Full 6M resets of 29-Sep-2026 and 30-Mar-2027: -0.20 and -0.28 bp; "
            "-28 NPV in total (TC9's third full reset, 29-Sep-2027, matches within 0.001 bp).",
            "evidence": "The INR curve reproduces Bloomberg's DFs within 4.3e-7, and TC8's "
            "28-Aug-2026 reset matches exactly with the same rule. Small residual of the "
            "provisional IRSWOF projection (OI-15). With all Bloomberg resets, the production "
            "payment calculation reproduces Bloomberg's NPV within 0.013.",
            "open_item": "OI-15",
        },
    ],
    "TC10": [
        {
            "id": "TC10-F1",
            "match": [("fixed", "2027-06-30"), ("floating", "2027-03-31"),
                      ("floating", "2027-06-30")],
            "classification": "Explained",
            "categories": ["rounding and displayed precision", "historical fixings"],
            "statement": "Within 1.3 yen per cashflow: fixed -67,813.70 vs -67,813 (whole yen), "
            "floating +0.14 / -1.21 yen with coupons within 0.002 bp.",
            "evidence": "The first floating period starts on the valuation date and uses the "
            "31-Mar-2026 TONA fixing 0.727% from market data (source stated; R5 to confirm the "
            "daily value). Bloomberg shows whole-yen amounts.",
            "open_item": "OI-16",
        },
    ],
}

# --- evidence requests -------------------------------------------------------------------------

EVIDENCE_REQUESTS: List[Dict[str, Any]] = [
    {
        "id": "R1",
        "priority": 2,
        "to": "Bloomberg (via SME)",
        "cases": ["TC7"],
        "affected": "TC7 floating payments (resets 28-Aug-2026, 25-Feb-2027, 27-Aug-2027)",
        "request": "Curve-234 discount factors on 28-Aug-2026, 24-Feb-2027, 25-Feb-2027, "
        "24-Aug-2027, 27-Aug-2027 and 25-Feb-2028, 31-Mar-2026 snapshot, at least 7 decimals "
        "(9 preferred).",
        "why": "Each reset depends only on the DF ratio over its observation window; the "
        "remaining gaps are 2.7e-6, 2.6e-6 and 0.7e-6 in those ratios, beyond 6-decimal "
        "display.",
        "distinguishes": "curve interpolation difference vs compounding / rounding of the "
        "fallback rate",
        "supports_first": "Bloomberg's DF ratios equal the Resets-tab rates' implied ratios "
        "(1.0007017, 1.0013195, 1.0010795): the difference is in the curve between pillars.",
        "supports_second": "They equal Optima's (1.0006990, 1.0013169, 1.0010788): the curves "
        "agree; the difference is in compounding or rounding of the published fallback rate.",
        "open_item": "OI-13",
    },
    {
        "id": "R2",
        "priority": 1,
        "to": "Bloomberg (via SME)",
        "cases": ["TC1", "TC3"],
        "affected": "TC1 Period 2, TC3 Periods 3-4 (30-Nov-2027, 28-Apr-2028)",
        "request": "Curve-490 items 1-4 already listed in OI-1: member list, construction "
        "settings, full-precision zero/DF at 30-Nov-2027, 28-May-2027 (control), 28-Apr-2028 "
        "and the 02-Apr-2027, 04-Oct-2027, 03-Apr-2028, 02-Apr-2029 pillars; confirmation that "
        "SWPM used curve 490 for both projection and discounting.",
        "why": "Pillar values do not depend on interpolation, so only off-pillar values and the "
        "construction settings can separate the remaining hypotheses.",
        "distinguishes": "missing curve members vs segment convention vs interpolation/time "
        "basis vs node placement",
        "supports_first": "Extra members between 18M and 2Y: rebuild with them reproduces both "
        "payment-date DFs.",
        "supports_second": "No extra members: the settings and off-pillar DFs identify the "
        "interpolation or node rule.",
        "open_item": "OI-1, OI-7",
    },
    {
        "id": "R3",
        "priority": 1,
        "to": "Market data (SIX) or Bloomberg",
        "cases": ["TC2"],
        "affected": "TC2 Period 1 under Method B only (Method A, the configured default, needs "
        "no historical SARON)",
        "request": "Daily SARON fixings from 29-Jan-2026 to 30-Mar-2026 (SIX), to be added to "
        "the market-data fixings (fixings.SARON).",
        "why": "Period 1's full observation window under the current rule (29-Jan-2026 -> "
        "30-Jul-2026) starts before the valuation date. Only 29-Jan -> 30-Mar-2026 (43 Swiss "
        "business days) needs historical fixings; observations from 31-Mar-2026 are "
        "projected. Production tests pin the exact range: without 29-Jan or without 30-Mar "
        "pricing fails; an extra 28-Jan fixing is ignored. Not found in public sources on "
        "14-Oct-2026. Independent of the P1 observation-end question (R8).",
        "distinguishes": "-",
        "supports_first": "-",
        "supports_second": "-",
        "open_item": "OI-11",
    },
    {
        "id": "R4",
        "priority": 3,
        "to": "Market data (NY Fed)",
        "cases": ["TC4"],
        "affected": "TC4 floating payment 30-Jun-2026",
        "request": "Confirm SOFR for 31-Mar-2026 = 3.68% against the NY Fed release.",
        "why": "The value used is from public secondary sources (stated in the fixings file).",
        "distinguishes": "-",
        "supports_first": "-",
        "supports_second": "-",
        "open_item": "OI-10",
    },
    {
        "id": "R5",
        "priority": 3,
        "to": "Market data (Bank of Japan)",
        "cases": ["TC10"],
        "affected": "TC10 floating payment 31-Mar-2027",
        "request": "Confirm TONA for 31-Mar-2026 = 0.727% against the Bank of Japan release.",
        "why": "The public source used gives the March 2026 last value, not a dated daily "
        "value.",
        "distinguishes": "-",
        "supports_first": "-",
        "supports_second": "-",
        "open_item": "OI-16",
    },
    {
        "id": "R6",
        "priority": 1,
        "to": "SME",
        "cases": ["TC5", "TC8", "TC9"],
        "affected": "TC5 P2, TC8 P3, TC9 P1 and P8 (all IRSWOF reset periods shorter than 6M)",
        "request": "How SWPM sets the IRSWOF 6M rate for a reset period shorter than 6M "
        "(first or final stub), and whether TC9's first reset (5.74185%, equal to its "
        "latest_index) is a projection or a stored value; confirmation of the IRSWOF index "
        "definition (6M simple ACT/365F forward from reset + 2 India business days on the INR "
        "OIS curve).",
        "why": "Every full 6M reset is reproduced within 0.3 bp, but all four short reset "
        "periods are 23-39 bp below the 6M forward; no tested rule explains them. They "
        "account for the whole TC5 and TC8 differences and almost all of TC9's.",
        "distinguishes": "stub interpolation rule vs stored first-fixing vs a different index "
        "tenor for stubs",
        "supports_first": "A stub rule (e.g. interpolated tenor): implement it in the IRSWOF "
        "benchmark and re-run TC5/TC8/TC9.",
        "supports_second": "A stored value: it becomes a trade/market input with its source, "
        "never inferred.",
        "open_item": "OI-15",
    },
    {
        "id": "R7",
        "priority": 3,
        "to": "Market data or SME",
        "cases": ["TC8"],
        "affected": "TC8 Period 1",
        "request": "An independent source for the IRSWOF 6M fixing of 27-Feb-2026 (5.36%).",
        "why": "The value comes from the TC8 trade record; Period 1 matches Bloomberg with it.",
        "distinguishes": "-",
        "supports_first": "-",
        "supports_second": "-",
        "open_item": "OI-15",
    },
    {
        "id": "R8",
        "priority": 2,
        "to": "Bloomberg (via SME)",
        "cases": ["TC2"],
        "affected": "TC2 Period 1 observation end (future observation date; not a blocker)",
        "request": "For TC2 Period 1 (reset 30-Jan-2026): the SF0006M fallback's IBOR period "
        "start and end dates and the SARON observation start and end dates SWPM uses, and "
        "how the 6M end is rolled when it falls on a weekend at month end.",
        "why": "The current rule reproduces Bloomberg's effective reset date for P2-P8 but "
        "gives 30-Jul-2026 for P1, where Bloomberg shows 29-Jul-2026. P1 is the only period "
        "whose unadjusted 6M end (Sun 02-Aug-2026) rolls forward into the next month.",
        "distinguishes": "a month-end roll convention for the fallback IBOR period vs some "
        "other P1-specific date rule",
        "supports_first": "IBOR end Fri 31-Jul-2026 (Modified Preceding or equivalent): test "
        "the roll on all TC2 and TC7 periods before changing the convention.",
        "supports_second": "IBOR end Mon 03-Aug-2026 with a different observation end: the "
        "shift or the effective-reset-date definition differs for P1; document and "
        "re-examine.",
        "open_item": "OI-11",
    },
    {
        "id": "R9",
        "priority": 1,
        "to": "Management / SME",
        "cases": ["TC2"],
        "affected": "TC2 floating leg (all periods); configured method and NPV",
        "request": "Decide the SARON observation convention for TC2 (SF0006M, ibor_fallback "
        "opt_in, reset_type In Advance): (a) the ISDA-style IBOR fallback fixed in advance at "
        "each reset date - SARON compounded over the 6M IBOR period starting reset + 1 EN "
        "business day, with a 2 Swiss business day observation shift (Method B); or (b) "
        "SARON compounded over each quarterly contractual accrual period (Method A) and, if "
        "so, with which observation shift or lookback (none is stated in the trade data; "
        "Method A currently uses none).",
        "why": "Method A is configured as a provisional operational default. Method B "
        "reproduces Bloomberg's P2-P8 coupons within 0.14 bp; Method A differs by -5.51 to "
        "+6.92 bp and +5.537 in NPV. The trade data contains no observation-shift or "
        "lookback term, so the no-shift choice is an assumption, not a validated "
        "convention.",
        "distinguishes": "in-advance 6M fallback (Method B) vs in-arrears accrual-period "
        "SARON (Method A), and Method A's shift",
        "supports_first": "Method B: set observation_dates to reset_date_fallback; TC2 then "
        "needs SARON 29-Jan -> 30-Mar-2026 (R3) and the P1 end-date question (R8).",
        "supports_second": "Method A: keep contractual_accrual and record the confirmed "
        "shift; a non-zero shift is a configuration change, re-run TC2.",
        "open_item": "OI-17",
    },
]

# --- blocked cases ------------------------------------------------------------------------------

# ``{requests}`` is replaced by the evidence requests that cover the case.
BLOCKER_ACTIONS: Dict[str, str] = {
    "NO_CURVE_ASSIGNMENT": "Add a curve snapshot for the currency ({requests}).",
    "MARKET_DATA_NOT_CURVE_READY": "Curve definition: tenors, conventions, benchmark "
    "({requests}).",
    "NO_MARKET_DATA": "Market data for the currency.",
    "UNSUPPORTED_BENCHMARK": "Index definition and mapping confirmed ({requests}), then "
    "implementation.",
    "UNSUPPORTED_CALENDAR": "QuantLib mapping of the calendar code named in the blocker "
    "confirmed ({requests}), then implementation.",
    "UNSUPPORTED_FLOATING_LEG": "Leg mechanics confirmed ({requests}), then implementation.",
    "MISSING_FIXINGS": "Supply the named fixings as market data ({requests}).",
    "CONTRACT_TERMS_UNRESOLVED": "SME decision on the contract terms ({requests}).",
    "NO_TRADE_INPUT_FILE": "Canonical trade input file.",
}

# --- conflicts between sources ---------------------------------------------------------------
# Statements in inputs or earlier notes that disagree with newer evidence, and which source
# this report treats as authoritative. (Conflicts in docs/IRS_OPEN_ITEMS.md were corrected
# in the register itself on 14-Oct-2026.)

SOURCE_CONFLICTS: List[Dict[str, Any]] = [
    {
        "id": "C1",
        "older": "market_data/2026-03-31/INR and JPY 'Discount Factor' columns.",
        "newer": "Bloomberg's own TC5/TC8/TC9 and TC6/TC10 payment-date DFs, which the OIS "
        "bootstrap of the same files' par rates reproduces within 4.3e-7 (INR) and 1.0e-6 "
        "(JPY); the supplied DFs differ from them by up to 1.5e-3 / 2.7e-3.",
        "authoritative": "The par-rate bootstrap (Market Rate = OIS par, established). The "
        "supplied DFs are kept unchanged as references; they are not from the curve Bloomberg "
        "priced with.",
        "action": "None; recorded in OI-15/OI-16.",
    },
    {
        "id": "C2",
        "older": "market_data/2026-03-31/JPY row displayed at +390 days.",
        "newer": "Read as the 15M quote it reproduces all five Bloomberg JPY DFs within "
        "1.0e-6; read as 13M/14M/16M/17M it misses by 1.6e-4 to 4.9e-4.",
        "authoritative": "15M (evidence).",
        "action": "None; recorded in OI-16 and in scripts/build_ois_curve_snapshots.py.",
    },
    {
        "id": "C3",
        "older": "tests/fixtures/bloomberg_irs/cases/TC1.json: lookback_days 1.",
        "newer": "source/TC1.json leg_2.days_before_accrual 0; Period 1 reconciles with 0.",
        "authoritative": "The Bloomberg source (production reads it). Known item OI-3; fixture "
        "unchanged.",
        "action": "Owner decision on the fixture (OI-3).",
    },
    {
        "id": "C4",
        "older": "source/TC2.json leg notionals and schedules 20,000,000 -> 2,500,000.",
        "newer": "Bloomberg cashflows, coupons and NPVs are on the 20,000 basis.",
        "authoritative": "20,000 (settled, OI-11). Source file unchanged; scaled in the "
        "generated trade input.",
        "action": "None (settled).",
    },
    {
        "id": "C5",
        "older": "TC5 Bloomberg Period 2 row: effective reset date 30-Dec-2026.",
        "newer": "The source schedule gives Period 2's reset as 29-Jun-2027.",
        "authoritative": "Unresolved; part of the stub question (R6).",
        "action": "R6.",
    },
]
