"""scripts/migrate_market_data_layout.py on fresh repository copies (never on this tree).

Each test copies the files the migration touches (market_data/, the expected-output
baselines, the trade files they reference) into a temporary repository, puts that copy in
the original pre-migration layout with --rollback, and checks it is byte-for-byte the
validated original. The migration is then exercised from there.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from market.market_data_layout import curve_snapshot_path, fixings_path
from scripts import migrate_market_data_layout as mig

ROOT = Path(__file__).resolve().parents[3]


def _tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _copy_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "market_data", repo / "market_data")
    shutil.copytree(ROOT / mig.BASELINE_DIR, repo / mig.BASELINE_DIR)
    (repo / "examples" / "irs").mkdir(parents=True)
    for trade in (ROOT / "examples" / "irs").glob("tc*_trade.json"):
        shutil.copy(trade, repo / "examples" / "irs" / trade.name)
    (repo / "tests" / "fixtures" / "bloomberg_irs").mkdir(parents=True, exist_ok=True)
    return repo


@pytest.fixture
def migrated_repo(tmp_path) -> Path:
    """A fresh copy of this (migrated) repository."""
    return _copy_repo(tmp_path)


@pytest.fixture
def original_repo(migrated_repo) -> Path:
    """A fresh copy in the original layout, verified byte-for-byte."""
    mig.rollback(migrated_repo)
    return migrated_repo


def _assert_original(repo: Path) -> None:
    for old, new, sha in mig.MOVES:
        assert hashlib.sha256((repo / old).read_bytes()).hexdigest() == sha
        assert not (repo / new).exists()
    for name, sha in mig.ORIGINAL_BASELINES.items():
        assert hashlib.sha256((repo / mig.BASELINE_DIR / name).read_bytes()).hexdigest() == sha
    assert not (repo / mig.JOURNAL).exists() and not (repo / mig.RECORD).exists()
    assert mig.preflight(repo)["state"] == "original"


def _assert_migrated_like_this_repo(repo: Path) -> None:
    for old, new, _ in mig.MOVES:
        assert not (repo / old).exists()
        assert (repo / new).read_bytes() == (ROOT / new).read_bytes()
    for name in mig.ORIGINAL_BASELINES:
        path = f"{mig.BASELINE_DIR}/{name}"
        assert (repo / path).read_bytes() == (ROOT / path).read_bytes()
    assert (repo / mig.RECORD).exists() and not (repo / mig.JOURNAL).exists()
    assert mig.preflight(repo)["state"] == "migrated"


# --- definitions agree with the canonical layout and this repository ------------------------


def test_new_paths_are_the_canonical_layout():
    assert [new for _, new, _ in mig.MOVES[:5]] == [
        curve_snapshot_path("2026-03-31", c, b).relative_to(ROOT).as_posix()
        for c, b in (("USD", "SOFR"), ("CHF", "SARON"), ("INR", "MIBOR"), ("JPY", "TONA"))
    ] + [fixings_path("2026-03-31").relative_to(ROOT).as_posix()]


def test_this_repository_is_migrated_and_verified():
    assert mig.preflight(ROOT)["state"] == "migrated"


# --- full procedure on a fresh copy -------------------------------------------------------


def test_rollback_of_a_completed_migration_restores_the_exact_originals(original_repo):
    _assert_original(original_repo)
    assert (original_repo / mig.EMPTIED_DIRS[0]).is_dir()


def test_migration_on_a_fresh_original_copy_reproduces_this_repository(original_repo):
    outcome = mig.migrate(original_repo, apply=True)
    assert len(outcome["changed"]) == len(mig.MOVES) + len(mig.ORIGINAL_BASELINES)
    _assert_migrated_like_this_repo(original_repo)
    assert not (original_repo / mig.EMPTIED_DIRS[0]).exists()
    before = _tree(original_repo)
    assert mig.migrate(original_repo, apply=True)["changed"] == []  # re-run: verify only
    assert _tree(original_repo) == before


def test_expected_values_and_hashes_are_unchanged_by_migration(original_repo):
    before = {n: json.loads((original_repo / mig.BASELINE_DIR / n).read_text())
              for n in mig.ORIGINAL_BASELINES}
    mig.migrate(original_repo, apply=True)
    for name, old in before.items():
        new = json.loads((original_repo / mig.BASELINE_DIR / name).read_text())
        assert new["expected"] == old["expected"]
        assert [f["sha256"] for f in new["provenance"]["inputs"]["market_files"]] == \
            [f["sha256"] for f in old["provenance"]["inputs"]["market_files"]]
        assert new["provenance"]["inputs"]["trade_file"] == \
            old["provenance"]["inputs"]["trade_file"]


def test_dry_run_changes_nothing(original_repo):
    before = _tree(original_repo)
    outcome = mig.migrate(original_repo, apply=False)
    assert outcome["state"] == "original" and len(outcome["plan"]) == 16
    assert _tree(original_repo) == before


def test_baselines_with_windows_line_endings_are_accepted(original_repo):
    for name in mig.ORIGINAL_BASELINES:
        path = original_repo / mig.BASELINE_DIR / name
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    mig.migrate(original_repo, apply=True)
    _assert_migrated_like_this_repo(original_repo)  # written back with LF, as captured


# --- preflight: any problem stops the migration before the first change ---------------------


def _tamper_recorded_hash(repo):
    path = repo / mig.BASELINE_DIR / "TC4.json"
    doc = json.loads(path.read_text())
    doc["provenance"]["inputs"]["market_files"][1]["sha256"] = "0" * 64
    path.write_text(json.dumps(doc, indent=2) + "\n")


def _tamper_expected(repo):
    path = repo / mig.BASELINE_DIR / "TC1.json"
    doc = json.loads(path.read_text())
    doc["expected"]["npv"] += 1.0
    path.write_text(json.dumps(doc, indent=2) + "\n")


def _extra_baseline(repo):
    doc = json.loads((repo / mig.BASELINE_DIR / "TC1.json").read_text())
    (repo / mig.BASELINE_DIR / "TC11.json").write_text(json.dumps(doc))


@pytest.mark.parametrize("tamper, message", [
    (_tamper_recorded_hash, "TC4.json: is neither the validated baseline"),
    (_tamper_expected, "TC1.json: is neither the validated baseline"),
    (lambda r: (r / mig.MOVES[2][0]).write_text("{}"), "inr_mibor_2026-03-31.json differs"),
    (lambda r: shutil.copy(r / mig.MOVES[0][0], r / mig.MOVES[0][1]), "two competing copies"),
    (lambda r: (r / mig.MOVES[4][0]).unlink(), "neither examples/irs/fixings_2026-03-31.json"),
    (lambda r: (r / "examples/irs/tc7_trade.json").write_text("{}"),
     "TC7.json: input examples/irs/tc7_trade.json differs"),
    (lambda r: (r / mig.BASELINE_DIR / "TC9.json").unlink(), "TC9.json: missing"),
    (_extra_baseline, "TC11.json: references a moved file"),
    (lambda r: ((r / mig.MIGRATIONS_DIR).mkdir(parents=True, exist_ok=True),
                (r / mig.JOURNAL).write_text("{}")), "previous migration was interrupted"),
])
def test_preflight_failure_changes_nothing(original_repo, tamper, message):
    tamper(original_repo)
    before = _tree(original_repo)
    with pytest.raises(mig.MigrationError, match="preflight failed|interrupted") as info:
        mig.migrate(original_repo, apply=True)
    assert message in str(info.value)
    assert _tree(original_repo) == before


def test_preflight_lists_every_problem(original_repo):
    (original_repo / mig.MOVES[1][0]).write_text("{}")
    _tamper_expected(original_repo)
    with pytest.raises(mig.MigrationError) as info:
        mig.migrate(original_repo, apply=True)
    assert "chf_saron" in str(info.value) and "TC1.json" in str(info.value)


# --- failure during the migration: automatic rollback ----------------------------------------


@pytest.mark.parametrize("fail_at", [
    f"move {mig.MOVES[0][0]}",            # after the first move
    f"move {mig.MOVES[-1][0]}",           # after every move, before any baseline
    "baseline TC5.json",                  # half of the baselines rewritten
    "baseline TC10.json",                 # everything changed, before verification
])
def test_failure_during_migration_is_rolled_back_automatically(original_repo, fail_at):
    before = _tree(original_repo)

    def hook(step):
        if step == fail_at:
            raise OSError(f"simulated failure after {step}")

    with pytest.raises(mig.MigrationError, match="rolled back, the original layout is restored"):
        mig.migrate(original_repo, apply=True, after_step=hook)
    assert _tree(original_repo) == before
    _assert_original(original_repo)


def test_interrupted_migration_is_recovered_with_rollback(original_repo):
    """Process stopped mid-way (no automatic rollback): the journal remains, --apply refuses,
    --rollback restores the original, and the migration then completes."""
    before = _tree(original_repo)

    def hook(step):
        if step == "baseline TC3.json":
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        mig.migrate(original_repo, apply=True, after_step=hook, rollback_on_error=False)
    assert (original_repo / mig.JOURNAL).exists()
    with pytest.raises(mig.MigrationError, match="interrupted"):
        mig.migrate(original_repo, apply=True)
    assert mig.main(["--rollback", "--root", str(original_repo)]) == 0
    assert _tree(original_repo) == before
    assert mig.main(["--apply", "--root", str(original_repo)]) == 0
    _assert_migrated_like_this_repo(original_repo)


def test_rollback_refuses_when_a_file_was_changed(migrated_repo):
    (migrated_repo / mig.MOVES[3][1]).write_text("{}")
    before = _tree(migrated_repo)
    with pytest.raises(mig.MigrationError, match="rollback preflight failed, nothing changed"):
        mig.rollback(migrated_repo)
    assert _tree(migrated_repo) == before


def test_cli_exit_codes(original_repo, capsys):
    assert mig.main(["--root", str(original_repo)]) == 0
    assert "preflight passed" in capsys.readouterr().out
    (original_repo / mig.MOVES[0][0]).write_text("{}")
    assert mig.main(["--apply", "--root", str(original_repo)]) == 2
    assert "MIGRATION STOPPED" in capsys.readouterr().err
