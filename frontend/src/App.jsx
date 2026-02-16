import { useState, useEffect, useCallback } from "react";

// ─── API CONFIG ───────────────────────────────────────────────────

const API = "http://localhost:8000/api/v1";


async function api(path, opts = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...opts.headers },
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "API error");
  }
  return res.json();
}

// ─── STYLES ───────────────────────────────────────────────────────
const theme = {
  bg: "#0a0e17",
  surface: "#111827",
  surfaceHover: "#1a2332",
  border: "#1e293b",
  borderActive: "#f59e0b",
  text: "#e2e8f0",
  textMuted: "#64748b",
  accent: "#f59e0b",
  accentDim: "#d97706",
  green: "#22c55e",
  red: "#ef4444",
  blue: "#3b82f6",
  purple: "#a78bfa",
  font: "'JetBrains Mono', 'Fira Code', monospace",
  fontDisplay: "'Space Grotesk', sans-serif",
};

// ─── ICON COMPONENTS ──────────────────────────────────────────────
const Icons = {
  Pricer: () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 2v20M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6" />
    </svg>
  ),
  Registry: () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" />
      <rect x="3" y="14" width="7" height="7" /><rect x="14" y="14" width="7" height="7" />
    </svg>
  ),
  ChevronDown: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M6 9l6 6 6-6" />
    </svg>
  ),
  Zap: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
    </svg>
  ),
  Compare: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M18 20V10M12 20V4M6 20v-6" />
    </svg>
  ),
};

// ─── SIDEBAR ──────────────────────────────────────────────────────
function Sidebar({ active, onNav }) {
  const items = [
    { id: "pricer", label: "Pricer", icon: Icons.Pricer },
    { id: "registry", label: "Registry", icon: Icons.Registry },
  ];

  return (
    <div style={{
      width: 220, minHeight: "100vh", background: theme.surface,
      borderRight: `1px solid ${theme.border}`, display: "flex",
      flexDirection: "column", padding: "0",
    }}>
      <div style={{
        padding: "24px 20px", borderBottom: `1px solid ${theme.border}`,
        display: "flex", alignItems: "center", gap: 10,
      }}>
        <div style={{
          width: 32, height: 32, borderRadius: 8,
          background: `linear-gradient(135deg, ${theme.accent}, ${theme.accentDim})`,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontWeight: 800, fontSize: 14, color: theme.bg,
        }}>Q</div>
        <div>
          <div style={{ fontFamily: theme.fontDisplay, fontWeight: 700, fontSize: 15, color: theme.text }}>
            QuantPricer
          </div>
          <div style={{ fontSize: 10, color: theme.textMuted, letterSpacing: 1 }}>v0.2.0</div>
        </div>
      </div>

      <div style={{ padding: "12px 8px", flex: 1 }}>
        {items.map((item) => (
          <button key={item.id} onClick={() => onNav(item.id)} style={{
            width: "100%", display: "flex", alignItems: "center", gap: 10,
            padding: "10px 12px", borderRadius: 8, border: "none", cursor: "pointer",
            marginBottom: 4, transition: "all 0.15s",
            background: active === item.id ? `${theme.accent}15` : "transparent",
            color: active === item.id ? theme.accent : theme.textMuted,
            fontFamily: theme.font, fontSize: 13,
          }}>
            <item.icon />{item.label}
          </button>
        ))}
      </div>

      <div style={{
        padding: "16px 20px", borderTop: `1px solid ${theme.border}`,
        fontSize: 10, color: theme.textMuted, fontFamily: theme.font,
      }}>
        QuantLib Pricing Platform
      </div>
    </div>
  );
}

// ─── FORM FIELD ───────────────────────────────────────────────────
function FormField({ label, children, hint }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label style={{
        display: "block", fontSize: 11, color: theme.textMuted,
        marginBottom: 5, fontFamily: theme.font, textTransform: "uppercase",
        letterSpacing: 0.8,
      }}>{label}</label>
      {children}
      {hint && <div style={{ fontSize: 10, color: theme.textMuted, marginTop: 3 }}>{hint}</div>}
    </div>
  );
}

function Input({ value, onChange, type = "text", placeholder, ...props }) {
  return (
    <input type={type} value={value} onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder} {...props}
      style={{
        width: "100%", padding: "8px 12px", borderRadius: 6,
        border: `1px solid ${theme.border}`, background: theme.bg,
        color: theme.text, fontFamily: theme.font, fontSize: 13,
        outline: "none", boxSizing: "border-box",
        transition: "border-color 0.15s",
      }}
      onFocus={(e) => e.target.style.borderColor = theme.borderActive}
      onBlur={(e) => e.target.style.borderColor = theme.border}
    />
  );
}

function Select({ value, onChange, options }) {
  return (
    <div style={{ position: "relative" }}>
      <select value={value} onChange={(e) => onChange(e.target.value)} style={{
        width: "100%", padding: "8px 12px", borderRadius: 6,
        border: `1px solid ${theme.border}`, background: theme.bg,
        color: theme.text, fontFamily: theme.font, fontSize: 13,
        outline: "none", appearance: "none", cursor: "pointer",
        boxSizing: "border-box",
      }}>
        {options.map((o) => (
          <option key={typeof o === "string" ? o : o.value} value={typeof o === "string" ? o : o.value}>
            {typeof o === "string" ? o : o.label}
          </option>
        ))}
      </select>
      <div style={{
        position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)",
        pointerEvents: "none", color: theme.textMuted,
      }}><Icons.ChevronDown /></div>
    </div>
  );
}

// ─── INSTRUMENT FORM (DYNAMIC) ────────────────────────────────────
const INSTRUMENT_DEFAULTS = {
  vanilla_option: {
    trade_id: "VAN-001", underlying: "AAPL", strike: "185", expiry: "2026-01-15",
    option_type: "call", exercise_type: "european", currency: "USD",
  },
  barrier_option: {
    trade_id: "BAR-001", underlying: "AAPL", strike: "185", expiry: "2026-01-15",
    option_type: "call", barrier_type: "down_out", barrier_level: "160", rebate: "0",
  },
  digital_option: {
    trade_id: "DIG-001", underlying: "AAPL", strike: "185", expiry: "2026-01-15",
    option_type: "call", digital_type: "cash_or_nothing", cash_payoff: "100",
  },
  asian_option: {
    trade_id: "ASIAN-001", underlying: "AAPL", strike: "185", expiry: "2026-01-15",
    option_type: "call", average_type: "arithmetic", strike_type: "fixed",
    averaging_start: "2025-01-15", fixing_frequency: "monthly",
  },
  lookback_option: {
    trade_id: "LB-001", underlying: "AAPL", expiry: "2026-01-15",
    option_type: "call", strike_type: "floating",
  },
};

const FIELD_OPTIONS = {
  option_type: ["call", "put"],
  exercise_type: ["european", "american", "bermudan"],
  barrier_type: ["down_out", "down_in", "up_out", "up_in"],
  digital_type: ["cash_or_nothing", "asset_or_nothing"],
  average_type: ["arithmetic", "geometric"],
  strike_type: ["fixed", "floating"],
  fixing_frequency: ["daily", "weekly", "monthly", "quarterly"],
};

const NUMERIC_FIELDS = new Set([
  "strike", "barrier_level", "rebate", "cash_payoff",
]);

function InstrumentForm({ instType, params, onChange }) {
  const defaults = INSTRUMENT_DEFAULTS[instType] || {};
  const fields = Object.keys(defaults);

  const handleChange = (field, val) => {
    onChange({ ...params, [field]: val });
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 16px" }}>
      {fields.map((f) => (
        <FormField key={f} label={f.replace(/_/g, " ")}>
          {FIELD_OPTIONS[f] ? (
            <Select value={params[f] || defaults[f]} onChange={(v) => handleChange(f, v)}
              options={FIELD_OPTIONS[f]} />
          ) : (
            <Input value={params[f] ?? defaults[f] ?? ""}
              onChange={(v) => handleChange(f, v)}
              type={NUMERIC_FIELDS.has(f) ? "number" : "text"} />
          )}
        </FormField>
      ))}
    </div>
  );
}

// ─── MARKET DATA FORM ─────────────────────────────────────────────
function MarketDataForm({ data, onChange }) {
  const setField = (path, val) => {
    const d = JSON.parse(JSON.stringify(data));
    const keys = path.split(".");
    let obj = d;
    for (let i = 0; i < keys.length - 1; i++) obj = obj[keys[i]];
    obj[keys[keys.length - 1]] = val;
    onChange(d);
  };

  const und = Object.keys(data.underlyings)[0] || "AAPL";
  const undData = data.underlyings[und] || { spot: 185, vol: 0.25, div_yield: 0.005 };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 16px" }}>
      <FormField label="Pricing Date">
        <Input value={data.pricing_date} onChange={(v) => setField("pricing_date", v)} />
      </FormField>
      <FormField label="Risk-Free Rate">
        <Input value={data.rate} onChange={(v) => setField("rate", parseFloat(v) || 0)} type="number" />
      </FormField>
      <FormField label="Spot Price">
        <Input value={undData.spot} onChange={(v) => setField(`underlyings.${und}.spot`, parseFloat(v) || 0)} type="number" />
      </FormField>
      <FormField label="Volatility">
        <Input value={undData.vol} onChange={(v) => setField(`underlyings.${und}.vol`, parseFloat(v) || 0)} type="number" />
      </FormField>
      <FormField label="Dividend Yield">
        <Input value={undData.div_yield} onChange={(v) => setField(`underlyings.${und}.div_yield`, parseFloat(v) || 0)} type="number" />
      </FormField>
    </div>
  );
}

// ─── RESULT DISPLAY ───────────────────────────────────────────────
function ResultCard({ result, loading, error }) {
  if (loading) {
    return (
      <div style={{
        padding: 40, textAlign: "center", color: theme.textMuted,
        fontFamily: theme.font,
      }}>
        <div style={{
          width: 24, height: 24, border: `2px solid ${theme.border}`,
          borderTopColor: theme.accent, borderRadius: "50%",
          animation: "spin 0.8s linear infinite", margin: "0 auto 12px",
        }} />
        Pricing...
        <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{
        padding: "16px 20px", background: `${theme.red}10`,
        border: `1px solid ${theme.red}30`, borderRadius: 8,
        color: theme.red, fontFamily: theme.font, fontSize: 13,
      }}>
        ⚠ {error}
      </div>
    );
  }

  if (!result) return null;

  return (
    <div style={{
      background: theme.surface, borderRadius: 10,
      border: `1px solid ${theme.border}`, overflow: "hidden",
    }}>
      {/* NPV Header */}
      <div style={{
        padding: "24px 28px",
        background: `linear-gradient(135deg, ${theme.accent}08, ${theme.accent}03)`,
        borderBottom: `1px solid ${theme.border}`,
      }}>
        <div style={{ fontSize: 11, color: theme.textMuted, fontFamily: theme.font, marginBottom: 4 }}>
          NET PRESENT VALUE
        </div>
        <div style={{
          fontSize: 36, fontWeight: 700, color: theme.accent,
          fontFamily: theme.fontDisplay, letterSpacing: -1,
        }}>
          ${result.npv?.toFixed(4)}
        </div>
        <div style={{ fontSize: 11, color: theme.textMuted, fontFamily: theme.font, marginTop: 6 }}>
          {result.trade_id} · {result.model} · {result.engine} · {result.elapsed_ms}ms
        </div>
      </div>

      {/* Greeks if present */}
      {result.greeks && (
        <div style={{ padding: "16px 28px" }}>
          <div style={{
            fontSize: 11, color: theme.textMuted, fontFamily: theme.font,
            marginBottom: 12, textTransform: "uppercase", letterSpacing: 1,
          }}>Greeks</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12 }}>
            {Object.entries(result.greeks).map(([name, val]) => (
              <div key={name} style={{
                padding: "10px 12px", background: theme.bg, borderRadius: 6,
                border: `1px solid ${theme.border}`,
              }}>
                <div style={{ fontSize: 10, color: theme.textMuted, textTransform: "uppercase", marginBottom: 4 }}>
                  {name}
                </div>
                <div style={{
                  fontSize: 15, fontWeight: 600, fontFamily: theme.font,
                  color: val === null ? theme.textMuted : (val >= 0 ? theme.green : theme.red),
                }}>
                  {val !== null ? val.toFixed(6) : "N/A"}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Compare results */}
      {result.compareResults && (
        <div style={{ padding: "16px 28px" }}>
          <div style={{
            fontSize: 11, color: theme.textMuted, fontFamily: theme.font,
            marginBottom: 12, textTransform: "uppercase", letterSpacing: 1,
          }}>Engine Comparison</div>
          <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: theme.font, fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${theme.border}` }}>
                {["Engine", "NPV", "Diff (bps)", "Time (ms)"].map((h) => (
                  <th key={h} style={{
                    textAlign: "left", padding: "8px 12px", color: theme.textMuted,
                    fontSize: 10, textTransform: "uppercase",
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.compareResults.map((r, i) => (
                <tr key={i} style={{ borderBottom: `1px solid ${theme.border}15` }}>
                  <td style={{ padding: "8px 12px", color: theme.text }}>{r.engine}</td>
                  <td style={{ padding: "8px 12px", color: theme.accent, fontWeight: 600 }}>
                    {r.npv?.toFixed(6) ?? "FAILED"}
                  </td>
                  <td style={{
                    padding: "8px 12px",
                    color: Math.abs(r.rel_diff_bps || 0) < 1 ? theme.green : theme.red,
                  }}>
                    {r.rel_diff_bps?.toFixed(2) ?? "—"}
                  </td>
                  <td style={{ padding: "8px 12px", color: theme.textMuted }}>
                    {r.elapsed_ms?.toFixed(1)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ─── PRICER PAGE ──────────────────────────────────────────────────
function PricerPage() {
  console.log("PRICE CLICKED");

  const [instType, setInstType] = useState("vanilla_option");
  const [instParams, setInstParams] = useState({ ...INSTRUMENT_DEFAULTS.vanilla_option });
  const [marketData, setMarketData] = useState({
    pricing_date: "2025-01-15",
    underlyings: { AAPL: { spot: 185.0, vol: 0.25, div_yield: 0.005 } },
    rate: 0.045,
  });
  const [model, setModel] = useState("black_scholes");
  const [engine, setEngine] = useState("analytic");
  const [engines, setEngines] = useState([]);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [mode, setMode] = useState("price"); // "price" or "compare"

  // Fetch compatible engines when instrument type changes
  useEffect(() => {
    api("/registry/engines/compatibility").then((compat) => {
      const available = compat[instType] || ["analytic"];
      setEngines(available);
      if (!available.includes(engine)) setEngine(available[0]);
    }).catch(() => setEngines(["analytic"]));
  }, [instType]);

  // Reset params when instrument type changes
  useEffect(() => {
    setInstParams({ ...INSTRUMENT_DEFAULTS[instType] || {} });
    setResult(null);
    setError(null);
  }, [instType]);

  // Sync underlying in market data with instrument params
  useEffect(() => {
    const und = instParams.underlying;
    if (und && !marketData.underlyings[und]) {
      setMarketData((prev) => ({
        ...prev,
        underlyings: { [und]: prev.underlyings[Object.keys(prev.underlyings)[0]] || { spot: 100, vol: 0.2, div_yield: 0 } },
      }));
    }
  }, [instParams.underlying]);

  const buildPayload = () => {
    const params = { ...instParams };
    NUMERIC_FIELDS.forEach((f) => {
      if (f in params) params[f] = parseFloat(params[f]) || 0;
    });
    return {
      instrument: { type: instType, params },
      market_data: marketData,
      model,
      engine,
    };
  };

  const handlePrice = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const payload = buildPayload();

      if (mode === "compare") {
        const res = await api("/pricing/compare", {
          method: "POST",
          body: JSON.stringify({ ...payload, engines: engines }),
        });
        setResult({
          trade_id: res.trade_id,
          npv: res.reference_npv,
          model, engine: res.reference_engine,
          elapsed_ms: 0,
          compareResults: res.results,
        });
      } else {
        const res = await api("/pricing/single", {
          method: "POST",
          body: JSON.stringify(payload),
        });

        // Also fetch Greeks
        let greeks = null;
        try {
          const gRes = await api("/sensitivities/greeks", {
            method: "POST",
            body: JSON.stringify({
              ...payload,
              measures: ["delta", "gamma", "vega", "theta", "rho"],
            }),
          });
          greeks = gRes.greeks;
        } catch {}

        setResult({ ...res, greeks });
      }
    } catch (e) {
      setError(e.message);
    }
    setLoading(false);
  };

  const instTypes = Object.keys(INSTRUMENT_DEFAULTS);

  return (
    <div style={{ maxWidth: 1000, margin: "0 auto" }}>
      {/* Header */}
      <div style={{ marginBottom: 32 }}>
        <h1 style={{
          fontSize: 28, fontWeight: 700, color: theme.text,
          fontFamily: theme.fontDisplay, margin: 0,
        }}>
          Instrument Pricer
        </h1>
        <p style={{ color: theme.textMuted, fontFamily: theme.font, fontSize: 13, margin: "6px 0 0" }}>
          Price any registered instrument with real-time Greeks
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
        {/* Left: Instrument Config */}
        <div>
          {/* Instrument Type Selector */}
          <div style={{
            background: theme.surface, borderRadius: 10,
            border: `1px solid ${theme.border}`, padding: "20px 24px", marginBottom: 16,
          }}>
            <FormField label="Instrument Type">
              <Select value={instType} onChange={setInstType}
                options={instTypes.map((t) => ({ value: t, label: t.replace(/_/g, " ").toUpperCase() }))} />
            </FormField>
            <InstrumentForm instType={instType} params={instParams} onChange={setInstParams} />
          </div>

          {/* Model & Engine */}
          <div style={{
            background: theme.surface, borderRadius: 10,
            border: `1px solid ${theme.border}`, padding: "20px 24px",
          }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
              <FormField label="Model">
                <Select value={model} onChange={setModel}
                  options={["black_scholes", "heston"]} />
              </FormField>
              <FormField label="Engine">
                <Select value={engine} onChange={setEngine}
                  options={engines.length ? engines : ["analytic"]} />
              </FormField>
            </div>
          </div>
        </div>

        {/* Right: Market Data + Actions */}
        <div>
          <div style={{
            background: theme.surface, borderRadius: 10,
            border: `1px solid ${theme.border}`, padding: "20px 24px", marginBottom: 16,
          }}>
            <div style={{
              fontSize: 11, color: theme.textMuted, fontFamily: theme.font,
              textTransform: "uppercase", letterSpacing: 1, marginBottom: 14,
            }}>Market Data</div>
            <MarketDataForm data={marketData} onChange={setMarketData} />
          </div>

          {/* Action Buttons */}
          <div style={{ display: "flex", gap: 10 }}>
            <button onClick={() => { setMode("price"); handlePrice(); }} style={{
              flex: 1, padding: "12px 20px", borderRadius: 8, border: "none",
              background: `linear-gradient(135deg, ${theme.accent}, ${theme.accentDim})`,
              color: theme.bg, fontFamily: theme.font, fontSize: 14, fontWeight: 700,
              cursor: "pointer", display: "flex", alignItems: "center",
              justifyContent: "center", gap: 8, transition: "transform 0.1s",
            }}
              onMouseDown={(e) => e.target.style.transform = "scale(0.98)"}
              onMouseUp={(e) => e.target.style.transform = "scale(1)"}
            >
              <Icons.Zap /> Price
            </button>
            <button onClick={() => { setMode("compare"); handlePrice(); }} style={{
              padding: "12px 20px", borderRadius: 8,
              border: `1px solid ${theme.border}`, background: theme.surface,
              color: theme.text, fontFamily: theme.font, fontSize: 13,
              cursor: "pointer", display: "flex", alignItems: "center",
              gap: 6, transition: "all 0.15s",
            }}>
              <Icons.Compare /> Compare
            </button>
          </div>
        </div>
      </div>

      {/* Results */}
      <div style={{ marginTop: 24 }}>
        <ResultCard result={result} loading={loading} error={error} />
      </div>
    </div>
  );
}

// ─── REGISTRY PAGE ────────────────────────────────────────────────
function RegistryPage() {
  const [instruments, setInstruments] = useState([]);
  const [engines, setEngines] = useState([]);
  const [compat, setCompat] = useState({});
  const [scenarios, setScenarios] = useState([]);
  const [tab, setTab] = useState("engines");

  useEffect(() => {
    api("/registry/instruments").then(setInstruments).catch(() => {});
    api("/registry/engines").then(setEngines).catch(() => {});
    api("/registry/engines/compatibility").then(setCompat).catch(() => {});
    api("/registry/scenarios").then(setScenarios).catch(() => {});
  }, []);

  const tabs = [
    { id: "engines", label: "Engine Compatibility" },
    { id: "instruments", label: "Instruments" },
    { id: "scenarios", label: "Scenarios" },
  ];

  const allEngineTypes = [...new Set(engines.map((e) => e.engine_type))].sort();
  const allInstTypes = Object.keys(compat).sort();

  return (
    <div style={{ maxWidth: 1000, margin: "0 auto" }}>
      <div style={{ marginBottom: 32 }}>
        <h1 style={{
          fontSize: 28, fontWeight: 700, color: theme.text,
          fontFamily: theme.fontDisplay, margin: 0,
        }}>Registry</h1>
        <p style={{ color: theme.textMuted, fontFamily: theme.font, fontSize: 13, margin: "6px 0 0" }}>
          Registered instruments, models, engines, and their compatibility
        </p>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 4, marginBottom: 20 }}>
        {tabs.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            padding: "8px 16px", borderRadius: 6, border: "none", cursor: "pointer",
            fontFamily: theme.font, fontSize: 12,
            background: tab === t.id ? `${theme.accent}20` : "transparent",
            color: tab === t.id ? theme.accent : theme.textMuted,
            transition: "all 0.15s",
          }}>{t.label}</button>
        ))}
      </div>

      {/* Engine Compatibility Matrix */}
      {tab === "engines" && (
        <div style={{
          background: theme.surface, borderRadius: 10,
          border: `1px solid ${theme.border}`, overflow: "hidden",
        }}>
          <table style={{
            width: "100%", borderCollapse: "collapse",
            fontFamily: theme.font, fontSize: 12,
          }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${theme.border}` }}>
                <th style={{
                  textAlign: "left", padding: "12px 16px", color: theme.textMuted,
                  fontSize: 10, textTransform: "uppercase", background: theme.bg,
                }}>Instrument</th>
                {allEngineTypes.map((et) => (
                  <th key={et} style={{
                    textAlign: "center", padding: "12px 8px", color: theme.textMuted,
                    fontSize: 10, textTransform: "uppercase", background: theme.bg,
                  }}>{et.replace(/_/g, " ")}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {allInstTypes.map((it) => (
                <tr key={it} style={{ borderBottom: `1px solid ${theme.border}15` }}>
                  <td style={{
                    padding: "10px 16px", color: theme.text, fontWeight: 600,
                  }}>{it.replace(/_/g, " ")}</td>
                  {allEngineTypes.map((et) => (
                    <td key={et} style={{ textAlign: "center", padding: "10px 8px" }}>
                      <span style={{
                        display: "inline-block", width: 20, height: 20,
                        borderRadius: "50%", lineHeight: "20px", fontSize: 11,
                        background: (compat[it] || []).includes(et) ? `${theme.green}20` : `${theme.red}10`,
                        color: (compat[it] || []).includes(et) ? theme.green : `${theme.red}40`,
                      }}>
                        {(compat[it] || []).includes(et) ? "✓" : "—"}
                      </span>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Instruments List */}
      {tab === "instruments" && (
        <div style={{
          background: theme.surface, borderRadius: 10,
          border: `1px solid ${theme.border}`, overflow: "hidden",
        }}>
          {instruments.map((inst, i) => (
            <div key={inst.type} style={{
              padding: "14px 20px", display: "flex", justifyContent: "space-between",
              alignItems: "center",
              borderBottom: i < instruments.length - 1 ? `1px solid ${theme.border}15` : "none",
            }}>
              <div>
                <div style={{ color: theme.text, fontSize: 14, fontWeight: 600 }}>
                  {inst.type.replace(/_/g, " ").toUpperCase()}
                </div>
                <div style={{ color: theme.textMuted, fontSize: 11 }}>{inst.class_name}</div>
              </div>
              <div style={{
                padding: "4px 10px", borderRadius: 4, fontSize: 10,
                background: `${theme.blue}15`, color: theme.blue,
                fontFamily: theme.font,
              }}>{inst.type}</div>
            </div>
          ))}
        </div>
      )}

      {/* Scenarios List */}
      {tab === "scenarios" && (
        <div style={{
          background: theme.surface, borderRadius: 10,
          border: `1px solid ${theme.border}`, overflow: "hidden",
        }}>
          {scenarios.map((s, i) => (
            <div key={s.key} style={{
              padding: "14px 20px",
              borderBottom: i < scenarios.length - 1 ? `1px solid ${theme.border}15` : "none",
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div style={{ color: theme.text, fontSize: 14, fontWeight: 600 }}>{s.name}</div>
                <div style={{
                  padding: "4px 10px", borderRadius: 4, fontSize: 10,
                  background: `${theme.purple}15`, color: theme.purple,
                  fontFamily: theme.font,
                }}>{s.key}</div>
              </div>
              <div style={{ color: theme.textMuted, fontSize: 12, marginTop: 4 }}>
                {s.shocks.map((sh) =>
                  `${sh.risk_factor} ${sh.shock_type} ${sh.value > 0 ? "+" : ""}${sh.value}`
                ).join(", ")}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── APP ──────────────────────────────────────────────────────────
export default function App() {
  const [page, setPage] = useState("pricer");

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap');
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: ${theme.bg}; color: ${theme.text}; font-family: ${theme.font}; }
        ::selection { background: ${theme.accent}40; }
        input[type="number"]::-webkit-inner-spin-button { opacity: 0.3; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: ${theme.bg}; }
        ::-webkit-scrollbar-thumb { background: ${theme.border}; border-radius: 3px; }
      `}</style>

      <div style={{ display: "flex", minHeight: "100vh" }}>
        <Sidebar active={page} onNav={setPage} />
        <div style={{ flex: 1, padding: "32px 40px", overflowY: "auto" }}>
          {page === "pricer" && <PricerPage />}
          {page === "registry" && <RegistryPage />}
        </div>
      </div>
    </>
  );
}