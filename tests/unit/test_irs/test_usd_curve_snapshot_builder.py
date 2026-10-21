"""scripts/build_usd_curve_snapshot.py reproduces the USD prepared snapshot byte for byte
from its raw zero-rate source, and never overwrites it."""

from __future__ import annotations

import json

import pytest

from scripts import build_usd_curve_snapshot as builder


def test_reproduction_is_byte_identical_to_the_canonical_snapshot():
    assert builder.build() == builder.TARGET.read_bytes()


def test_check_mode_is_the_default_and_writes_nothing(capsys):
    before = builder.TARGET.read_bytes()
    assert builder.main([]) == 0
    assert "byte-identical" in capsys.readouterr().out
    assert builder.TARGET.read_bytes() == before


def test_output_goes_to_a_new_file_only(tmp_path, capsys):
    out = tmp_path / "usd.json"
    assert builder.main(["--output", str(out)]) == 0
    assert out.read_bytes() == builder.TARGET.read_bytes()
    assert builder.main(["--output", str(out)]) == 2  # exists: never overwritten
    assert builder.main(["--output", str(builder.TARGET)]) == 2
    assert "never overwrites" in capsys.readouterr().err


def test_a_changed_source_is_detected(tmp_path, capsys):
    source = tmp_path / "zero.json"
    doc = json.loads(builder.SOURCE.read_text(encoding="utf-8"))
    doc["observations"][5]["zero_rate_percent"] += 0.0001
    source.write_text(json.dumps(doc), encoding="utf-8")
    assert builder.main(["--source", str(source)]) == 1
    assert "DIFFERS" in capsys.readouterr().err


def test_only_the_rates_tenors_and_dfs_come_from_the_source():
    source = json.loads(builder.SOURCE.read_text(encoding="utf-8"))
    curve = builder.build_document(source)["curves"][builder.CURVE_ID]
    assert [o["tenor"] for o in curve["observations"]] == [
        r["inferred_tenor"] for r in source["observations"]]
    assert [o["discount_factor"] for o in curve["observations"]] == [
        r["discount_factor"] for r in source["observations"]]
    assert curve["conventions"] == builder.CONVENTIONS  # recorded constants, documented


@pytest.mark.parametrize("change, message", [
    (lambda d: d.update(currency="EUR"), "currency"),
    (lambda d: d.update(reference_date="2026-03-30"), "reference_date"),
    (lambda d: d["observations"].pop(), "20 observations"),
    (lambda d: d["observations"][0].pop("inferred_tenor"), "observation 1"),
])
def test_invalid_source_is_rejected(change, message):
    doc = json.loads(builder.SOURCE.read_text(encoding="utf-8"))
    change(doc)
    with pytest.raises(builder.SourceError, match=message):
        builder.build_document(doc)
