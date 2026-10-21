# Market data (canonical store)

One store for raw market data and the prepared snapshots the pricing engine reads.
The layout is defined in code once, in `market/market_data_layout.py`.

```
market_data/
  <valuation date>/
    fixings_<valuation date>.json           shared dated fixings, all currencies
    <CCY>/
      market_data.json                      raw source export (builders only)
      <ccy>_<curve>_<valuation date>.json   prepared curve snapshot (engine input)
      <other raw sources>                   e.g. USD zero-rate export
  migrations/                               record of each layout migration
```

## Roles

| File | Role | Read by |
|---|---|---|
| `<CCY>/market_data.json` | Raw source: Bloomberg curve export (Date, Market Rate, Discount Factor) | Snapshot builders, tests |
| `<CCY>/<ccy>_<curve>_<date>.json` | Prepared snapshot: curve id, conventions, pillars, zero rates. **The only curve file the pricing engine reads.** | `price_irs_engine.resolve_market_files`, audit, regression suite |
| `fixings_<date>.json` | Index fixings on or before the valuation date, each series with its source. Shared by all currencies, so kept once at the date level. | Resolver, only when a trade needs a fixing |

Each prepared snapshot exists once. Nothing else in the repository holds a copy
(`examples/irs/` holds trade inputs only). A missing file is an error; there is no
fallback to another date, currency or folder.

## How each 2026-03-31 snapshot was prepared

| Snapshot | Source in this folder | Builder | Notes |
|---|---|---|---|
| `USD/usd_sofr_2026-03-31.json` (curve `USD-SOFR-490`) | `USD/2026-03-31-USD-SOFR-zero.json` (Bloomberg 490-USDSOFR "Zero Rate" column, supplied by the SME on 09-Oct-2026) | `python -m scripts.build_usd_curve_snapshot` (check mode by default) reproduces the stored snapshot **byte for byte**; `tests/unit/test_irs/test_usd_curve_snapshot_builder.py` checks this. | Derived from the source: tenors, zero rates (`Zero Rate % / 100`), DFs. Fixed in the builder as recorded at creation, not derived from the source: curve id, conventions, assignment, provenance text. The zero rates are **not** in `USD/market_data.json`; only the DFs are shared (identical). The snapshot is not a bootstrap from the par rates. |
| `CHF/chf_saron_2026-03-31.json` (curve 234) | `CHF/market_data.json` discount factors | `python -m scripts.build_chf_curve_snapshot` | zero = -ln(DF)/t |
| `INR/inr_mibor_2026-03-31.json` | `INR/market_data.json` par rates | `python -m scripts.build_ois_curve_snapshots [--check]` | QuantLib OIS bootstrap |
| `JPY/jpy_tona_2026-03-31.json` | `JPY/market_data.json` par rates | `python -m scripts.build_ois_curve_snapshots [--check]` | QuantLib OIS bootstrap |

### USD snapshot conventions (stated in the snapshot, applied by `market/curves/irs_zero_curve.py`)

- Reference date 2026-03-31; calendar US-SOFR; spot lag 2 business days; Modified Following;
  no end-of-month.
- Pillar = spot + tenor (tenors inferred in the source file, not exported).
- Zero rates: ACT/365F, continuously compounded.
- Interpolation `linear_zero` (linear in continuously compounded zero rate); flat first zero
  from the reference date to the first pillar; no extrapolation beyond the last pillar.
- Discount-factor check tolerance 1e-6 against the exported DFs.
- Known differences against Bloomberg: docs/IRS_OPEN_ITEMS.md OI-1, OI-7.

## Rebuilding versus reproducing

The builders reproduce or check the existing snapshots, and none of them rebuilds a curve as
part of this layout change:

| Builder | Snapshot | How it is checked |
|---|---|---|
| `build_usd_curve_snapshot` | USD | Byte for byte. Writes only to a new file given with `--output`. |
| `build_chf_curve_snapshot` | CHF | Text equality. Prints the snapshot to stdout. |
| `build_ois_curve_snapshots --check` | INR, JPY | Numerically, zero rates within 1e-12. Writes only without `--check`. |

Changing how a curve is constructed is a separate future task, including building the USD
curve from the par rates in `USD/market_data.json` (OI-1). It needs its own decision, and
the regression baselines would change with it.

## Migration 2026-10-21

`scripts/migrate_market_data_layout.py` moved the prepared snapshots and the fixings file
from `examples/irs/`, and the USD zero-rate source from
`tests/fixtures/bloomberg_irs/curves/`, into this layout. File contents are byte-identical
(SHA-256 checked before and after every move). The expected-output baselines had their
recorded input *paths* updated (`provenance.path_migrations`); hashes and expected values are
unchanged. The record is `migrations/2026-10-21-market-data-layout.json`.

Safety, in order:

1. A preflight checks every file, every baseline (against its validated hash), and every input
   hash a baseline records. Nothing changes if any check fails.
2. A journal of the plan and the original baselines is written before the first change.
3. Any failure rolls back automatically.
4. `--rollback` recovers an interrupted migration, or reverses a completed one.

Tests run on fresh repository copies: `tests/unit/test_irs/test_market_data_migration.py`.

```
python -m scripts.migrate_market_data_layout              # preflight + plan, no change
python -m scripts.migrate_market_data_layout --apply
python -m scripts.migrate_market_data_layout --rollback
```

Because contents were not edited, two texts inside the moved files still describe the old
location:

- The USD snapshot's `provenance` names
  `tests/fixtures/bloomberg_irs/curves/2026-03-31-USD-SOFR-zero.json`, now
  `USD/2026-03-31-USD-SOFR-zero.json`. The builder reproduces that text verbatim.
- That source file's `purpose` still calls it a test-only oracle curve. Its role is now the
  raw source of the USD prepared snapshot.

Not moved: `examples/irs/fixings_2026-03-31_tc11_test.json`, a TC11 test-only fixings
override (adds SOFR 30-Mar-2026). The resolver never reads it.
