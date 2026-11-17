/**
 * Interest Rate Swap — instrument module
 *
 * Workspace: the IRS page #page-irs in optima.html (original three-tab design: Economic
 * Terms, Amortization Schedule, Market Data & Pricing Results). The core opens it through
 * the registry (`workspacePage`); this module owns its behaviour.
 *
 * Pricing: only the existing Python IRS engine, through POST /api/v1/pricing/irs
 * (services.irs_inputs: normalize -> price_normalized -> price_irs_engine, canonical
 * market data). This module reads the inputs, maps them to the engine's trade-input
 * contract (services/irs_inputs/contract.py, TradeInputs) and displays the engine's
 * response. It contains no pricing calculation and shows no number the engine did not
 * return.
 *
 * Mapping rules:
 *  - values are sent in analyst units and labels, exactly as the Excel input workbook
 *    holds them (rate in percent, spread in bp, labels such as "Modified Following");
 *    the backend normalizer converts and validates them;
 *  - an empty field, or one that does not apply to the floating-leg type, is sent as
 *    null (the reset schedule of an overnight leg as []), never as a default;
 *  - every select starts blank, so nothing is chosen for the user.
 *
 * The option lists equal the labels the normalizer supports
 * (services/irs_inputs/normalizer.py); tests/unit/test_irs/test_irs_frontend_contract.py
 * keeps them, the field map and the page markup in sync.
 */

const IRS_OPTIONS = {
  currencies:           ['USD', 'CHF', 'JPY', 'INR'],
  directions:           ['Pay', 'Receive'],
  paymentFrequencies:   ['Annual', 'Semiannual', 'Quarterly', 'Monthly'],
  dayCounts:            ['ACT/360', 'ACT/365', '30/360'],
  businessDayConventions: ['Modified Following', 'Following', 'Preceding', 'Unadjusted'],
  calendars:            ['FD', 'JN', 'RB', 'SZ'],
  benchmarks:           ['INR OIS', 'SF0006M (SARON fallback)', 'SOFR', 'TONAR'],
  indexTenors:          ['1D', '6M'],
  resetFrequencies:     ['Daily', 'Semiannual'],
  rateTimings:          ['In Arrears', 'In Advance'],
  lookbackTypes:        ['Lookback'],
  compounding:          ['Daily Compounded'],
  spreadTreatments:     ['Exclude Spread'],
  fixingCalendars:      ['EN', 'RB', 'SZ'],
  termCompounding:      ['None', 'Flat'],
  observationMethods:   ['Method A: contractual accrual (PROVISIONAL R9)',
                         'Method B: reset-date fallback'],
  principalExchanges:   ['Never'],
  amortisationTypes:    ['Custom Schedule', 'Bullet / No Amortisation'],
  curves:               ['USD SOFR', 'CHF SARON', 'JPY TONAR', 'INR OIS'],
  interpolations:       ['Piecewise Linear (Cont)'],
};

// page field (element id "irs-<field>") -> [contract section, contract key]
const IRS_FIELD_MAP = {
  trade_id: ['trade', 'trade_id'], currency: ['trade', 'currency'], notional: ['trade', 'notional'],
  effective_date: ['trade', 'effective_date'], maturity_date: ['trade', 'maturity_date'],
  valuation_date: ['trade', 'valuation_date'],

  fixed_direction: ['fixed_leg', 'direction'], fixed_rate_percent: ['fixed_leg', 'rate_percent'],
  fixed_payment_frequency: ['fixed_leg', 'payment_frequency'], fixed_day_count: ['fixed_leg', 'day_count'],
  fixed_bdc: ['fixed_leg', 'business_day_convention'], fixed_calendar: ['fixed_leg', 'calendar'],

  float_direction: ['floating_leg', 'direction'], benchmark: ['floating_leg', 'benchmark'],
  index_tenor: ['floating_leg', 'index_tenor'], spread_bp: ['floating_leg', 'spread_bp'],
  leverage: ['floating_leg', 'leverage'], reset_frequency: ['floating_leg', 'reset_frequency'],
  float_payment_frequency: ['floating_leg', 'payment_frequency'], float_day_count: ['floating_leg', 'day_count'],
  float_bdc: ['floating_leg', 'business_day_convention'], float_calendar: ['floating_leg', 'calendar'],
  rate_timing: ['floating_leg', 'rate_timing'], lookback_days: ['floating_leg', 'lookback_days'],
  lookback_type: ['floating_leg', 'lookback_type'], rate_cutoff_days: ['floating_leg', 'rate_cutoff_days'],
  compounding: ['floating_leg', 'compounding'], spread_treatment: ['floating_leg', 'spread_treatment'],
  fixing_calendar: ['floating_leg', 'fixing_calendar'], fixing_lag_days: ['floating_leg', 'fixing_lag_days'],
  term_compounding: ['floating_leg', 'term_compounding'], observation_method: ['floating_leg', 'observation_method'],

  principal_exchange: ['notional', 'principal_exchange'], amortisation_type: ['notional', 'amortisation_type'],

  curve: ['market_data', 'curve'], snapshot_folder: ['market_data', 'snapshot_folder'],
  curve_source_file: ['market_data', 'curve_source_file'],
  fixings_source_file: ['market_data', 'fixings_source_file'],
  reference_date: ['market_data', 'reference_date'], interpolation: ['market_data', 'interpolation'],
};

const IRS_NUMBER_FIELDS = new Set(['notional', 'fixed_rate_percent', 'spread_bp', 'leverage',
  'lookback_days', 'rate_cutoff_days', 'fixing_lag_days']);

// Editable tables: column order on the page -> contract row keys.
const IRS_SCHEDULE_COLUMNS = [
  {id: 'period', type: 'number'},
  {id: 'accrual_start', type: 'date'},
  {id: 'accrual_end', type: 'date'},
  {id: 'payment_date', type: 'date'},
  {id: 'amortisation_percent', type: 'number'},
  {id: 'amortisation_amount', type: 'number'},
  {id: 'notional', type: 'number'},          // "Balance": the period's notional
  {id: 'action', type: 'text'},
];
const IRS_RESET_COLUMNS = [
  {id: 'payment_period', type: 'number'},
  {id: 'reset_date', type: 'date'},
  {id: 'rate_start', type: 'date'},
  {id: 'rate_end', type: 'date'},
];
const IRS_TABLES = {
  schedule: {tbody: 'irs-amort-rows1', columns: IRS_SCHEDULE_COLUMNS},
  resets:   {tbody: 'irs-amort-rows2', columns: IRS_RESET_COLUMNS},
};

// ── small helpers (display formatting only) ──
const _irsEl = (id) => document.getElementById(id);
const _irsField = (f) => _irsEl('irs-' + f);
const _irsNum = (v, d) => (v === null || v === undefined) ? '—'
  : Number(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
const _irsPct = (v, d = 5) => (v === null || v === undefined) ? '—' : (Number(v) * 100).toFixed(d) + '%';
const _irsCls = (v) => (v === null || v === undefined) ? '' : (v < 0 ? 'irs-negative' : 'irs-positive');
const _irsEsc = (s) => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

function _irsValue(raw, isNumber) {
  const t = String(raw ?? '').trim();
  if (t === '') return null;
  if (isNumber) {
    const n = Number(t);
    return Number.isFinite(n) ? n : t;   // an invalid number is sent as typed; the backend rejects it
  }
  return t;
}

// Sets an input or select. A value that is not one of a select's options is added
// (marked "not in list") so it is shown and sent, not silently dropped.
function _irsSet(el, value) {
  if (!el) return;
  const v = (value === null || value === undefined) ? '' : String(value);
  if (el.tagName === 'SELECT' && ![...el.options].some(o => o.value === v)) {
    const opt = document.createElement('option');
    opt.value = v; opt.textContent = v + ' (not in list)';
    el.appendChild(opt);
  }
  el.value = v;
}

function _irsSetOptions(el, values, blankLabel = '') {
  if (!el) return;
  const prev = el.value;
  el.innerHTML = '';
  ['', ...values].forEach(v => {
    const opt = document.createElement('option');
    opt.value = v; opt.textContent = v === '' ? blankLabel : v;
    el.appendChild(opt);
  });
  if (prev) _irsSet(el, prev);
}

let _irsWorkbookFile = null;
let _irsBound = false;

// Reads a JSON response; a non-JSON reply (e.g. a server error page) becomes a clear error.
async function _irsJson(r) {
  const text = await r.text();
  let data = null;
  try { data = JSON.parse(text); } catch {
    throw new Error(`server error ${r.status} ${r.statusText}`.trim() + ' (see the API server log)');
  }
  if (!r.ok) throw new Error(data?.detail?.message || `${r.status} ${r.statusText}`);
  return data;
}


const irs = {

  // Own workspace page (core: openModulePage); no generic grouped fields.
  workspacePage: 'page-irs',
  breadcrumbAsset: 'Interest Rate Derivatives',
  fieldGroups: null,
  flatFields: null,

  apiType: 'irs',
  apiEndpoint: '/pricing/irs',          // core: priceViaModuleEndpoint
  mapPayload: null,
  bulkUpload: false,
  hideModelEngine: true,
  onFieldChange: null,

  // ── page lifecycle ──────────────────────────────────────────────
  onOpen() {
    if (!_irsBound) { irs._bind(); _irsBound = true; }
    irs._applyLegType();
    irs._updatePaymentSpan();
    irs.refreshMarket();
  },

  _root() { return _irsEl('page-irs'); },

  _showTopTab(id) {
    const root = irs._root();
    root.querySelectorAll('.irs-top-tab').forEach(t => t.classList.toggle('irs-active', t.dataset.topTab === id));
    root.querySelectorAll('.irs-top-pane').forEach(p => p.classList.toggle('irs-active', p.id === id));
  },

  _setResults(show) {
    const results = _irsEl('irs-pricing-results');
    const mpPane = _irsEl('irs-market-pricing');
    if (results) results.style.display = show ? '' : 'none';
    if (mpPane) mpPane.classList.toggle('irs-has-results', show);
  },

  _bind() {
    const root = irs._root();
    // select options: exactly the engine's labels, blank first
    root.querySelectorAll('select[data-opts]').forEach(s => _irsSetOptions(s, IRS_OPTIONS[s.dataset.opts] || []));

    root.querySelectorAll('.irs-top-tab').forEach(tab =>
      tab.addEventListener('click', () => irs._showTopTab(tab.dataset.topTab)));
    root.querySelectorAll('.irs-sub-tab').forEach(tab => tab.addEventListener('click', () => {
      root.querySelectorAll('.irs-sub-tab').forEach(t => t.classList.toggle('irs-active', t === tab));
      root.querySelectorAll('.irs-sub-pane').forEach(p => p.classList.toggle('irs-active', p.id === tab.dataset.subTab));
    }));

    // Price IRS / Reset (Reset hides the results, as in the original design)
    root.querySelectorAll('.irs-btn-primary').forEach(btn =>
      btn.addEventListener('click', () => priceViaModuleEndpoint(irs, btn)));
    root.querySelectorAll('.irs-btn-secondary').forEach(btn =>
      btn.addEventListener('click', () => irs._setResults(false)));

    // fit the page to the window height (original behaviour)
    const fit = () => {
      if (!root.classList.contains('active')) return;
      const top = root.getBoundingClientRect().top + window.pageYOffset;
      root.style.height = Math.max(420, window.innerHeight - top) + 'px';
    };
    window.addEventListener('resize', fit);
    new MutationObserver(fit).observe(root, { attributes: true, attributeFilter: ['class'] });
    fit();

    // dependent fields
    _irsField('fixed_direction').addEventListener('change', () => {
      const v = _irsField('fixed_direction').value;
      if (v === 'Pay') _irsSet(_irsField('float_direction'), 'Receive');
      else if (v === 'Receive') _irsSet(_irsField('float_direction'), 'Pay');
    });
    ['index_tenor', 'benchmark'].forEach(f => _irsField(f).addEventListener('change', () => irs._applyLegType()));
    ['valuation_date', 'currency'].forEach(f => _irsField(f).addEventListener('change', () => irs.refreshMarket()));
    _irsEl('irs-market-refresh').addEventListener('click', () => irs.refreshMarket());

    // schedule tables
    root.querySelectorAll('.irs-add-row').forEach(b =>
      b.addEventListener('click', () => irs._addRow(b.dataset.table, null)));

    // workbook import
    _irsEl('irs-wb-file').addEventListener('change', () => irs.readWorkbook());
    _irsEl('irs-wb-sheet').addEventListener('change', () => irs.loadSheet(_irsEl('irs-wb-sheet').value));
  },

  /** Overnight (1D) vs term-rate (6M) floating-leg fields; observation method for SF0006M. */
  _applyLegType() {
    const tenor = _irsField('index_tenor').value;
    const sf = tenor === '6M' && _irsField('benchmark').value.startsWith('SF0006M');
    irs._root().querySelectorAll('[data-leg]').forEach(el => {
      const leg = el.dataset.leg;
      el.hidden = !((leg === '1D' && tenor === '1D') || (leg === '6M' && tenor === '6M') || (leg === 'SF' && sf));
    });
  },

  _isApplicable(el) {
    for (let n = el; n && n.id !== 'page-irs'; n = n.parentElement) if (n.hidden) return false;
    return true;
  },

  // ── editable tables ─────────────────────────────────────────────
  _addRow(table, row) {
    const def = IRS_TABLES[table];
    const tbody = _irsEl(def.tbody);
    const tr = document.createElement('tr');
    def.columns.forEach(c => {
      const td = document.createElement('td');
      const inp = document.createElement('input');
      inp.type = c.type === 'number' ? 'number' : (c.type === 'date' ? 'date' : 'text');
      if (c.type === 'number') inp.step = 'any';
      inp.dataset.col = c.id;
      const v = row ? row[c.id] : null;
      if (v !== null && v !== undefined) inp.value = v;
      if (table === 'schedule' && c.id === 'payment_date') inp.addEventListener('change', () => irs._updatePaymentSpan());
      td.appendChild(inp);
      tr.appendChild(td);
    });
    const td = document.createElement('td');
    const del = document.createElement('button');
    del.type = 'button'; del.className = 'irs-del-row'; del.title = 'Remove row'; del.textContent = '×';
    del.addEventListener('click', () => { tr.remove(); irs._updatePaymentSpan(); });
    td.appendChild(del);
    tr.appendChild(td);
    tbody.appendChild(tr);
  },

  _setRows(table, rows) {
    _irsEl(IRS_TABLES[table].tbody).innerHTML = '';
    (rows || []).forEach(r => irs._addRow(table, r));
    irs._updatePaymentSpan();
  },

  _rows(table) {
    const def = IRS_TABLES[table];
    const rows = [];
    _irsEl(def.tbody).querySelectorAll('tr').forEach(tr => {
      const row = {}; let any = false;
      def.columns.forEach(c => {
        const raw = tr.querySelector(`input[data-col="${c.id}"]`)?.value ?? '';
        if (String(raw).trim() !== '') any = true;
        row[c.id] = _irsValue(raw, c.type === 'number');
      });
      if (any) rows.push(row);
    });
    return rows;
  },

  // First / Last Payment: shown from the schedule rows (display only, not inputs)
  _updatePaymentSpan() {
    const dates = irs._rows('schedule').map(r => r.payment_date).filter(Boolean).sort();
    _irsSet(_irsEl('irs-first-payment'), dates[0] || '');
    _irsSet(_irsEl('irs-last-payment'), dates[dates.length - 1] || '');
  },

  // ── request / form ──────────────────────────────────────────────
  /** Page inputs -> TradeInputs (services/irs_inputs/contract.py). */
  buildRequest() {
    const inputs = {trade: {}, fixed_leg: {}, floating_leg: {}, notional: {}, resets: {}, market_data: {}};
    Object.entries(IRS_FIELD_MAP).forEach(([field, [section, key]]) => {
      const el = _irsField(field);
      inputs[section][key] = (el && irs._isApplicable(el)) ? _irsValue(el.value, IRS_NUMBER_FIELDS.has(field)) : null;
    });
    inputs.notional.schedule = irs._rows('schedule');
    inputs.resets.schedule = irs._isApplicable(_irsEl('irs-resets-table')) ? irs._rows('resets') : [];
    return inputs;
  },

  /** TradeInputs (e.g. from an input workbook sheet) -> page. */
  fillForm(inputs) {
    Object.entries(IRS_FIELD_MAP).forEach(([field, [section, key]]) =>
      _irsSet(_irsField(field), inputs?.[section]?.[key]));
    irs._setRows('schedule', inputs?.notional?.schedule || []);
    irs._setRows('resets', inputs?.resets?.schedule || []);
    irs._applyLegType();
  },

  // ── market data (read-only display of what the engine uses) ─────
  async refreshMarket() {
    const day = (_irsField('valuation_date').value || '').trim();
    const ccy = (_irsField('currency').value || '').trim();
    const rows = _irsEl('irs-curve-rows');
    const legs = ['irs-mkt-discount-a', 'irs-mkt-discount-b', 'irs-mkt-forward'];
    const empty = (msg) => {
      rows.innerHTML = `<tr><td colspan="4" class="irs-empty">${_irsEsc(msg)}</td></tr>`;
      legs.forEach(id => _irsSet(_irsEl(id), ''));
      _irsSet(_irsEl('irs-data-source'), '');
    };
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || !ccy) {
      _irsSetOptions(_irsField('curve_source_file'), []);
      _irsSetOptions(_irsField('fixings_source_file'), []);
      empty('Set Currency and Valuation Date to show the curve the engine uses.');
      return;
    }
    const q = `valuation_date=${encodeURIComponent(day)}&currency=${encodeURIComponent(ccy)}`;
    try {
      const files = await apiGet('/pricing/irs/market-files?' + q);
      _irsSetOptions(_irsField('curve_source_file'), files.curves.map(c => c.curve_source_file));
      _irsSetOptions(_irsField('fixings_source_file'), files.fixings_files, '(none)');
    } catch (e) { /* the curve request below reports the problem */ }
    try {
      const res = await apiGet('/pricing/irs/curve?' + q);
      const byRole = {};
      res.curves.forEach(c => c.roles.forEach(r => { byRole[r] = c; }));
      const label = (c) => c ? `${c.curve_id} · ${res.file}` : '';
      _irsSet(_irsEl('irs-mkt-discount-a'), label(byRole.discount));
      _irsSet(_irsEl('irs-mkt-discount-b'), label(byRole.discount));
      _irsSet(_irsEl('irs-mkt-forward'), label(byRole.forecast));
      _irsSet(_irsEl('irs-data-source'), res.provenance || '');
      _irsEl('irs-data-source').title = res.provenance || '';
      const curve = byRole.forecast || res.curves[0];
      const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
      const fmtDate = (iso) => { const [y, m, d] = iso.split('-'); return `${d}-${MONTHS[+m - 1]}-${y}`; };
      rows.innerHTML = curve.pillars.map(p => `<tr><td>${fmtDate(p.date)}</td><td>${_irsEsc(p.tenor)}</td>` +
        `<td class="irs-number">${_irsPct(p.zero_rate, 5)}</td><td class="irs-number">${_irsNum(p.discount_factor, 6)}</td></tr>`).join('');
      const cv = curve.conventions || {};
      _irsEl('irs-curve-note').textContent =
        `The engine's prepared curve ${curve.curve_id} (${res.file}), shown read-only: it is not an input. ` +
        `Zero rates ${cv.compounding || ''} ${cv.day_count || ''}, ${cv.interpolation || ''} interpolation; ` +
        `pillar dates and discount factors from the engine's curve builder (spot ${res.curves[0].spot_date}).`;
    } catch (e) {
      empty(e.message.includes('404') ? `No prepared ${ccy} curve for ${day} in market_data/.` : 'Could not load the curve: ' + e.message);
    }
  },

  // ── workbook import ─────────────────────────────────────────────
  async readWorkbook() {
    const status = _irsEl('irs-wb-status');
    _irsWorkbookFile = _irsEl('irs-wb-file')?.files?.[0] || null;
    _irsSetOptions(_irsEl('irs-wb-sheet'), [], 'Sheet');
    if (!_irsWorkbookFile) return;
    const form = new FormData();
    form.append('file', _irsWorkbookFile);
    try {
      const r = await fetch(API + '/pricing/irs/workbook', {method: 'POST', body: form});
      const data = await _irsJson(r);
      _irsSetOptions(_irsEl('irs-wb-sheet'), data.sheets, 'Sheet');
      status.textContent = `${data.sheets.length} sheet(s): choose one`;
    } catch (e) {
      status.textContent = 'Could not read the workbook: ' + e.message;
    }
  },

  async loadSheet(sheet) {
    const status = _irsEl('irs-wb-status');
    if (!sheet || !_irsWorkbookFile) return;
    const form = new FormData();
    form.append('file', _irsWorkbookFile);
    form.append('sheet', sheet);
    try {
      const r = await fetch(API + '/pricing/irs/workbook', {method: 'POST', body: form});
      const data = await _irsJson(r);
      _irsSet(_irsField('valuation_date'), data.trade_inputs?.trade?.valuation_date);
      _irsSet(_irsField('currency'), data.trade_inputs?.trade?.currency);
      await irs.refreshMarket();            // so the stated file names are in the lists
      irs.fillForm(data.trade_inputs);
      irs._setResults(false);
      status.textContent = `Loaded ${sheet}. Review, then Price IRS.`;
    } catch (e) {
      status.textContent = `Could not load ${sheet}: ` + e.message;
    }
  },

  // ── results ─────────────────────────────────────────────────────
  /** Renders the engine's response in the Pricing Results panel. */
  onPriceResult(res, request) {
    irs._lastRequest = request;
    const ccy = _irsEsc(res.currency);
    const fixedSide = res.fixed_leg_side === 'pay' ? 'Pay' : 'Receive';
    const floatSide = res.fixed_leg_side === 'pay' ? 'Receive' : 'Pay';
    const card = (label, value, sub, primary) => `
      <div class="irs-result-card${primary ? ' irs-primary' : ''}">
        <div class="irs-result-label">${label}</div>
        <div class="irs-result-value ${_irsCls(value)}" data-value="${value}">${_irsNum(value, 2)}</div>
        <div class="irs-result-sub">${sub}</div>
      </div>`;
    const cards = (cls) => `<div class="irs-result-grid irs-three ${cls}">
        ${card('Fixed Leg PV', res.fixed_leg_npv, `${fixedSide} · ${ccy}`)}
        ${card('Floating Leg PV', res.floating_leg_npv, `${floatSide} · ${_irsEsc(res.floating_benchmark)}`)}
        ${card('Net NPV', res.npv, ccy, true)}
      </div>`;

    // Cashflows: one row per payment date (net rows), with each leg's rate and amount
    const byDate = (rows) => Object.fromEntries(rows.map(r => [r.payment_date, r]));
    const fx = byDate(res.fixed_leg), fl = byDate(res.floating_leg);
    const cfRows = res.net.map(n => {
      const f = fx[n.payment_date] || {}, g = fl[n.payment_date] || {};
      const settled = n.status === 'Settled';
      const dash = '—';
      return `<tr class="${settled ? 'irs-settled' : ''}">
        <td>${f.period ?? g.period ?? ''}</td><td>${f.accrual_start ?? g.accrual_start ?? ''}</td>
        <td>${f.accrual_end ?? g.accrual_end ?? ''}</td><td>${n.payment_date}${settled ? ' (settled)' : ''}</td>
        <td class="irs-number">${_irsNum(n.notional, 2)}</td>
        <td class="irs-number">${settled || f.rate === undefined ? dash : _irsPct(f.rate)}</td>
        <td class="irs-number ${_irsCls(n.fixed)}">${settled ? dash : _irsNum(n.fixed, 2)}</td>
        <td class="irs-number">${settled || g.rate === undefined ? dash : _irsPct(g.rate)}</td>
        <td class="irs-number ${_irsCls(n.floating)}">${settled ? dash : _irsNum(n.floating, 2)}</td>
        <td class="irs-number ${_irsCls(n.net)}">${settled ? dash : _irsNum(n.net, 2)}</td>
        <td class="irs-number">${settled ? dash : _irsNum(n.df, 7)}</td>
        <td class="irs-number ${_irsCls(n.net_pv)}">${settled ? dash : _irsNum(n.net_pv, 2)}</td></tr>`;
    }).join('');
    const cfTable = `<div class="irs-table-container"><table>
      <thead><tr><th>Period</th><th>Start</th><th>End</th><th>Payment Date</th><th class="irs-number">Notional</th>
      <th class="irs-number">Fixed Rate</th><th class="irs-number">Fixed CF</th><th class="irs-number">Float Rate</th>
      <th class="irs-number">Float CF</th><th class="irs-number">Net CF</th><th class="irs-number">Discount Factor</th>
      <th class="irs-number">PV</th></tr></thead><tbody>${cfRows}
      <tr class="irs-total"><td colspan="11">Net NPV</td><td class="irs-number ${_irsCls(res.npv)}">${_irsNum(res.npv, 2)}</td></tr>
      </tbody></table></div>`;

    const legTable = (rows, floating, npv) => {
      const body = rows.map(r => {
        const s = r.status === 'Settled', d = '—';
        return `<tr class="${s ? 'irs-settled' : ''}"><td>${r.period}</td><td>${r.status}</td>
          <td>${r.accrual_start}</td><td>${r.accrual_end}</td><td>${r.payment_date}</td>
          <td class="irs-number">${_irsNum(r.notional, 2)}</td><td class="irs-number">${_irsNum(r.amortisation, 2)}</td>
          <td class="irs-number">${s ? d : _irsNum(r.dcf, 6)}</td><td class="irs-number">${s ? d : _irsPct(r.rate, 6)}</td>
          ${floating ? `<td class="irs-number">${s || r.spread === null ? d : _irsNum(r.spread * 10000, 2)}</td>` : ''}
          <td class="irs-number ${_irsCls(r.amount)}">${s ? d : _irsNum(r.amount, 2)}</td>
          <td class="irs-number">${s ? d : _irsNum(r.df, 7)}</td>
          <td class="irs-number ${_irsCls(r.pv)}">${s ? d : _irsNum(r.pv, 2)}</td></tr>`;
      }).join('');
      const cols = floating ? 13 : 12;
      return `<div class="irs-table-container"><table><thead><tr><th>Period</th><th>Status</th>
        <th>Accrual Start</th><th>Accrual End</th><th>Payment Date</th><th class="irs-number">Notional</th>
        <th class="irs-number">Amortisation</th><th class="irs-number">Year Fraction</th>
        <th class="irs-number">${floating ? 'Rate incl. Spread' : 'Fixed Rate'}</th>
        ${floating ? '<th class="irs-number">Spread (bp)</th>' : ''}
        <th class="irs-number">Amount</th><th class="irs-number">Discount Factor</th><th class="irs-number">PV</th></tr></thead>
        <tbody>${body}<tr class="irs-total"><td colspan="${cols - 1}">Leg PV</td>
        <td class="irs-number ${_irsCls(npv)}">${_irsNum(npv, 2)}</td></tr></tbody></table></div>`;
    };

    const notes = (res.notes || []).map(n => `<div class="irs-note">${_irsEsc(n)}</div>`).join('');
    _irsEl('irs-results-title').textContent = `Pricing Results — ${res.trade_id} · ${res.currency} · valuation ${res.valuation_date}`;
    _irsEl('irs-results-body').innerHTML = `
      <div class="irs-section-body">
        <div class="irs-download-row">
          <span class="irs-download-status" id="irs-download-status"></span>
          <button type="button" class="irs-download-btn" id="irs-download-btn">Download Excel</button>
        </div>
        ${cards('irs-headline')}
      </div>
      <div class="irs-tabs">
        <div class="irs-tab irs-active" data-tab="irs-cashflows">Cashflows</div>
        <div class="irs-tab" data-tab="irs-fixed-leg">Fixed Leg</div>
        <div class="irs-tab" data-tab="irs-floating-leg">Floating Leg</div>
        <div class="irs-tab" data-tab="irs-notes">Notes${(res.notes || []).length ? ` (${res.notes.length})` : ''}</div>
      </div>
      <div class="irs-tab-content irs-tab-pane irs-active" id="irs-cashflows">
        <div class="irs-subheading">Projected Cashflows — ${_irsEsc(res.trade_id)} (Optima IRS engine)</div>
        ${cfTable}
        <div class="irs-subheading" style="margin-top:18px;">Leg Valuation</div>
        ${cards('irs-leg-valuation')}
      </div>
      <div class="irs-tab-content irs-tab-pane" id="irs-fixed-leg">
        <div class="irs-subheading">Fixed Leg — ${fixedSide}</div>${legTable(res.fixed_leg, false, res.fixed_leg_npv)}
      </div>
      <div class="irs-tab-content irs-tab-pane" id="irs-floating-leg">
        <div class="irs-subheading">Floating Leg — ${floatSide} · ${_irsEsc(res.floating_benchmark)}</div>${legTable(res.floating_leg, true, res.floating_leg_npv)}
      </div>
      <div class="irs-tab-content irs-tab-pane" id="irs-notes">
        <dl class="irs-facts">
          <dt>Market Data</dt><dd>${(res.market_files || []).map(_irsEsc).join(', ')}</dd>
          ${(res.fixing_reasons || []).length ? `<dt>Fixings Used For</dt><dd>${res.fixing_reasons.map(_irsEsc).join('; ')}</dd>` : ''}
          <dt>Settled Periods</dt><dd>${res.settled_periods} (paid on or before the valuation date; excluded from the NPV)</dd>
          <dt>Pricing</dt><dd>${_irsEsc(res.engine)} engine, ${_irsEsc(res.model)} model</dd>
          <dt>Sign Convention</dt><dd>${_irsEsc(res.sign_convention)}</dd>
        </dl>
        ${notes}
      </div>`;
    irs._bindResultTabs();
    _irsEl('irs-download-btn').addEventListener('click', () => irs.downloadReport());
    irs.downloadReport();            // automatic download after each successful price
    irs._setResults(true);
    irs._showTopTab('irs-market-pricing');
  },

  /**
   * Downloads the results workbook for the last priced request: the engine prices it again
   * and services.irs_outputs.excel_report.write_pricing_report writes it, exactly as
   * `price_irs_workbook --output` does (POST /api/v1/pricing/irs/report).
   */
  async downloadReport() {
    const status = _irsEl('irs-download-status');
    const btn = _irsEl('irs-download-btn');
    if (!irs._lastRequest) return;
    if (btn) btn.disabled = true;
    if (status) status.textContent = 'Preparing Excel…';
    try {
      const r = await fetch(API + '/pricing/irs/report', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(irs._lastRequest),
      });
      if (!r.ok) await _irsJson(r);                 // throws with the server's message
      const blob = await r.blob();
      const m = /filename="([^"]+)"/.exec(r.headers.get('Content-Disposition') || '');
      const name = m ? m[1] : 'IRS_results.xlsx';
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = name;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      if (status) status.textContent = `Excel downloaded: ${name}`;
    } catch (e) {
      if (status) status.textContent = 'Excel download failed: ' + e.message;
    } finally {
      if (btn) btn.disabled = false;
    }
  },

  /** Validation, market-data and pricing errors from the endpoint, listed in full. */
  onPriceError(err) {
    irs._lastRequest = null;
    const d = err.detail;
    let title = 'Pricing failed';
    let body = `<div class="irs-note irs-warning">${_irsEsc(err.message)}</div>`;
    if (d && typeof d === 'object' && !Array.isArray(d)) {
      title = {input_validation: 'Input problems — the trade was not priced',
               market_data: 'Market data problem — the trade was not priced',
               pricing: 'Pricing error'}[d.error] || title;
      body = `<div class="irs-note irs-warning">${_irsEsc(d.message)}</div>` +
        ((d.issues || []).length ? `<ul class="irs-issues">${d.issues.map(i => {
          const k = i.indexOf(':');
          return k > 0 ? `<li><code>${_irsEsc(i.slice(0, k))}</code>${_irsEsc(i.slice(k))}</li>` : `<li>${_irsEsc(i)}</li>`;
        }).join('')}</ul>` : '');
    } else if (Array.isArray(d)) {
      body = `<ul class="irs-issues">${d.map(i => `<li>${_irsEsc(i.msg || JSON.stringify(i))}</li>`).join('')}</ul>`;
    } else if (!err.status) {
      title = 'The pricing service could not be reached';
    }
    _irsEl('irs-results-title').textContent = title;
    _irsEl('irs-results-body').innerHTML = `<div class="irs-section-body" id="irs-pricing-error">${body}</div>`;
    irs._setResults(true);
    irs._showTopTab('irs-market-pricing');
  },

  _bindResultTabs() {
    const panel = _irsEl('irs-pricing-results');
    panel.querySelectorAll('.irs-tab').forEach(tab => tab.addEventListener('click', () => {
      panel.querySelectorAll('.irs-tab').forEach(t => t.classList.toggle('irs-active', t === tab));
      panel.querySelectorAll('.irs-tab-pane').forEach(p => p.classList.toggle('irs-active', p.id === tab.dataset.tab));
    }));
  },
};

INSTRUMENT_REGISTRY['irs'] = irs;
