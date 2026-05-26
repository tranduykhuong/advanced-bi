"""Pydantic response models for the TradeMap-style mock API."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class TradeFlowRecord(BaseModel):
    """Single bilateral trade flow record (mirrors TradeMap export schema)."""

    reporter_code: str = Field(..., description="ISO-3 reporter country code, e.g. 'VNM'")
    reporter_name: str
    partner_code: str = Field(..., description="ISO-3 partner country code, e.g. 'CHN'")
    partner_name: str
    hs_code: str = Field(..., description="HS commodity code (up to 6 digits)")
    hs_description: str
    period_year: int = Field(..., ge=2000, le=2030)
    trade_flow: str = Field(..., description="'Export' or 'Import'")
    trade_value_usd: float = Field(..., description="Trade value in USD")
    quantity: Optional[float] = None
    quantity_unit: Optional[str] = None
    source_system: str = Field(default="TRADEMAP_MOCK")


class TradeFlowPage(BaseModel):
    """Paginated response envelope for trade flow queries."""

    page: int
    page_size: int
    total_records: int
    data: list[TradeFlowRecord]


class CountryMeta(BaseModel):
    iso3_code: str
    iso2_code: str
    country_name: str
    region: str
    is_reporter: bool = True
    is_partner: bool = True


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
