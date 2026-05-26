"""
Pydantic response models for the TradeMap-style mock API.
Extend or replace these models to match your actual data source schema.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class TradeFlowRecord(BaseModel):
    reporter_code: str
    reporter_name: str
    partner_code: str
    partner_name: str
    hs_code: str
    hs_description: str
    period_year: int
    trade_flow: str  # "Export" | "Import"
    trade_value_usd: float
    quantity: Optional[float] = None
    quantity_unit: Optional[str] = None
    source_system: str = "TRADEMAP_MOCK"


class TradeFlowPage(BaseModel):
    page: int
    page_size: int
    total_records: int
    data: list[TradeFlowRecord]


class CountryMeta(BaseModel):
    iso3_code: str
    iso2_code: str
    country_name: str
    region: str


class HsProductMeta(BaseModel):
    hs_code: str
    hs_chapter: str
    description: str
    hs_version: str = "HS2017"


class MetadataResponse(BaseModel):
    countries: list[CountryMeta]
    hs_products: list[HsProductMeta]


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
