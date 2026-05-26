"""
VPS1 — Mock Data Source API
Simulates external trade data sources (TradeMap, UN Comtrade, GSO).

Endpoints to implement:
  GET /health                  — liveness check (already wired)
  GET /api/trade/flows         — paginated bilateral trade flow records
  GET /api/trade/metadata      — country + HS product dimension lists
  GET /api/files/{filename}    — serve files from /app/raw_data/

HOW TO START:
  1. Define your seed data or connect to a real source below.
  2. Implement the body of each TODO endpoint.
  3. Add any extra endpoints your ETL pipeline requires.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from .models import (
    HealthResponse,
    MetadataResponse,
    TradeFlowPage,
)

app = FastAPI(
    title="BI DW Mock Source API",
    description="Simulates TradeMap / UN Comtrade / GSO data sources.",
    version="1.0.0",
)

RAW_DATA_DIR = Path(os.getenv("RAW_DATA_PATH", "/app/raw_data"))


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse, tags=["Infrastructure"])
def health_check():
    return HealthResponse(status="ok", service="mock_api", version="1.0.0")


# ---------------------------------------------------------------------------
# TODO: Implement trade data endpoints
# ---------------------------------------------------------------------------

@app.get("/api/trade/flows", response_model=TradeFlowPage, tags=["Trade Data"])
def get_trade_flows(
    reporter: Optional[str] = Query(None, description="ISO-3 reporter country code"),
    partner:  Optional[str] = Query(None, description="ISO-3 partner country code"),
    year:     Optional[int] = Query(None, description="Reporting year"),
    page:     int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
) -> TradeFlowPage:
    """
    Return paginated bilateral trade flow records.

    TODO:
      - Load data from raw_data/ CSV files or an in-memory seed list.
      - Apply reporter / partner / year filters.
      - Return a TradeFlowPage with correct pagination metadata.
    """
    raise NotImplementedError("TODO: implement get_trade_flows()")


@app.get("/api/trade/metadata", response_model=MetadataResponse, tags=["Trade Data"])
def get_metadata() -> MetadataResponse:
    """
    Return reference dimension lists: countries and HS products.

    TODO:
      - Populate from raw_data/ reference files or a hard-coded seed.
      - Return a MetadataResponse with countries and hs_products lists.
    """
    raise NotImplementedError("TODO: implement get_metadata()")


@app.get("/api/files/{filename}", tags=["Raw Files"])
def download_raw_file(filename: str):
    """
    Serve a static raw data file from the raw_data directory.

    TODO:
      - The path-traversal guard (Path(filename).name) is already a
        good practice; keep it when you implement this.
    """
    safe_name = Path(filename).name
    file_path = RAW_DATA_DIR / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File '{safe_name}' not found.")
    return FileResponse(path=str(file_path), filename=safe_name)
