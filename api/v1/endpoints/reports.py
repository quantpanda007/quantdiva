"""
Reports endpoint — generates AI-powered deal reports via local Ollama LLM.

Endpoints:
  POST /api/v1/reports/generate   — generate portfolio or single deal report
  GET  /api/v1/reports/health     — check Ollama status
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fastapi.responses import Response
from services.report.pdf_report import generate_pdf_report
from services.report.report_service import (
    generate_portfolio_report,
    generate_single_deal_report,
    check_ollama_health,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PortfolioReportRequest(BaseModel):
    results:        List[Dict[str, Any]]
    errors:         List[Dict[str, Any]] = []
    valuation_date: str
    method:         str = "flat"
    client_name:    str = ""
    report_type:    str = "portfolio"   # "portfolio" or "single"


class ReportResponse(BaseModel):
    report_type: str
    markdown:    str
    word_count:  int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/generate", response_model=ReportResponse)
def generate_report(req: PortfolioReportRequest):
    """
    Generate an AI-powered MTM report from pricing results.

    - report_type = "portfolio" : full portfolio summary (bulk results)
    - report_type = "single"    : single deal note (one result in results list)
    """
    # Check Ollama is available before trying
    health = check_ollama_health()
    if health["status"] == "offline":
        raise HTTPException(
            status_code=503,
            detail=(
                "Ollama is not running. "
                "Please start it by running 'ollama serve' in a terminal."
            ),
        )
    if health["status"] == "model_missing":
        raise HTTPException(
            status_code=503,
            detail=(
                f"Model 'llama3.1:8b' is not available. "
                f"Run: ollama pull llama3.1:8b"
            ),
        )

    try:
        if req.report_type == "single":
            if not req.results:
                raise HTTPException(400, "No result provided for single deal report.")
            markdown = generate_single_deal_report(
                result=req.results[0],
                valuation_date=req.valuation_date,
            )
        else:
            markdown = generate_portfolio_report(
                results=req.results,
                errors=req.errors,
                valuation_date=req.valuation_date,
                method=req.method,
                client_name=req.client_name,
            )

        return ReportResponse(
            report_type=req.report_type,
            markdown=markdown,
            word_count=len(markdown.split()),
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {e}")


@router.post("/generate-pdf")
def generate_pdf(req: PortfolioReportRequest):
    """
    Generate a full multi-page PDF report with charts and AI narrative.
    Returns PDF bytes as application/pdf.
    """
    # First generate the narrative
    health = check_ollama_health()
    if health["status"] == "offline":
        raise HTTPException(503, "Ollama is not running. Run 'ollama serve'.")
    if health["status"] == "model_missing":
        raise HTTPException(503, "Model llama3.1:8b not found. Run 'ollama pull llama3.1:8b'.")

    try:
        narrative = generate_portfolio_report(
            results=req.results,
            errors=req.errors,
            valuation_date=req.valuation_date,
            method=req.method,
            client_name=req.client_name,
        )

        pdf_bytes = generate_pdf_report(
            results=req.results,
            errors=req.errors,
            valuation_date=req.valuation_date,
            method=req.method,
            client_name=req.client_name,
            narrative=narrative,
        )

        filename = f"Optima_Report_{req.client_name or 'Portfolio'}_{req.valuation_date}.pdf"
        filename = filename.replace(" ", "_").replace(",", "")

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except RuntimeError as e:
        import traceback
        raise HTTPException(500, f"PDF generation failed: {traceback.format_exc()}")
 


@router.get("/health")
def ollama_health():
    """Check if Ollama is running and the model is ready."""
    return check_ollama_health()
