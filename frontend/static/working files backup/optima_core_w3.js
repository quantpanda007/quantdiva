/**
 * ╔══════════════════════════════════════════════════════════════════╗
 * ║                   OPTIMA — CORE APPLICATION LOGIC                ║
 * ║                                                                  ║
 * ║  Shared UI behavior, API calls, chart rendering, panel logic.   ║
 * ║  Uses INSTRUMENT_REGISTRY for per-instrument field groups,      ║
 * ║  payload mapping, and custom logic.                              ║
 * ║                                                                  ║
 * ║  Depends on: schema_master.js, _base.js, instrument modules,    ║
 * ║              optima_registry.js, Plotly CDN                      ║
 * ╚══════════════════════════════════════════════════════════════════╝
 */

const API = '/api/v1';
const $ = id => document.getElementById(id);
let currentInst = null;
let currentPreset = null;  // Preset field overrides from card click

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
    line: { color: '#0ea5e9', width: 2 }, marker: { size: 4 }, ...extra }];
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
    colorscale: [[0,'#ef4444'],[0.5,'#0ea5e9'],[1,'#10b981']],
    hovertemplate: 'Spot: %{x}<br>Vol: %{y}<br>NPV: $%{z:.2f}<extra></extra>' }];
  const layout = { ...PLOT_LAYOUT, title: { text: title, font: { size: 13 } },
    xaxis: { ...PLOT_LAYOUT.xaxis, title: 'Spot' },
    yaxis: { ...PLOT_LAYOUT.yaxis, title: 'Volatility' },
    height: 320 };
  Plotly.newPlot(divId, traces, layout, PLOT_CONFIG);
}


// ═══════════════════════════════════════════════════════════════════
// LOGIN
// ═══════════════════════════════════════════════════════════════════

const VALID_USERS = { admin: 'optima123', demo: 'demo' };

function handleLogin() {
  const user = $('login-user').value.trim();
  const pass = $('login-pass').value;
  if (VALID_USERS[user] && VALID_USERS[user] === pass) {
    $('login-screen').style.display = 'none';
    $('app-shell').style.display = '';
    $('login-error').textContent = '';
  } else {
    $('login-error').textContent = 'Invalid username or password';
    $('login-pass').value = '';
    $('login-pass').focus();
  }
}

$('login-btn').addEventListener('click', handleLogin);
$('login-pass').addEventListener('keydown', e => { if (e.key === 'Enter') handleLogin(); });
$('login-user').addEventListener('keydown', e => { if (e.key === 'Enter') $('login-pass').focus(); });

$('btn-logout').addEventListener('click', () => {
  $('app-shell').style.display = 'none';
  $('login-screen').style.display = '';
  $('login-user').value = '';
  $('login-pass').value = '';
  $('login-user').focus();
  goModules();
});


// ═══════════════════════════════════════════════════════════════════
// WORKSPACE MODE TOGGLE (Single Deal vs Bulk Upload)
// ═══════════════════════════════════════════════════════════════════

function setWorkspaceMode(mode) {
  const singleMode = $('ws-single-mode');
  const bulkMode = $('ws-bulk-mode');
  if (!singleMode || !bulkMode) return;

  document.querySelectorAll('.mode-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.mode === mode);
  });

  if (mode === 'single') {
    singleMode.style.display = '';
    bulkMode.style.display = 'none';
  } else {
    singleMode.style.display = 'none';
    bulkMode.style.display = '';
  }
}

// Mode toggle clicks
document.querySelectorAll('.mode-btn').forEach(btn => {
  btn.addEventListener('click', () => setWorkspaceMode(btn.dataset.mode));
});


// ═══════════════════════════════════════════════════════════════════
// BULK UPLOAD — File handling, drag-drop, API call
// ═══════════════════════════════════════════════════════════════════

// Drop zone interactions
const dropZone = $('bulk-drop-zone');
if (dropZone) {
  dropZone.addEventListener('click', () => $('bulk-file').click());

  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('dragover');
  });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file && (file.name.endsWith('.xlsx') || file.name.endsWith('.xls'))) {
      stageBulkFile(file);
    }
  });
}

$('bulk-file').addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (file) stageBulkFile(file);
  e.target.value = '';
});

let _lastBulkFile = null;  // store for Excel re-download

// Stage a file — show filename, reveal Price button, don't call API yet
function stageBulkFile(file) {
  _lastBulkFile = file;
  const dropZone = $('bulk-drop-zone');
  dropZone.querySelector('.bulk-drop-text').textContent = `📄 ${file.name}`;
  dropZone.querySelector('.bulk-drop-hint').textContent = 'Click ⚡ Price to run valuation, or drop a different file to replace';
  $('bulk-price-btn').style.display = '';
  // Reset previous results
  $('bulk-status').style.display = 'none';
  $('bulk-summary').style.display = 'none';
  $('bulk-results-wrap').style.display = 'none';
  $('bulk-excel-row').style.display = 'none';
}

// Price button — run the API call
$('bulk-price-btn').addEventListener('click', () => {
  if (_lastBulkFile) processBulkFile(_lastBulkFile);
});

async function processBulkFile(file) {
  _lastBulkFile = file;
  const statusDiv = $('bulk-status');
  statusDiv.style.display = '';
  statusDiv.className = 'bulk-status loading';
  statusDiv.textContent = `⏳ Pricing ${file.name} ...`;

  // Hide previous results
  $('bulk-summary').style.display = 'none';
  $('bulk-results-wrap').style.display = 'none';
  $('bulk-excel-row').style.display = 'none';

  try {
    const rd = parseFloat($('bulk-rd').value) / 100 || 0.065;
    const rf = parseFloat($('bulk-rf').value) / 100 || 0.045;
    const interp = $('bulk-interp')?.value || 'linear';

    const formData = new FormData();
    formData.append('file', file);

    const contractType = currentInst === 'fx_range_forward' ? 'range_forward' : 'forward';
    const url = `${API}/pricing/bulk-price?domestic_rate=${rd}&foreign_rate=${rf}&interpolation=${interp}&contract_type=${contractType}`;
    const resp = await fetch(url, { method: 'POST', body: formData });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${resp.status}`);
    }

    const data = await resp.json();
    renderBulkResults(data);

    statusDiv.className = 'bulk-status success';
    statusDiv.textContent = `✓ ${data.priced} deals priced · ${data.errors} errors · Method: ${data.method}`;
  } catch (err) {
    statusDiv.className = 'bulk-status error';
    statusDiv.textContent = `✗ Upload failed: ${err.message}`;
  }
}

function renderBulkResults(data) {
  // Summary strip
  const fmt = (n) => n.toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  $('bs-priced').textContent = data.priced;
  $('bs-npv').textContent = fmt(data.total_npv);
  $('bs-npv').style.color = data.total_npv >= 0 ? 'var(--green)' : 'var(--red)';
  $('bs-lt').textContent = fmt(data.total_long_term);
  $('bs-st').textContent = fmt(data.total_short_term);
  $('bs-errors').textContent = data.errors;
  $('bs-errors').style.color = data.errors > 0 ? 'var(--red)' : 'var(--green)';
  $('bulk-summary').style.display = '';

  // Results table
  const tbody = $('bulk-results-body');
  tbody.innerHTML = '';
  (data.results || []).forEach(r => {
    const npvColor = r.npv >= 0 ? 'var(--green)' : 'var(--red)';
    const statusColor = r.status === 'OK' ? 'var(--green)' : 'var(--text-muted)';
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${r.ref}</td>
      <td>${r.client}</td>
      <td>${r.ccy_pair}</td>
      <td>${r.strike.toFixed(4)}</td>
      <td>${r.maturity}</td>
      <td>${r.forward.toFixed(4)}</td>
      <td style="color:${npvColor};font-weight:600">${fmt(r.npv)}</td>
      <td>${fmt(r.long_term)}</td>
      <td>${fmt(r.short_term)}</td>
      <td style="color:${statusColor}">${r.status}</td>
    `;
    tbody.appendChild(tr);
  });
  $('bulk-results-wrap').style.display = '';
  $('bulk-excel-row').style.display = '';
}

// Excel download button — uses stored file
$('bulk-excel-btn')?.addEventListener('click', async () => {
  if (!_lastBulkFile) return;
  try {
    const rd = parseFloat($('bulk-rd').value) / 100 || 0.065;
    const rf = parseFloat($('bulk-rf').value) / 100 || 0.045;
    const interp = $('bulk-interp')?.value || 'linear';
    const formData = new FormData();
    formData.append('file', _lastBulkFile);
    const contractType = currentInst === 'fx_range_forward' ? 'range_forward' : 'forward';
    const url = `${API}/pricing/bulk-upload?domestic_rate=${rd}&foreign_rate=${rf}&interpolation=${interp}&contract_type=${contractType}`;
    const resp = await fetch(url, { method: 'POST', body: formData });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const blob = await resp.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    const cd = resp.headers.get('Content-Disposition');
    const match = cd && cd.match(/filename="?([^"]+)"?/);
    a.download = match ? match[1] : `Optima_BulkResults_${_lastBulkFile.name}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
  } catch (err) {
    alert('Excel download failed: ' + err.message);
  }
});

$('bulk-template-btn').addEventListener('click', async () => {
  try {
    const resp = await fetch(`${API}/pricing/bulk-template`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'Optima_BulkUpload_Template.xlsx';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch (err) {
    alert('Failed to download template: ' + err.message);
  }
});


// ═══════════════════════════════════════════════════════════════════
// NAVIGATION — Login → Modules → Valuation (expandable) → Workspace
// ═══════════════════════════════════════════════════════════════════

let navStack = []; // tracks navigation history for back button

function showPage(pageId) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const pg = $(pageId);
  if (pg) pg.classList.add('active');
}

function updateBreadcrumb(parts) {
  // parts: [{text, id?}] — id means clickable
  const bc = $('breadcrumb');
  if (!parts || parts.length === 0) {
    bc.style.display = 'none';
    $('btn-go-back').style.display = 'none';
    return;
  }
  bc.style.display = 'flex';
  $('btn-go-back').style.display = navStack.length > 0 ? '' : 'none';
  // Use bc-module, bc-asset, bc-inst for up to 3 levels
  const slots = ['bc-module', 'bc-asset', 'bc-inst'];
  const seps = ['bc-sep2', 'bc-sep3'];
  slots.forEach((s, i) => {
    const el = $(s);
    if (!el) return;
    if (i < parts.length) {
      el.textContent = parts[i].text;
      el.style.display = '';
      if (i > 0 && seps[i-1]) $(seps[i-1]).style.display = '';
    } else {
      el.style.display = 'none';
      if (i > 0 && seps[i-1]) $(seps[i-1]).style.display = 'none';
    }
  });
}

function goModules() {
  navStack = [];
  currentInst = null;
  currentPreset = null;
  showPage('page-modules');
  updateBreadcrumb([]);
}

function goValuation() {
  navStack = ['modules'];
  currentInst = null;
  currentPreset = null;
  showPage('page-valuation');
  updateBreadcrumb([{text: 'Valuation'}]);
}

function goBack() {
  if (navStack.length === 0) return;
  const prev = navStack[navStack.length - 1];
  if (prev === 'modules') {
    goModules();
  } else if (prev === 'valuation') {
    goValuation();
  } else {
    goModules();
  }
}

// Module box clicks
document.querySelectorAll('.module-box').forEach(box => {
  box.addEventListener('click', () => {
    if (box.classList.contains('disabled')) return;
    const mod = box.dataset.module;
    if (mod === 'valuation') goValuation();
  });
});

$('logo-home').addEventListener('click', goModules);
$('bc-home').addEventListener('click', goModules);
$('btn-go-back').addEventListener('click', goBack);

function openWorkspace(instType, preset) {
  currentInst = instType;
  currentPreset = preset || null;
  const schema = SCHEMA[instType];
  if (!schema) return;

  showPage('page-workspace');
  navStack = ['modules', 'valuation'];
  updateBreadcrumb([
    {text: 'Valuation'},
    {text: schema.asset},
    {text: preset?._cardLabel || schema.label},
  ]);
  $('ws-trade-title').textContent = (preset?._cardLabel || schema.label) + ' — Trade Inputs';

  // Reset displays
  $('npv-value').textContent = '—';
  $('npv-meta').textContent = 'Configure and click Price';
  $('compare-card').style.display = 'none';
  $('diagnostics').textContent = 'Run a pricing to see diagnostics.';

  // Hide all outputs until Price is clicked
  if ($('ws-outputs')) $('ws-outputs').style.display = 'none';

  // Reset results strip
  if ($('rs-npv')) { $('rs-npv').textContent = '—'; $('rs-npv').style.color = ''; }
  if ($('rs-long-term')) $('rs-long-term').textContent = '—';
  if ($('rs-short-term')) $('rs-short-term').textContent = '—';

  // Check if instrument has grouped layout (from registry or legacy FIELD_GROUPS)
  const instModule = INSTRUMENT_REGISTRY[instType];
  const grouped = instModule?.fieldGroups ||
    (typeof FIELD_GROUPS !== 'undefined' && FIELD_GROUPS[instType]);
  const wsGrouped = $('ws-grouped-fields');
  const wsFlat = $('ws-flat-left');

  // Show mode toggle for instruments that support bulk
  const bulkSupported = instModule?.bulkUpload === true;
  const modeToggle = $('ws-mode-toggle');
  if (modeToggle) modeToggle.style.display = bulkSupported ? '' : 'none';
  setWorkspaceMode('single');

  // Toggle Model & Engine card vs compact action row
  const hideModelEngine = instModule?.hideModelEngine === true;
  const engineCard = $('ws-engine-card');
  const actionRow = $('ws-action-row');
  if (engineCard) engineCard.style.display = hideModelEngine ? 'none' : '';
  if (actionRow) actionRow.style.display = '';  // always show action row

  if (grouped && wsGrouped) {
    // Show grouped layout, hide flat
    wsGrouped.style.display = '';
    if (wsFlat) wsFlat.style.display = 'none';
    buildGroupedFields(instType, grouped);
  } else {
    // Show flat layout, hide grouped
    if (wsGrouped) wsGrouped.style.display = 'none';
    if (wsFlat) wsFlat.style.display = '';
    buildTradeFields(instType);
    buildMarketData(instType, schema);
  }

  if (!hideModelEngine) {
    buildModelEngine(schema);
    renderEngineParams(schema);
  }
  buildGreeks(schema);
  buildOutputPanels(schema);
  buildAnalysis(schema);
}


// ═══════════════════════════════════════════════════════════════════
// BUILD: Grouped Fields (business team 3-column layout)
// ═══════════════════════════════════════════════════════════════════

function buildGroupedFields(instType, config) {
  const container = $('ws-grouped-fields');
  container.innerHTML = '';

  // Apply column count from config (default 3)
  const cols = config.columns || 3;
  container.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;

  // Set default reporting date to today for all date fields that are empty
  const today = new Date().toISOString().slice(0, 10);

  config.groups.forEach(group => {
    const body = document.createElement('div');
    body.className = 'field-group-body';

    if (group.fullWidth && group.layout) {
      const row = document.createElement('div');
      row.className = 'fg-row ' + group.layout;
      group.fields.forEach(f => {
        if (f.sub) return;
        row.appendChild(createGroupedField(f, today));
      });
      body.appendChild(row);
    } else {
      group.fields.forEach(f => {
        if (f.sub) {
          const subTitle = document.createElement('div');
          subTitle.className = 'sub-group-title';
          subTitle.textContent = f.sub;
          body.appendChild(subTitle);
        } else {
          body.appendChild(createGroupedField(f, today));
        }
      });
    }

    let el;
    if (group.collapsible !== false) {
      // ALL groups are collapsible — open by default unless group.collapsed = true
      el = document.createElement('details');
      el.className = 'field-group field-group-collapsible' + (group.fullWidth ? ' full-width' : '');
      if (!group.collapsed) el.open = true;
      const summary = document.createElement('summary');
      summary.textContent = group.label;
      el.appendChild(summary);
      el.appendChild(body);
    } else {
      // Standard group — static header inside card div
      el = document.createElement('div');
      el.className = 'field-group' + (group.fullWidth ? ' full-width' : '');
      const header = document.createElement('div');
      header.className = 'field-group-header';
      header.textContent = group.label;
      el.appendChild(header);
      el.appendChild(body);
    }

    container.appendChild(el);
  });
}

function createGroupedField(f, today) {
  const wrap = document.createElement('div');

  // Handle hint type — display-only text, no input
  if (f.type === 'hint') {
    const hint = document.createElement('div');
    hint.className = 'field-hint';
    hint.id = 'f-' + f.id;
    hint.textContent = f.val || '';
    hint.style.cssText = 'font-size:10px;color:var(--cyan);opacity:0.7;margin-top:-2px;font-style:italic;';
    wrap.appendChild(hint);
    return wrap;
  }

  const lbl = document.createElement('label');
  lbl.textContent = f.label;
  wrap.appendChild(lbl);

  // Apply preset override if available
  const presetVal = currentPreset?.[f.id];
  let val = presetVal !== undefined ? presetVal : f.val;

  // Auto-fill reporting date with today
  if (f.id === 'reporting_date' && !val) val = today;

  let el;
  if (f.type === 'select') {
    el = document.createElement('select');
    (f.opts || []).forEach(o => {
      const opt = document.createElement('option');
      opt.value = o; opt.textContent = o;
      if (o === val) opt.selected = true;
      el.appendChild(opt);
    });
  } else {
    el = document.createElement('input');
    el.type = f.type === 'date' ? 'text' : f.type;
    if (f.type === 'number') el.step = 'any';
    if (f.ph) el.placeholder = f.ph;
    if (f.type === 'date') el.placeholder = 'YYYY-MM-DD';
    if (f.ro) el.readOnly = true;
  }
  el.id = 'f-' + f.id;
  if (val !== undefined && val !== '') el.value = val;

  // Instrument-specific field change handlers (from registry)
  const instModule = INSTRUMENT_REGISTRY[currentInst];
  if (instModule?.onFieldChange) {
    el.addEventListener('change', () => instModule.onFieldChange(f.id));
  }

  wrap.appendChild(el);
  return wrap;
}



// ═══════════════════════════════════════════════════════════════════
// BUILD: Trade Input Fields
// ═══════════════════════════════════════════════════════════════════

function buildTradeFields(instType) {
  const container = $('ws-trade-fields');
  container.innerHTML = '';
  const instModule = INSTRUMENT_REGISTRY[instType];
  const fields = instModule?.flatFields || FIELDS[instType] || [];
  fields.forEach(f => {
    const div = document.createElement('div');
    // Apply preset override if card provided one
    const presetVal = currentPreset?.[f.id];
    const val = presetVal !== undefined ? presetVal : f.val;
    let html = `<label>${f.label}</label>`;
    if (f.type === 'select') {
      html += `<select id="f-${f.id}">${(f.opts||[]).map(o =>
        `<option value="${o}"${o===val?' selected':''}>${o}</option>`).join('')}</select>`;
    } else if (f.type === 'date') {
      html += `<input type="text" id="f-${f.id}" value="${val||''}" placeholder="YYYY-MM-DD"/>`;
    } else {
      html += `<input type="${f.type}" id="f-${f.id}" value="${val??''}" placeholder="${f.ph||''}"/>`;
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
      line: { color: '#0ea5e9', width: 2 } },
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

// ═══════════════════════════════════════════════════════════════════
// PAYLOAD VALIDATION — runs before every API call
// ═══════════════════════════════════════════════════════════════════
function validatePayload(payload) {
  const errors = [];

  const spot = payload?.market_data?.underlyings
    ? Object.values(payload.market_data.underlyings)[0]?.spot
    : null;

  if (spot === null || spot === undefined || isNaN(spot)) {
    errors.push('Spot rate is required.');
  } else if (spot <= 0) {
    errors.push(`Spot rate must be greater than zero (got ${spot}).`);
  }

  // Instrument-level checks
  const params = payload?.instrument?.params || {};

  if (params.strike !== undefined) {
    if (isNaN(params.strike) || params.strike <= 0)
      errors.push(`Strike must be greater than zero (got ${params.strike}).`);
  }
  if (params.notional !== undefined) {
    if (isNaN(params.notional) || params.notional <= 0)
      errors.push(`Notional must be greater than zero (got ${params.notional}).`);
  }

  const rd = payload?.market_data?.rate_curve?.[0]?.rate;
  if (rd !== undefined && (isNaN(rd) || rd < 0))
    errors.push(`Domestic rate cannot be negative (got ${rd}).`);

  const rf = payload?.market_data?.foreign_rate;
  if (rf !== undefined && (isNaN(rf) || rf < 0))
    errors.push(`Foreign rate cannot be negative (got ${rf}).`);

  return errors;
}

function collectPayload() {
  const instType = currentInst;
  const instModule = INSTRUMENT_REGISTRY[instType];
  const grouped = instModule?.fieldGroups ||
    (typeof FIELD_GROUPS !== 'undefined' && FIELD_GROUPS[instType]);
  let params = {};
  const allFields = {};

  if (grouped) {
    // Collect ALL values from grouped fields
    grouped.groups.forEach(group => {
      group.fields.forEach(f => {
        if (f.sub || f.type === 'hint') return;
        const el = $('f-' + f.id);
        if (!el) return;
        let val = el.value;
        if (f.type === 'number') val = parseFloat(val) || 0;
        allFields[f.id] = val;
      });
    });

    // Use instrument-specific payload mapping if available
    if (instModule?.mapPayload) {
      params = instModule.mapPayload(allFields);
    } else {
      // Default: filter out metadata, keep pricing fields
      Object.entries(allFields).forEach(([k, v]) => {
        if (!METADATA_KEYS.has(k)) params[k] = v;
      });
      // Default field name mapping
      if (allFields.notional_1_amount && !params.notional) params.notional = allFields.notional_1_amount;
      if (allFields.notional_1_position && !params.direction) params.direction = allFields.notional_1_position.toLowerCase();
      if (allFields.maturity_date && !params.expiry) params.expiry = allFields.maturity_date;
      if (allFields.maturity_date) params.delivery_date = allFields.maturity_date;
    }
  } else {
    // Collect from flat FIELDS (legacy or instrument-module flatFields)
    const fields = instModule?.flatFields || FIELDS[instType] || [];
    fields.forEach(f => {
      const el = $('f-' + f.id);
      if (!el) return;
      let val = el.value;
      if (f.type === 'number') val = parseFloat(val) || 0;
      params[f.id] = val;
    });
  }

  // Build market data from correct source
  const underlying = params.ccy_pair || params.underlying || params.commodity || 'USD';
  const underlyings = {};

  const spotVal = allFields.spot ?? (($('f-md-spot') || {}).value) ?? 100;
  const volVal = allFields.vol ?? (($('f-md-vol') || {}).value) ?? 0.25;
  const divVal = (($('f-md-div') || {}).value) ?? 0;

  const _pf = (v, def) => { const n = parseFloat(v); return isNaN(n) ? def : n; };

  underlyings[underlying] = {
    spot: _pf(spotVal, 100),
    vol: _pf(volVal, 0.25),
    div_yield: _pf(divVal, 0),
  };

  const rateVal = allFields.rate ?? (($('f-md-rate') || {}).value) ?? 0.065;
  const foreignVal = allFields.foreign_rate ?? (($('f-md-foreign_rate') || {}).value) ?? 0.045;
  const rateCurve = [{ tenor: '1Y', rate: _pf(rateVal, 0.065) }];

  const pricingDate = allFields.reporting_date ||
    (($('f-md-pricing_date') || {}).value) ||
    new Date().toISOString().slice(0, 10);

  // Use instrument-specific API type if different from UI type
  const apiInstType = instModule?.apiType || instType;

  const payload = {
    instrument: { type: apiInstType, params },
    market_data: {
      pricing_date: pricingDate,
      underlyings, rate_curve: rateCurve,
      foreign_rate: _pf(foreignVal, 0.045),
    },
    model: $('f-model')?.value || 'analytical',
    engine: $('f-engine')?.value || 'analytic',
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
  if ($('rs-npv')) $('rs-npv').textContent = '...';
  try {
    const payload = collectPayload();
    const validationErrors = validatePayload(payload);
    if (validationErrors.length) {
      alert('⚠️ Validation Error:\n\n' + validationErrors.join('\n'));
      if ($('rs-npv')) $('rs-npv').textContent = '—';
      return;
    }
    const schema = SCHEMA[currentInst];
    const measures = (schema.sensitivities || []).map(s => s.id);

    const [priceRes, greeksRes] = await Promise.all([
      apiPost('/pricing/single', payload),
      measures.length ? apiPost('/sensitivities/greeks', { ...payload, measures }).catch(() => null) : null,
    ]);

    // Always reveal outputs first — before any processing that could throw
    if ($('ws-outputs')) $('ws-outputs').style.display = 'block';
    if ($('ws-results-strip')) $('ws-results-strip').style.display = 'grid';
    $('diagnostics').textContent = JSON.stringify(priceRes, null, 2);

    const npv = typeof priceRes.npv === 'number' ? priceRes.npv : null;
    const npvFmt = npv !== null
      ? npv.toLocaleString(undefined, { minimumFractionDigits: 4, maximumFractionDigits: 4 })
      : (priceRes.error || 'N/A');

    if ($('npv-value')) $('npv-value').textContent = npv !== null ? '$' + npvFmt : npvFmt;
    if ($('npv-meta')) $('npv-meta').textContent = [priceRes.trade_id, priceRes.model, priceRes.engine, priceRes.elapsed_ms != null ? priceRes.elapsed_ms + 'ms' : ''].filter(Boolean).join(' · ');

    if ($('rs-npv')) {
      $('rs-npv').textContent = npv !== null
        ? npv.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
        : '—';
      $('rs-npv').style.color = npv !== null ? (npv >= 0 ? 'var(--green)' : 'var(--red)') : '';

      const matEl = $('f-maturity_date') || $('f-expiry');
      if (matEl && matEl.value && npv !== null) {
        const monthsToMaturity = (new Date(matEl.value) - new Date()) / (1000 * 60 * 60 * 24 * 30);
        if (monthsToMaturity > 12) {
          if ($('rs-long-term')) $('rs-long-term').textContent = npv.toLocaleString(undefined, { maximumFractionDigits: 2 });
          if ($('rs-short-term')) $('rs-short-term').textContent = '0.00';
        } else {
          if ($('rs-long-term')) $('rs-long-term').textContent = '0.00';
          if ($('rs-short-term')) $('rs-short-term').textContent = npv.toLocaleString(undefined, { maximumFractionDigits: 2 });
        }
      }
    }

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
    console.error('Price error:', e);
    if ($('ws-outputs')) $('ws-outputs').style.display = 'block';
    if ($('ws-results-strip')) $('ws-results-strip').style.display = 'grid';
    if ($('npv-value')) $('npv-value').textContent = 'Error';
    if ($('npv-meta')) $('npv-meta').textContent = e.message;
    if ($('rs-npv')) { $('rs-npv').textContent = 'Error'; $('rs-npv').style.color = 'var(--red)'; }
    $('diagnostics').textContent = 'Error: ' + e.message;
  }
});


// ═══════════════════════════════════════════════════════════════════
// EVENT: Compare Button
// ═══════════════════════════════════════════════════════════════════

$('btn-compare')?.addEventListener('click', async () => {
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

$('btn-export')?.addEventListener('click', async () => {
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
  if ($('ws-outputs')) $('ws-outputs').style.display = 'none';
  if ($('rs-npv')) { $('rs-npv').textContent = '—'; $('rs-npv').style.color = ''; }
  if ($('rs-long-term')) $('rs-long-term').textContent = '—';
  if ($('rs-short-term')) $('rs-short-term').textContent = '—';
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
    // Backend LadderRequest expects instruments (plural), risk_factor, bump_type, bumps[]
    if (payload.instrument && !payload.instruments) {
      payload.instruments = [payload.instrument];
    }
    payload.risk_factor = def.variable;  // "spot", "vol", "rate"
    payload.bump_type = 'relative';

    // Generate bump array from range and steps
    const bumps = [];
    const halfRange = rangePct / 100;
    for (let i = 0; i < steps; i++) {
      bumps.push(-halfRange + (2 * halfRange / (steps - 1)) * i);
    }
    payload.bumps = bumps;

    // Remove fields the backend doesn't expect
    delete payload.variable;
    delete payload.range_pct;
    delete payload.steps;

    const res = await apiPost('/sensitivities/ladder', payload);
    const points = res.results || res.ladder || res.points || [];

    if (points.length) {
      const x = points.map(p => p.bump ?? p.shock ?? p.value ?? p.x);
      const y = points.map(p => p.total_shocked ?? p.npv ?? p.y);
      plotLine(`anal-${key}-chart`, x, y, def.title, def.label, 'NPV');

      // Render table
      const tableDiv = $(`anal-${key}-table`);
      const baseNpv = points[0]?.total_base ?? y[Math.floor(y.length / 2)];
      let thtml = '<table><thead><tr><th>Bump</th><th>NPV</th><th>P&L Impact</th></tr></thead><tbody>';
      points.forEach(p => {
        const bump = p.bump ?? p.shock ?? p.value ?? 0;
        const npv = p.total_shocked ?? p.npv ?? 0;
        const impact = p.total_impact ?? (npv - baseNpv);
        const color = impact >= 0 ? 'var(--green)' : 'var(--red)';
        const bumpLabel = (bump * 100).toFixed(1) + '%';
        thtml += `<tr><td>${bumpLabel}</td><td style="color:var(--accent)">${npv.toLocaleString(undefined, { maximumFractionDigits: 0 })}</td><td style="color:${color}">${impact >= 0 ? '+' : ''}${impact.toLocaleString(undefined, { maximumFractionDigits: 0 })}</td></tr>`;
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
    if (payload.instrument && !payload.instruments) {
      payload.instruments = [payload.instrument];
    }
    // Backend ScenarioRequest expects scenario_name + shocks as List[{risk_factor, shock_type, value}]
    payload.scenario_name = scenDef.key;
    payload.shocks = [];
    if (scenDef.shocks.spot) payload.shocks.push({risk_factor: 'spot', shock_type: 'relative', value: scenDef.shocks.spot});
    if (scenDef.shocks.vol) payload.shocks.push({risk_factor: 'vol', shock_type: 'absolute', value: scenDef.shocks.vol});
    if (scenDef.shocks.rate) payload.shocks.push({risk_factor: 'rate', shock_type: 'absolute', value: scenDef.shocks.rate});
    delete payload.scenario;

    const res = await apiPost('/risk/scenario', payload);

    const baseNpv = res.total_base ?? res.base_npv ?? 0;
    const stressedNpv = res.total_shocked ?? res.stressed_npv ?? res.scenario_npv ?? 0;
    const pnl = res.total_impact ?? (stressedNpv - baseNpv);

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
        const p = { ...payload };
        if (p.instrument && !p.instruments) p.instruments = [p.instrument];
        p.scenario_name = s.key;
        p.shocks = [];
        if (s.shocks.spot) p.shocks.push({risk_factor: 'spot', shock_type: 'relative', value: s.shocks.spot});
        if (s.shocks.vol) p.shocks.push({risk_factor: 'vol', shock_type: 'absolute', value: s.shocks.vol});
        if (s.shocks.rate) p.shocks.push({risk_factor: 'rate', shock_type: 'absolute', value: s.shocks.rate});
        delete p.scenario;
        const res = await apiPost('/risk/scenario', p);
        results.push({ name: s.name, base: res.total_base, stressed: res.total_shocked, pnl: res.total_impact });
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
    if (payload.instrument && !payload.instruments) {
      payload.instruments = [payload.instrument];
    }
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
        { x: tenors, y: zeros.map(v => v * 100), name: 'Zero Rate', line: { color: '#0ea5e9' } },
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

// Module tab clicks
document.querySelectorAll('.mod-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    const tabId = tab.dataset.tab;
    if (tabId === 'valuation') goValuation();
    // Other tabs disabled for now
  });
});

// FX category card clicks (with preset support)
document.querySelectorAll('.fx-card').forEach(card => {
  card.addEventListener('click', () => {
    const inst = card.dataset.inst;
    const presetStr = card.dataset.preset;
    let preset = presetStr ? JSON.parse(presetStr) : null;
    if (preset) preset._cardLabel = card.dataset.label || SCHEMA[inst]?.label;
    else if (card.dataset.label) preset = { _cardLabel: card.dataset.label };
    openWorkspace(inst, preset);
  });
});

// Generic inst-card clicks (for rates, equity, commodity, credit sections)
document.querySelectorAll('.inst-card').forEach(card => {
  card.addEventListener('click', () => openWorkspace(card.dataset.inst));
});

checkHealth();

// URL param support: ?inst=vanilla_option or ?inst=fx_option&preset={"option_type":"call","direction":"buy"}
const urlInst = new URLSearchParams(window.location.search).get('inst');
const urlPreset = new URLSearchParams(window.location.search).get('preset');
if (urlInst && SCHEMA[urlInst]) {
  let preset = null;
  try { preset = urlPreset ? JSON.parse(urlPreset) : null; } catch {}
  openWorkspace(urlInst, preset);
}