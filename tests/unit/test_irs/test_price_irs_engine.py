"""price_irs_engine.py: market data resolved from the trade before any market file is read.

Which files are opened is checked two ways: every path passed to the script's file loader
is recorded, and the other currencies' snapshots in the temporary market folder are
deliberately invalid JSON, so reading one would fail. Pricing is compared with the
production report path (price_irs on the merged ten-case market document).
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

import price_irs_engine as engine
from scripts.irs_case_audit import load_market_document
from scripts.irs_observation_methods import with_method
from services.pricers.irs_valuation import price_irs

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "examples" / "irs"
MARKET = ROOT / "market_data" / "2026-03-31"
SNAPSHOTS = {"USD": "usd_sofr_2026-03-31.json", "CHF": "chf_saron_2026-03-31.json",
             "INR": "inr_mibor_2026-03-31.json", "JPY": "jpy_tona_2026-03-31.json"}
FIXINGS = "fixings_2026-03-31.json"


def _snapshot(currency: str) -> Path:
    """Canonical prepared snapshot (market_data/<date>/<CCY>/)."""
    return MARKET / currency / SNAPSHOTS[currency]

# case -> (currency snapshot, fixings needed?) under the production conventions
EXPECTED = {
    "TC1": ("USD", False), "TC2": ("CHF", False), "TC3": ("USD", False), "TC4": ("USD", True),
    "TC5": ("INR", False), "TC6": ("JPY", False), "TC7": ("CHF", False), "TC8": ("INR", True),
    "TC9": ("INR", False), "TC10": ("JPY", True),
}


def _trade(case: str) -> dict:
    return json.loads((EXAMPLES / f"{case.lower()}_trade.json").read_text(encoding="utf-8"))


def _market_dir(tmp_path: Path, currency: str, with_fixings: bool = True) -> Path:
    """A market root in the canonical layout (<root>/2026-03-31/<CCY>/, fixings at the date
    level): real snapshot for ``currency`` (+ fixings); every other currency's snapshot is
    invalid JSON, so reading it would raise."""
    root = tmp_path / "market"
    dated = root / "2026-03-31"
    for ccy, name in SNAPSHOTS.items():
        (dated / ccy).mkdir(parents=True)
        if ccy == currency:
            shutil.copy(_snapshot(ccy), dated / ccy / name)
        else:
            (dated / ccy / name).write_text("NOT JSON - must not be read", encoding="utf-8")
    if with_fixings:
        shutil.copy(MARKET / FIXINGS, dated / FIXINGS)
    return root


@pytest.fixture
def opened(monkeypatch):
    """Names of every file the script's loader reads."""
    names = []
    real = engine.load

    def recording(path):
        names.append(Path(path).name)
        return real(path)

    monkeypatch.setattr(engine, "load", recording)
    return names


def _write_trade(tmp_path: Path, doc: dict, name: str = "trade.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def production():
    """NPVs and cashflows from the production report path, per case."""
    market = load_market_document()
    return {case: price_irs(_trade(case), market) for case in EXPECTED}


# --- selection --------------------------------------------------------------------------------


@pytest.mark.parametrize("case", sorted(EXPECTED, key=lambda c: int(c[2:])))
def test_each_trade_resolves_only_its_market_data(case, tmp_path):
    currency, needs_fixings = EXPECTED[case]
    selection = engine.resolve_market_files(_trade(case), _market_dir(tmp_path, currency))
    expected = [SNAPSHOTS[currency]] + ([FIXINGS] if needs_fixings else [])
    assert [f.name for f in selection.files] == expected
    assert selection.currency == currency
    assert bool(selection.fixing_reasons) is needs_fixings


def test_chf_trade_needing_fixings_opens_only_chf_and_fixings(tmp_path, opened, capsys):
    """TC2 under Method B (reset-date fallback) observes SARON from 29-Jan-2026: CHF curve +
    fixings only. Pricing then stops on the missing SARON history (R3), clearly."""
    trade = _write_trade(tmp_path, with_method(_trade("TC2"), "reset_date_fallback"))
    folder = _market_dir(tmp_path, "CHF")
    assert engine.main(["--trade", str(trade), "--market-root", str(folder)]) == 1
    assert opened == ["trade.json", SNAPSHOTS["CHF"], FIXINGS]
    out = capsys.readouterr()
    assert "SARON observed from 2026-01-29 (Method B)" in out.out
    assert "SARON" in out.err and "2026-01-29" in out.err


@pytest.mark.parametrize("case", ["TC1", "TC4", "TC5", "TC8", "TC6", "TC10", "TC7"])
def test_main_opens_only_the_resolved_files(case, tmp_path, opened, production, capsys):
    currency, needs_fixings = EXPECTED[case]
    trade = _write_trade(tmp_path, _trade(case))
    folder = _market_dir(tmp_path, currency)
    assert engine.main(["--trade", str(trade), "--market-root", str(folder)]) == 0
    assert opened == ["trade.json", SNAPSHOTS[currency]] + ([FIXINGS] if needs_fixings else [])
    assert f"NPV {production[case].npv:,.4f}" in capsys.readouterr().out


def test_explicit_market_override_is_used_as_given(tmp_path, opened, monkeypatch, capsys):
    def must_not_resolve(*_args, **_kwargs):
        raise AssertionError("resolution must not run when --market is given")

    monkeypatch.setattr(engine, "resolve_market_files", must_not_resolve)
    trade = _write_trade(tmp_path, _trade("TC1"))
    usd = str(_snapshot("USD"))
    assert engine.main(["--trade", str(trade), "--market", usd]) == 0
    assert opened == ["trade.json", SNAPSHOTS["USD"]]
    assert "NPV -7,955.7262" in capsys.readouterr().out


def test_market_option_without_files_is_rejected():
    with pytest.raises(SystemExit):
        engine.main(["--trade", str(EXAMPLES / "tc1_trade.json"), "--market"])


# --- errors -----------------------------------------------------------------------------------


def test_unavailable_valuation_date_fails_clearly(tmp_path, opened, capsys):
    doc = _trade("TC1")
    doc["params"]["valuation_date"] = "2026-04-01"
    trade = _write_trade(tmp_path, doc)
    folder = _market_dir(tmp_path, "USD")
    assert engine.main(["--trade", str(trade), "--market-root", str(folder)]) == 2
    err = capsys.readouterr().err
    assert "no USD SOFR market snapshot for the trade's valuation date 2026-04-01" in err
    assert "usd_sofr_2026-04-01.json" in err
    assert opened == ["trade.json"]  # no fallback to another date


def test_missing_currency_snapshot_fails_clearly(tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir()
    with pytest.raises(engine.MarketDataResolutionError, match="no INR MIBOR market snapshot"):
        engine.resolve_market_files(_trade("TC5"), folder)


def test_missing_required_fixings_file_fails_clearly(tmp_path):
    folder = _market_dir(tmp_path, "USD", with_fixings=False)
    with pytest.raises(engine.MarketDataResolutionError,
                       match=r"needs fixings on or before 2026-03-31.*SOFRRATE observed from "
                             r"2026-03-31.*fixings_2026-03-31\.json does not exist"):
        engine.resolve_market_files(_trade("TC4"), folder)


def test_invalid_trade_fails_before_market_resolution(tmp_path):
    doc = _trade("TC1")
    del doc["params"]["valuation_date"]
    with pytest.raises(engine.MarketDataResolutionError, match="invalid trade"):
        engine.resolve_market_files(doc, _market_dir(tmp_path, "USD"))
    with pytest.raises(engine.MarketDataResolutionError, match="no 'params'"):
        engine.resolve_market_files({}, tmp_path)


def test_date_mismatch_is_rejected(tmp_path, capsys):
    shifted = json.loads((_snapshot("USD")).read_text(encoding="utf-8"))
    shifted["valuation_date"] = "2026-04-01"
    shifted["curves"]["USD-SOFR-490"]["reference_date"] = "2026-04-01"
    usd = _write_trade(tmp_path, shifted, "usd_shifted.json")
    trade = str(EXAMPLES / "tc1_trade.json")
    assert engine.main(["--trade", trade, "--market", str(usd)]) == 2
    assert "trade valuation date 2026-03-31 != market valuation date 2026-04-01" in \
        capsys.readouterr().err
    assert engine.main(["--trade", trade, "--market", str(usd),
                        str(MARKET / FIXINGS)]) == 2
    assert "different valuation dates" in capsys.readouterr().err


def test_duplicate_definitions_are_rejected(capsys):
    usd = str(_snapshot("USD"))
    assert engine.main(["--trade", str(EXAMPLES / "tc1_trade.json"), "--market", usd,
                        usd]) == 2
    assert "already defined" in capsys.readouterr().err


def test_currency_and_curve_incompatibilities_are_rejected(tmp_path, capsys):
    trade = str(EXAMPLES / "tc1_trade.json")
    assert engine.main(["--trade", trade, "--market", str(_snapshot("CHF"))]) == 2
    assert "no curve assignment for USD" in capsys.readouterr().err
    wrong = json.loads((_snapshot("USD")).read_text(encoding="utf-8"))
    wrong["curves"]["USD-SOFR-490"]["benchmark"] = "TONA"
    path = _write_trade(tmp_path, wrong, "usd_wrong_benchmark.json")
    assert engine.main(["--trade", trade, "--market", str(path)]) == 2
    assert "needs a 'SOFR' forecast curve" in capsys.readouterr().err


# --- pricing unchanged ------------------------------------------------------------------------


@pytest.mark.parametrize("case", sorted(EXPECTED, key=lambda c: int(c[2:])))
def test_pricing_and_cashflows_equal_the_production_path(case, tmp_path, production):
    currency, _ = EXPECTED[case]
    selection = engine.resolve_market_files(_trade(case), _market_dir(tmp_path, currency))
    instrument, ccy, result, legs, rows, settled = engine.price(
        _trade(case), engine.merge_market(list(selection.files)))
    reference = production[case]
    assert result.npv == pytest.approx(reference.npv, abs=1e-9)
    assert legs["fixed"] == pytest.approx(reference.fixed_leg_npv, abs=1e-9)
    assert legs["floating"] == pytest.approx(reference.floating_leg_npv, abs=1e-9)
    assert [(r.leg, r.period, r.payment_date) for r in rows] == \
        [(r.leg, r.period, r.payment_date) for r in reference.cashflows]
    for mine, ref in zip(rows, reference.cashflows):
        assert mine.amount == pytest.approx(ref.amount, abs=1e-9)
        assert mine.present_value == pytest.approx(ref.present_value, abs=1e-9)
    assert sum(r.present_value for r in rows) == pytest.approx(result.npv, abs=1e-8)
    assert [s.payment_date for s in settled] == [s.payment_date for s in reference.settled]


@pytest.mark.parametrize("case", ["TC4", "TC8", "TC10"])
def test_fixings_rule_matches_what_pricing_needs(case, production):
    """Where the rule loads fixings, pricing without them fails or gives another NPV."""
    market = load_market_document()
    del market["fixings"]
    try:
        npv = price_irs(_trade(case), market).npv
    except Exception:  # noqa: BLE001 - missing history is reported as a pricing failure
        return
    assert abs(npv - production[case].npv) > 1e-6


def test_report_output_is_unchanged(tmp_path, capsys):
    trade = _write_trade(tmp_path, copy.deepcopy(_trade("TC4")))
    assert engine.main(["--trade", str(trade)]) == 0  # default: the canonical store
    out = capsys.readouterr().out
    assert "Settled (pay on or before the valuation date; excluded from the NPV)" in out
    assert "2026-06-30       -1,924.15       -1,906.43" in out
    assert "Total" in out and "difference" in out


# --- canonical market-data layout (market_data/<date>/<CCY>/, fixings at the date level) ----


@pytest.mark.parametrize("case", sorted(EXPECTED))
def test_default_resolution_uses_the_single_canonical_store(case):
    currency, needs_fixings = EXPECTED[case]
    selection = engine.resolve_market_files(_trade(case))
    expected = [_snapshot(currency)] + ([MARKET / FIXINGS] if needs_fixings else [])
    assert list(selection.files) == expected


def test_no_prepared_market_file_remains_in_examples():
    """One canonical copy: examples/irs holds trades (and the TC11 test-only fixings
    override), never a curve snapshot or the shared fixings file."""
    leftovers = sorted(p.name for p in EXAMPLES.glob("*_2026-03-31.json"))
    assert leftovers == []
    for currency, name in SNAPSHOTS.items():
        assert _snapshot(currency).is_file()
    assert (MARKET / FIXINGS).is_file()
