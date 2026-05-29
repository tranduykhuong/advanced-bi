"""Shared APTIAD CSV column mappings and helpers."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

# Normalize raw CSV headers (strip whitespace/newlines) → stage snake_case columns.
COLUMN_RENAME_MAP: dict[str, str] = {
    "No.": "aptiad_no",
    "Title": "title",
    "Members": "members_raw",
    "Status": "status",
    "Scope": "scope",
    "Type": "agreement_type",
    "Upgraded": "upgraded",
    "Upgraded Status": "upgraded_status",
    "Year of Signature (Upgraded)": "year_signature_upgraded",
    "Year of Enforcement/Termination (Upgraded)": "year_enforcement_upgraded",
    "Trade in Goods": "trade_in_goods",
    "Year of Signature (Goods)": "year_signature_goods",
    "Year of Enforcement/ Termination (Goods)": "year_enforcement_goods",
    "WTO Notification (Goods)": "wto_notification_goods",
    "WTO Notification Link": "wto_notification_link_goods",
    "WTO Notification Year (Goods)": "wto_notification_year_goods",
    "WTO Consideration Process (Goods)": "wto_consideration_goods",
    "SPS/TBT": "sps_tbt",
    "Anti-Dumping Duty": "anti_dumping_duty",
    "Safeguard": "safeguard",
    "Trade in Services": "trade_in_services",
    "Year of Signature (Services)": "year_signature_services",
    "Year of Enforcement/ Termination (Services)": "year_enforcement_services",
    "WTO Notification (Services)": "wto_notification_services",
    "WTO Notification Year (Services)": "wto_notification_year_services",
    "WTO Consideration Process (Services)": "wto_consideration_services",
    "Liberalization Approach (Services)": "liberalization_services",
    "Investment": "investment",
    "Year of Signature (Investment)": "year_signature_investment",
    "Year of Enforcement/ Termination (Investment)": "year_enforcement_investment",
    "Liberatlization approach (Investment)": "liberalization_investment",
    "BIT (Source UNCTAD)": "bit_unctad",
    "Trade Facilitation & Customs Cooperation": "trade_facilitation",
    "Government Procurement": "gov_procurement",
    "Competition Policy": "competition_policy",
    "Intellectual Property": "intellectual_property",
    "Dispute Settlement": "dispute_settlement",
    "Temporary Movement of Natural Persons": "movement_natural_persons",
    "Sustainable Development Related Provisions": "sd_related",
    "Sustainable Development by Concept": "sd_by_concept",
    "Labour protection": "labour",
    "Human Rights": "human_rights",
    "Gender": "gender",
    "Health": "health",
    "Environment": "environment",
    "SMEs": "smes",
    "Technical Cooperation": "technical_cooperation",
    "Transparency": "transparency",
    "Financial Services": "financial_services",
    "Telecommunications": "telecommunications",
    "E-commerce": "ecommerce",
    "Online Consumer Protection (in E-commerce Chapter)": "ecommerce_consumer_protection",
    "Personal Data Protection (in E-commerce Chapter)": "ecommerce_personal_data",
    "Data flows (in E-commerce Chapter)": "ecommerce_data_flows",
    "Link to website": "link_website",
}

STAGE_DATA_COLUMNS: list[str] = list(COLUMN_RENAME_MAP.values())

STAGE_LOAD_COLUMNS: list[str] = [
    *STAGE_DATA_COLUMNS,
    "source_file",
    "snapshot_date",
    "batch_id",
]

SNAPSHOT_FILENAME_RE = re.compile(
    r"APTIAD_(\d{2})\.(\d{2})\.(\d{4})\.csv$",
    re.IGNORECASE,
)


def normalize_header(name: str) -> str:
    """Collapse whitespace/newlines in CSV headers for lookup."""
    return " ".join(str(name).replace("\n", " ").split())


def build_rename_map(raw_columns: list[str]) -> dict[str, str]:
    """Map actual CSV column names to stage snake_case names."""
    rename: dict[str, str] = {}
    for col in raw_columns:
        normalized = normalize_header(col)
        if normalized in COLUMN_RENAME_MAP:
            rename[col] = COLUMN_RENAME_MAP[normalized]
        else:
            raise ValueError(f"Unmapped APTIAD column: {col!r} (normalized: {normalized!r})")
    return rename


def parse_snapshot_date(filename: str) -> date | None:
    """Parse snapshot date from APTIAD_DD.MM.YYYY.csv filename."""
    match = SNAPSHOT_FILENAME_RE.search(filename)
    if not match:
        return None
    day, month, year = (int(match.group(i)) for i in range(1, 4))
    return date(year, month, day)
