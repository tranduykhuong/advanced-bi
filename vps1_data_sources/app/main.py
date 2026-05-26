"""
VPS1 — Mock Data Source API
Simulates TradeMap-style trade data endpoints and serves static raw files.

Endpoints:
  GET /health                  — liveness check
  GET /api/trade/flows         — paginated bilateral trade flow records
  GET /api/trade/metadata      — country + HS product dimension lists
  GET /api/files/{filename}    — serve files from /app/raw_data/
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from .models import (
    HealthResponse,
    HsProductMeta,
    CountryMeta,
    MetadataResponse,
    TradeFlowPage,
    TradeFlowRecord,
)

app = FastAPI(
    title="BI DW Mock Source API",
    description="Simulates TradeMap / UN Comtrade data sources for the BI trade analytics DW.",
    version="1.0.0",
)

RAW_DATA_DIR = Path(os.getenv("RAW_DATA_PATH", "/app/raw_data"))

# ---------------------------------------------------------------------------
# Static seed data (realistic enough for integration testing)
# ---------------------------------------------------------------------------

_COUNTRIES: list[CountryMeta] = [
    CountryMeta(iso3_code="VNM", iso2_code="VN", country_name="Viet Nam",     region="South-East Asia"),
    CountryMeta(iso3_code="CHN", iso2_code="CN", country_name="China",         region="East Asia"),
    CountryMeta(iso3_code="USA", iso2_code="US", country_name="United States", region="North America"),
    CountryMeta(iso3_code="JPN", iso2_code="JP", country_name="Japan",         region="East Asia"),
    CountryMeta(iso3_code="DEU", iso2_code="DE", country_name="Germany",       region="Europe"),
    CountryMeta(iso3_code="KOR", iso2_code="KR", country_name="Korea, Rep.",   region="East Asia"),
    CountryMeta(iso3_code="SGP", iso2_code="SG", country_name="Singapore",     region="South-East Asia"),
    CountryMeta(iso3_code="THA", iso2_code="TH", country_name="Thailand",      region="South-East Asia"),
    CountryMeta(iso3_code="MYS", iso2_code="MY", country_name="Malaysia",      region="South-East Asia"),
    CountryMeta(iso3_code="AUS", iso2_code="AU", country_name="Australia",     region="Oceania"),
]

_HS_PRODUCTS: list[HsProductMeta] = [
    HsProductMeta(hs_code="0306", hs_chapter="03", description="Crustaceans"),
    HsProductMeta(hs_code="0902", hs_chapter="09", description="Tea"),
    HsProductMeta(hs_code="2709", hs_chapter="27", description="Petroleum oils, crude"),
    HsProductMeta(hs_code="6104", hs_chapter="61", description="Women's suits, knitted"),
    HsProductMeta(hs_code="8471", hs_chapter="84", description="Automatic data processing machines"),
    HsProductMeta(hs_code="8517", hs_chapter="85", description="Telephone sets; smartphones"),
    HsProductMeta(hs_code="6403", hs_chapter="64", description="Footwear with outer soles of rubber"),
    HsProductMeta(hs_code="4407", hs_chapter="44", description="Wood sawn or chipped lengthwise"),
    HsProductMeta(hs_code="1006", hs_chapter="10", description="Rice"),
    HsProductMeta(hs_code="0901", hs_chapter="09", description="Coffee"),
]

# Generate synthetic trade flow records spanning 2018–2023
_TRADE_FLOWS: list[TradeFlowRecord] = []
import itertools, random  # noqa: E402

random.seed(42)
for year in range(2018, 2024):
    for reporter, partner in itertools.islice(
        itertools.permutations([c.iso3_code for c in _COUNTRIES], 2), 30
    ):
        for product in random.sample(_HS_PRODUCTS, 3):
            reporter_meta = next(c for c in _COUNTRIES if c.iso3_code == reporter)
            partner_meta  = next(c for c in _COUNTRIES if c.iso3_code == partner)
            _TRADE_FLOWS.append(
                TradeFlowRecord(
                    reporter_code=reporter,
                    reporter_name=reporter_meta.country_name,
                    partner_code=partner,
                    partner_name=partner_meta.country_name,
                    hs_code=product.hs_code,
                    hs_description=product.description,
                    period_year=year,
                    trade_flow=random.choice(["Export", "Import"]),
                    trade_value_usd=round(random.uniform(50_000, 50_000_000), 2),
                    quantity=round(random.uniform(100, 100_000), 2),
                    quantity_unit=random.choice(["KG", "NO", "MT"]),
                )
            )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse, tags=["Infrastructure"])
def health_check():
    return HealthResponse(status="ok", service="mock_api", version="1.0.0")


@app.get("/api/trade/flows", response_model=TradeFlowPage, tags=["Trade Data"])
def get_trade_flows(
    reporter: Optional[str] = Query(None, description="Filter by ISO-3 reporter code"),
    partner: Optional[str] = Query(None, description="Filter by ISO-3 partner code"),
    year: Optional[int] = Query(None, description="Filter by reporting year"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    """Return paginated bilateral trade flow records (TradeMap-style)."""
    results = _TRADE_FLOWS

    if reporter:
        results = [r for r in results if r.reporter_code == reporter.upper()]
    if partner:
        results = [r for r in results if r.partner_code == partner.upper()]
    if year:
        results = [r for r in results if r.period_year == year]

    total = len(results)
    start = (page - 1) * page_size
    return TradeFlowPage(
        page=page,
        page_size=page_size,
        total_records=total,
        data=results[start : start + page_size],
    )


@app.get("/api/trade/metadata", response_model=MetadataResponse, tags=["Trade Data"])
def get_metadata():
    """Return dimension metadata: country list and HS product list."""
    return MetadataResponse(countries=_COUNTRIES, hs_products=_HS_PRODUCTS)


@app.get("/api/files/{filename}", tags=["Raw Files"])
def download_raw_file(filename: str):
    """Serve a static raw data file from the raw_data directory."""
    safe_name = Path(filename).name  # prevent path traversal
    file_path = RAW_DATA_DIR / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File '{safe_name}' not found.")
    return FileResponse(path=str(file_path), filename=safe_name)
