#!/usr/bin/env python3
"""
sync_files.py — Auto-place downloaded files into the quantlib-pricing project.

USAGE:
------
1. QUICK MODE: Drop a file with its target path encoded in the filename:
    
    Download a file I give you and save it as:
        engines__lattice__binomial_engine.py
    
    Then run:
        python sync_files.py
    
    It will be placed at: engines/lattice/binomial_engine.py

2. EXPLICIT MODE: Specify source and destination:
    
        python sync_files.py --src ~/Downloads/binomial_engine.py --dst engines/lattice/binomial_engine.py

3. BATCH MODE: Process all *.py files in a staging folder:
    
        python sync_files.py --batch ~/Downloads/quantlib-staging/

4. INTERACTIVE MODE: Pick from files in your downloads folder:
    
        python sync_files.py --interactive

HOW FILENAME ENCODING WORKS:
-----------------------------
    Double underscores (__) represent directory separators.
    Single underscores (_) are kept as-is.
    
    Examples:
        engines__analytic__bsm_engine.py        → engines/analytic/bsm_engine.py
        instruments__common__payoffs.py          → instruments/common/payoffs.py
        models__equity__heston.py                → models/equity/heston.py
        services__calibration__implied_vol.py    → services/calibration/implied_vol.py
"""

import argparse
import shutil
import sys
import os
from pathlib import Path
from datetime import datetime


# ---------------------------------------------------------------------------
# Configuration — EDIT THIS to match your local setup
# ---------------------------------------------------------------------------

# Detect OS and set paths accordingly
import platform

if platform.system() == "Windows":
    # Windows paths — UPDATE THESE to your actual locations
    PROJECT_ROOT = Path(r"C:\Users\Abhishek\Quantdiva\quantlib-pricing")
    DEFAULT_STAGING_DIR = Path(r"C:\Users\Abhishek\Quantdiva\quantlib-staging")
else:
    # macOS / Linux
    PROJECT_ROOT = Path(__file__).parent.resolve()
    DEFAULT_STAGING_DIR = Path.home() / "Downloads" / "quantlib-staging"

# Override: if this script lives inside the project, use its location
if (Path(__file__).parent / "core").exists():
    PROJECT_ROOT = Path(__file__).parent.resolve()

# Log file for tracking all synced files
SYNC_LOG = PROJECT_ROOT / ".sync_log.txt"


# ---------------------------------------------------------------------------
# Core sync logic
# ---------------------------------------------------------------------------

def decode_filename(encoded_name: str) -> str:
    """
    Convert encoded filename to relative path.
    
    engines__analytic__bsm_engine.py → engines/analytic/bsm_engine.py
    """
    # Split off extension
    stem, ext = os.path.splitext(encoded_name)
    # Replace double underscore with path separator
    path_str = stem.replace("__", os.sep)
    return path_str + ext


def sync_file(src: Path, dst_relative: str, dry_run: bool = False) -> bool:
    """
    Copy src file to PROJECT_ROOT / dst_relative.
    Creates directories as needed. Backs up existing files.
    """
    dst = PROJECT_ROOT / dst_relative

    # Create parent directories
    dst.parent.mkdir(parents=True, exist_ok=True)

    # Ensure __init__.py exists in every directory in the path
    parts = Path(dst_relative).parts[:-1]  # all dirs except the file
    for i in range(1, len(parts) + 1):
        init_path = PROJECT_ROOT / Path(*parts[:i]) / "__init__.py"
        if not init_path.exists():
            if not dry_run:
                init_path.touch()
            print(f"  Created: {init_path.relative_to(PROJECT_ROOT)}")

    # Backup existing file
    if dst.exists():
        backup = dst.with_suffix(dst.suffix + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        if not dry_run:
            shutil.copy2(dst, backup)
        print(f"  Backed up: {dst_relative} → {backup.name}")

    # Copy
    if not dry_run:
        shutil.copy2(src, dst)
        log_sync(src.name, dst_relative)

    status = "WOULD COPY" if dry_run else "SYNCED"
    print(f"  {status}: {src.name} → {dst_relative}")
    return True


def log_sync(src_name: str, dst_relative: str):
    """Append to sync log for audit trail."""
    with open(SYNC_LOG, "a") as f:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"{timestamp} | {src_name} → {dst_relative}\n")


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def mode_quick(staging_dir: Path, dry_run: bool = False):
    """Process all files with encoded names (double-underscore pattern)."""
    if not staging_dir.exists():
        print(f"Staging directory does not exist: {staging_dir}")
        print(f"Create it with: mkdir -p {staging_dir}")
        return

    files = list(staging_dir.glob("*.py"))
    if not files:
        print(f"No .py files found in {staging_dir}")
        return

    print(f"Found {len(files)} file(s) in {staging_dir}:\n")
    
    synced = 0
    for f in sorted(files):
        if "__" in f.stem:
            dst = decode_filename(f.name)
            print(f"  {f.name}")
            print(f"    → {dst}")
            if sync_file(f, dst, dry_run):
                synced += 1
                if not dry_run:
                    # Move processed file to a 'done' subfolder
                    done_dir = staging_dir / "done"
                    done_dir.mkdir(exist_ok=True)
                    shutil.move(str(f), str(done_dir / f.name))
        else:
            print(f"  SKIPPED (no __ encoding): {f.name}")

    print(f"\nSynced {synced} file(s).")


def mode_explicit(src: str, dst: str, dry_run: bool = False):
    """Copy a specific file to a specific destination."""
    src_path = Path(src).expanduser()
    if not src_path.exists():
        print(f"Source file not found: {src_path}")
        return
    sync_file(src_path, dst, dry_run)


def mode_batch(batch_dir: str, dry_run: bool = False):
    """Process all .py files in a directory using encoded naming."""
    mode_quick(Path(batch_dir).expanduser(), dry_run)


def mode_interactive(staging_dir: Path, dry_run: bool = False):
    """Interactive mode: show files and ask where to place them."""
    if not staging_dir.exists():
        staging_dir.mkdir(parents=True, exist_ok=True)
        print(f"Created staging dir: {staging_dir}")

    files = sorted(staging_dir.glob("*.py"))
    if not files:
        print(f"No .py files in {staging_dir}")
        return

    print(f"\nFiles in {staging_dir}:\n")
    for i, f in enumerate(files):
        auto_dst = decode_filename(f.name) if "__" in f.stem else "?"
        print(f"  [{i}] {f.name}  →  {auto_dst}")

    print()
    for i, f in enumerate(files):
        if "__" in f.stem:
            auto_dst = decode_filename(f.name)
            answer = input(f"  {f.name} → {auto_dst}  [Y/n/custom path]: ").strip()
            if answer.lower() in ("", "y", "yes"):
                sync_file(f, auto_dst, dry_run)
            elif answer.lower() in ("n", "no", "skip"):
                print("    Skipped.")
            else:
                sync_file(f, answer, dry_run)
        else:
            dst = input(f"  {f.name} → Enter destination path: ").strip()
            if dst:
                sync_file(f, dst, dry_run)
            else:
                print("    Skipped.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Sync downloaded files into quantlib-pricing project structure.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EXAMPLES:
  python sync_files.py                                           # Quick mode: process staging folder
  python sync_files.py --interactive                             # Interactive: confirm each file
  python sync_files.py --src ~/Downloads/bsm.py --dst engines/analytic/bsm_engine.py
  python sync_files.py --batch ~/Downloads/quantlib-staging/
  python sync_files.py --dry-run                                 # Preview without copying
        """,
    )
    parser.add_argument("--src", help="Source file path")
    parser.add_argument("--dst", help="Destination relative path within project")
    parser.add_argument("--batch", help="Batch process all .py files in directory")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
    parser.add_argument("--staging", default=str(DEFAULT_STAGING_DIR), help="Staging directory path")
    parser.add_argument("--dry-run", action="store_true", help="Preview without making changes")

    args = parser.parse_args()

    print(f"Project root: {PROJECT_ROOT}")
    print(f"Staging dir:  {args.staging}\n")

    if args.src and args.dst:
        mode_explicit(args.src, args.dst, args.dry_run)
    elif args.batch:
        mode_batch(args.batch, args.dry_run)
    elif args.interactive:
        mode_interactive(Path(args.staging), args.dry_run)
    else:
        mode_quick(Path(args.staging), args.dry_run)


if __name__ == "__main__":
    main()
