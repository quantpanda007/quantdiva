"""
Report Service — generates professional deal reports using local Ollama LLM.

Calls Ollama at localhost:11434 with structured pricing results,
returns a markdown-formatted report. No data leaves the machine.

Supported report types:
  - fx_forward_portfolio  : bulk FX forward/range forward portfolio summary
  - fx_forward_single     : single deal commentary
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

OLLAMA_URL  = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.1:8b"
TIMEOUT_SEC  = 300   # CPU inference is slower — give it time


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_portfolio_prompt(
    results: List[Dict[str, Any]],
    errors: List[Dict[str, Any]],
    valuation_date: str,
    method: str,
    client_name: str = "",
) -> str:
    """Build prompt for FX forward portfolio report."""

    active   = [r for r in results if r.get("status") != "Expired"]
    expired  = [r for r in results if r.get("status") == "Expired"]
    total_npv   = sum(r.get("npv", 0) for r in active)
    total_lt    = sum(r.get("long_term", 0) for r in active)
    total_st    = sum(r.get("short_term", 0) for r in active)
    total_notional = sum(r.get("notional_1", 0) for r in active)

    # Build deal table for prompt
    deal_lines = []
    for r in active:
        fwd   = r.get("forward_rate")
        npv   = r.get("npv", 0)
        sign  = "+" if npv >= 0 else ""
        deal_lines.append(
            f"  - {r.get('transaction_ref','—')} | "
            f"Client: {r.get('client_name','—')} | "
            f"Cpty: {r.get('cpty_b') or r.get('cpty_a','—')} | "
            f"Notional: USD {r.get('notional_1',0):,.0f} | "
            f"Strike: {r.get('strike',0):.4f} | "
            f"Forward: {round(fwd,4) if fwd else '—'} | "
            f"Maturity: {r.get('maturity_date','—') if not hasattr(r.get('maturity_date'), 'isoformat') else r['maturity_date'].isoformat()} | "
            f"NPV: INR {sign}{npv:,.0f} | "
            f"Direction: {r.get('direction_1','—')}"
        )

    deal_table = "\n".join(deal_lines) if deal_lines else "  No active deals."

    # Counterparty concentration
    cpty_exposure: Dict[str, float] = {}
    for r in active:
        cpty = r.get("cpty_b") or r.get("cpty_a") or "Unknown"
        cpty_exposure[cpty] = cpty_exposure.get(cpty, 0) + r.get("notional_1", 0)

    # Client concentration
    client_exposure: Dict[str, float] = {}
    for r in active:
        cl = r.get("client_name") or "Unknown"
        client_exposure[cl] = client_exposure.get(cl, 0) + r.get("notional_1", 0)

    # Near-maturity deals (within 60 days of valuation date)
    try:
        vd = date.fromisoformat(valuation_date)
        near_maturity = []
        for r in active:
            mat = r.get("maturity_date")
            if mat:
                mat_date = mat if isinstance(mat, date) else date.fromisoformat(str(mat))
                days = (mat_date - vd).days
                if 0 < days <= 60:
                    near_maturity.append(
                        f"{r.get('transaction_ref','—')} ({days} days, "
                        f"NPV INR {r.get('npv',0):,.0f})"
                    )
    except Exception:
        near_maturity = []

    prompt = f"""You are a senior financial analyst at a derivatives advisory firm.
Generate a professional Mark-to-Market (MTM) report for the following FX Forward portfolio.
Use formal financial language. Be concise and precise. Do not make up numbers — use only the data provided.

PORTFOLIO DATA
==============
Client: {client_name or 'Portfolio'}
Valuation Date: {valuation_date}
Pricing Method: {'Curve-based' if method == 'curve' else 'Flat Rate'}
Total Active Deals: {len(active)}
Expired Deals: {len(expired)}
Parse/Pricing Errors: {len(errors)}
Total Notional: USD {total_notional:,.0f}
Total NPV: INR {total_npv:,.0f}
Long Term NPV (>1Y): INR {total_lt:,.0f}
Short Term NPV (<1Y): INR {total_st:,.0f}

DEAL DETAILS
============
{deal_table}

COUNTERPARTY EXPOSURE
=====================
{chr(10).join(f'  {k}: USD {v:,.0f}' for k, v in sorted(cpty_exposure.items(), key=lambda x: -x[1]))}

CLIENT CONCENTRATION
====================
{chr(10).join(f'  {k}: USD {v:,.0f}' for k, v in sorted(client_exposure.items(), key=lambda x: -x[1]))}

NEAR-MATURITY DEALS (within 60 days)
=====================================
{chr(10).join(near_maturity) if near_maturity else '  None'}

IMPORTANT RULES — follow strictly:
- Use ONLY the numbers provided above. Do NOT calculate or infer any values.
- NPV for each deal is given exactly — do not modify or recalculate.
- A "Sell" direction deal with positive NPV means client locked in a strike ABOVE current forward — that is in-the-money for the client.
- Counterparty (Cpty) is the bank on the other side of the trade, not the client.
- Best-performing = highest NPV. Worst-performing = lowest NPV. Use the exact NPV figures given.

Write the report using EXACTLY this structure:

## Portfolio Summary
[2-3 sentences: total deals, notional, aggregate NPV, overall position]

## Key Observations
[4-6 bullet points: largest position by notional, best/worst NPV deal, maturity profile, forward vs strike observation]

## Risk Flags
[3-5 bullet points: counterparty concentration, client concentration, near-maturity deals, any negative NPV positions]

## Deal-by-Deal Commentary
[One line per active deal: ref, direction, NPV with sign, brief explanation]

Keep the total report under 400 words. Use INR for NPV values and USD for notional.
"""
    return prompt


def _build_single_deal_prompt(
    result: Dict[str, Any],
    valuation_date: str,
) -> str:
    """Build prompt for single deal commentary."""
    npv    = result.get("npv", 0)
    fwd    = result.get("forward_rate")
    strike = result.get("strike", 0)
    itm    = (fwd > strike) if fwd else None
    direction = (result.get("direction") or "").lower()

    prompt = f"""You are a senior financial analyst. Write a brief professional deal note for this FX Forward.

DEAL DATA
=========
Reference: {result.get('transaction_ref','—')}
Client: {result.get('client_name','—')}
Currency Pair: {result.get('ccy_pair','USDINR')}
Direction: {direction}
Strike Rate: {strike:.4f}
Forward Rate: {round(fwd,4) if fwd else '—'}
Disc Factor: {result.get('disc_factor','—')}
Notional: USD {result.get('notional',0):,.0f}
Maturity: {result.get('maturity_date','—')}
Valuation Date: {valuation_date}
NPV: INR {npv:,.0f}

Write a deal note using EXACTLY this structure:

## Deal Summary
[1-2 sentences: what this deal is, direction, maturity]

## Valuation
[2-3 sentences: current NPV, whether in-the-money or out-of-the-money, forward vs strike comparison]

## Key Risk
[1-2 sentences: main risk factor for this deal]

Keep it under 150 words. Be precise and professional.
"""
    return prompt


# ---------------------------------------------------------------------------
# Ollama caller
# ---------------------------------------------------------------------------

def _call_ollama(prompt: str) -> str:
    """Call Ollama API and return the generated text."""
    payload = {
        "model":  OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.3,    # low temp = consistent, professional output
            "top_p": 0.9,
            "num_predict": 800,    # max tokens
        },
    }
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=TIMEOUT_SEC)
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", "").strip()
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            "Cannot connect to Ollama. "
            "Make sure Ollama is running: open a terminal and run 'ollama serve'"
        )
    except requests.exceptions.Timeout:
        raise RuntimeError(
            f"Ollama took longer than {TIMEOUT_SEC}s to respond. "
            "Try again — first inference is slower on CPU."
        )
    except Exception as e:
        raise RuntimeError(f"Ollama error: {e}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_portfolio_report(
    results: List[Dict[str, Any]],
    errors: List[Dict[str, Any]],
    valuation_date: str,
    method: str = "flat",
    client_name: str = "",
) -> str:
    """
    Generate a portfolio MTM report from bulk pricing results.
    Returns markdown string.
    """
    if not results:
        raise ValueError("No pricing results to report on.")
    prompt   = _build_portfolio_prompt(results, errors, valuation_date, method, client_name)
    markdown = _call_ollama(prompt)
    return markdown


def generate_single_deal_report(
    result: Dict[str, Any],
    valuation_date: str,
) -> str:
    """
    Generate a single deal note from single pricing result.
    Returns markdown string.
    """
    prompt   = _build_single_deal_prompt(result, valuation_date)
    markdown = _call_ollama(prompt)
    return markdown


def warmup_ollama() -> None:
    """
    Send a tiny request to load the model into memory.
    Call once at startup so first real report is fast.
    """
    try:
        requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL,
            "prompt": "Hi",
            "stream": False,
            "options": {"num_predict": 1},
        }, timeout=60)
    except Exception:
        pass  # silently ignore — warmup is best-effort


def check_ollama_health() -> Dict[str, Any]:
    """Check if Ollama is running and the model is available."""
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=5)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        model_ready = any(OLLAMA_MODEL in m for m in models)
        return {
            "status":      "ok" if model_ready else "model_missing",
            "ollama_url":  OLLAMA_URL,
            "model":       OLLAMA_MODEL,
            "model_ready": model_ready,
            "available_models": models,
        }
    except Exception as e:
        return {
            "status":  "offline",
            "error":   str(e),
            "message": "Run 'ollama serve' to start Ollama",
        }