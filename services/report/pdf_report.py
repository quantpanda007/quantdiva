"""
PDF Report Generator — Optima FX Forward Portfolio Report
Uses fpdf2 (no system dependencies) + Plotly/kaleido for charts.

Pages:
  Page 1 — Cover + Portfolio Summary + AI Narrative
  Page 2 — NPV by Deal + NPV by Counterparty charts
  Page 3 — Maturity Timeline + Deal table
"""

from __future__ import annotations

import os
import re
import tempfile
from datetime import date, datetime
from typing import Any, Dict, List

from fpdf import FPDF


def _s(text) -> str:
    """Sanitize text for fpdf2 latin-1 fonts — replace unsupported chars."""
    return (str(text)
        .replace('—', '-')   # em dash
        .replace('–', '-')   # en dash
        .replace('’', "'")   # right single quote
        .replace('‘', "'")   # left single quote
        .replace('“', '"')   # left double quote
        .replace('”', '"')   # right double quote
        .replace('•', '*')   # bullet
        .replace('₹', 'Rs.') # rupee sign
        .replace(' ', ' ')   # non-breaking space
    )


# ---------------------------------------------------------------------------
# Colour palette (Optima dark theme)
# ---------------------------------------------------------------------------
BG     = (10,  15,  26)
PANEL  = (15,  22,  41)
CARD   = (21,  29,  48)
BORDER = (30,  45,  74)
TEXT   = (226, 232, 240)
MUTED  = (100, 116, 139)
ACCENT = (14,  165, 233)
GREEN  = (16,  185, 129)
RED    = (239, 68,  68)


# ---------------------------------------------------------------------------
# Chart generators (Plotly + kaleido → temp PNG files)
# ---------------------------------------------------------------------------

def _fig_to_tmp(fig) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    fig.write_image(tmp.name, width=720, height=340, scale=2)
    return tmp.name


def _chart_npv_by_deal(results: List[Dict]) -> str:
    import plotly.graph_objects as go
    active = [r for r in results if r.get("status") != "Expired"]
    refs   = [r.get("transaction_ref", r.get("ref", "")) for r in active]
    npvs   = [r.get("npv", 0) for r in active]
    colors = ["#10b981" if n >= 0 else "#ef4444" for n in npvs]
    fig = go.Figure(go.Bar(
        x=refs, y=npvs, marker_color=colors,
        text=[f"Rs.{n:,.0f}" for n in npvs],
        textposition="outside",
        textfont=dict(size=10, color="#e2e8f0"),
    ))
    fig.update_layout(
        title=dict(text="NPV by Deal (INR)", font=dict(color="#e2e8f0", size=14)),
        plot_bgcolor="#0f1629", paper_bgcolor="#0f1629",
        font=dict(color="#94a3b8", size=11),
        xaxis=dict(gridcolor="#1e2d4a", tickangle=-20),
        yaxis=dict(gridcolor="#1e2d4a", tickformat=",.0f"),
        margin=dict(l=70, r=40, t=50, b=80),
    )
    return _fig_to_tmp(fig)


def _chart_npv_by_counterparty(results: List[Dict]) -> str:
    import plotly.graph_objects as go
    active = [r for r in results if r.get("status") != "Expired"]
    cpty_npv: Dict[str, float] = {}
    for r in active:
        cpty = r.get("cpty_b") or r.get("cpty_a") or "Unknown"
        cpty_npv[cpty] = cpty_npv.get(cpty, 0) + r.get("npv", 0)
    cptys  = list(cpty_npv.keys())
    npvs   = [cpty_npv[c] for c in cptys]
    colors = ["#10b981" if n >= 0 else "#ef4444" for n in npvs]
    fig = go.Figure(go.Bar(
        x=cptys, y=npvs, marker_color=colors,
        text=[f"Rs.{n:,.0f}" for n in npvs],
        textposition="outside",
        textfont=dict(size=11, color="#e2e8f0"),
    ))
    fig.update_layout(
        title=dict(text="NPV by Counterparty (INR)", font=dict(color="#e2e8f0", size=14)),
        plot_bgcolor="#0f1629", paper_bgcolor="#0f1629",
        font=dict(color="#94a3b8", size=11),
        xaxis=dict(gridcolor="#1e2d4a"),
        yaxis=dict(gridcolor="#1e2d4a", tickformat=",.0f"),
        margin=dict(l=70, r=40, t=50, b=60),
    )
    return _fig_to_tmp(fig)


def _chart_maturity_timeline(results: List[Dict], valuation_date: str) -> str:
    import plotly.graph_objects as go
    active = [r for r in results if r.get("status") != "Expired"]
    try:
        vd = date.fromisoformat(valuation_date)
    except Exception:
        vd = date.today()
    maturities, refs, npvs = [], [], []
    for r in active:
        mat = r.get("maturity_date") or r.get("maturity")
        if mat:
            try:
                mat_date = mat if isinstance(mat, date) else date.fromisoformat(str(mat))
                maturities.append(str(mat_date))
                refs.append(r.get("transaction_ref", r.get("ref", "")))
                npvs.append(r.get("npv", 0))
            except Exception:
                pass
    colors = ["#10b981" if n >= 0 else "#ef4444" for n in npvs]
    sizes  = [max(12, min(28, abs(n) / 50000)) for n in npvs]
    fig = go.Figure()
    for mat, ref in zip(maturities, refs):
        fig.add_shape(type="line", x0=valuation_date, x1=mat, y0=ref, y1=ref,
                      line=dict(color="#1e2d4a", width=6))
    fig.add_trace(go.Scatter(
        x=maturities, y=refs, mode="markers+text",
        marker=dict(size=sizes, color=colors, line=dict(width=1, color="#0a0f1a")),
        text=[f"Rs.{n:,.0f}" for n in npvs],
        textposition="middle right",
        textfont=dict(size=9, color="#e2e8f0"),
    ))
    fig.add_shape(type="line",
        x0=valuation_date, x1=valuation_date, y0=0, y1=1,
        xref="x", yref="paper",
        line=dict(color="#f59e0b", width=1, dash="dash"),
    )
    fig.add_annotation(
        x=valuation_date, y=1, xref="x", yref="paper",
        text="Valuation Date", showarrow=False,
        font=dict(color="#f59e0b", size=9), yanchor="bottom",
    )
    fig.update_layout(
        title=dict(text="Maturity Timeline", font=dict(color="#e2e8f0", size=14)),
        plot_bgcolor="#0f1629", paper_bgcolor="#0f1629",
        font=dict(color="#94a3b8", size=10),
        xaxis=dict(gridcolor="#1e2d4a", type="date"),
        yaxis=dict(gridcolor="#1e2d4a"),
        margin=dict(l=150, r=80, t=50, b=40),
        height=300,
    )
    return _fig_to_tmp(fig)


# ---------------------------------------------------------------------------
# FPDF subclass
# ---------------------------------------------------------------------------

class OptimaPDF(FPDF):

    def normalize_text(self, text: str) -> str:
        """Override to sanitize unicode before encoding as latin-1."""
        text = (str(text)
            .replace('—', '-')
            .replace('–', '-')
            .replace('’', "'")
            .replace('‘', "'")
            .replace('“', '"')
            .replace('”', '"')
            .replace('•', '*')
            .replace('₹', 'Rs.')
            .replace(' ', ' ')
            .replace('…', '...')
        )
        return super().normalize_text(text)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(*MUTED)
        self.cell(0, 5,
            f"Optima  |  Confidential  |  For Internal Use Only  |  Page {self.page_no()}",
            align="C")

    def bg(self):
        self.set_fill_color(*BG)
        self.rect(0, 0, self.w, self.h, "F")

    def header_band(self, title, subtitle=""):
        self.set_fill_color(*PANEL)
        self.rect(0, 0, self.w, 22, "F")
        self.set_draw_color(*ACCENT)
        self.set_line_width(0.8)
        self.line(0, 22, self.w, 22)
        self.set_xy(12, 7)
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(*ACCENT)
        self.cell(120, 8, title)
        if subtitle:
            self.set_xy(self.w - 85, 10)
            self.set_font("Helvetica", "", 8)
            self.set_text_color(*MUTED)
            self.cell(75, 5, subtitle, align="R")

    def kpi_card(self, x, y, w, h, label, value, vc=TEXT):
        self.set_fill_color(*CARD)
        self.rect(x, y, w, h, "F")
        self.set_draw_color(*BORDER)
        self.set_line_width(0.3)
        self.rect(x, y, w, h, "D")
        self.set_xy(x, y + 2.5)
        self.set_font("Helvetica", "", 6)
        self.set_text_color(*MUTED)
        self.cell(w, 4, label.upper(), align="C")
        self.set_xy(x, y + 7.5)
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*vc)
        self.cell(w, 5, str(value), align="C")

    def section_hdr(self, text):
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*ACCENT)
        self.cell(0, 5, text.upper(), ln=True)
        self.set_draw_color(*ACCENT)
        self.set_line_width(0.3)
        self.line(self.l_margin, self.get_y(), self.l_margin + self.epw, self.get_y())
        self.ln(3)

    def narrative(self, md: str):
        for line in md.split("\n"):
            line = line.strip()
            if not line:
                self.ln(2)
            elif line.startswith("## "):
                self.ln(1)
                self.set_font("Helvetica", "B", 9.5)
                self.set_text_color(*ACCENT)
                self.set_x(self.l_margin)
                self.multi_cell(self.epw, 5, line[3:])
                self.set_draw_color(*BORDER)
                self.set_line_width(0.2)
                self.line(self.l_margin, self.get_y(), self.l_margin + self.epw, self.get_y())
                self.ln(2)
            elif line.startswith(("* ", "- ", "• ")):
                clean = re.sub(r'\*\*(.+?)\*\*', r'\1', line[2:])
                self.set_font("Helvetica", "", 9)
                self.set_text_color(*TEXT)
                x0 = self.l_margin
                self.set_x(x0 + 3)
                self.set_fill_color(*ACCENT)
                self.circle(self.get_x() + 0.5, self.get_y() + 2.8, 0.9, "F")
                self.set_x(x0 + 6)
                self.multi_cell(self.epw - 6, 5, clean)
            else:
                clean = re.sub(r'\*\*(.+?)\*\*', r'\1', line)
                self.set_font("Helvetica", "", 9)
                self.set_text_color(*TEXT)
                self.set_x(self.l_margin)
                self.multi_cell(self.epw, 5, clean)

    def chart_box(self, path, y, h):
        self.set_fill_color(*CARD)
        self.rect(self.l_margin, y, self.epw, h + 2, "F")
        self.set_draw_color(*BORDER)
        self.set_line_width(0.3)
        self.rect(self.l_margin, y, self.epw, h + 2, "D")
        self.image(path, x=self.l_margin + 1, y=y + 1, w=self.epw - 2, h=h)


# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------

def _p1(pdf, client, vd, method, active, total_npv, lt, st, notional, errors, narrative):
    pdf.add_page()
    pdf.bg()

    # Cover header
    pdf.set_fill_color(*PANEL)
    pdf.rect(0, 0, pdf.w, 34, "F")
    pdf.set_draw_color(*ACCENT)
    pdf.set_line_width(0.8)
    pdf.line(0, 34, pdf.w, 34)

    pdf.set_xy(12, 7)
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*ACCENT)
    pdf.cell(0, 9, _s("Optima"))

    pdf.set_xy(12, 17)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 5, _s("Mastering Risk, Empowering Decisions"))

    pdf.set_xy(pdf.w - 88, 8)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*TEXT)
    pdf.cell(78, 6, _s("FX Forward Portfolio — MTM Report"), align="R")

    pdf.set_xy(pdf.w - 88, 15)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(78, 5, f"Generated: {datetime.now().strftime('%d %b %Y  %H:%M')}", align="R")

    # Meta row
    pdf.set_xy(12, 38)
    for label, val in [("Client", client or "Portfolio"),
                       ("Valuation Date", vd),
                       ("Method", "Curve-based" if method == "curve" else "Flat Rate")]:
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*MUTED)
        pdf.cell(25, 5, label + ":")
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(*ACCENT if label == "Method" else TEXT)
        pdf.cell(35, 5, val)

    # KPI strip
    ky = 47
    kh = 18
    kw = (pdf.epw - 5 * 3) / 6
    kx = pdf.l_margin
    npv_c = GREEN if total_npv >= 0 else RED
    sign  = "+" if total_npv >= 0 else ""
    for lbl, val, vc in [
        ("Active Deals",      str(len(active)),              TEXT),
        ("Notional (USD)",    f"{notional:,.0f}",            TEXT),
        ("Aggregate NPV INR", f"{sign}{total_npv:,.0f}",     npv_c),
        ("Long Term >1Y",     f"{lt:,.0f}",                  TEXT),
        ("Short Term <1Y",    f"{st:,.0f}",                  TEXT),
        ("Errors",            str(len(errors)),               RED if errors else GREEN),
    ]:
        pdf.kpi_card(kx, ky, kw, kh, lbl, val, vc)
        kx += kw + 3

    pdf.set_y(ky + kh + 8)
    pdf.section_hdr("AI-Generated Analysis  (Llama 3.1 8B)")
    pdf.narrative(narrative)

    # Disclaimer footer box
    pdf.set_y(-28)
    pdf.set_fill_color(*PANEL)
    pdf.rect(pdf.l_margin, pdf.get_y(), pdf.epw, 12, "F")
    pdf.set_xy(pdf.l_margin + 3, pdf.get_y() + 2)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(pdf.epw - 6, 4, "This report was generated by Optima using a locally-hosted LLM (Llama 3.1 8B). All computations are on-premise. Figures are indicative and for internal use only.")


def _p2(pdf, client, vd, chart_deal, chart_cpty):
    pdf.add_page()
    pdf.bg()
    pdf.header_band("Portfolio Analytics", f"{client or 'Portfolio'}  .  {vd}")
    y = 28
    pdf.chart_box(chart_deal, y, 72)
    y += 78
    pdf.chart_box(chart_cpty, y, 72)


def _p3(pdf, client, vd, chart_tl, results):
    pdf.add_page()
    pdf.bg()
    pdf.header_band("Deal Details", f"{client or 'Portfolio'}  .  {vd}")

    pdf.set_y(28)
    pdf.chart_box(chart_tl, 28, 60)

    pdf.set_y(94)
    pdf.section_hdr("Deal-Level Detail")

    hdrs = ["Ref", "Client", "Cpty", "Ccy", "Strike", "Forward", "Notional", "Maturity", "NPV INR", "Status"]
    cws  = [28, 22, 14, 14, 16, 16, 22, 22, 22, 12]

    # Table header
    pdf.set_fill_color(*PANEL)
    pdf.set_font("Helvetica", "B", 6.5)
    pdf.set_text_color(*ACCENT)
    pdf.set_draw_color(*ACCENT)
    pdf.set_line_width(0.4)
    for h, w in zip(hdrs, cws):
        align = "R" if h not in ("Ref","Client","Cpty","Ccy","Status") else "L"
        pdf.cell(w, 6, h, border="B", align=align)
    pdf.ln()

    active = [r for r in results if r.get("status") != "Expired"]
    for i, r in enumerate(active):
        npv   = r.get("npv", 0)
        fwd   = r.get("forward_rate") or r.get("forward")
        color = GREEN if npv >= 0 else RED
        sign  = "+" if npv >= 0 else ""
        pdf.set_fill_color(*(CARD if i % 2 == 0 else (13, 20, 36)))
        pdf.set_draw_color(*BORDER)
        pdf.set_line_width(0.2)

        row = [
            (r.get("transaction_ref", r.get("ref",""))[:16], "L"),
            (r.get("client_name", r.get("client",""))[:10], "L"),
            ((r.get("cpty_b") or r.get("cpty_a",""))[:8], "L"),
            (r.get("ccy_pair",""), "L"),
            (f"{r.get('strike',0):.4f}", "R"),
            (f"{round(fwd,4) if fwd else '—'}", "R"),
            (f"{r.get('notional_1', r.get('notional',0)):,.0f}", "R"),
            (str(r.get("maturity_date", r.get("maturity",""))), "R"),
            (f"{sign}{npv:,.0f}", "R"),
            (r.get("status","OK"), "L"),
        ]
        for idx, ((val, align), w) in enumerate(zip(row, cws)):
            if idx == 8:
                pdf.set_text_color(*color)
                pdf.set_font("Helvetica", "B", 7)
            else:
                pdf.set_text_color(*TEXT)
                pdf.set_font("Helvetica", "", 7)
            pdf.cell(w, 5.5, val, border="B", align=align, fill=True)
        pdf.ln()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_pdf_report(
    results: List[Dict[str, Any]],
    errors: List[Dict[str, Any]],
    valuation_date: str,
    method: str,
    client_name: str,
    narrative: str,
) -> bytes:
    active         = [r for r in results if r.get("status") != "Expired"]
    total_npv      = sum(r.get("npv", 0) for r in active)
    total_lt       = sum(r.get("long_term", 0) for r in active)
    total_st       = sum(r.get("short_term", 0) for r in active)
    total_notional = sum(r.get("notional_1", r.get("notional", 0)) for r in active)

    c1 = _chart_npv_by_deal(results)
    c2 = _chart_npv_by_counterparty(results)
    c3 = _chart_maturity_timeline(results, valuation_date)

    try:
        pdf = OptimaPDF(orientation="P", unit="mm", format="A4")
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.set_margins(12, 10, 12)

        _p1(pdf, client_name, valuation_date, method,
            active, total_npv, total_lt, total_st, total_notional, errors, narrative)
        _p2(pdf, client_name, valuation_date, c1, c2)
        _p3(pdf, client_name, valuation_date, c3, results)

        return bytes(pdf.output())
    finally:
        for p in [c1, c2, c3]:
            try: os.unlink(p)
            except Exception: pass