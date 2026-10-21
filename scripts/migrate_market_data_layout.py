"""Controlled migration: prepared market data into ``market_data/<date>/<CCY>/``.

Moves (never copies) the four prepared curve snapshots, the shared dated fixings file and
the USD zero-rate source into the canonical layout (``market.market_data_layout``), so each
file has exactly one copy, and updates the input *paths* recorded in the ten expected-output
baselines. File contents, recorded hashes and expected values do not change.

    python -m scripts.migrate_market_data_layout              # preflight + plan; no change
    python -m scripts.migrate_market_data_layout --apply      # migrate
    python -m scripts.migrate_market_data_layout --rollback   # restore the previous layout

Safety
------
1. **Preflight before any change.** Every check runs first; if one fails nothing is touched:
   * each file to move is at its old path (and not at its new path) with the validated
     SHA-256 below; a file at both paths would be two competing copies;
   * each baseline is the validated original (SHA-256 below, line endings ignored), every
     input it references (trade file and market files) exists with the hash it recorded,
     and its updated form is computed and checked (expected values identical) in memory;
   * no other baseline references a file being moved; no interrupted migration is pending.
2. **Journal.** Before the first change, the plan and the original text of every baseline
   are written to ``market_data/migrations/<id>.journal.json``. It is removed only after
   the migrated tree has been verified and the record written.
3. **Automatic rollback.** If any step fails, the files moved so far are moved back and the
   baselines restored, and the tree is verified to be the original again.
4. **Recovery.** If the process is stopped without completing (power loss, killed), the
   journal remains; ``--apply`` then refuses to run, and ``--rollback`` restores the
   original layout. ``--rollback`` also reverses a completed migration. It runs its own
   preflight first and can be re-run if interrupted.

Baselines are written atomically (temporary file + replace) with LF line endings, as
captured. Re-running ``--apply`` after a completed migration only verifies it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]

MIGRATION_ID = "2026-10-21-market-data-layout"
BASELINE_DIR = "tests/fixtures/irs_expected_outputs"
MIGRATIONS_DIR = "market_data/migrations"
RECORD = f"{MIGRATIONS_DIR}/{MIGRATION_ID}.json"
JOURNAL = f"{MIGRATIONS_DIR}/{MIGRATION_ID}.journal.json"

# (old path, new path, SHA-256 of the file as validated at validation_phase1)
MOVES: Tuple[Tuple[str, str, str], ...] = (
    ("examples/irs/usd_sofr_2026-03-31.json",
     "market_data/2026-03-31/USD/usd_sofr_2026-03-31.json",
     "10c80ed3c4a8667a7a75de8773a55d3ef73c6b38036196dd9aab174454ad8724"),
    ("examples/irs/chf_saron_2026-03-31.json",
     "market_data/2026-03-31/CHF/chf_saron_2026-03-31.json",
     "b99824b3b0b417cb255d48971a0bf4791fd0efc6ecf6cbafa00e02e46f1c6c8d"),
    ("examples/irs/inr_mibor_2026-03-31.json",
     "market_data/2026-03-31/INR/inr_mibor_2026-03-31.json",
     "a3ab7eebd7f469022dff1c655386fe6d040edafda5d08599a1893976b2b698cf"),
    ("examples/irs/jpy_tona_2026-03-31.json",
     "market_data/2026-03-31/JPY/jpy_tona_2026-03-31.json",
     "387664cdaff12a5c45d458f837de84895e2dabd8b7fb1c5c978a9a95679001ec"),
    ("examples/irs/fixings_2026-03-31.json",
     "market_data/2026-03-31/fixings_2026-03-31.json",
     "8199b8abab5041120545d6b96e6f3e68bcefee47623d42d8b73e14fa24d16d59"),
    # Raw source of the USD prepared snapshot (Bloomberg 490-USDSOFR "Zero Rate" column).
    ("tests/fixtures/bloomberg_irs/curves/2026-03-31-USD-SOFR-zero.json",
     "market_data/2026-03-31/USD/2026-03-31-USD-SOFR-zero.json",
     "c110828ebea8627a1abdf4fb204c5a1a49f2ce5248be9b5552350cab76e9d4e9"),
)
# SHA-256 (LF line endings) of each expected-output baseline as captured at
# validation_phase1, before this migration.
ORIGINAL_BASELINES: Dict[str, str] = {
    "TC1.json": "24a9fb75ffde175da858ed0c5f6923d74e74aef017b4d2ef4e9af59e9a432f2c",
    "TC2.json": "a85e4f31fa8b43853f892f0b3f18bf6da040a7e281a55bb6cc23e4880c7157bc",
    "TC3.json": "78113d4460d06722fef89448c731cc972725ea8ffc64b6480a0beb6fa4a9c653",
    "TC4.json": "4fefa6c391bc9e529f9d9c9cf9d682d4100c104c3cb8fe4ce4899dd2b8e92308",
    "TC5.json": "d2204a8849e9f463f1eb16f119f0a4e76896e813a9828242d9df0559ec668997",
    "TC6.json": "f283588771673ecd9fcaf33aa51442a6690d362ca1d3fcba12958b7919524f11",
    "TC7.json": "f5ca8ba98425653bf9e52e9f21d2bb720abb32d6aa11da09879b952ccd6f7424",
    "TC8.json": "3ce04798263bc91ba0edf7652b336ad002d9aa4a370aa8421115073045604d79",
    "TC9.json": "f2444df72e841dbe20b883ab7344882f35776f25fa2113a3d5b89006adac8906",
    "TC10.json": "4aa03314ac944acabd08106fbae1cdd52d351c2c85e544bdf539fa834c3625f2",
}
# Folders emptied by the moves (removed when empty; recreated on rollback).
EMPTIED_DIRS = ("tests/fixtures/bloomberg_irs/curves",)
NOT_MOVED = {
    "examples/irs/fixings_2026-03-31_tc11_test.json":
        "TC11 test-only fixings override (adds SOFR 30-Mar-2026); not a canonical market "
        "file and not used by the resolver",
}
_PATH_MAP = {old: new for old, new, _ in MOVES}
_REVERSE_MAP = {new: old for old, new, _ in MOVES}


class MigrationError(RuntimeError):
    pass


# --- helpers ------------------------------------------------------------------------------


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _text(path: Path) -> str:
    """File text with LF line endings (git may have converted them on Windows)."""
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(text.encode("utf-8"))  # LF, as captured, on every platform
    os.replace(tmp, path)


def _dump(doc) -> str:
    return json.dumps(doc, indent=2) + "\n"


def migrated_baseline(original: str) -> str:
    """Baseline text with the moved input paths updated (pure function)."""
    doc = json.loads(original)
    expected = json.dumps(doc["expected"], sort_keys=True)
    files = doc["provenance"]["inputs"]["market_files"]
    moved = [(f["path"], _PATH_MAP[f["path"]]) for f in files if f["path"] in _PATH_MAP]
    for entry in files:
        entry["path"] = _PATH_MAP.get(entry["path"], entry["path"])
    doc["provenance"].setdefault("path_migrations", []).append({
        "migration": MIGRATION_ID,
        "moved": [{"from": a, "to": b} for a, b in moved],
        "note": "file paths only; file contents (sha256) and expected values unchanged",
    })
    if json.dumps(doc["expected"], sort_keys=True) != expected:
        raise MigrationError("expected values would change")  # cannot happen; guarded
    return _dump(doc)


def original_baseline(migrated: str) -> str:
    """Inverse of ``migrated_baseline`` (pure function)."""
    doc = json.loads(migrated)
    for entry in doc["provenance"]["inputs"]["market_files"]:
        entry["path"] = _REVERSE_MAP.get(entry["path"], entry["path"])
    history = [m for m in doc["provenance"].get("path_migrations", [])
               if m.get("migration") != MIGRATION_ID]
    if history:
        doc["provenance"]["path_migrations"] = history
    else:
        doc["provenance"].pop("path_migrations", None)
    return _dump(doc)


def _baseline_state(name: str, text: str) -> str:
    """'original' or 'migrated' (each verified by hash), else MigrationError."""
    if _sha_bytes(text.encode()) == ORIGINAL_BASELINES[name]:
        return "original"
    try:
        restored = original_baseline(text)
    except (ValueError, KeyError, TypeError) as exc:
        raise MigrationError(f"{BASELINE_DIR}/{name}: not a readable baseline ({exc})") from exc
    if (_sha_bytes(restored.encode()) == ORIGINAL_BASELINES[name]
            and migrated_baseline(restored) == text):
        return "migrated"
    raise MigrationError(f"{BASELINE_DIR}/{name}: is neither the validated baseline nor its "
                         "migrated form (changed since validation_phase1?)")


def _check_references(root: Path, name: str, text: str, problems: List[str]) -> None:
    """Every input a baseline records must exist (at its current or post-move path) with
    the hash recorded at capture."""
    inputs = json.loads(text)["provenance"]["inputs"]
    for entry in [inputs["trade_file"], *inputs["market_files"]]:
        recorded, path = entry["sha256"], entry["path"]
        candidates = [path] + ([_PATH_MAP[path]] if path in _PATH_MAP else []) + (
            [_REVERSE_MAP[path]] if path in _REVERSE_MAP else [])
        present = [c for c in candidates if (root / c).is_file()]
        if not present:
            problems.append(f"{BASELINE_DIR}/{name}: input {path} not found")
        elif _sha(root / present[0]) != recorded:
            problems.append(f"{BASELINE_DIR}/{name}: input {present[0]} differs from the "
                            f"file used at capture (sha256 {recorded[:12]}...)")
        if path in _PATH_MAP and recorded != dict((o, s) for o, _, s in MOVES)[path]:
            problems.append(f"{BASELINE_DIR}/{name}: records {path} with a hash other than "
                            "the validated file")


# --- preflight ------------------------------------------------------------------------------


def preflight(root: Path = ROOT, *, allow_journal: bool = False) -> Dict[str, object]:
    """Check the whole tree without changing it. Returns {'state': 'original' | 'migrated'
    | 'mixed', 'moves': {old: 'old'|'new'}, 'baselines': {name: state}}; raises
    MigrationError listing every problem found."""
    root = Path(root)
    problems: List[str] = []
    if (root / JOURNAL).exists() and not allow_journal:
        raise MigrationError(f"{JOURNAL} exists: a previous migration was interrupted; run "
                             "--rollback to restore the original layout first")
    moves: Dict[str, str] = {}
    for old, new, sha in MOVES:
        at_old, at_new = (root / old).is_file(), (root / new).is_file()
        if at_old and at_new:
            problems.append(f"both {old} and {new} exist: two competing copies")
        elif at_old or at_new:
            where = old if at_old else new
            if _sha(root / where) != sha:
                problems.append(f"{where} differs from the validated file (sha256 "
                                f"{_sha(root / where)[:12]}..., expected {sha[:12]}...)")
            moves[old] = "old" if at_old else "new"
        else:
            problems.append(f"neither {old} nor {new} exists")
    baselines: Dict[str, str] = {}
    for name in ORIGINAL_BASELINES:
        path = root / BASELINE_DIR / name
        if not path.is_file():
            problems.append(f"{BASELINE_DIR}/{name}: missing")
            continue
        text = _text(path)
        try:
            baselines[name] = _baseline_state(name, text)
        except MigrationError as exc:
            problems.append(str(exc))
            continue
        _check_references(root, name, text, problems)
    for path in sorted((root / BASELINE_DIR).glob("*.json")):
        if path.name in ORIGINAL_BASELINES:
            continue
        refs = json.loads(_text(path)).get("provenance", {}).get("inputs", {})
        paths = [f.get("path") for f in refs.get("market_files", [])]
        if any(p in _PATH_MAP or p in _REVERSE_MAP for p in paths):
            problems.append(f"{BASELINE_DIR}/{path.name}: references a moved file but is not "
                            "one of the baselines this migration updates")
    if problems:
        raise MigrationError("preflight failed, nothing changed:\n  - " + "\n  - ".join(problems))
    states = set(moves.values()) | {"old" if s == "original" else "new"
                                    for s in baselines.values()}
    state = {"old": "original", "new": "migrated"}[states.pop()] if len(states) == 1 \
        else "mixed"
    return {"state": state, "moves": moves, "baselines": baselines}


# --- migrate --------------------------------------------------------------------------------


def migrate(root: Path = ROOT, apply: bool = False, *,
            after_step: Optional[Callable[[str], None]] = None,
            rollback_on_error: bool = True) -> Dict[str, object]:
    """Preflight, then (with ``apply``) migrate. ``after_step`` is a test hook called after
    each change; ``rollback_on_error=False`` simulates an interrupted process (tests)."""
    root = Path(root)
    check = preflight(root)
    if check["state"] == "mixed":
        raise MigrationError("partially migrated tree without a journal; run --rollback")
    if check["state"] == "migrated":
        return {"state": "migrated", "changed": [], "record": RECORD}
    plan = [f"move {old} -> {new}" for old, new, _ in MOVES] + [
        f"update paths in {BASELINE_DIR}/{name}" for name in ORIGINAL_BASELINES]
    if not apply:
        return {"state": "original", "plan": plan, "changed": []}

    originals = {name: _text(root / BASELINE_DIR / name) for name in ORIGINAL_BASELINES}
    updated = {name: migrated_baseline(text) for name, text in originals.items()}
    (root / MIGRATIONS_DIR).mkdir(parents=True, exist_ok=True)
    _write_atomic(root / JOURNAL, _dump({
        "migration": MIGRATION_ID,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "moves": [{"from": o, "to": n, "sha256": s} for o, n, s in MOVES],
        "original_baselines": originals,
    }))
    changed: List[str] = []
    step = after_step or (lambda _: None)
    try:
        for old, new, sha in MOVES:
            (root / new).parent.mkdir(parents=True, exist_ok=True)
            os.replace(root / old, root / new)
            if _sha(root / new) != sha:
                raise MigrationError(f"{new}: content changed during the move")
            changed.append(f"moved {old} -> {new}")
            step(f"move {old}")
        for name, text in updated.items():
            _write_atomic(root / BASELINE_DIR / name, text)
            changed.append(f"updated {BASELINE_DIR}/{name}")
            step(f"baseline {name}")
        for folder in EMPTIED_DIRS:
            if (root / folder).is_dir() and not any((root / folder).iterdir()):
                (root / folder).rmdir()
        verified = preflight(root, allow_journal=True)
        if verified["state"] != "migrated":
            raise MigrationError(f"post-migration check found state {verified['state']!r}")
        _write_atomic(root / RECORD, _dump({
            "migration": MIGRATION_ID,
            "purpose": "single canonical market-data store: market_data/<date>/<CCY>/ for "
                       "raw and prepared curve data; shared fixings at market_data/<date>/",
            "moves": [{"from": o, "to": n, "sha256": s} for o, n, s in MOVES],
            "content_changed": False,
            "baselines_path_updated": [f"{BASELINE_DIR}/{n}" for n in ORIGINAL_BASELINES],
            "not_moved": NOT_MOVED,
            "rollback": "python -m scripts.migrate_market_data_layout --rollback",
            "applied_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }))
        (root / JOURNAL).unlink()
    except BaseException as exc:
        if not rollback_on_error:
            raise
        try:
            rollback(root)
        except Exception as again:  # noqa: BLE001 - reported with the original failure
            raise MigrationError(f"migration failed ({exc!r}) and the automatic rollback "
                                 f"also failed ({again}); the journal {JOURNAL} is kept: "
                                 "fix the cause and run --rollback") from exc
        raise MigrationError(f"migration failed ({exc!r}); rolled back, the original layout "
                             "is restored and verified") from exc
    return {"state": "migrated", "changed": changed, "record": RECORD}


# --- rollback -------------------------------------------------------------------------------


def rollback(root: Path = ROOT) -> Dict[str, object]:
    """Restore the original layout after an interrupted, failed or completed migration.
    Checks everything first; changes nothing if a check fails."""
    root = Path(root)
    journal_path = root / JOURNAL
    journal = json.loads(_text(journal_path)) if journal_path.exists() else None
    # Preflight: classify every file and baseline before changing anything.
    problems: List[str] = []
    moves_back: List[Tuple[str, str, str]] = []
    for old, new, sha in MOVES:
        at_old, at_new = (root / old).is_file(), (root / new).is_file()
        if at_old and at_new:
            problems.append(f"both {old} and {new} exist")
        elif at_new:
            if _sha(root / new) != sha:
                problems.append(f"{new} differs from the validated file")
            moves_back.append((old, new, sha))
        elif at_old:
            if _sha(root / old) != sha:
                problems.append(f"{old} differs from the validated file")
        else:
            problems.append(f"neither {old} nor {new} exists")
    restores: Dict[str, str] = {}
    for name in ORIGINAL_BASELINES:
        path = root / BASELINE_DIR / name
        if journal is not None:
            original = journal["original_baselines"][name]
            if _sha_bytes(original.encode()) != ORIGINAL_BASELINES[name]:
                problems.append(f"journal copy of {name} is not the validated baseline")
            elif not path.is_file() or _text(path) != original:
                restores[name] = original
            continue
        if not path.is_file():
            problems.append(f"{BASELINE_DIR}/{name}: missing")
            continue
        try:
            if _baseline_state(name, _text(path)) == "migrated":
                restores[name] = original_baseline(_text(path))
        except MigrationError as exc:
            problems.append(str(exc))
    if problems:
        raise MigrationError("rollback preflight failed, nothing changed:\n  - "
                             + "\n  - ".join(problems))
    for folder in EMPTIED_DIRS:
        (root / folder).mkdir(parents=True, exist_ok=True)
    for old, new, sha in moves_back:
        (root / old).parent.mkdir(parents=True, exist_ok=True)
        os.replace(root / new, root / old)
        if _sha(root / old) != sha:
            raise MigrationError(f"{old}: content changed during the move back")
    for name, text in restores.items():
        _write_atomic(root / BASELINE_DIR / name, text)
    for folder in (root / BASELINE_DIR, root / MIGRATIONS_DIR):
        for leftover in folder.glob("*.tmp") if folder.is_dir() else ():
            leftover.unlink()
    for path in (root / RECORD, journal_path):
        if path.exists():
            path.unlink()
    migrations = root / MIGRATIONS_DIR
    if migrations.is_dir() and not any(migrations.iterdir()):
        migrations.rmdir()
    if preflight(root)["state"] != "original":
        raise MigrationError("rollback did not restore the original layout")
    return {"state": "original", "moved_back": [n for _, n, _ in moves_back],
            "baselines_restored": sorted(restores)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--apply", action="store_true", help="perform the migration")
    action.add_argument("--rollback", action="store_true",
                        help="restore the original layout (interrupted or completed)")
    parser.add_argument("--root", default=ROOT, help="repository root (default: this repo)")
    args = parser.parse_args(argv)
    try:
        if args.rollback:
            outcome = rollback(Path(args.root))
            print(f"rolled back: {len(outcome['moved_back'])} file(s) moved back, "
                  f"{len(outcome['baselines_restored'])} baseline(s) restored; "
                  "original layout verified")
            return 0
        outcome = migrate(Path(args.root), apply=args.apply)
    except MigrationError as exc:
        print(f"MIGRATION STOPPED: {exc}", file=sys.stderr)
        return 2
    if outcome["state"] == "migrated" and not outcome["changed"]:
        print(f"already migrated and verified (record {outcome['record']})")
    elif args.apply:
        for line in outcome["changed"]:
            print(line)
        print(f"migrated and verified; record {outcome['record']}")
    else:
        print("preflight passed (all files, baselines and recorded hashes verified). Plan:")
        for line in outcome["plan"]:
            print(f"  {line}")
        print("dry run: nothing changed (use --apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
