/**
 * ╔══════════════════════════════════════════════════════════════════╗
 * ║                   OPTIMA — INSTRUMENT SCHEMA v0.6               ║
 * ║                                                                  ║
 * ║  Master configuration for all derivative instruments.            ║
 * ║  Drives the entire UI — fields, market data, models, engines,   ║
 * ║  sensitivities, analysis panels, and output panel visibility.   ║
 * ║                                                                  ║
 * ║  v0.6 Changes:                                                   ║
 * ║  - FIELD_GROUPS: Grouped 3-column workspace layout               ║
 * ║    (Counterparty | Economic Terms | Dates) matching              ║
 * ║    business team's Deloitte single deal UI                       ║
 * ║  - New fields: transaction_ref, client_name, counterparties,     ║
 * ║    dual notionals, effective_date, forward/discount curves       ║
 * ║  - Results strip: CCY selector, Long Term / Short Term split     ║
 * ╚══════════════════════════════════════════════════════════════════╝
 */


// ═══════════════════════════════════════════════════════════════════
// 0. TOP-LEVEL MODULE TABS
// ═══════════════════════════════════════════════════════════════════

const MODULE_TABS = [
  { id: 'valuation',    label: 'Valuation',           active: true },
  { id: 'fixed_income', label: 'Fixed Income',        active: false },
  { id: 'correlation',  label: 'Correlation Matrices', active: false },
  { id: 'het',          label: 'HET',                 active: false },
  { id: 'ecl',          label: 'ECL',                 active: false },
  { id: 'var',          label: 'VaR',                 active: false },
  { id: 'cash_mgmt',    label: 'Cash Management',     active: false },
  { id: 'alm',          label: 'ALM',                 active: false },
];


// ═══════════════════════════════════════════════════════════════════
// 1. VALUATION — ASSET CLASS SUB-SECTIONS
// ═══════════════════════════════════════════════════════════════════

const ASSET_CLASSES = [
  { id: 'fx',        label: 'FX',            badge: 'badge-fx' },
  { id: 'rates',     label: 'Interest Rate', badge: 'badge-rates' },
  { id: 'commodity', label: 'Commodity',     badge: 'badge-cmdty' },
  { id: 'equity',    label: 'Equity',        badge: 'badge-eq' },
  { id: 'credit',    label: 'Credit',        badge: 'badge-credit' },
];


// ═══════════════════════════════════════════════════════════════════
// 2. FX CATEGORY LAYOUT
// ═══════════════════════════════════════════════════════════════════
//
// Each card maps to a schema key + optional preset overrides.
// Presets override default field values when opening the workspace.

const FX_CATEGORIES = [
  {
    title: 'Forwards',
    cards: [
      { inst: 'fx_forward',       label: 'Vanilla Forward' },
      { inst: 'fx_range_forward', label: 'Range Forward' },
    ],
  },
  {
    title: 'Options',
    cards: [
      { inst: 'fx_option', label: 'Buy Call (BC)',   preset: { option_type: 'call',  direction: 'buy' } },
      { inst: 'fx_option', label: 'Sell Call (SC)',  preset: { option_type: 'call',  direction: 'sell' } },
      { inst: 'fx_option', label: 'Sell Put (SP)',   preset: { option_type: 'put',   direction: 'sell' } },
      { inst: 'fx_option', label: 'Buy Put (BP)',    preset: { option_type: 'put',   direction: 'buy' } },
      { inst: 'fx_seagull',      label: 'Seagull' },
      { inst: 'fx_call_spread',  label: 'Call Spread' },
      { inst: 'fx_put_spread',   label: 'Put Spread' },
      { inst: 'fx_range_forward_opt', label: 'Range Forward' },
    ],
  },
  {
    title: 'Swaps',
    cards: [
      { inst: 'principal_only_swap', label: 'POS' },
      { inst: 'ccirs',               label: 'CCIRS' },
    ],
  },
  {
    title: 'Exotics',
    cards: [
      { inst: 'fx_swaption',      label: 'Swaption' },
      { inst: 'fx_digital',       label: 'Digital Option' },
      { inst: 'fx_barrier',       label: 'Barrier Option' },
    ],
  },
];


// ═══════════════════════════════════════════════════════════════════
// 3. INSTRUMENT SCHEMA
// ═══════════════════════════════════════════════════════════════════

const SCHEMA = {

  // ─── FX: FORWARDS ──────────────────────────────────────────────

  fx_forward: {
    label:'FX Vanilla Forward', asset:'FX', badge:'badge-fx',
    market_data:['spot_rate','domestic_rate','foreign_rate'],
    models:[{v:'black_scholes',l:'Garman-Kohlhagen'}],
    engines:[{v:'analytic',l:'Analytic'}],
    sensitivities:[{id:'delta',l:'Delta',d:4},{id:'rho',l:'Rho',d:2}],
    analysis:['spot_ladder','scenario'],
    payoff:false, cashflows:false, risk_ladder:false, curves:false, resets:false,
  },
  fx_range_forward: {
    label:'FX Range Forward (Fwd)', asset:'FX', badge:'badge-fx',
    market_data:['spot_rate','domestic_rate','foreign_rate','fx_vol'],
    models:[{v:'black_scholes',l:'Garman-Kohlhagen'}],
    engines:[{v:'analytic',l:'Analytic'}],
    sensitivities:[{id:'delta',l:'Delta',d:4},{id:'gamma',l:'Gamma',d:4},{id:'vega',l:'Vega',d:4}],
    analysis:['spot_ladder','scenario'],
    payoff:true, cashflows:false, risk_ladder:false, curves:false, resets:false,
  },

  // ─── FX: OPTIONS ───────────────────────────────────────────────

  fx_option: {
    label:'FX Option', asset:'FX', badge:'badge-fx',
    market_data:['spot_rate','domestic_rate','foreign_rate','fx_vol'],
    models:[{v:'black_scholes',l:'Garman-Kohlhagen'},{v:'heston',l:'Heston'}],
    engines:[
      {v:'analytic',l:'Analytic',params:[]},
      {v:'monte_carlo',l:'Monte Carlo',params:['mc_paths','mc_steps']},
      {v:'heston_analytic',l:'Heston Analytic',params:['v0','kappa','theta_v','sigma_v','rho_h']},
    ],
    sensitivities:[{id:'delta',l:'Delta',d:4},{id:'gamma',l:'Gamma',d:4},{id:'vega',l:'Vega',d:4},{id:'theta',l:'Theta',d:4},{id:'rho',l:'Rho',d:4}],
    analysis:['spot_ladder','vol_ladder','spot_vol_matrix','scenario'],
    payoff:true, cashflows:false, risk_ladder:false, curves:false, resets:false,
  },
  fx_seagull: {
    label:'FX Seagull', asset:'FX', badge:'badge-fx',
    market_data:['spot_rate','domestic_rate','foreign_rate','fx_vol'],
    models:[{v:'black_scholes',l:'Garman-Kohlhagen'}],
    engines:[{v:'analytic',l:'Analytic'}],
    sensitivities:[{id:'delta',l:'Delta',d:4},{id:'gamma',l:'Gamma',d:4},{id:'vega',l:'Vega',d:4}],
    analysis:['spot_ladder','scenario'],
    payoff:true, cashflows:false, risk_ladder:false, curves:false, resets:false,
  },
  fx_call_spread: {
    label:'FX Call Spread', asset:'FX', badge:'badge-fx',
    market_data:['spot_rate','domestic_rate','foreign_rate','fx_vol'],
    models:[{v:'black_scholes',l:'Garman-Kohlhagen'}],
    engines:[{v:'analytic',l:'Analytic'}],
    sensitivities:[{id:'delta',l:'Delta',d:4},{id:'gamma',l:'Gamma',d:4},{id:'vega',l:'Vega',d:4}],
    analysis:['spot_ladder','scenario'],
    payoff:true, cashflows:false, risk_ladder:false, curves:false, resets:false,
  },
  fx_put_spread: {
    label:'FX Put Spread', asset:'FX', badge:'badge-fx',
    market_data:['spot_rate','domestic_rate','foreign_rate','fx_vol'],
    models:[{v:'black_scholes',l:'Garman-Kohlhagen'}],
    engines:[{v:'analytic',l:'Analytic'}],
    sensitivities:[{id:'delta',l:'Delta',d:4},{id:'gamma',l:'Gamma',d:4},{id:'vega',l:'Vega',d:4}],
    analysis:['spot_ladder','scenario'],
    payoff:true, cashflows:false, risk_ladder:false, curves:false, resets:false,
  },
  fx_range_forward_opt: {
    label:'FX Range Forward (Opt)', asset:'FX', badge:'badge-fx',
    market_data:['spot_rate','domestic_rate','foreign_rate','fx_vol'],
    models:[{v:'black_scholes',l:'Garman-Kohlhagen'}],
    engines:[{v:'analytic',l:'Analytic'}],
    sensitivities:[{id:'delta',l:'Delta',d:4},{id:'gamma',l:'Gamma',d:4},{id:'vega',l:'Vega',d:4}],
    analysis:['spot_ladder','vol_ladder','scenario'],
    payoff:true, cashflows:false, risk_ladder:false, curves:false, resets:false,
  },

  // ─── FX: SWAPS ─────────────────────────────────────────────────

  principal_only_swap: {
    label:'Principal Only Swap (POS)', asset:'FX', badge:'badge-fx',
    market_data:['spot_rate','domestic_rate','foreign_rate'],
    models:[{v:'discounting',l:'Discounting'}],
    engines:[{v:'analytic',l:'Analytic'}],
    sensitivities:[{id:'delta',l:'Delta',d:4},{id:'rho',l:'Rho',d:2}],
    analysis:['spot_ladder'],
    payoff:false, cashflows:true, risk_ladder:false, curves:false, resets:false,
  },
  ccirs: {
    label:'Cross Currency Interest Rate Swap', asset:'FX', badge:'badge-fx',
    market_data:['spot_rate','domestic_rate','foreign_rate'],
    models:[{v:'discounting',l:'Discounting'}],
    engines:[{v:'analytic',l:'Analytic'}],
    sensitivities:[{id:'dv01',l:'DV01',d:2},{id:'delta',l:'FX Delta',d:4},{id:'duration',l:'Duration',d:4}],
    analysis:['rate_ladder','spot_ladder','scenario'],
    payoff:false, cashflows:true, risk_ladder:true, curves:true, resets:true,
  },

  // ─── FX: EXOTICS ───────────────────────────────────────────────

  fx_swaption: {
    label:'FX Swaption', asset:'FX', badge:'badge-fx',
    market_data:['spot_rate','domestic_rate','foreign_rate','fx_vol'],
    models:[{v:'black_scholes',l:'Garman-Kohlhagen'},{v:'bachelier',l:'Bachelier'}],
    engines:[{v:'analytic',l:'Analytic'},{v:'monte_carlo',l:'Monte Carlo',params:['mc_paths','mc_steps']}],
    sensitivities:[{id:'delta',l:'Delta',d:4},{id:'gamma',l:'Gamma',d:4},{id:'vega',l:'Vega',d:4},{id:'theta',l:'Theta',d:4}],
    analysis:['spot_ladder','vol_ladder','scenario'],
    payoff:true, cashflows:false, risk_ladder:false, curves:false, resets:false,
  },
  fx_digital: {
    label:'FX Digital Option', asset:'FX', badge:'badge-fx',
    market_data:['spot_rate','domestic_rate','foreign_rate','fx_vol'],
    models:[{v:'black_scholes',l:'Garman-Kohlhagen'}],
    engines:[{v:'analytic',l:'Analytic'},{v:'monte_carlo',l:'Monte Carlo',params:['mc_paths','mc_steps']}],
    sensitivities:[{id:'delta',l:'Delta',d:4},{id:'gamma',l:'Gamma',d:4},{id:'vega',l:'Vega',d:4}],
    analysis:['spot_ladder','vol_ladder'],
    payoff:true, cashflows:false, risk_ladder:false, curves:false, resets:false,
  },
  fx_barrier: {
    label:'FX Barrier Option', asset:'FX', badge:'badge-fx',
    market_data:['spot_rate','domestic_rate','foreign_rate','fx_vol'],
    models:[{v:'black_scholes',l:'Garman-Kohlhagen'}],
    engines:[{v:'analytic',l:'Analytic'},{v:'monte_carlo',l:'Monte Carlo',params:['mc_paths','mc_steps']}],
    sensitivities:[{id:'delta',l:'Delta',d:4},{id:'gamma',l:'Gamma',d:4},{id:'vega',l:'Vega',d:4},{id:'theta',l:'Theta',d:4},{id:'rho',l:'Rho',d:4}],
    analysis:['spot_ladder','vol_ladder','scenario'],
    payoff:true, cashflows:false, risk_ladder:false, curves:false, resets:false,
  },

  // ─── INTEREST RATES ────────────────────────────────────────────

  irs: {
    label:'Interest Rate Swap', asset:'Interest Rates', badge:'badge-rates',
    market_data:['rate_curve'],
    models:[{v:'discounting',l:'Discounting'}],
    engines:[{v:'analytic',l:'Analytic'}],
    sensitivities:[{id:'dv01',l:'DV01',d:2},{id:'duration',l:'Duration',d:4},{id:'convexity',l:'Convexity',d:2}],
    analysis:['rate_ladder','scenario'],
    payoff:false, cashflows:true, risk_ladder:true, curves:true, resets:true,
  },
  cos: {
    label:'Coupon Only Swap', asset:'Interest Rates', badge:'badge-rates',
    market_data:['rate_curve'],
    models:[{v:'discounting',l:'Discounting'}],
    engines:[{v:'analytic',l:'Analytic'}],
    sensitivities:[{id:'dv01',l:'DV01',d:2},{id:'duration',l:'Duration',d:4}],
    analysis:['rate_ladder'],
    payoff:false, cashflows:true, risk_ladder:true, curves:true, resets:true,
  },
  cap_floor: {
    label:'Cap', asset:'Interest Rates', badge:'badge-rates',
    market_data:['rate_curve','ir_vol'],
    models:[{v:'black_scholes',l:'Black-76'},{v:'bachelier',l:'Bachelier'},{v:'hull_white_1f',l:'Hull-White 1F'}],
    engines:[{v:'analytic',l:'Analytic'},{v:'bachelier',l:'Bachelier'},{v:'hull_white',l:'HW Tree'}],
    sensitivities:[{id:'dv01',l:'DV01',d:2},{id:'vega',l:'Vega',d:4},{id:'duration',l:'Duration',d:4}],
    analysis:['rate_ladder','vol_ladder','scenario'],
    payoff:false, cashflows:true, risk_ladder:true, curves:true, resets:false,
  },
  floor: {
    label:'Floor', asset:'Interest Rates', badge:'badge-rates',
    market_data:['rate_curve','ir_vol'],
    models:[{v:'black_scholes',l:'Black-76'},{v:'bachelier',l:'Bachelier'},{v:'hull_white_1f',l:'Hull-White 1F'}],
    engines:[{v:'analytic',l:'Analytic'},{v:'bachelier',l:'Bachelier'},{v:'hull_white',l:'HW Tree'}],
    sensitivities:[{id:'dv01',l:'DV01',d:2},{id:'vega',l:'Vega',d:4},{id:'duration',l:'Duration',d:4}],
    analysis:['rate_ladder','vol_ladder','scenario'],
    payoff:false, cashflows:true, risk_ladder:true, curves:true, resets:false,
  },
  ir_collar: {
    label:'Collar', asset:'Interest Rates', badge:'badge-rates',
    market_data:['rate_curve','ir_vol'],
    models:[{v:'black_scholes',l:'Black-76'}],
    engines:[{v:'analytic',l:'Analytic'}],
    sensitivities:[{id:'dv01',l:'DV01',d:2},{id:'vega',l:'Vega',d:4}],
    analysis:['rate_ladder','scenario'],
    payoff:false, cashflows:true, risk_ladder:true, curves:true, resets:false,
  },
  swaption: {
    label:'Swaption', asset:'Interest Rates', badge:'badge-rates',
    market_data:['rate_curve','ir_vol'],
    models:[{v:'black_scholes',l:'Black-76'},{v:'bachelier',l:'Bachelier'},{v:'hull_white_1f',l:'Hull-White 1F'}],
    engines:[{v:'analytic',l:'Analytic'},{v:'bachelier',l:'Bachelier'},{v:'hull_white',l:'HW Tree'}],
    sensitivities:[{id:'dv01',l:'DV01',d:2},{id:'vega',l:'Vega',d:4},{id:'duration',l:'Duration',d:4}],
    analysis:['rate_ladder','vol_ladder','scenario'],
    payoff:false, cashflows:true, risk_ladder:true, curves:true, resets:false,
  },
  fra: {
    label:'FRA', asset:'Interest Rates', badge:'badge-rates',
    market_data:['rate_curve'],
    models:[{v:'discounting',l:'Discounting'}],
    engines:[{v:'analytic',l:'Analytic'}],
    sensitivities:[{id:'dv01',l:'DV01',d:2}],
    analysis:['rate_ladder'],
    payoff:false, cashflows:true, risk_ladder:true, curves:true, resets:false,
  },
  bond: {
    label:'Fixed Rate Bond / G-Sec', asset:'Interest Rates', badge:'badge-rates',
    market_data:['rate_curve'],
    models:[{v:'discounting',l:'Discounting'}],
    engines:[{v:'analytic',l:'Analytic'}],
    sensitivities:[{id:'dv01',l:'DV01',d:2},{id:'duration',l:'Duration',d:4},{id:'convexity',l:'Convexity',d:2}],
    analysis:['rate_ladder','scenario'],
    payoff:false, cashflows:true, risk_ladder:true, curves:true, resets:false,
  },

  // ─── EQUITY ────────────────────────────────────────────────────

  equity_swap: {
    label:'Equity Swap', asset:'Equity', badge:'badge-eq',
    market_data:['spot','rate_curve'],
    models:[{v:'discounting',l:'Discounting'}],
    engines:[{v:'analytic',l:'Analytic'}],
    sensitivities:[{id:'delta',l:'Delta',d:4},{id:'rho',l:'Rho',d:2}],
    analysis:['spot_ladder','scenario'],
    payoff:false, cashflows:false, risk_ladder:false, curves:false, resets:false,
  },
  esop: {
    label:'ESOP', asset:'Equity', badge:'badge-eq',
    market_data:['spot','vol','div_yield','rate_curve'],
    models:[{v:'black_scholes',l:'Black-Scholes'}],
    engines:[{v:'analytic',l:'Analytic'},{v:'binomial',l:'Binomial (CRR)'}],
    sensitivities:[{id:'delta',l:'Delta',d:4},{id:'vega',l:'Vega',d:4},{id:'theta',l:'Theta',d:4}],
    analysis:['spot_ladder','vol_ladder'],
    payoff:true, cashflows:false, risk_ladder:false, curves:false, resets:false,
  },
  vanilla_option: {
    label:'Vanilla Option', asset:'Equity', badge:'badge-eq',
    market_data:['spot','vol','div_yield','rate_curve'],
    models:[{v:'black_scholes',l:'Black-Scholes'},{v:'heston',l:'Heston'}],
    engines:[
      {v:'analytic',l:'Analytic',params:[]},
      {v:'finite_difference',l:'Finite Difference',params:['grid_points','time_steps']},
      {v:'binomial',l:'Binomial (CRR)',params:['tree_steps']},
      {v:'monte_carlo',l:'Monte Carlo',params:['mc_paths','mc_steps']},
      {v:'heston_analytic',l:'Heston Analytic',params:['v0','kappa','theta_v','sigma_v','rho_h']},
    ],
    sensitivities:[{id:'delta',l:'Delta',d:4},{id:'gamma',l:'Gamma',d:4},{id:'vega',l:'Vega',d:4},{id:'theta',l:'Theta',d:4},{id:'rho',l:'Rho',d:4}],
    analysis:['spot_ladder','vol_ladder','spot_vol_matrix','scenario'],
    payoff:true, cashflows:false, risk_ladder:false, curves:false, resets:false,
  },
  barrier_option: {
    label:'Barrier Option', asset:'Equity', badge:'badge-eq',
    market_data:['spot','vol','div_yield','rate_curve'],
    models:[{v:'black_scholes',l:'Black-Scholes'}],
    engines:[{v:'analytic',l:'Analytic',params:[]},{v:'finite_difference',l:'Finite Difference',params:['grid_points','time_steps']},{v:'monte_carlo',l:'Monte Carlo',params:['mc_paths','mc_steps']}],
    sensitivities:[{id:'delta',l:'Delta',d:4},{id:'gamma',l:'Gamma',d:4},{id:'vega',l:'Vega',d:4},{id:'theta',l:'Theta',d:4},{id:'rho',l:'Rho',d:4}],
    analysis:['spot_ladder','vol_ladder','scenario'],
    payoff:true, cashflows:false, risk_ladder:false, curves:false, resets:false,
  },
  digital_option: {
    label:'Digital Option', asset:'Equity', badge:'badge-eq',
    market_data:['spot','vol','div_yield','rate_curve'],
    models:[{v:'black_scholes',l:'Black-Scholes'}],
    engines:[{v:'analytic',l:'Analytic'},{v:'finite_difference',l:'Finite Difference'}],
    sensitivities:[{id:'delta',l:'Delta',d:4},{id:'gamma',l:'Gamma',d:4},{id:'vega',l:'Vega',d:4}],
    analysis:['spot_ladder','vol_ladder'],
    payoff:true, cashflows:false, risk_ladder:false, curves:false, resets:false,
  },
  asian_option: {
    label:'Asian Option', asset:'Equity', badge:'badge-eq',
    market_data:['spot','vol','div_yield','rate_curve'],
    models:[{v:'black_scholes',l:'Black-Scholes'}],
    engines:[{v:'monte_carlo',l:'Monte Carlo',params:['mc_paths','mc_steps']}],
    sensitivities:[{id:'delta',l:'Delta',d:4},{id:'gamma',l:'Gamma',d:4},{id:'vega',l:'Vega',d:4},{id:'theta',l:'Theta',d:4}],
    analysis:['spot_ladder','vol_ladder'],
    payoff:true, cashflows:false, risk_ladder:false, curves:false, resets:false,
  },
  lookback_option: {
    label:'Lookback Option', asset:'Equity', badge:'badge-eq',
    market_data:['spot','vol','div_yield','rate_curve'],
    models:[{v:'black_scholes',l:'Black-Scholes'}],
    engines:[{v:'monte_carlo',l:'Monte Carlo',params:['mc_paths','mc_steps']}],
    sensitivities:[{id:'delta',l:'Delta',d:4},{id:'vega',l:'Vega',d:4},{id:'theta',l:'Theta',d:4}],
    analysis:['spot_ladder','vol_ladder'],
    payoff:true, cashflows:false, risk_ladder:false, curves:false, resets:false,
  },

  // ─── COMMODITY ─────────────────────────────────────────────────

  commodity_future: {
    label:'Commodity Future', asset:'Commodity', badge:'badge-cmdty',
    market_data:['spot','rate_curve'],
    models:[{v:'discounting',l:'Cost of Carry'}],
    engines:[{v:'analytic',l:'Analytic'}],
    sensitivities:[{id:'delta',l:'Delta',d:4}],
    analysis:['spot_ladder'],
    payoff:false, cashflows:false, risk_ladder:false, curves:false, resets:false,
  },
  commodity_swap: {
    label:'Commodity Swap / Forward', asset:'Commodity', badge:'badge-cmdty',
    market_data:['spot','rate_curve'],
    models:[{v:'discounting',l:'Discounting'}],
    engines:[{v:'analytic',l:'Analytic'}],
    sensitivities:[{id:'delta',l:'Delta',d:4},{id:'rho',l:'Rho',d:2}],
    analysis:['spot_ladder','scenario'],
    payoff:false, cashflows:true, risk_ladder:false, curves:false, resets:false,
  },
  commodity_asian_option: {
    label:'Asian Option (Avg Strike)', asset:'Commodity', badge:'badge-cmdty',
    market_data:['spot','vol','rate_curve'],
    models:[{v:'black_scholes',l:'Black-76'}],
    engines:[{v:'monte_carlo',l:'Monte Carlo',params:['mc_paths','mc_steps']}],
    sensitivities:[{id:'delta',l:'Delta',d:4},{id:'gamma',l:'Gamma',d:4},{id:'vega',l:'Vega',d:4}],
    analysis:['spot_ladder','vol_ladder'],
    payoff:true, cashflows:false, risk_ladder:false, curves:false, resets:false,
  },
  commodity_spot_avg_option: {
    label:'Spot Option (Avg Strike)', asset:'Commodity', badge:'badge-cmdty',
    market_data:['spot','vol','rate_curve'],
    models:[{v:'black_scholes',l:'Black-76'}],
    engines:[{v:'monte_carlo',l:'Monte Carlo',params:['mc_paths','mc_steps']}],
    sensitivities:[{id:'delta',l:'Delta',d:4},{id:'gamma',l:'Gamma',d:4},{id:'vega',l:'Vega',d:4}],
    analysis:['spot_ladder','vol_ladder'],
    payoff:true, cashflows:false, risk_ladder:false, curves:false, resets:false,
  },

  // ─── CREDIT ────────────────────────────────────────────────────

  cds: {
    label:'Credit Default Swap', asset:'Credit', badge:'badge-credit',
    market_data:['rate_curve','hazard_rate','recovery_rate'],
    models:[{v:'hazard_rate',l:'Hazard Rate'}],
    engines:[{v:'midpoint',l:'MidPoint'},{v:'bootstrapped',l:'Bootstrapped'},{v:'isda',l:'ISDA'}],
    sensitivities:[{id:'cs01',l:'CS01',d:2},{id:'dv01',l:'DV01',d:2}],
    analysis:['spread_ladder','scenario'],
    payoff:false, cashflows:true, risk_ladder:false, curves:false, resets:false,
  },
};


// ═══════════════════════════════════════════════════════════════════
// 4. TRADE INPUT FIELDS
// ═══════════════════════════════════════════════════════════════════

const FIELDS = {
  // FX Forwards
  fx_forward:[{id:'ccy_pair',label:'Currency Pair',type:'text',val:'USDINR'},{id:'notional',label:'Notional',type:'number',val:1e6},{id:'strike',label:'Forward Rate',type:'number',val:84.50},{id:'expiry',label:'Maturity',type:'date',val:'2026-01-15'},{id:'direction',label:'Direction',type:'select',opts:['buy','sell'],val:'buy'}],
  fx_range_forward:[{id:'ccy_pair',label:'Currency Pair',type:'text',val:'USDINR'},{id:'notional',label:'Notional',type:'number',val:1e6},{id:'strike',label:'Strike Rate',type:'number',val:86.88},{id:'expiry',label:'Maturity Date',type:'date',val:'2026-01-15'},{id:'direction',label:'Direction',type:'select',opts:['buy','sell'],val:'sell'}],
  // FX Options
  fx_option:[{id:'ccy_pair',label:'Currency Pair',type:'text',val:'USDINR'},{id:'notional',label:'Notional',type:'number',val:1e6},{id:'strike',label:'Strike',type:'number',val:84.50},{id:'expiry',label:'Expiry',type:'date',val:'2026-01-15'},{id:'option_type',label:'Option Type',type:'select',opts:['call','put'],val:'call'},{id:'direction',label:'Direction',type:'select',opts:['buy','sell'],val:'buy'}],
  fx_seagull:[{id:'ccy_pair',label:'Currency Pair',type:'text',val:'USDINR'},{id:'notional',label:'Notional',type:'number',val:1e6},{id:'put_strike',label:'Put Strike',type:'number',val:82.50},{id:'call_strike',label:'Call Strike',type:'number',val:85.50},{id:'call_spread_strike',label:'Call Spread Strike',type:'number',val:87},{id:'expiry',label:'Expiry',type:'date',val:'2026-01-15'},{id:'direction',label:'Direction',type:'select',opts:['exporter','importer'],val:'exporter'}],
  fx_call_spread:[{id:'ccy_pair',label:'Currency Pair',type:'text',val:'USDINR'},{id:'notional',label:'Notional',type:'number',val:1e6},{id:'long_strike',label:'Long Call Strike',type:'number',val:85},{id:'short_strike',label:'Short Call Strike',type:'number',val:87},{id:'expiry',label:'Expiry',type:'date',val:'2026-01-15'}],
  fx_put_spread:[{id:'ccy_pair',label:'Currency Pair',type:'text',val:'USDINR'},{id:'notional',label:'Notional',type:'number',val:1e6},{id:'long_strike',label:'Long Put Strike',type:'number',val:84},{id:'short_strike',label:'Short Put Strike',type:'number',val:82},{id:'expiry',label:'Expiry',type:'date',val:'2026-01-15'}],
  fx_range_forward_opt:[{id:'ccy_pair',label:'Currency Pair',type:'text',val:'USDINR'},{id:'notional',label:'Notional',type:'number',val:1e6},{id:'lower_strike',label:'Lower Strike (Put)',type:'number',val:83},{id:'upper_strike',label:'Upper Strike (Call)',type:'number',val:86},{id:'expiry',label:'Expiry',type:'date',val:'2026-01-15'},{id:'direction',label:'Direction',type:'select',opts:['exporter','importer'],val:'exporter'},{id:'premium',label:'Premium',type:'number',val:0}],
  // FX Swaps
  principal_only_swap:[{id:'ccy_pair',label:'Currency Pair',type:'text',val:'USDINR'},{id:'notional_domestic',label:'Domestic Notional',type:'number',val:84e6},{id:'notional_foreign',label:'Foreign Notional',type:'number',val:1e6},{id:'start_date',label:'Start Date',type:'date',val:'2025-01-15'},{id:'maturity_date',label:'Maturity',type:'date',val:'2028-01-15'},{id:'exchange_rate',label:'Agreed Rate',type:'number',val:84}],
  ccirs:[{id:'ccy_pair',label:'Currency Pair',type:'text',val:'USDINR'},{id:'notional_domestic',label:'Domestic Notional (INR)',type:'number',val:84e7},{id:'notional_foreign',label:'Foreign Notional (USD)',type:'number',val:1e7},{id:'start_date',label:'Start Date',type:'date',val:'2025-01-15'},{id:'maturity_date',label:'Maturity',type:'date',val:'2030-01-15'},{id:'fixed_rate_domestic',label:'Fixed Rate (Domestic)',type:'number',val:0.065},{id:'fixed_rate_foreign',label:'Fixed Rate (Foreign)',type:'number',val:0.045},{id:'direction',label:'Direction',type:'select',opts:['pay_domestic','receive_domestic'],val:'pay_domestic'}],
  // FX Exotics
  fx_swaption:[{id:'ccy_pair',label:'Currency Pair',type:'text',val:'USDINR'},{id:'notional',label:'Notional',type:'number',val:1e6},{id:'strike',label:'Strike',type:'number',val:84.50},{id:'expiry',label:'Option Expiry',type:'date',val:'2026-01-15'},{id:'swap_tenor',label:'Swap Tenor',type:'text',val:'1Y'},{id:'option_type',label:'Type',type:'select',opts:['payer','receiver'],val:'payer'}],
  fx_digital:[{id:'ccy_pair',label:'Currency Pair',type:'text',val:'USDINR'},{id:'notional',label:'Notional',type:'number',val:1e6},{id:'strike',label:'Strike',type:'number',val:84.50},{id:'expiry',label:'Expiry',type:'date',val:'2026-01-15'},{id:'option_type',label:'Option Type',type:'select',opts:['call','put'],val:'call'},{id:'cash_payoff',label:'Cash Payoff',type:'number',val:1.0}],
  fx_barrier:[{id:'ccy_pair',label:'Currency Pair',type:'text',val:'USDINR'},{id:'notional',label:'Notional',type:'number',val:1e6},{id:'strike',label:'Strike',type:'number',val:84.50},{id:'expiry',label:'Expiry',type:'date',val:'2026-01-15'},{id:'option_type',label:'Option Type',type:'select',opts:['call','put'],val:'call'},{id:'barrier_level',label:'Barrier Level',type:'number',val:87},{id:'barrier_type',label:'Barrier Type',type:'select',opts:['UpOut','DownOut','UpIn','DownIn'],val:'UpOut'}],
  // Rates
  irs:[{id:'notional',label:'Notional',type:'number',val:1e7},{id:'currency',label:'Currency',type:'select',opts:['INR','USD','EUR'],val:'INR'},{id:'start_date',label:'Start Date',type:'date',val:'2025-01-15'},{id:'maturity_date',label:'Maturity',type:'date',val:'2030-01-15'},{id:'fixed_rate',label:'Fixed Rate',type:'number',val:0.065},{id:'float_spread',label:'Float Spread',type:'number',val:0},{id:'direction',label:'Direction',type:'select',opts:['pay_fixed','receive_fixed'],val:'pay_fixed'}],
  cos:[{id:'notional',label:'Notional',type:'number',val:1e7},{id:'currency',label:'Currency',type:'select',opts:['INR','USD','EUR'],val:'INR'},{id:'start_date',label:'Start Date',type:'date',val:'2025-01-15'},{id:'maturity_date',label:'Maturity',type:'date',val:'2030-01-15'},{id:'coupon_rate',label:'Coupon Rate',type:'number',val:0.065},{id:'float_index',label:'Float Index',type:'select',opts:['MIBOR','SOFR','EURIBOR'],val:'MIBOR'},{id:'direction',label:'Direction',type:'select',opts:['pay_fixed','receive_fixed'],val:'pay_fixed'}],
  cap_floor:[{id:'notional',label:'Notional',type:'number',val:1e7},{id:'currency',label:'Currency',type:'select',opts:['INR','USD','EUR'],val:'USD'},{id:'start_date',label:'Start Date',type:'date',val:'2025-01-15'},{id:'maturity_date',label:'Maturity',type:'date',val:'2030-01-15'},{id:'strike',label:'Cap Strike Rate',type:'number',val:0.05},{id:'cap_floor_type',label:'Type',type:'select',opts:['cap'],val:'cap'}],
  floor:[{id:'notional',label:'Notional',type:'number',val:1e7},{id:'currency',label:'Currency',type:'select',opts:['INR','USD','EUR'],val:'USD'},{id:'start_date',label:'Start Date',type:'date',val:'2025-01-15'},{id:'maturity_date',label:'Maturity',type:'date',val:'2030-01-15'},{id:'strike',label:'Floor Strike Rate',type:'number',val:0.04},{id:'cap_floor_type',label:'Type',type:'select',opts:['floor'],val:'floor'}],
  ir_collar:[{id:'notional',label:'Notional',type:'number',val:1e7},{id:'currency',label:'Currency',type:'select',opts:['INR','USD','EUR'],val:'INR'},{id:'start_date',label:'Start Date',type:'date',val:'2025-01-15'},{id:'maturity_date',label:'Maturity',type:'date',val:'2030-01-15'},{id:'cap_strike',label:'Cap Strike',type:'number',val:0.07},{id:'floor_strike',label:'Floor Strike',type:'number',val:0.05}],
  swaption:[{id:'notional',label:'Notional',type:'number',val:1e7},{id:'currency',label:'Currency',type:'select',opts:['INR','USD','EUR'],val:'USD'},{id:'expiry',label:'Expiry',type:'date',val:'2026-01-15'},{id:'swap_tenor',label:'Swap Tenor',type:'text',val:'5Y'},{id:'strike',label:'Strike',type:'number',val:0.045},{id:'swaption_type',label:'Type',type:'select',opts:['payer','receiver'],val:'payer'}],
  fra:[{id:'notional',label:'Notional',type:'number',val:1e7},{id:'currency',label:'Currency',type:'select',opts:['INR','USD','EUR'],val:'USD'},{id:'start_date',label:'Start Date',type:'date',val:'2025-06-15'},{id:'maturity_date',label:'Maturity',type:'date',val:'2025-12-15'},{id:'fixed_rate',label:'FRA Rate',type:'number',val:0.045},{id:'direction',label:'Direction',type:'select',opts:['pay','receive'],val:'pay'}],
  bond:[{id:'notional',label:'Notional',type:'number',val:1e6},{id:'currency',label:'Currency',type:'select',opts:['INR','USD','EUR'],val:'INR'},{id:'issue_date',label:'Issue Date',type:'date',val:'2024-01-15'},{id:'maturity_date',label:'Maturity',type:'date',val:'2034-01-15'},{id:'coupon_rate',label:'Coupon Rate',type:'number',val:0.072},{id:'frequency',label:'Frequency',type:'select',opts:['annual','semiannual','quarterly'],val:'semiannual'}],
  // Equity
  equity_swap:[{id:'underlying',label:'Underlying Index',type:'text',val:'NIFTY 50'},{id:'notional',label:'Notional',type:'number',val:1e7},{id:'currency',label:'Currency',type:'select',opts:['INR','USD'],val:'INR'},{id:'start_date',label:'Start Date',type:'date',val:'2025-01-15'},{id:'maturity_date',label:'Maturity',type:'date',val:'2026-01-15'},{id:'return_type',label:'Return Type',type:'select',opts:['total_return','price_return'],val:'total_return'},{id:'fixed_rate',label:'Fixed Rate',type:'number',val:0.065}],
  esop:[{id:'underlying',label:'Underlying Equity',type:'text',val:'RELIANCE'},{id:'strike',label:'Strike (Grant Price)',type:'number',val:2500},{id:'grant_date',label:'Grant Date',type:'date',val:'2024-01-15'},{id:'vesting_date',label:'Vesting Date',type:'date',val:'2027-01-15'},{id:'expiry',label:'Expiry',type:'date',val:'2029-01-15'},{id:'notional',label:'Quantity (Options)',type:'number',val:1000}],
  vanilla_option:[{id:'underlying',label:'Underlying',type:'text',val:'AAPL'},{id:'strike',label:'Strike',type:'number',val:185},{id:'expiry',label:'Expiry',type:'date',val:'2026-01-15'},{id:'option_type',label:'Option Type',type:'select',opts:['call','put'],val:'call'},{id:'notional',label:'Quantity (Contracts)',type:'number',val:100}],
  barrier_option:[{id:'underlying',label:'Underlying',type:'text',val:'AAPL'},{id:'strike',label:'Strike',type:'number',val:185},{id:'expiry',label:'Expiry',type:'date',val:'2026-01-15'},{id:'option_type',label:'Option Type',type:'select',opts:['call','put'],val:'call'},{id:'barrier_level',label:'Barrier Level',type:'number',val:200},{id:'barrier_type',label:'Barrier Type',type:'select',opts:['UpOut','DownOut','UpIn','DownIn'],val:'UpOut'},{id:'notional',label:'Quantity (Contracts)',type:'number',val:100}],
  digital_option:[{id:'underlying',label:'Underlying',type:'text',val:'AAPL'},{id:'strike',label:'Strike',type:'number',val:185},{id:'expiry',label:'Expiry',type:'date',val:'2026-01-15'},{id:'option_type',label:'Option Type',type:'select',opts:['call','put'],val:'call'},{id:'cash_payoff',label:'Cash Payoff',type:'number',val:1},{id:'notional',label:'Quantity (Contracts)',type:'number',val:100}],
  asian_option:[{id:'underlying',label:'Underlying',type:'text',val:'AAPL'},{id:'strike',label:'Strike',type:'number',val:185},{id:'expiry',label:'Expiry',type:'date',val:'2026-01-15'},{id:'option_type',label:'Option Type',type:'select',opts:['call','put'],val:'call'},{id:'averaging_type',label:'Averaging',type:'select',opts:['arithmetic','geometric'],val:'arithmetic'},{id:'notional',label:'Quantity (Contracts)',type:'number',val:100}],
  lookback_option:[{id:'underlying',label:'Underlying',type:'text',val:'AAPL'},{id:'expiry',label:'Expiry',type:'date',val:'2026-01-15'},{id:'option_type',label:'Option Type',type:'select',opts:['call','put'],val:'call'},{id:'notional',label:'Quantity (Contracts)',type:'number',val:100}],
  // Commodity
  commodity_future:[{id:'commodity',label:'Commodity',type:'select',opts:['Brent Crude','WTI','Gold','Silver','Copper','Natural Gas','Wheat','Corn'],val:'Brent Crude'},{id:'notional',label:'Notional (Units)',type:'number',val:1000},{id:'contract_month',label:'Contract Month',type:'text',val:'2026-APR'},{id:'futures_price',label:'Futures Price',type:'number',val:78.50},{id:'currency',label:'Currency',type:'select',opts:['USD','INR'],val:'USD'}],
  commodity_swap:[{id:'commodity',label:'Commodity',type:'select',opts:['Brent Crude','WTI','Gold','Silver','Copper','Natural Gas'],val:'Brent Crude'},{id:'notional',label:'Notional (Units)',type:'number',val:10000},{id:'currency',label:'Currency',type:'select',opts:['USD','INR'],val:'USD'},{id:'fixed_price',label:'Fixed Price',type:'number',val:78.10},{id:'start_date',label:'Start Date',type:'date',val:'2025-01-15'},{id:'maturity_date',label:'Maturity',type:'date',val:'2026-01-15'},{id:'payment_freq',label:'Payment Frequency',type:'select',opts:['monthly','quarterly'],val:'monthly'}],
  commodity_asian_option:[{id:'commodity',label:'Commodity',type:'select',opts:['Brent Crude','WTI','Gold','Silver','Copper'],val:'Brent Crude'},{id:'notional',label:'Notional (Units)',type:'number',val:5000},{id:'strike',label:'Strike Price',type:'number',val:80},{id:'expiry',label:'Expiry',type:'date',val:'2026-06-15'},{id:'option_type',label:'Option Type',type:'select',opts:['call','put'],val:'call'},{id:'avg_frequency',label:'Avg Frequency',type:'select',opts:['daily','weekly','monthly'],val:'monthly'},{id:'currency',label:'Currency',type:'select',opts:['USD','INR'],val:'USD'}],
  commodity_spot_avg_option:[{id:'commodity',label:'Commodity',type:'select',opts:['Brent Crude','WTI','Gold','Silver','Copper'],val:'Brent Crude'},{id:'notional',label:'Notional (Units)',type:'number',val:5000},{id:'option_type',label:'Option Type',type:'select',opts:['call','put'],val:'call'},{id:'window_start',label:'Avg Window Start',type:'date',val:'2026-01-01'},{id:'window_end',label:'Avg Window End',type:'date',val:'2026-06-30'},{id:'expiry',label:'Expiry',type:'date',val:'2026-06-30'},{id:'currency',label:'Currency',type:'select',opts:['USD','INR'],val:'USD'}],
  // Credit
  cds:[{id:'notional',label:'Notional',type:'number',val:1e7},{id:'currency',label:'Currency',type:'select',opts:['USD','EUR','INR'],val:'USD'},{id:'start_date',label:'Start Date',type:'date',val:'2025-01-15'},{id:'maturity_date',label:'Maturity',type:'date',val:'2030-01-15'},{id:'spread',label:'Spread',type:'number',val:0.01},{id:'direction',label:'Direction',type:'select',opts:['buy','sell'],val:'buy'},{id:'recovery_rate',label:'Recovery Rate',type:'number',val:0.40},{id:'hazard_rate',label:'Hazard Rate',type:'number',val:0.02}],
};


// ═══════════════════════════════════════════════════════════════════
// 5-8. SUPPORTING DEFINITIONS
// ═══════════════════════════════════════════════════════════════════

const MD_FIELDS = {
  pricing_date:{id:'pricing_date',label:'Pricing Date',type:'date'},
  spot:{id:'spot',label:'Spot Price',type:'number',ph:'e.g. 192.50'},
  spot_rate:{id:'spot',label:'Spot Rate',type:'number',ph:'e.g. 84.35'},
  vol:{id:'vol',label:'Volatility',type:'number',ph:'e.g. 0.25'},
  fx_vol:{id:'vol',label:'FX Volatility',type:'number',ph:'e.g. 0.06'},
  ir_vol:{id:'vol',label:'IR Volatility',type:'number',ph:'e.g. 0.20'},
  div_yield:{id:'div',label:'Dividend Yield',type:'number',ph:'e.g. 0.005'},
  rate_curve:{id:'rate',label:'Discount Rate',type:'number',ph:'e.g. 0.045'},
  domestic_rate:{id:'rate',label:'Domestic Rate',type:'number',ph:'e.g. 0.065'},
  foreign_rate:{id:'foreign_rate',label:'Foreign Rate',type:'number',ph:'e.g. 0.045'},
  hazard_rate:{id:'md_hazard',label:'Hazard Rate',type:'number',ph:'e.g. 0.02'},
  recovery_rate:{id:'md_recovery',label:'Recovery Rate',type:'number',ph:'e.g. 0.40'},
};

const ENGINE_PARAM_DEFS = {
  mc_paths:{id:'mc-paths',label:'MC Paths',type:'number',val:10000},
  mc_steps:{id:'mc-steps',label:'MC Steps',type:'number',val:252},
  grid_points:{id:'fd-grid',label:'FD Grid Points',type:'number',val:100},
  time_steps:{id:'fd-tsteps',label:'FD Time Steps',type:'number',val:100},
  tree_steps:{id:'tree-steps',label:'Tree Steps',type:'number',val:200},
  v0:{id:'h-v0',label:'v₀ (Init Var)',type:'number',val:0.04},
  kappa:{id:'h-kappa',label:'κ (Mean Rev)',type:'number',val:1.5},
  theta_v:{id:'h-theta',label:'θ (Long Var)',type:'number',val:0.04},
  sigma_v:{id:'h-sigma',label:'σᵥ (Vol of Vol)',type:'number',val:0.3},
  rho_h:{id:'h-rho',label:'ρ (Correlation)',type:'number',val:-0.7},
};

const ENGINE_PARAM_MAP = {
  mc_paths:'num_paths',mc_steps:'num_steps',grid_points:'grid_points',
  time_steps:'time_steps',tree_steps:'tree_steps',
  v0:'v0',kappa:'kappa',theta_v:'theta',sigma_v:'sigma',rho_h:'rho',
};

const ANALYSIS_PANELS = {
  spot_ladder:{title:'Spot Sensitivity Ladder',variable:'spot',label:'Spot Price',range:20,steps:11},
  vol_ladder:{title:'Volatility Ladder',variable:'vol',label:'Volatility',range:50,steps:11},
  rate_ladder:{title:'Rate Sensitivity Ladder',variable:'rate',label:'Interest Rate',range:2,steps:11},
  spread_ladder:{title:'Spread Sensitivity Ladder',variable:'spread',label:'Credit Spread',range:2,steps:11},
  spot_vol_matrix:{title:'Spot × Vol Heatmap',variable:null,label:null},
  scenario:{title:'Scenario Analysis',variable:null,label:null},
};

const SCENARIOS = [
  {name:'Market Crash (-20%)',key:'market_crash',shocks:{spot:-0.20,vol:0.50,rate:-0.01}},
  {name:'Vol Spike (+50%)',key:'vol_spike',shocks:{spot:0,vol:0.50,rate:0}},
  {name:'Rate Shock +100bp',key:'rate_up',shocks:{spot:0,vol:0,rate:0.01}},
  {name:'Rate Shock -100bp',key:'rate_down',shocks:{spot:0,vol:0,rate:-0.01}},
  {name:'Bull Market (+15%)',key:'bull',shocks:{spot:0.15,vol:-0.20,rate:0}},
  {name:'Stagflation',key:'stagflation',shocks:{spot:-0.10,vol:0.30,rate:0.02}},
];


// ═══════════════════════════════════════════════════════════════════
// 9. FIELD GROUPS — Grouped 3-column workspace layout
// ═══════════════════════════════════════════════════════════════════
//
// Instruments WITH a FIELD_GROUPS entry get the grouped layout
// (Counterparty | Economic Terms | Dates) matching the business
// team's Deloitte single deal UI.
//
// Instruments WITHOUT an entry fall back to the flat FIELDS layout.
//
// Group types:
//   {sub:'Title'}          → Sub-group heading (e.g. "Counterparty A")
//   {id, label, type, ...} → Standard field (same format as FIELDS)
//   fullWidth: true        → Group spans all 3 columns
//   layout: 'r3'           → Use 3-column row layout within group

const FIELD_GROUPS = {

  // ─── FX FORWARD ─── Matches Deloitte single deal layout exactly
  fx_forward: {
    groups: [
      {
        id:'counterparty', label:'Counterparty Details',
        fields: [
          {id:'optima_id',label:'Optima ID',type:'text',val:'',ph:'Auto-generated',ro:true},
          {id:'client_name',label:'Client Name',type:'text',val:'',ph:'e.g. EXL India'},
          {id:'transaction_ref',label:'Transaction Ref No.',type:'text',val:'',ph:'e.g. L01SFWD000130'},
          {id:'contract_type',label:'Type of Contract',type:'text',val:'Forward',ro:true},
          {sub:'Counterparty A'},
          {id:'cpty_a_name',label:'Name',type:'text',val:'',ph:'e.g. EXL India'},
          {id:'cpty_a_direction',label:'Direction',type:'select',opts:['Buy','Sell'],val:'Buy'},
          {sub:'Counterparty B'},
          {id:'cpty_b_name',label:'Name',type:'text',val:'',ph:'e.g. BOA'},
          {id:'cpty_b_direction',label:'Direction',type:'select',opts:['Buy','Sell'],val:'Sell'},
        ],
      },
      {
        id:'economic', label:'Economic Terms',
        fields: [
          {id:'strike',label:'Strike Rate',type:'number',val:86.88,ph:'Forward rate'},
          {id:'ccy_pair',label:'Currency Pair',type:'select',opts:['USDINR','EURINR','GBPINR','EURUSD','GBPUSD','USDJPY'],val:'USDINR'},
          {sub:'Notional Currency 1'},
          {id:'notional_1_position',label:'Position',type:'select',opts:['Buy','Sell'],val:'Sell'},
          {id:'notional_1_ccy',label:'Currency',type:'select',opts:['INR','USD','EUR','GBP','JPY'],val:'INR'},
          {id:'notional_1_amount',label:'Amount',type:'number',val:10000000,ph:'e.g. 10,00,000'},
          {sub:'Notional Currency 2'},
          {id:'notional_2_position',label:'Position',type:'select',opts:['Buy','Sell'],val:'Buy'},
          {id:'notional_2_ccy',label:'Currency',type:'select',opts:['INR','USD','EUR','GBP','JPY'],val:'USD'},
          {id:'notional_2_amount',label:'Amount',type:'number',val:0,ph:'Derived from CCY1'},
        ],
      },
      {
        id:'dates', label:'Dates',
        fields: [
          {id:'transaction_date',label:'Transaction Date',type:'date',val:'2022-11-07'},
          {id:'effective_date',label:'Effective Date',type:'date',val:'2022-11-07'},
          {id:'reporting_date',label:'Valuation / Reporting Date',type:'date',val:''},
          {id:'maturity_date',label:'Maturity Date',type:'date',val:'2025-07-29'},
        ],
      },
      {
        id:'market_data', label:'Market Data as on Valuation Date', fullWidth:true,
        fields: [
          {id:'spot',label:'Spot',type:'number',val:85.47,ph:'e.g. 85.47'},
          {id:'rate',label:'Domestic Rate',type:'number',val:0.065,ph:'e.g. 0.065'},
          {id:'foreign_rate',label:'Foreign Rate',type:'number',val:0.045,ph:'e.g. 0.045'},
          {id:'forward_curve',label:'Forward Curve',type:'text',val:'INR.MIFOR',ph:'Curve name'},
          {id:'forward_rate',label:'Forward Rate',type:'number',val:0,ph:'Computed'},
          {id:'discount_curve',label:'Discount Curve',type:'text',val:'INR.OIS',ph:'Curve name'},
          {id:'discount_factor',label:'Discount Factor',type:'number',val:0,ph:'Computed'},
          {id:'premium',label:'Premium',type:'number',val:0,ph:'0 for forwards'},
        ],
        layout:'r3',
      },
    ],
  },

  // ─── FX OPTION ─── Same structure, adds vol/option fields
  fx_option: {
    groups: [
      {
        id:'counterparty', label:'Counterparty Details',
        fields: [
          {id:'optima_id',label:'Optima ID',type:'text',val:'',ph:'Auto-generated',ro:true},
          {id:'client_name',label:'Client Name',type:'text',val:'',ph:'e.g. EXL India'},
          {id:'transaction_ref',label:'Transaction Ref No.',type:'text',val:''},
          {id:'contract_type',label:'Type of Contract',type:'text',val:'Option',ro:true},
          {sub:'Counterparty A'},
          {id:'cpty_a_name',label:'Name',type:'text',val:''},
          {id:'cpty_a_direction',label:'Direction',type:'select',opts:['Buy','Sell'],val:'Buy'},
          {sub:'Counterparty B'},
          {id:'cpty_b_name',label:'Name',type:'text',val:''},
          {id:'cpty_b_direction',label:'Direction',type:'select',opts:['Buy','Sell'],val:'Sell'},
        ],
      },
      {
        id:'economic', label:'Economic Terms',
        fields: [
          {id:'strike',label:'Strike Rate',type:'number',val:84.50},
          {id:'ccy_pair',label:'Currency Pair',type:'select',opts:['USDINR','EURINR','GBPINR','EURUSD'],val:'USDINR'},
          {id:'option_type',label:'Option Type',type:'select',opts:['call','put'],val:'put'},
          {id:'direction',label:'Buy/Sell',type:'select',opts:['buy','sell'],val:'buy'},
          {sub:'Notional Currency 1'},
          {id:'notional_1_position',label:'Position',type:'select',opts:['Buy','Sell'],val:'Sell'},
          {id:'notional_1_ccy',label:'Currency',type:'select',opts:['INR','USD','EUR'],val:'INR'},
          {id:'notional_1_amount',label:'Amount',type:'number',val:1000000},
          {id:'maturity_date',label:'Maturity Date',type:'date',val:'2026-01-15'},
          {id:'premium_amount',label:'Premium Paid',type:'number',val:0},
        ],
      },
      {
        id:'dates', label:'Dates',
        fields: [
          {id:'transaction_date',label:'Transaction Date',type:'date',val:''},
          {id:'effective_date',label:'Effective Date',type:'date',val:''},
          {id:'reporting_date',label:'Valuation / Reporting Date',type:'date',val:''},
        ],
      },
      {
        id:'market_data', label:'Market Data as on Valuation Date', fullWidth:true,
        fields: [
          {id:'spot',label:'Spot',type:'number',val:85.47},
          {id:'vol',label:'Volatility',type:'number',val:0.06,ph:'e.g. 0.06'},
          {id:'premium',label:'Premium',type:'number',val:0},
          {id:'forward_rate',label:'Forward Rate',type:'number',val:0},
          {id:'discount_curve',label:'Discount Curve',type:'text',val:'INR.OIS'},
          {id:'discount_factor',label:'Discount Factor',type:'number',val:0},
        ],
        layout:'r3',
      },
    ],
  },

  // ─── FX RANGE FORWARD (delivery window — same pricing as vanilla forward) ───
  fx_range_forward: {
    groups: [
      {
        id:'counterparty', label:'Counterparty Details',
        fields: [
          {id:'optima_id',label:'Optima ID',type:'text',val:'',ro:true},
          {id:'client_name',label:'Client Name',type:'text',val:'',ph:'e.g. Balkrishna Industries'},
          {id:'transaction_ref',label:'Transaction Ref No.',type:'text',val:''},
          {id:'contract_type',label:'Type of Contract',type:'text',val:'Range Forward',ro:true},
          {sub:'Counterparty A'},
          {id:'cpty_a_name',label:'Name',type:'text',val:''},
          {id:'cpty_a_direction',label:'Direction',type:'select',opts:['Buy','Sell'],val:'Buy'},
          {sub:'Counterparty B'},
          {id:'cpty_b_name',label:'Name',type:'text',val:''},
          {id:'cpty_b_direction',label:'Direction',type:'select',opts:['Buy','Sell'],val:'Sell'},
        ],
      },
      {
        id:'economic', label:'Economic Terms',
        fields: [
          {id:'strike',label:'Strike Rate',type:'number',val:86.88,ph:'Forward rate'},
          {id:'ccy_pair',label:'Currency Pair',type:'select',opts:['USDINR','EURINR','GBPINR','EURUSD','GBPUSD','USDJPY'],val:'USDINR'},
          {sub:'Notional Currency 1'},
          {id:'notional_1_position',label:'Position',type:'select',opts:['Buy','Sell'],val:'Sell'},
          {id:'notional_1_ccy',label:'Currency',type:'select',opts:['INR','USD','EUR','GBP','JPY'],val:'INR'},
          {id:'notional_1_amount',label:'Amount',type:'number',val:10000000,ph:'e.g. 10,00,000'},
          {sub:'Notional Currency 2'},
          {id:'notional_2_position',label:'Position',type:'select',opts:['Buy','Sell'],val:'Buy'},
          {id:'notional_2_ccy',label:'Currency',type:'select',opts:['INR','USD','EUR','GBP','JPY'],val:'USD'},
          {id:'notional_2_amount',label:'Amount',type:'number',val:0,ph:'Derived from CCY1'},
        ],
      },
      {
        id:'dates', label:'Dates',
        fields: [
          {id:'transaction_date',label:'Transaction Date',type:'date',val:''},
          {id:'effective_date',label:'Effective Date',type:'date',val:''},
          {id:'reporting_date',label:'Valuation / Reporting Date',type:'date',val:''},
          {sub:'Delivery Window'},
          {id:'delivery_start_date',label:'Delivery Start Date',type:'date',val:'',ph:'From date'},
          {id:'delivery_end_date',label:'Delivery End Date',type:'date',val:'',ph:'To date'},
          {sub:'Computed Maturity'},
          {id:'maturity_date',label:'Maturity Date',type:'date',val:'',ph:'Auto-computed from direction'},
          {id:'maturity_hint',label:'',type:'hint',val:'Sell → start date, Buy → end date'},
        ],
      },
      {
        id:'market_data', label:'Market Data as on Valuation Date', fullWidth:true,
        fields: [
          {id:'spot',label:'Spot',type:'number',val:85.47,ph:'e.g. 85.47'},
          {id:'rate',label:'Domestic Rate',type:'number',val:0.065,ph:'e.g. 0.065'},
          {id:'foreign_rate',label:'Foreign Rate',type:'number',val:0.045,ph:'e.g. 0.045'},
          {id:'forward_curve',label:'Forward Curve',type:'text',val:'INR.MIFOR',ph:'Curve name'},
          {id:'forward_rate',label:'Forward Rate',type:'number',val:0,ph:'Computed'},
          {id:'discount_curve',label:'Discount Curve',type:'text',val:'INR.OIS',ph:'Curve name'},
          {id:'discount_factor',label:'Discount Factor',type:'number',val:0,ph:'Computed'},
          {id:'premium',label:'Premium',type:'number',val:0,ph:'0 for forwards'},
        ],
        layout:'r3',
      },
    ],
  },
};