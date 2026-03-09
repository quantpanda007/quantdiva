/**
 * ╔══════════════════════════════════════════════════════════════════╗
 * ║                   OPTIMA — APPLICATION LOGIC                     ║
 * ║                                                                  ║
 * ║  All UI behavior, API calls, chart rendering, and panel logic.  ║
 * ║  Depends on: optima_schema.js (loaded first), Plotly CDN        ║
 * ║                                                                  ║
 * ║  Version: 0.4.0                                                  ║
 * ╚══════════════════════════════════════════════════════════════════╝
 */

const API = '/api/v1';
const $ = id => document.getElementById(id);
let currentInst = null;

// ═══════════════════════════════════════════════════════════════════
// PLOTLY DEFAULTS — dark terminal aesthetic
// ═══════════════════════════════════════════════════════════════════

const PLOT_LAYOUT = {
  paper_bgcolor: 'rgba(0,0,0,0)',
  plot_bgcolor: 'rgba(10,15,26,0.5)',
  font: { color: '#94a3b8', size: 11, family: 'Inter, system-ui' },
  margin: { t: 30, r: 20, b: 40, l: 55 },
  xaxis: { gridcolor: '#1e2d4a', zerolinecolor: '#2e4a7a' },
  yaxis: { gridcolor: '#1e2d4a', zerolinecolor: '#2e4a7a' },
};
const PLOT_CONFIG = { displayModeBar: false, responsive: true };

function plotLine(divId, x, y, title, xLabel, yLabel, extra) {
  const traces = [{ x, y, type: 'scatter', mode: 'lines+markers',
    line: { color: '#f59e0b', width: 2 }, marker: { size: 4 }, ...extra }];
  const layout = { ...PLOT_LAYOUT, title: { text: title, font: { size: 13 } },
    xaxis: { ...PLOT_LAYOUT.xaxis, title: xLabel },
    yaxis: { ...PLOT_LAYOUT.yaxis, title: yLabel },
    height: 260 };
  Plotly.newPlot(divId, traces, layout, PLOT_CONFIG);
}

function plotBar(divId, x, y, title, xLabel, yLabel) {
  const colors = y.map(v => v >= 0 ? '#10b981' : '#ef4444');
  const traces = [{ x, y, type: 'bar', marker: { color: colors } }];
  const layout = { ...PLOT_LAYOUT, title: { text: title, font: { size: 13 } },
    xaxis: { ...PLOT_LAYOUT.xaxis, title: xLabel },
    yaxis: { ...PLOT_LAYOUT.yaxis, title: yLabel },
    height: 260 };
  Plotly.newPlot(divId, traces, layout, PLOT_CONFIG);
}

function plotHeatmap(divId, z, x, y, title) {
  const traces = [{ z, x, y, type: 'heatmap',
    colorscale: [[0,'#ef4444'],[0.5,'#f59e0b'],[1,'#10b981']],
    hovertemplate: 'Spot: %{x}<br>Vol: %{y}<br>NPV: $%{z:.2f}<extra></extra>' }];
  const layout = { ...PLOT_LAYOUT, title: { text: title, font: { size: 13 } },
    xaxis: { ...PLOT_LAYOUT.xaxis, title: 'Spot' },
    yaxis: { ...PLOT_LAYOUT.yaxis, title: 'Volatility' },
    height: 320 };
  Plotly.newPlot(divId, traces, layout, PLOT_CONFIG);
}


// ═══════════════════════════════════════════════════════════════════
// NAVIGATION
// ═══════════════════════════════════════════════════════════════════

function goHome() {
  $('page-home').classList.add('active');
  $('page-workspace').classList.remove('active');
  $('breadcrumb').style.display = 'none';
  $('btn-go-home').style.display = 'none';
  currentInst = null;
}

function openWorkspace(instType) {
  currentInst = instType;
  const schema = SCHEMA[instType];
  if (!schema) return;

  $('page-home').classList.remove('active');
  $('page-workspace').classList.add('active');
  $('breadcrumb').style.display = 'flex';
  $('btn-go-home').style.display = '';
  $('bc-asset').textContent = schema.asset;
  $('bc-inst').textContent = schema.label;
  $('ws-trade-title').textContent = schema.label + ' — Trade Inputs';

  // Reset displays
  $('npv-value').textContent = '—';
  $('npv-meta').textContent = 'Configure and click Price';
  $('compare-card').style.display = 'none';
  $('diagnostics').textContent = 'Run a pricing to see diagnostics.';

  // Build all panels
  buildTradeFields(instType);
  buildMarketData(instType, schema);
  buildModelEngine(schema);
  renderEngineParams(schema);
  buildGreeks(schema);
  buildOutputPanels(schema);
  buildAnalysis(schema);
}


// ═══════════════════════════════════════════════════════════════════
// BUILD: Trade Input Fields
// ═══════════════════════════════════════════════════════════════════

function buildTradeFields(instType) {
  const container = $('ws-trade-fields');
  container.innerHTML = '';
  (FIELDS[instType] || []).forEach(f => {
    const div = document.createElement('div');
    let html = `<label>${f.label}</label>`;
    if (f.type === 'select') {
      html += `<select id="f-${f.id}">${(f.opts||[]).map(o =>
        `<option value="${o}"${o===f.val?' selected':''}>${o}</option>`).join('')}</select>`;
    } else if (f.type === 'date') {
      html += `<input type="text" id="f-${f.id}" value="${f.val||''}" placeholder="YYYY-MM-DD"/>`;
    } else {
      html += `<input type="${f.type}" id="f-${f.id}" value="${f.val??''}" placeholder="${f.ph||''}"/>`;
    }
    div.innerHTML = html;
    container.appendChild(div);
  });
}


// ═══════════════════════════════════════════════════════════════════
// BUILD: Market Data
// ═══════════════════════════════════════════════════════════════════

function buildMarketData(instType, schema) {
  const container = $('ws-md-fields');
  container.innerHTML = '';
  // Always add pricing date
  addMdField(container, MD_FIELDS.pricing_date, new Date().toISOString().slice(0,10));
  // Schema-driven fields
  (schema.market_data || []).forEach(key => {
    const def = MD_FIELDS[key];
    if (def) addMdField(container, def);
  });
}

function addMdField(container, def, defaultVal) {
  const div = document.createElement('div');
  const val = defaultVal || '';
  if (def.type === 'date') {
    div.innerHTML = `<label>${def.label}</label><input type="text" id="f-md-${def.id}" value="${val}" placeholder="YYYY-MM-DD"/>`;
  } else {
    div.innerHTML = `<label>${def.label}</label><input type="number" id="f-md-${def.id}" value="${val}" step="any" placeholder="${def.ph||''}"/>`;
  }
  container.appendChild(div);
}


// ═══════════════════════════════════════════════════════════════════
// BUILD: Model & Engine
// ═══════════════════════════════════════════════════════════════════

function buildModelEngine(schema) {
  const ms = $('f-model'), es = $('f-engine');
  ms.innerHTML = (schema.models||[]).map(m =>
    `<option value="${m.v}">${m.l}</option>`).join('');
  es.innerHTML = (schema.engines||[]).map(e =>
    `<option value="${e.v}">${e.l}</option>`).join('');
  es.onchange = () => renderEngineParams(schema);
}

function renderEngineParams(schema) {
  const container = $('ws-engine-params');
  container.innerHTML = '';
  const engine = (schema.engines||[]).find(e => e.v === $('f-engine').value);
  if (!engine?.params?.length) return;
  const grid = document.createElement('div');
  grid.className = 'grid g3';
  grid.style.marginTop = '8px';
  engine.params.forEach(key => {
    const def = ENGINE_PARAM_DEFS[key];
    if (!def) return;
    const d = document.createElement('div');
    d.innerHTML = `<label>${def.label}</label><input type="number" id="f-${def.id}" value="${def.val}" step="any"/>`;
    grid.appendChild(d);
  });
  container.appendChild(grid);
}


// ═══════════════════════════════════════════════════════════════════
// BUILD: Greeks / Sensitivities
// ═══════════════════════════════════════════════════════════════════

function buildGreeks(schema) {
  const grid = $('ws-greeks-grid');
  grid.innerHTML = '';
  const cols = (schema.sensitivities||[]).length;
  grid.style.gridTemplateColumns = `repeat(${Math.min(cols,5)}, 1fr)`;
  (schema.sensitivities||[]).forEach(t => {
    grid.innerHTML += `<div class="kpi-tile"><div class="kpi-label">${t.l}</div><div class="kpi-val" id="g-${t.id}">—</div></div>`;
  });
}


// ═══════════════════════════════════════════════════════════════════
// BUILD: Output Panels (NEW — schema-driven visibility)
// ═══════════════════════════════════════════════════════════════════

function buildOutputPanels(schema) {
  // Show/hide schema-driven output sections
  $('ws-payoff-section').style.display = schema.payoff ? '' : 'none';
  $('ws-cashflows-section').style.display = schema.cashflows ? '' : 'none';
  $('ws-risk-section').style.display = schema.risk_ladder ? '' : 'none';
  $('ws-curves-section').style.display = schema.curves ? '' : 'none';
  $('ws-resets-section').style.display = schema.resets ? '' : 'none';

  // Clear contents
  $('payoff-chart').innerHTML = '';
  $('cashflows-body').innerHTML = '';
  $('risk-ladder-body').innerHTML = '';
  $('risk-ladder-chart').innerHTML = '';
  $('curves-body').innerHTML = '';
  $('curves-chart').innerHTML = '';
  $('resets-body').innerHTML = '';

  // Auto-render payoff if applicable
  if (schema.payoff) renderPayoff();
}


// ═══════════════════════════════════════════════════════════════════
// PANEL G: Payoff Diagram (client-side)
// ═══════════════════════════════════════════════════════════════════

function renderPayoff() {
  const fields = FIELDS[currentInst] || [];
  const params = {};
  fields.forEach(f => {
    const el = $('f-' + f.id);
    params[f.id] = el ? (f.type === 'number' ? parseFloat(el.value) || 0 : el.value) : f.val;
  });

  const strike = params.strike || params.long_strike || params.put_strike || 100;
  const spotEl = $('f-md-spot');
  const currentSpot = spotEl ? parseFloat(spotEl.value) || strike : strike;
  const optType = params.option_type || 'call';
  const lo = strike * 0.6, hi = strike * 1.4;
  const steps = 100;
  const dx = (hi - lo) / steps;

  const x = [], yPayoff = [];
  for (let i = 0; i <= steps; i++) {
    const s = lo + i * dx;
    x.push(s);
    let payoff = 0;
    if (currentInst === 'digital_option') {
      payoff = optType === 'call' ? (s >= strike ? (params.cash_payoff||1) : 0) : (s <= strike ? (params.cash_payoff||1) : 0);
    } else if (currentInst.includes('spread')) {
      const k1 = params.long_strike || params.put_strike || strike;
      const k2 = params.short_strike || params.call_strike || strike;
      if (currentInst.includes('put')) {
        payoff = Math.max(k1 - s, 0) - Math.max(k2 - s, 0);
      } else {
        payoff = Math.max(s - k1, 0) - Math.max(s - k2, 0);
      }
    } else {
      payoff = optType === 'call' ? Math.max(s - strike, 0) : Math.max(strike - s, 0);
    }
    yPayoff.push(payoff);
  }

  const traces = [
    { x, y: yPayoff, type: 'scatter', mode: 'lines', name: 'Payoff at Expiry',
      line: { color: '#f59e0b', width: 2 } },
    { x: [currentSpot, currentSpot], y: [Math.min(...yPayoff), Math.max(...yPayoff)],
      type: 'scatter', mode: 'lines', name: 'Current Spot',
      line: { color: '#3b82f6', width: 1, dash: 'dot' } },
  ];
  const layout = { ...PLOT_LAYOUT, height: 250, showlegend: true,
    legend: { x: 0.02, y: 0.98, bgcolor: 'rgba(0,0,0,0)', font: { size: 10 } },
    title: { text: 'Payoff at Expiry', font: { size: 13 } },
    xaxis: { ...PLOT_LAYOUT.xaxis, title: 'Spot Price' },
    yaxis: { ...PLOT_LAYOUT.yaxis, title: 'Payoff' },
    shapes: [{ type: 'line', x0: lo, x1: hi, y0: 0, y1: 0,
      line: { color: '#475569', width: 1, dash: 'dash' } }],
  };
  Plotly.newPlot('payoff-chart', traces, layout, PLOT_CONFIG);
}


// ═══════════════════════════════════════════════════════════════════
// BUILD: Analysis Panels (ladders, heatmap, scenario)
// ═══════════════════════════════════════════════════════════════════

function buildAnalysis(schema) {
  const container = $('ws-analysis-panels');
  container.innerHTML = '';
  (schema.analysis || []).forEach(key => {
    const def = ANALYSIS_PANELS[key];
    if (!def) return;
    const div = document.createElement('div');
    div.className = 'card';

    if (def.variable) {
      // Ladder panel
      div.innerHTML = `
        <div class="card-title"><div class="dot"></div>${def.title}</div>
        <div class="grid g3" style="margin-bottom:10px">
          <div><label>Variable</label><input value="${def.label}" readonly style="color:var(--text-dim)"/></div>
          <div><label>Range (%)</label><input type="number" id="anal-${key}-range" value="${def.range}"/></div>
          <div><label>Steps</label><input type="number" id="anal-${key}-steps" value="${def.steps}"/></div>
        </div>
        <button class="btn btn-sm" onclick="runLadder('${key}')">Run</button>
        <div id="anal-${key}-chart" style="margin-top:10px"></div>
        <div id="anal-${key}-table" style="margin-top:8px;max-height:250px;overflow-y:auto"></div>`;
    } else if (key === 'spot_vol_matrix') {
      div.innerHTML = `
        <div class="card-title"><div class="dot"></div>${def.title}</div>
        <div class="grid g2" style="margin-bottom:10px">
          <div><label>Spot Range (%)</label><input type="number" id="anal-matrix-spot-range" value="20"/></div>
          <div><label>Vol Range (%)</label><input type="number" id="anal-matrix-vol-range" value="50"/></div>
        </div>
        <button class="btn btn-sm" onclick="runMatrix()">Generate</button>
        <div id="anal-matrix-chart" style="margin-top:10px"></div>`;
    } else if (key === 'scenario') {
      const opts = SCENARIOS.map(s =>
        `<option value="${s.key}">${s.name}</option>`).join('');
      div.innerHTML = `
        <div class="card-title"><div class="dot"></div>${def.title}</div>
        <div class="grid g2" style="margin-bottom:10px">
          <div><label>Scenario</label><select id="anal-scenario-select">${opts}</select></div>
          <div style="display:flex;align-items:flex-end;gap:8px">
            <button class="btn btn-sm" onclick="runScenario()" style="flex:1">Run</button>
            <button class="btn btn-sm" onclick="runAllScenarios()" style="flex:1">Run All</button>
          </div>
        </div>
        <div id="anal-scenario-result" style="margin-top:8px"></div>`;
    }
    container.appendChild(div);
  });
}


// ═══════════════════════════════════════════════════════════════════
// COLLECT PAYLOAD (shared by all API calls)
// ═══════════════════════════════════════════════════════════════════

function collectPayload() {
  const instType = currentInst;
  const fields = FIELDS[instType] || [];
  const params = {};
  fields.forEach(f => {
    const el = $('f-' + f.id);
    if (!el) return;
    let val = el.value;
    if (f.type === 'number') val = parseFloat(val) || 0;
    params[f.id] = val;
  });

  const underlying = params.ccy_pair || params.underlying || params.commodity || 'USD';
  const underlyings = {};
  const spotEl = $('f-md-spot');
  const volEl = $('f-md-vol');
  const divEl = $('f-md-div');
  underlyings[underlying] = {
    spot: spotEl ? parseFloat(spotEl.value) || 100 : 100,
    vol: volEl ? parseFloat(volEl.value) || 0.25 : 0.25,
    div_yield: divEl ? parseFloat(divEl.value) || 0 : 0,
  };

  const rateEl = $('f-md-rate');
  const foreignEl = $('f-md-foreign_rate');
  const rateCurve = [{ tenor: '1Y', rate: rateEl ? parseFloat(rateEl.value) || 0.045 : 0.045 }];

  const payload = {
    instrument: { type: instType, params },
    market_data: {
      pricing_date: ($('f-md-pricing_date') || {}).value || new Date().toISOString().slice(0, 10),
      underlyings, rate_curve: rateCurve,
    },
    model: $('f-model').value,
    engine: $('f-engine').value,
    engine_params: {},
  };

  // Collect engine params dynamically
  const schema = SCHEMA[instType];
  const engineDef = (schema?.engines || []).find(e => e.v === payload.engine);
  (engineDef?.params || []).forEach(key => {
    const def = ENGINE_PARAM_DEFS[key];
    if (!def) return;
    const el = $('f-' + def.id);
    if (!el) return;
    const backendKey = ENGINE_PARAM_MAP[key] || key;
    payload.engine_params[backendKey] = parseFloat(el.value) || 0;
  });

  if (foreignEl) {
    payload.market_data.foreign_rate = parseFloat(foreignEl.value) || 0.045;
  }
  return payload;
}


// ═══════════════════════════════════════════════════════════════════
// API HELPER
// ═══════════════════════════════════════════════════════════════════

async function apiPost(path, body) {
  const r = await fetch(API + path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status}: ${(await r.text()).slice(0, 200)}`);
  return r.json();
}

async function apiGet(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error(`${r.status}: ${(await r.text()).slice(0, 200)}`);
  return r.json();
}


// ═══════════════════════════════════════════════════════════════════
// EVENT: Price Button
// ═══════════════════════════════════════════════════════════════════

$('btn-price').addEventListener('click', async () => {
  $('npv-value').textContent = '...';
  $('npv-meta').textContent = 'Pricing...';
  try {
    const payload = collectPayload();
    const schema = SCHEMA[currentInst];
    const measures = (schema.sensitivities || []).map(s => s.id);

    const [priceRes, greeksRes] = await Promise.all([
      apiPost('/pricing/single', payload),
      measures.length ? apiPost('/sensitivities/greeks', { ...payload, measures }).catch(() => null) : null,
    ]);

    $('npv-value').textContent = '$' + priceRes.npv.toLocaleString(undefined, { minimumFractionDigits: 4, maximumFractionDigits: 4 });
    $('npv-meta').textContent = [priceRes.trade_id, priceRes.model, priceRes.engine, priceRes.elapsed_ms + 'ms'].join(' · ');
    $('diagnostics').textContent = JSON.stringify(priceRes, null, 2);

    if (greeksRes?.greeks) {
      (schema.sensitivities || []).forEach(t => {
        const el = $('g-' + t.id);
        if (!el) return;
        const v = greeksRes.greeks[t.id];
        el.textContent = typeof v === 'number' ? v.toFixed(t.d) : '—';
        el.style.color = typeof v === 'number' ? (v >= 0 ? 'var(--green)' : 'var(--red)') : '';
      });
    }
  } catch (e) {
    $('npv-value').textContent = 'Error';
    $('npv-meta').textContent = e.message;
  }
});


// ═══════════════════════════════════════════════════════════════════
// EVENT: Compare Button
// ═══════════════════════════════════════════════════════════════════

$('btn-compare').addEventListener('click', async () => {
  try {
    const payload = collectPayload();
    const schema = SCHEMA[currentInst];
    payload.engines = (schema.engines || []).map(e => e.v);
    const res = await apiPost('/pricing/compare', payload);
    $('compare-card').style.display = '';
    const body = $('compare-body');
    body.innerHTML = '';
    (res.results || []).forEach(r => {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${r.engine}</td><td style="color:var(--accent)">${r.npv != null ? '$' + r.npv.toFixed(4) : 'Failed'}</td><td>${r.diff_bps != null ? r.diff_bps.toFixed(1) : '—'}</td><td>${r.elapsed_ms ?? '—'}</td>`;
      body.appendChild(tr);
    });
  } catch (e) { alert(e.message); }
});


// ═══════════════════════════════════════════════════════════════════
// EVENT: Excel Export
// ═══════════════════════════════════════════════════════════════════

$('btn-export').addEventListener('click', async () => {
  try {
    const payload = collectPayload();
    payload.include_mc_data = true;
    const r = await fetch(API + '/export/pricing', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!r.ok) throw new Error(await r.text());
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `Optima_${currentInst}_${Date.now()}.xlsx`;
    a.click();
  } catch (e) { alert('Export failed: ' + e.message); }
});


// ═══════════════════════════════════════════════════════════════════
// EVENT: Clear
// ═══════════════════════════════════════════════════════════════════

$('btn-clear').addEventListener('click', () => {
  $('npv-value').textContent = '—';
  $('npv-meta').textContent = 'Configure and click Price';
  document.querySelectorAll('#ws-greeks-grid .kpi-val').forEach(el => {
    el.textContent = '—';
    el.style.color = '';
  });
  $('compare-card').style.display = 'none';
  $('diagnostics').textContent = 'Run a pricing to see diagnostics.';
});


// ═══════════════════════════════════════════════════════════════════
// EVENT: Valuate (MTM P&L)
// ═══════════════════════════════════════════════════════════════════

$('btn-valuate').addEventListener('click', async () => {
  try {
    const payload = collectPayload();
    payload.market_data.pricing_date = $('v-val-date').value || payload.market_data.pricing_date;
    const res = await apiPost('/pricing/single', payload);
    const entry = parseFloat($('v-entry-price').value) || 0;
    const dir = $('v-direction').value === 'long' ? 1 : -1;
    const pnl = dir * (res.npv - entry);
    $('v-entry-npv').textContent = '$' + entry.toLocaleString(undefined, { maximumFractionDigits: 2 });
    $('v-current-npv').textContent = '$' + res.npv.toLocaleString(undefined, { maximumFractionDigits: 4 });
    $('v-pnl').textContent = (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toLocaleString(undefined, { maximumFractionDigits: 2 });
    $('v-pnl').style.color = pnl >= 0 ? 'var(--green)' : 'var(--red)';
  } catch (e) { alert(e.message); }
});


// ═══════════════════════════════════════════════════════════════════
// ANALYSIS: Run Sensitivity Ladder
// ═══════════════════════════════════════════════════════════════════

async function runLadder(key) {
  const def = ANALYSIS_PANELS[key];
  if (!def) return;
  const rangeEl = $(`anal-${key}-range`);
  const stepsEl = $(`anal-${key}-steps`);
  const rangePct = parseFloat(rangeEl?.value) || def.range;
  const steps = parseInt(stepsEl?.value) || def.steps;

  try {
    const payload = collectPayload();
    payload.variable = def.variable;
    payload.range_pct = rangePct;
    payload.steps = steps;

    const res = await apiPost('/sensitivities/ladder', payload);
    const points = res.ladder || res.points || res.results || [];

    if (points.length) {
      const x = points.map(p => p.shock ?? p.value ?? p.x);
      const y = points.map(p => p.npv ?? p.y);
      plotLine(`anal-${key}-chart`, x, y, def.title, def.label, 'NPV');

      // Render table
      const tableDiv = $(`anal-${key}-table`);
      let thtml = '<table><thead><tr><th>' + def.label + '</th><th>NPV</th><th>Δ NPV</th></tr></thead><tbody>';
      const baseNpv = res.base_npv || y[Math.floor(y.length / 2)];
      points.forEach(p => {
        const val = p.shock ?? p.value ?? p.x;
        const npv = p.npv ?? p.y;
        const diff = npv - baseNpv;
        const color = diff >= 0 ? 'var(--green)' : 'var(--red)';
        thtml += `<tr><td>${typeof val === 'number' ? val.toFixed(4) : val}</td><td style="color:var(--accent)">$${npv.toLocaleString(undefined, { maximumFractionDigits: 2 })}</td><td style="color:${color}">${diff >= 0 ? '+' : ''}${diff.toLocaleString(undefined, { maximumFractionDigits: 2 })}</td></tr>`;
      });
      thtml += '</tbody></table>';
      tableDiv.innerHTML = thtml;
    }
  } catch (e) {
    $(`anal-${key}-chart`).innerHTML = `<div style="color:var(--red);padding:12px">Error: ${e.message}</div>`;
  }
}


// ═══════════════════════════════════════════════════════════════════
// ANALYSIS: Run Spot × Vol Matrix
// ═══════════════════════════════════════════════════════════════════

async function runMatrix() {
  try {
    const payload = collectPayload();
    payload.variable_x = 'spot';
    payload.variable_y = 'vol';
    payload.range_x_pct = parseFloat($('anal-matrix-spot-range')?.value) || 20;
    payload.range_y_pct = parseFloat($('anal-matrix-vol-range')?.value) || 50;
    payload.steps_x = 9;
    payload.steps_y = 9;

    const res = await apiPost('/sensitivities/matrix', payload);
    if (res.matrix && res.x_values && res.y_values) {
      plotHeatmap('anal-matrix-chart', res.matrix, res.x_values, res.y_values, 'Spot × Vol Heatmap');
    }
  } catch (e) {
    $('anal-matrix-chart').innerHTML = `<div style="color:var(--red);padding:12px">Error: ${e.message}</div>`;
  }
}


// ═══════════════════════════════════════════════════════════════════
// ANALYSIS: Scenario
// ═══════════════════════════════════════════════════════════════════

async function runScenario() {
  const key = $('anal-scenario-select')?.value;
  const scenDef = SCENARIOS.find(s => s.key === key);
  if (!scenDef) return;

  try {
    const payload = collectPayload();
    payload.scenario = { name: scenDef.key, shocks: scenDef.shocks };
    const res = await apiPost('/risk/scenario', payload);

    const baseNpv = res.base_npv ?? 0;
    const stressedNpv = res.stressed_npv ?? res.scenario_npv ?? 0;
    const pnl = stressedNpv - baseNpv;

    $('anal-scenario-result').innerHTML = `
      <div class="grid g3">
        <div class="kpi-tile"><div class="kpi-label">Base NPV</div><div class="kpi-val">$${baseNpv.toLocaleString(undefined, { maximumFractionDigits: 2 })}</div></div>
        <div class="kpi-tile"><div class="kpi-label">Stressed NPV</div><div class="kpi-val">$${stressedNpv.toLocaleString(undefined, { maximumFractionDigits: 2 })}</div></div>
        <div class="kpi-tile" style="border-color:${pnl >= 0 ? 'var(--green)' : 'var(--red)'}"><div class="kpi-label">P&L Impact</div><div class="kpi-val" style="color:${pnl >= 0 ? 'var(--green)' : 'var(--red)'}">${pnl >= 0 ? '+' : ''}$${pnl.toLocaleString(undefined, { maximumFractionDigits: 2 })}</div></div>
      </div>`;
  } catch (e) {
    $('anal-scenario-result').innerHTML = `<div style="color:var(--red)">Error: ${e.message}</div>`;
  }
}

async function runAllScenarios() {
  const resultDiv = $('anal-scenario-result');
  resultDiv.innerHTML = '<div style="color:var(--text-muted)">Running all scenarios...</div>';

  try {
    const payload = collectPayload();
    const results = [];

    for (const s of SCENARIOS) {
      try {
        const p = { ...payload, scenario: { name: s.key, shocks: s.shocks } };
        const res = await apiPost('/risk/scenario', p);
        results.push({ name: s.name, base: res.base_npv, stressed: res.stressed_npv ?? res.scenario_npv, pnl: (res.stressed_npv ?? res.scenario_npv ?? 0) - (res.base_npv ?? 0) });
      } catch {
        results.push({ name: s.name, base: 0, stressed: 0, pnl: 0, error: true });
      }
    }

    let html = '<table><thead><tr><th>Scenario</th><th>Base NPV</th><th>Stressed</th><th>P&L</th></tr></thead><tbody>';
    results.forEach(r => {
      const color = r.error ? 'var(--text-dim)' : (r.pnl >= 0 ? 'var(--green)' : 'var(--red)');
      html += `<tr><td>${r.name}</td><td>$${(r.base||0).toLocaleString(undefined,{maximumFractionDigits:2})}</td><td>$${(r.stressed||0).toLocaleString(undefined,{maximumFractionDigits:2})}</td><td style="color:${color}">${r.error ? 'Error' : (r.pnl>=0?'+':'')+'$'+r.pnl.toLocaleString(undefined,{maximumFractionDigits:2})}</td></tr>`;
    });
    html += '</tbody></table>';

    // Add bar chart
    const names = results.filter(r=>!r.error).map(r=>r.name);
    const pnls = results.filter(r=>!r.error).map(r=>r.pnl);
    resultDiv.innerHTML = html + '<div id="scenario-all-chart" style="margin-top:10px"></div>';
    if (names.length) plotBar('scenario-all-chart', names, pnls, 'Scenario P&L', '', 'P&L Impact');
  } catch (e) {
    resultDiv.innerHTML = `<div style="color:var(--red)">Error: ${e.message}</div>`;
  }
}


// ═══════════════════════════════════════════════════════════════════
// PANEL J/M: Cashflow Schedule
// ═══════════════════════════════════════════════════════════════════

$('btn-cashflows').addEventListener('click', async () => {
  $('cashflows-body').innerHTML = '<div style="color:var(--text-muted)">Loading cashflows...</div>';
  try {
    const payload = collectPayload();
    const res = await apiPost('/pricing/cashflows', payload);

    let html = '';
    (res.legs || [res]).forEach((leg, i) => {
      const legName = leg.leg_name || `Leg ${i + 1}`;
      const totalPv = leg.total_pv ?? (leg.flows || []).reduce((s, f) => s + (f.pv || 0), 0);
      html += `<div style="margin-bottom:16px"><div style="display:flex;justify-content:space-between;margin-bottom:6px"><span style="font-weight:600;color:var(--cyan);font-size:12px;text-transform:uppercase">${legName}</span><span style="color:var(--accent);font-size:12px">PV: $${totalPv.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span></div>`;
      html += '<div style="max-height:250px;overflow-y:auto"><table><thead><tr><th>Period</th><th>Pay Date</th><th>Notional</th><th>Rate</th><th>Cashflow</th><th>DF</th><th>PV</th></tr></thead><tbody>';
      (leg.flows || []).forEach(f => {
        html += `<tr><td>${f.period_start || ''} → ${f.period_end || ''}</td><td>${f.payment_date || ''}</td><td>${(f.notional||0).toLocaleString()}</td><td>${((f.rate||0)*100).toFixed(3)}%</td><td style="color:var(--accent)">${(f.cashflow||0).toLocaleString(undefined,{maximumFractionDigits:0})}</td><td>${(f.discount_factor||0).toFixed(4)}</td><td>${(f.pv||0).toLocaleString(undefined,{maximumFractionDigits:0})}</td></tr>`;
      });
      html += '</tbody></table></div></div>';
    });

    if (res.net_pv != null) {
      html += `<div style="text-align:right;font-weight:700;color:var(--accent);margin-top:8px">Net PV: $${res.net_pv.toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>`;
    }
    $('cashflows-body').innerHTML = html || '<div style="color:var(--text-dim)">No cashflow data returned.</div>';
  } catch (e) {
    $('cashflows-body').innerHTML = `<div style="color:var(--red)">Error: ${e.message}</div>`;
  }
});


// ═══════════════════════════════════════════════════════════════════
// PANEL K: Risk Ladder (DV01 by Bucket)
// ═══════════════════════════════════════════════════════════════════

$('btn-risk-ladder').addEventListener('click', async () => {
  $('risk-ladder-body').innerHTML = '<div style="color:var(--text-muted)">Computing risk ladder...</div>';
  try {
    const payload = collectPayload();
    payload.variable = 'rate';
    payload.buckets = ['1Y', '2Y', '3Y', '5Y', '7Y', '10Y', '15Y', '20Y', '30Y'];
    const res = await apiPost('/sensitivities/ladder', payload);
    const points = res.ladder || res.points || res.results || [];

    if (points.length) {
      const tenors = points.map(p => p.tenor || p.label || p.shock);
      const dv01s = points.map(p => p.dv01 || p.npv_change || p.delta_npv || 0);
      const total = dv01s.reduce((s, v) => s + v, 0);

      let html = '<table><thead><tr><th>Tenor</th><th>DV01</th></tr></thead><tbody>';
      points.forEach((p, i) => {
        html += `<tr><td>${tenors[i]}</td><td style="color:${dv01s[i]>=0?'var(--green)':'var(--red)'}">${dv01s[i].toLocaleString(undefined,{maximumFractionDigits:2})}</td></tr>`;
      });
      html += `<tr style="font-weight:700;border-top:2px solid var(--border)"><td>TOTAL</td><td style="color:var(--accent)">${total.toLocaleString(undefined,{maximumFractionDigits:2})}</td></tr></tbody></table>`;
      $('risk-ladder-body').innerHTML = html;
      plotBar('risk-ladder-chart', tenors, dv01s, 'DV01 by Tenor Bucket', 'Tenor', 'DV01');
    }
  } catch (e) {
    $('risk-ladder-body').innerHTML = `<div style="color:var(--red)">Error: ${e.message}</div>`;
  }
});


// ═══════════════════════════════════════════════════════════════════
// PANEL L: Curve Data
// ═══════════════════════════════════════════════════════════════════

$('btn-curves').addEventListener('click', async () => {
  $('curves-body').innerHTML = '<div style="color:var(--text-muted)">Loading curve data...</div>';
  try {
    const payload = collectPayload();
    const res = await apiPost('/market/yield-curve/query', payload);
    const points = res.curve || res.points || res.tenors || [];

    if (points.length) {
      let html = '<table><thead><tr><th>Tenor</th><th>Zero Rate</th><th>Discount Factor</th><th>Forward Rate</th></tr></thead><tbody>';
      const tenors = [], zeros = [], fwds = [];
      points.forEach(p => {
        tenors.push(p.tenor || p.label);
        zeros.push(p.zero_rate || p.rate || 0);
        fwds.push(p.forward_rate || 0);
        html += `<tr><td>${p.tenor||p.label}</td><td>${((p.zero_rate||p.rate||0)*100).toFixed(3)}%</td><td>${(p.discount_factor||0).toFixed(6)}</td><td>${((p.forward_rate||0)*100).toFixed(3)}%</td></tr>`;
      });
      html += '</tbody></table>';
      $('curves-body').innerHTML = html;

      const traces = [
        { x: tenors, y: zeros.map(v => v * 100), name: 'Zero Rate', line: { color: '#f59e0b' } },
        { x: tenors, y: fwds.map(v => v * 100), name: 'Forward Rate', line: { color: '#3b82f6', dash: 'dash' } },
      ];
      const layout = { ...PLOT_LAYOUT, height: 260, showlegend: true,
        legend: { x: 0.02, y: 0.98, bgcolor: 'rgba(0,0,0,0)' },
        title: { text: 'Yield Curve', font: { size: 13 } },
        xaxis: { ...PLOT_LAYOUT.xaxis, title: 'Tenor' },
        yaxis: { ...PLOT_LAYOUT.yaxis, title: 'Rate (%)' } };
      Plotly.newPlot('curves-chart', traces, layout, PLOT_CONFIG);
    }
  } catch (e) {
    $('curves-body').innerHTML = `<div style="color:var(--red)">Error: ${e.message}</div>`;
  }
});


// ═══════════════════════════════════════════════════════════════════
// PANEL O: Resets (Fixings)
// ═══════════════════════════════════════════════════════════════════

$('btn-resets').addEventListener('click', async () => {
  $('resets-body').innerHTML = '<div style="color:var(--text-muted)">Loading resets...</div>';
  try {
    const payload = collectPayload();
    const res = await apiPost('/pricing/resets', payload);
    const resets = res.resets || res.fixings || [];

    if (resets.length) {
      let html = '<table><thead><tr><th>Reset Date</th><th>Index</th><th>Fixing</th><th>Status</th></tr></thead><tbody>';
      resets.forEach(r => {
        const status = r.status || (r.realized ? 'Realized' : 'Projected');
        const icon = status === 'Realized' ? '●' : '◎';
        const color = status === 'Realized' ? 'var(--green)' : 'var(--text-muted)';
        html += `<tr><td>${r.date || r.reset_date}</td><td>${r.index || ''}</td><td>${((r.rate || r.fixing || 0) * 100).toFixed(3)}%</td><td style="color:${color}">${icon} ${status}</td></tr>`;
      });
      html += '</tbody></table>';
      $('resets-body').innerHTML = html;
    } else {
      $('resets-body').innerHTML = '<div style="color:var(--text-dim)">No reset data available.</div>';
    }
  } catch (e) {
    $('resets-body').innerHTML = `<div style="color:var(--red)">Error: ${e.message}</div>`;
  }
});


// ═══════════════════════════════════════════════════════════════════
// HEALTH CHECK
// ═══════════════════════════════════════════════════════════════════

async function checkHealth() {
  try {
    const r = await fetch(API.replace('/api/v1', '') + '/health');
    const d = await r.json();
    $('api-status').textContent = '✓ API v' + d.version;
    $('api-status').classList.add('ok');
  } catch { $('api-status').textContent = '✗ API Offline'; }
}


// ═══════════════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════════════

// Card click handlers
document.querySelectorAll('.inst-card').forEach(card => {
  card.addEventListener('click', () => openWorkspace(card.dataset.inst));
});
$('logo-home').addEventListener('click', goHome);
$('bc-home').addEventListener('click', goHome);
$('btn-go-home').addEventListener('click', goHome);

checkHealth();

// URL param support: ?inst=vanilla_option
const urlInst = new URLSearchParams(window.location.search).get('inst');
if (urlInst && SCHEMA[urlInst]) openWorkspace(urlInst);
