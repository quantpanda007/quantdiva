# Optima — Output Panel Specification

**Version:** 0.4.0  
**Date:** 2026-02-28  
**Status:** DRAFT — awaiting approval before implementation  
**Inspiration:** Bloomberg SWPM / OVI terminal output tabs

---

## 1. Architecture Overview

Every output panel follows the same pattern:

```
┌─────────────────────────────────────────────────────┐
│  PANEL                                              │
│  ├── Trigger        : Button click or auto-compute  │
│  ├── Data Source     : API endpoint + payload        │
│  ├── Rendering      : Table / Chart / Grid          │
│  ├── Applicability  : Which instrument types         │
│  └── Schema Key     : How it's defined in schema     │
└─────────────────────────────────────────────────────┘
```

Panels are organized into **collapsible sections** in the workspace,  
shown/hidden per instrument based on schema configuration.

---

## 2. Panel Inventory

### 2.1 Universal Panels (all 27 instruments)

| # | Panel | Bloomberg Equiv | Status |
|---|-------|-----------------|--------|
| A | NPV + Meta | Main tab header | ✅ Done |
| B | Sensitivities (Greeks) | Main tab → risk summary | ✅ Done |
| C | Engine Comparison | N/A (Optima-specific) | ✅ Done |
| D | Scenario Analysis | Tab 9 — Scenario | 🔲 UI only |
| E | Diagnostics | N/A (developer tool) | ✅ Done |
| F | Valuation (MTM P&L) | Trade → Valuation | ✅ Done |

### 2.2 Options Panels (equity, FX, commodity options)

| # | Panel | Bloomberg Equiv | Status |
|---|-------|-----------------|--------|
| G | Payoff Diagram | OVI → Payoff chart | 🔲 New |
| H | Sensitivity Ladder | Tab 10 — Risk | 🔲 UI only |
| I | Sensitivity Matrix | Tab 12 — Matrix | 🔲 UI only |

### 2.3 Rates Panels (IRS, COS, Cap/Floor, Swaption, FRA, Bond)

| # | Panel | Bloomberg Equiv | Status |
|---|-------|-----------------|--------|
| J | Cashflow Schedule | Tab 6 — Cashflow | 🔲 New |
| K | Risk Ladder (DV01 by bucket) | Tab 10 — Risk | 🔲 New |
| L | Curve Data | Tab 5 — Curves | 🔲 New |

### 2.4 Credit Panels (CDS)

| # | Panel | Bloomberg Equiv | Status |
|---|-------|-----------------|--------|
| M | Cashflow Schedule | Tab 6 — Cashflow | 🔲 New |
| N | Spread Ladder (CS01) | Tab 10 — Risk | 🔲 New |

### 2.5 Swap-Specific Panels (IRS, COS)

| # | Panel | Bloomberg Equiv | Status |
|---|-------|-----------------|--------|
| O | Resets (Fixings) | Tab 7 — Resets | 🔲 New |
| P | Amortization Schedule | Cashflow → Amort | 🔲 New |

---

## 3. Panel Specifications

---

### Panel A — NPV + Meta ✅

**Applicability:** All instruments  
**Trigger:** "Price" button  
**API:** `POST /api/v1/pricing/single`

**Display:**
```
┌──────────────────────────────────┐
│  NET PRESENT VALUE               │
│  $12,847.3921                    │
│  VAN-001 · black_scholes ·       │
│  analytic · 3ms                  │
└──────────────────────────────────┘
```

**Fields:** `npv`, `trade_id`, `model`, `engine`, `elapsed_ms`

---

### Panel B — Sensitivities ✅

**Applicability:** All instruments (schema-driven)  
**Trigger:** Auto-computed with Price  
**API:** `POST /api/v1/sensitivities/greeks`

**Payload addition:** `"measures": ["delta", "gamma", "vega", "theta", "rho"]`  
(measures list comes from `schema.sensitivities[].id`)

**Display:** Grid of KPI tiles
```
┌────────┬────────┬────────┬────────┬────────┐
│ DELTA  │ GAMMA  │ VEGA   │ THETA  │ RHO    │
│ 0.6234 │ 0.0182 │ 38.221 │-12.441 │ 28.932 │
└────────┴────────┴────────┴────────┴────────┘
```

**Per-instrument variation (from schema):**
- Equity options: Delta, Gamma, Vega, Theta, Rho
- IRS/Bond: DV01, Duration, Convexity
- CDS: CS01, DV01
- FX: Delta, Gamma, Vega, Theta, Rho
- Cap/Floor/Swaption: DV01, Vega, Duration

---

### Panel C — Engine Comparison ✅

**Applicability:** Instruments with 2+ engines  
**Trigger:** "Compare" button  
**API:** `POST /api/v1/pricing/compare`

**Display:** Table
```
┌──────────────────┬────────────┬───────────┬─────────┐
│ Engine           │ NPV        │ Diff (bps)│ Time    │
├──────────────────┼────────────┼───────────┼─────────┤
│ analytic         │ $12,847.39 │ —         │ 3ms     │
│ finite_difference│ $12,847.52 │ 0.1       │ 12ms    │
│ monte_carlo      │ $12,851.03 │ 2.8       │ 1,204ms │
└──────────────────┴────────────┴───────────┴─────────┘
```

---

### Panel D — Scenario Analysis 🔲

**Applicability:** All instruments with `"scenario"` in `schema.analysis`  
**Trigger:** "Run" button in scenario panel  
**API:** `POST /api/v1/risk/scenario`

**Payload:**
```json
{
  "instrument": { ... },
  "market_data": { ... },
  "model": "black_scholes",
  "engine": "analytic",
  "scenario": {
    "name": "market_crash",
    "shocks": { "spot": -0.20 }
  }
}
```

**Predefined Scenarios:**
| Scenario | Spot Shock | Vol Shock | Rate Shock |
|----------|-----------|-----------|------------|
| Market Crash (-20%) | -0.20 | +0.50 | -0.01 |
| Vol Spike (+50%) | 0 | +0.50 | 0 |
| Rate Shock +100bp | 0 | 0 | +0.01 |
| Rate Shock -100bp | 0 | 0 | -0.01 |
| Bull Market (+15%) | +0.15 | -0.20 | 0 |
| Stagflation | -0.10 | +0.30 | +0.02 |

**Display:** Table with bar chart
```
┌────────────────────┬────────────┬────────────┬──────────┐
│ Scenario           │ Base NPV   │ Stressed   │ P&L      │
├────────────────────┼────────────┼────────────┼──────────┤
│ Market Crash       │ $12,847    │ $8,203     │ -$4,644  │
│ Vol Spike          │ $12,847    │ $15,221    │ +$2,374  │
│ Rate +100bp        │ $12,847    │ $12,519    │ -$328    │
└────────────────────┴────────────┴────────────┴──────────┘
```

**Schema key:** `"scenario"` in `schema.analysis[]`

---

### Panel E — Diagnostics ✅

**Applicability:** All instruments  
**Trigger:** Auto-populated with Price  
**Display:** Collapsible `<pre>` block with raw JSON response

---

### Panel F — Valuation (MTM) ✅

**Applicability:** All instruments  
**Trigger:** "Valuate" button  
**API:** `POST /api/v1/pricing/single` (reprices at valuation date)

**Inputs:** Trade date, Entry price, Direction (long/short), Valuation date  
**Display:**
```
┌────────────┬──────────────┬───────────────┐
│ Entry NPV  │ Current NPV  │ Unrealized P&L│
│ $10,000.00 │ $12,847.39   │ +$2,847.39    │
└────────────┴──────────────┴───────────────┘
```

---

### Panel G — Payoff Diagram 🔲 NEW

**Applicability:** Options only  
**Instruments:** `vanilla_option`, `barrier_option`, `digital_option`, `asian_option`,
`lookback_option`, `fx_option`, `fx_range_forward`, `fx_seagull`,
`fx_put_spread`, `fx_call_spread`, `commodity_asian_option`, `commodity_spot_avg_option`

**Trigger:** Auto-generated on workspace open (client-side calculation)  
**API:** None (pure client-side math from trade params)

**Calculation (client-side):**
```
For spot_range = [strike * 0.5 ... strike * 1.5], step = 1%:
  call_payoff = max(spot - strike, 0)
  put_payoff  = max(strike - spot, 0)
  barrier: apply knock-in/knock-out logic
  spread: long_leg_payoff - short_leg_payoff
```

**Display:** Line chart (Plotly or inline SVG)
```
  Payoff ($)
  │        ╱
  │       ╱
  │──────╱──────── 0
  │               
  └──────────────── Spot
        Strike↑
```

**Chart elements:**
- X-axis: Spot price (range: ±50% around strike)
- Y-axis: Payoff at expiry
- Lines: Payoff at expiry (solid), Current P&L (dashed)
- Marker: Current spot price (vertical dotted line)
- Zero line: Horizontal at y=0

**Schema key:** New field `"payoff": true` in instrument schema, OR derive from presence of `option_type` / `strike` in FIELDS.

---

### Panel H — Sensitivity Ladder 🔲

**Applicability:** Instruments with `"spot_ladder"`, `"vol_ladder"`, `"rate_ladder"`, or `"spread_ladder"` in `schema.analysis`

**Trigger:** "Run" button in analysis panel  
**API:** `POST /api/v1/sensitivities/ladder`

**Payload:**
```json
{
  "instrument": { ... },
  "market_data": { ... },
  "model": "black_scholes",
  "engine": "analytic",
  "variable": "spot",
  "range_pct": 20,
  "steps": 11
}
```

**Variables by ladder type:**
| Ladder Key | Variable | Bump Target | Typical Range |
|-----------|----------|-------------|---------------|
| `spot_ladder` | `spot` | Underlying spot price | ±20% |
| `vol_ladder` | `vol` | Implied volatility | ±50% |
| `rate_ladder` | `rate` | Discount rate | ±200bp |
| `spread_ladder` | `spread` | Credit spread | ±200bp |

**Display:** Table + Line chart side by side
```
┌──────────┬────────────┬──────────┐    ╭─────────────────╮
│ Spot     │ NPV        │ Delta    │    │   NPV vs Spot   │
├──────────┼────────────┼──────────┤    │      ╱           │
│ 148.00   │ $5,221     │ 0.31     │    │    ╱             │
│ 166.50   │ $8,934     │ 0.48     │    │  ╱               │
│ 185.00   │ $12,847    │ 0.62     │    │╱                 │
│ 203.50   │ $17,102    │ 0.74     │    ╰─────────────────╯
│ 222.00   │ $21,644    │ 0.83     │
└──────────┴────────────┴──────────┘
```

**Schema key:** `schema.analysis[]` entries like `"spot_ladder"`, `"vol_ladder"`, etc.

---

### Panel I — Sensitivity Matrix (Heatmap) 🔲

**Applicability:** Instruments with `"spot_vol_matrix"` in `schema.analysis`  
**Instruments:** `vanilla_option`, `fx_option`

**Trigger:** "Generate" button  
**API:** `POST /api/v1/sensitivities/matrix`

**Payload:**
```json
{
  "instrument": { ... },
  "market_data": { ... },
  "variable_x": "spot",
  "variable_y": "vol",
  "range_x_pct": 20,
  "range_y_pct": 50,
  "steps_x": 9,
  "steps_y": 9
}
```

**Display:** Color-coded heatmap grid
```
        Vol →  0.15   0.20   0.25   0.30   0.35
Spot ↓
  160          $3.2   $5.1   $7.0   $8.9   $10.8
  170          $5.8   $7.9   $9.9   $11.8  $13.6
  180          $9.1   $11.2  $13.1  $14.9  $16.7
  190          $13.0  $14.9  $16.7  $18.4  $20.0
  200          $17.4  $19.1  $20.7  $22.2  $23.6

Colors: Red (low NPV) → Yellow (mid) → Green (high NPV)
Highlight: Cell at current spot × current vol
```

**Schema key:** `"spot_vol_matrix"` in `schema.analysis[]`

---

### Panel J — Cashflow Schedule 🔲 NEW

**Applicability:** Rates + Credit instruments  
**Instruments:** `irs`, `cos`, `cap_floor`, `floor`, `swaption`, `fra`, `bond`, `cds`

**Trigger:** "Cashflows" button (or auto with Price)  
**API:** `POST /api/v1/pricing/cashflows` ← NEW ENDPOINT NEEDED

**Payload:** Same as pricing payload

**Response:**
```json
{
  "legs": [
    {
      "leg_name": "Fixed Leg",
      "flows": [
        {
          "period_start": "2025-01-15",
          "period_end": "2025-07-15",
          "payment_date": "2025-07-17",
          "notional": 10000000,
          "rate": 0.065,
          "accrual_days": 181,
          "accrual_fraction": 0.5028,
          "cashflow": 326806.00,
          "discount_factor": 0.9785,
          "pv": 319773.43
        }
      ]
    },
    {
      "leg_name": "Float Leg",
      "flows": [ ... ]
    }
  ],
  "total_pv_leg1": 3180291.00,
  "total_pv_leg2": 3195832.00,
  "net_pv": -15541.00
}
```

**Display:** Scrollable table per leg
```
FIXED LEG                                                    PV: $3,180,291
┌────────────┬────────────┬────────────┬──────────┬──────────┬───────────┬──────────┐
│ Period      │ Pay Date   │ Notional   │ Rate     │ Accrual  │ Cashflow  │ PV       │
├────────────┼────────────┼────────────┼──────────┼──────────┼───────────┼──────────┤
│ Jan-Jul 25 │ 2025-07-17 │ 10,000,000 │ 6.500%   │ 0.5028   │ 326,806   │ 319,773  │
│ Jul-Jan 26 │ 2026-01-15 │ 10,000,000 │ 6.500%   │ 0.5056   │ 328,611   │ 312,904  │
│ ...        │            │            │          │          │           │          │
└────────────┴────────────┴────────────┴──────────┴──────────┴───────────┴──────────┘

FLOAT LEG                                                    PV: $3,195,832
┌────────────┬────────────┬────────────┬──────────┬──────────┬───────────┬──────────┐
│ Period      │ Pay Date   │ Notional   │ Proj Rate│ Accrual  │ Cashflow  │ PV       │
├────────────┼────────────┼────────────┼──────────┼──────────┼───────────┼──────────┤
│ Jan-Jul 25 │ 2025-07-17 │ 10,000,000 │ 6.823%   │ 0.5028   │ 343,048   │ 335,664  │
│ ...        │            │            │          │          │           │          │
└────────────┴────────────┴────────────┴──────────┴──────────┴───────────┴──────────┘

NET PV: -$15,541 (Pay Fixed perspective)
```

**Schema key:** New field `"cashflows": true` in instrument schema

---

### Panel K — Risk Ladder (DV01 by Bucket) 🔲 NEW

**Applicability:** Rates instruments  
**Instruments:** `irs`, `cos`, `cap_floor`, `floor`, `swaption`, `fra`, `bond`

**Trigger:** "Risk" button or auto with Price  
**API:** `POST /api/v1/sensitivities/ladder` with `variable: "rate"` and bucket tenors

**Payload:**
```json
{
  "instrument": { ... },
  "market_data": { ... },
  "variable": "rate",
  "buckets": ["1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "30Y"]
}
```

**Display:** Table + Bar chart
```
┌────────┬──────────┬──────────────────────┐
│ Tenor  │ DV01     │ ████████████         │
├────────┼──────────┼──────────────────────┤
│ 1Y     │ -12.3    │ ██                   │
│ 2Y     │ -45.8    │ ████                 │
│ 3Y     │ -89.2    │ ████████             │
│ 5Y     │ -156.4   │ █████████████        │
│ 7Y     │ -98.1    │ █████████            │
│ 10Y    │ -42.6    │ ████                 │
│ TOTAL  │ -444.4   │                      │
└────────┴──────────┴──────────────────────┘
```

**Schema key:** New field `"risk_ladder": true` in instrument schema

---

### Panel L — Curve Data 🔲 NEW

**Applicability:** Rates instruments  
**Instruments:** `irs`, `cos`, `cap_floor`, `floor`, `swaption`, `fra`, `bond`

**Trigger:** Auto-populated with Price  
**API:** `POST /api/v1/market/yield-curve/query`

**Display:** Table + Yield curve chart
```
┌────────┬──────────┬──────────────┬──────────────┐
│ Tenor  │ Zero Rate│ Discount Fct │ Forward Rate │
├────────┼──────────┼──────────────┼──────────────┤
│ 1M     │ 4.350%   │ 0.9964       │ 4.350%       │
│ 3M     │ 4.420%   │ 0.9890       │ 4.490%       │
│ 6M     │ 4.480%   │ 0.9780       │ 4.540%       │
│ 1Y     │ 4.500%   │ 0.9569       │ 4.540%       │
│ 2Y     │ 4.450%   │ 0.9161       │ 4.350%       │
│ 5Y     │ 4.380%   │ 0.8050       │ 4.248%       │
│ 10Y    │ 4.420%   │ 0.6475       │ 4.500%       │
│ 30Y    │ 4.550%   │ 0.2615       │ 4.895%       │
└────────┴──────────┴──────────────┴──────────────┘
```

**Chart:** Line chart with Zero Rate and Forward Rate curves

**Schema key:** New field `"curves": true` in instrument schema

---

### Panel M — CDS Cashflow Schedule 🔲 NEW

**Applicability:** Credit instruments  
**Instruments:** `cds`

**Trigger:** "Cashflows" button  
**API:** `POST /api/v1/pricing/cashflows` (same endpoint as Panel J)

**Display:**
```
PREMIUM LEG
┌────────────┬────────────┬──────────┬──────────┬────────────┐
│ Period      │ Pay Date   │ Spread   │ Cashflow │ PV         │
├────────────┼────────────┼──────────┼──────────┼────────────┤
│ Q1 2025    │ 2025-03-20 │ 100bp    │ 25,000   │ 24,850     │
│ Q2 2025    │ 2025-06-20 │ 100bp    │ 25,000   │ 24,412     │
│ ...        │            │          │          │            │
└────────────┴────────────┴──────────┴──────────┴────────────┘

DEFAULT LEG
┌────────────┬──────────────────┬───────────────┬────────────┐
│ Period      │ Survival Prob    │ Default Prob  │ Exp Loss PV│
├────────────┼──────────────────┼───────────────┼────────────┤
│ Q1 2025    │ 99.50%           │ 0.50%         │ 29,850     │
│ Q2 2025    │ 99.00%           │ 0.50%         │ 29,550     │
│ ...        │            │          │          │            │
└────────────┴──────────────────┴───────────────┴────────────┘
```

**Schema key:** Reuse `"cashflows": true`

---

### Panel N — Spread Ladder 🔲 NEW

**Applicability:** `cds`  
**Trigger:** "Run" in spread ladder panel  
**API:** `POST /api/v1/sensitivities/ladder` with `variable: "spread"`

Same display format as Panel H, with Credit Spread on X-axis.

**Schema key:** `"spread_ladder"` already in `schema.analysis[]`

---

### Panel O — Resets (Fixings) 🔲 NEW

**Applicability:** Floating-rate instruments  
**Instruments:** `irs`, `cos`

**Trigger:** Auto-populated with Cashflows  
**API:** Part of cashflow response, or `POST /api/v1/pricing/resets` ← NEW

**Display:**
```
┌────────────┬──────────┬──────────┬──────────────┐
│ Reset Date │ Index    │ Fixing   │ Status       │
├────────────┼──────────┼──────────┼──────────────┤
│ 2025-01-15 │ SOFRATE  │ 4.350%   │ ● Realized   │
│ 2025-04-15 │ SOFRATE  │ 4.280%   │ ● Realized   │
│ 2025-07-15 │ SOFRATE  │ 4.180%   │ ◎ Projected  │
│ 2025-10-15 │ SOFRATE  │ 4.120%   │ ◎ Projected  │
│ ...        │          │          │              │
└────────────┴──────────┴──────────┴──────────────┘
```

**Schema key:** New field `"resets": true` in instrument schema

---

### Panel P — Amortization Schedule 🔲 NEW

**Applicability:** Amortizing swaps (future, once amortization is supported)  
**Instruments:** `irs` (with amortization flag), `cos`

**Trigger:** Auto with Cashflows  
**API:** Part of cashflow response

**Display:**
```
┌────────────┬───────────────┬───────────────┬──────────────┐
│ Date       │ Notional      │ Amortization  │ Remaining    │
├────────────┼───────────────┼───────────────┼──────────────┤
│ 2025-01-15 │ 10,000,000    │ 0             │ 10,000,000   │
│ 2026-01-15 │ 10,000,000    │ 2,000,000     │ 8,000,000    │
│ 2027-01-15 │ 8,000,000     │ 2,000,000     │ 6,000,000    │
│ ...        │               │               │              │
└────────────┴───────────────┴───────────────┴──────────────┘
```

**Schema key:** New field `"amortization": true` (only when instrument params include amortization schedule)

---

## 4. Schema Extensions

To support the new panels, add these optional fields to instrument schemas:

```javascript
// In SCHEMA entries:
{
  // ... existing fields ...
  analysis: ['spot_ladder', 'vol_ladder', 'scenario'],  // existing
  
  // NEW output panel flags:
  payoff: true,           // Show payoff diagram (options)
  cashflows: true,        // Show cashflow schedule (rates, credit)
  risk_ladder: true,      // Show DV01 by bucket (rates)
  curves: true,           // Show discount/forecast curves (rates)
  resets: true,           // Show fixing schedule (floating-rate)
  amortization: false,    // Show amort schedule (if applicable)
}
```

**Proposed schema additions by instrument:**

| Instrument | payoff | cashflows | risk_ladder | curves | resets | amortization |
|-----------|--------|-----------|-------------|--------|--------|--------------|
| fx_forward | — | — | — | — | — | — |
| fx_option | ✓ | — | — | — | — | — |
| fx_range_forward | ✓ | — | — | — | — | — |
| fx_seagull | ✓ | — | — | — | — | — |
| fx_put_spread | ✓ | — | — | — | — | — |
| fx_call_spread | ✓ | — | — | — | — | — |
| principal_only_swap | — | ✓ | — | — | — | — |
| irs | — | ✓ | ✓ | ✓ | ✓ | future |
| cos | — | ✓ | ✓ | ✓ | ✓ | future |
| cap_floor | — | ✓ | ✓ | ✓ | — | — |
| floor | — | ✓ | ✓ | ✓ | — | — |
| ir_collar | — | ✓ | ✓ | ✓ | — | — |
| swaption | — | ✓ | ✓ | ✓ | — | — |
| fra | — | ✓ | ✓ | ✓ | — | — |
| bond | — | ✓ | ✓ | ✓ | — | — |
| equity_swap | — | — | — | — | — | — |
| esop | ✓ | — | — | — | — | — |
| vanilla_option | ✓ | — | — | — | — | — |
| barrier_option | ✓ | — | — | — | — | — |
| digital_option | ✓ | — | — | — | — | — |
| asian_option | ✓ | — | — | — | — | — |
| lookback_option | ✓ | — | — | — | — | — |
| commodity_future | — | — | — | — | — | — |
| commodity_swap | — | ✓ | — | — | — | — |
| commodity_asian_option | ✓ | — | — | — | — | — |
| commodity_spot_avg_option | ✓ | — | — | — | — | — |
| cds | — | ✓ | — | — | — | — |

---

## 5. New API Endpoints Needed

| Endpoint | Method | Purpose | Priority |
|----------|--------|---------|----------|
| `/api/v1/pricing/cashflows` | POST | Cashflow schedule for rates/credit | HIGH |
| `/api/v1/pricing/resets` | POST | Fixing schedule for floating-rate | MEDIUM |
| `/api/v1/sensitivities/ladder` | POST | Already exists — wire to UI | HIGH |
| `/api/v1/sensitivities/matrix` | POST | Already exists — wire to UI | HIGH |
| `/api/v1/risk/scenario` | POST | Already exists — wire to UI | HIGH |
| `/api/v1/market/yield-curve/query` | POST | Already exists — wire to UI | MEDIUM |

---

## 6. Implementation Order

### Phase 1 — Wire Existing APIs (no backend changes)
1. **Panel D** — Scenario Analysis (wire `/risk/scenario`)
2. **Panel H** — Sensitivity Ladders (wire `/sensitivities/ladder` + chart)
3. **Panel I** — Matrix Heatmap (wire `/sensitivities/matrix` + chart)

### Phase 2 — Client-Side Additions
4. **Panel G** — Payoff Diagram (pure JS, no API needed)

### Phase 3 — New Backend Endpoints
5. **Panel J/M** — Cashflow Schedule (new `/pricing/cashflows` endpoint)
6. **Panel K** — Risk Ladder by Bucket (extend `/sensitivities/ladder`)
7. **Panel L** — Curve Data (wire `/market/yield-curve/query`)

### Phase 4 — Enhancements
8. **Panel O** — Resets (new `/pricing/resets` or part of cashflows)
9. **Panel P** — Amortization (dependent on instrument support)

---

## 7. Chart Library

**Recommendation:** Lightweight inline SVG charts rendered client-side.

No external chart library needed for the terminal aesthetic. SVG gives:
- Pixel-perfect rendering matching the dark theme
- No CDN dependency (single HTML file stays self-contained)
- Tiny footprint vs. Plotly/Chart.js

For the heatmap (Panel I), use an HTML `<table>` with CSS background-color gradients.

If richer interactivity is later needed (tooltips, zoom), add Plotly via CDN as a single `<script>` tag.

---

## 8. UI Layout in Workspace

```
┌─────────────────────────────────────────────────────────┐
│ ◈ Optima          Home › Equity › Vanilla Option        │
├────────────────────────────┬────────────────────────────┤
│ TRADE INPUTS               │ NPV + META                 │
│ [fields from FIELDS]       │ [$12,847.3921]             │
│                            │                            │
│ MARKET DATA                │ SENSITIVITIES              │
│ [fields from MD_FIELDS]    │ [schema-driven tiles]      │
│                            │                            │
│ MODEL & ENGINE             │ ENGINE COMPARISON          │
│ [dropdowns + params]       │ [table — on demand]        │
│                            │                            │
│ [⚡ Price] [▦ Compare]     │ DIAGNOSTICS                │
│ [📥 Excel] [✕ Clear]      │ [collapsible JSON]         │
├────────────────────────────┴────────────────────────────┤
│ ▸ Payoff Diagram          (options only)                │
│ ▸ Cashflow Schedule       (rates/credit only)           │
│ ▸ Curve Data              (rates only)                  │
│ ▸ Resets                  (floating-rate only)          │
│ ▸ Valuation (MTM)                                       │
├─────────────────────────────────────────────────────────┤
│ ▸ Analysis                                              │
│   ┌─────────────────────┬─────────────────────┐        │
│   │ Spot Ladder + Chart │ Vol Ladder + Chart   │        │
│   ├─────────────────────┼─────────────────────┤        │
│   │ Spot×Vol Heatmap    │ Scenario Analysis    │        │
│   └─────────────────────┴─────────────────────┘        │
├─────────────────────────────────────────────────────────┤
│ ▸ Risk                   (rates only)                   │
│   ┌─────────────────────┬─────────────────────┐        │
│   │ DV01 Bucket Ladder  │ Bar Chart            │        │
│   └─────────────────────┴─────────────────────┘        │
└─────────────────────────────────────────────────────────┘
```

All sections below the main pricing area are **collapsible** (`<details>`).  
Sections only appear if the instrument schema includes the relevant flag.