"""TC11 (SLLSL9TR, USD SOFR, amortising, seasoned): screenshot-extracted SWPM trade ->
production trade input (scripts/convert_swpm_screenshot_trade.py).

examples/irs/tc11_trade.json is the user's screenshot extraction and is never modified.
examples/irs/tc11_trade_production.json is the converted production input. Bloomberg values
embedded in the source are used here only for INPUT consistency (dates, day counts, the
notional basis); they are not expected pricing results.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import QuantLib as ql

import price_irs_engine as engine
from instruments.rates.irs.pricing_instrument import FreshOISInstrument
from scripts import convert_swpm_screenshot_trade as converter
from scripts.irs_case_audit import load_market_document

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "examples" / "irs" / "tc11_trade.json"
PRODUCTION = ROOT / "examples" / "irs" / "tc11_trade_production.json"

pytestmark = pytest.mark.skipif(not SOURCE.exists(), reason="TC11 source not present")


def _source() -> dict:
    return json.loads(SOURCE.read_text(encoding="utf-8"))


def _production() -> dict:
    return json.loads(PRODUCTION.read_text(encoding="utf-8"))


def test_fixture_is_exactly_the_converter_output_and_source_is_untouched():
    before = SOURCE.read_bytes()
    text = converter.to_text(converter.convert(_source()))
    assert SOURCE.read_bytes() == before
    assert PRODUCTION.read_text(encoding="utf-8").replace("\r\n", "\n") == text


def test_mapping_of_contract_terms():
    p = _production()["params"]
    assert (p["trade_id"], p["currency"], p["valuation_date"], p["effective_date"],
            p["maturity_date"], p["fixed_leg_side"]) == (
        "SLLSL9TR", "USD", "2026-03-31", "2026-01-01", "2027-09-30", "pay")
    fx, fl = p["fixed_leg"], p["floating_leg"]
    assert fx["fixed_rate"] == pytest.approx(0.04) and fx["day_count"] == "ACT/360"
    assert fx["payment_frequency"] == fl["payment_frequency"] == "semiannual"
    assert fx["accrual_date_adjustment"] == fl["accrual_date_adjustment"] == {
        "calendar": "FD", "business_day_convention": "modified_following"}
    assert (fl["benchmark"], fl["benchmark_tenor"], fl["reset_frequency"]) == (
        "SOFRRATE", "1D", "daily")
    assert fl["spread"] == pytest.approx(0.002) and fl["leverage"] == 1.0
    assert fl["observation"] == {"lookback_days": 0, "cutoff_days": 1,
                                 "reset_timing": "In Arrears", "compounding": "ExcludeSprd",
                                 "lookback_type": "Lookback"}
    # Same observation terms and calendar as the established USD SOFR inputs (TC4).
    tc4 = json.loads((ROOT / "examples" / "irs" / "tc4_trade.json").read_text(encoding="utf-8"))
    assert fl["observation"] == tc4["params"]["floating_leg"]["observation"]


def test_production_parser_accepts_the_fixture():
    trade = FreshOISInstrument.from_dict(_production()["params"]).trade
    assert trade.floating_term_rate is None  # overnight leg, not a term-rate leg
    notionals = [float(p.notional.amount) for p in trade.fixed_periods]
    assert notionals == [510e6, 382.5e6, 255e6, 127.5e6]  # amortising schedule as transcribed
    assert [float(p.notional.amount) for p in trade.floating_periods] == notionals


def test_schedule_matches_bloomberg_cashflow_rows():
    """Input consistency only: dates and day counts of Bloomberg's own cashflow table."""
    p = _production()["params"]
    cf = _source()["trade"]["cashflows"]
    for leg, rows in (("fixed_leg", cf["fixed_leg"]["cashflows"]),
                      ("floating_leg", cf["floating_leg"]["cashflows"])):
        for period, row in zip(p[leg]["periods"], rows):
            assert (period["accrual_start"], period["accrual_end"], period["payment_date"]) == (
                row["accrual_start"], row["accrual_end"], row["pay_date"])
            start, end = (ql.Date(int(d[8:]), int(d[5:7]), int(d[:4]))
                          for d in (row["accrual_start"], row["accrual_end"]))
            assert end - start == row["days"]


def test_notional_basis_is_an_open_decision():
    """The transcribed balances are kept unchanged (scale 1). Every Bloomberg cashflow amount
    in the source is exactly 1/1000 of what those balances imply: a decision, not inferred."""
    p = _production()["params"]
    rows = _source()["trade"]["cashflows"]["fixed_leg"]["cashflows"]
    for period, row in zip(p["fixed_leg"]["periods"], rows):
        implied = period["notional"] * 0.04 * row["days"] / 360
        assert -row["payment"] / implied == pytest.approx(1e-3, abs=1e-8)
    scaled = converter.convert(_source(), notional_scale=1e-3)["params"]
    assert scaled["fixed_leg"]["periods"][0]["notional"] == 510000


def test_market_resolution_and_missing_sofr_fixing():
    doc = _production()
    selection = engine.resolve_market_files(doc)
    assert [f.name for f in selection.files] == ["usd_sofr_2026-03-31.json",
                                                 "fixings_2026-03-31.json"]
    assert selection.fixing_reasons == (
        "floating period 2: SOFRRATE observed from 2026-03-30",)
    with pytest.raises(Exception, match="Missing SOFRON Actual/360 fixing for March 30th, 2026"):
        engine.price(doc, engine.merge_market(list(selection.files)))


def test_prices_once_the_missing_fixing_exists():
    """Capability check with a SYNTHETIC 30-Mar-2026 SOFR value (test only, never market
    data, not a result): with that day supplied the converted trade prices, period 1 is
    settled and the cashflows close to the NPV."""
    market = copy.deepcopy(load_market_document())
    market["fixings"]["SOFR"]["values"]["2026-03-30"] = 0.0368
    instrument, ccy, result, legs, rows, settled = engine.price(_production(), market)
    assert [s.payment_date.isoformat() for s in settled] == ["2026-03-30", "2026-03-30"]
    assert len(rows) == 6
    assert sum(r.present_value for r in rows) == pytest.approx(result.npv, abs=1e-6)


# --- unsupported or inconsistent sources are rejected, not guessed --------------------------


def _mutated(change) -> dict:
    src = _source()
    change(src["trade"])
    return src


@pytest.mark.parametrize("change, message", [
    (lambda t: t["legs"]["floating"].update(index_tenor="6M"), "only overnight"),
    (lambda t: t["legs"]["floating"].update(reset_frequency="SemiAnnual"), "reset_frequency"),
    (lambda t: t["legs"]["fixed"].update(principal_exchange="Final"), "principal_exchange"),
    (lambda t: t["legs"]["fixed"].update(payment_delay=2), "payment_delay"),
    (lambda t: t["legs"]["fixed"].update(adjustment="Acc Only"), "adjustment"),
    (lambda t: t["legs"]["floating"].update(day_count="ACT/ACT"), "day_count"),
    (lambda t: t["legs"]["fixed"]["amortization_schedule"][2].update(balance=1), "balance"),
    (lambda t: t["legs"]["fixed"]["amortization_schedule"][1].update(
        accrual_start="2026-03-31"), "contiguous"),
    (lambda t: t["legs"]["floating"]["amortization_schedule"][3].update(spread_bp=25.0),
     "spread differs"),
    (lambda t: t["legs"]["floating"].update(currency="EUR"), "currency"),
    (lambda t: t["legs"]["fixed"].update(pay_receive="Receive"), "same side"),
])
def test_unsupported_or_inconsistent_terms_are_rejected(change, message):
    with pytest.raises(converter.UnsupportedConversion, match=message):
        converter.convert(_mutated(change))


def test_source_without_trade_key_is_rejected():
    with pytest.raises(converter.UnsupportedConversion, match="no top-level 'trade'"):
        converter.convert({"params": {}})


def test_cli_never_writes_over_the_source(tmp_path, capsys):
    assert converter.main([str(SOURCE), str(SOURCE)]) == 2
    assert "never modified" in capsys.readouterr().err
    out = tmp_path / "out.json"
    assert converter.main([str(SOURCE), str(out)]) == 0
    assert converter.main([str(SOURCE), str(out)]) == 2  # no silent overwrite
    assert converter.main([str(SOURCE), str(out), "--check"]) == 0
