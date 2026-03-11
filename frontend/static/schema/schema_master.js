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
// INSTRUMENT_REGISTRY — populated by individual instrument modules
// ═══════════════════════════════════════════════════════════════════

const INSTRUMENT_REGISTRY = {};
