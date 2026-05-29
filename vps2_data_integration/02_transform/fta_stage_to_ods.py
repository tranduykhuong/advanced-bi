"""Transform stage.stage_aptiad rows into typed ODS fta records."""

from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch
from common.chunking import DEFAULT_CHUNK_SIZE

logger = get_logger(__name__)

STATUS_MAP = {
    "entry into force": "Entry into Force",
    "under negotiation": "Under Negotiation",
    "terminated": "Terminated",
    "signed & pending ratification": "Signed & Pending ratification",
    "suspension": "Suspension",
}

SCOPE_MAP = {
    "bilateral": "Bilateral",
    "country - bloc": "Country - Bloc",
    "plurilateral": "Plurilateral",
    "bloc - bloc": "Bloc - Bloc",
}

STAGE_PROVISION_TO_ODS = {
    "sps_tbt": "provision_sps_tbt",
    "anti_dumping_duty": "provision_anti_dumping",
    "safeguard": "provision_safeguard",
    "trade_facilitation": "provision_trade_facilitation",
    "gov_procurement": "provision_gov_procurement",
    "competition_policy": "provision_competition_policy",
    "intellectual_property": "provision_intellectual_property",
    "dispute_settlement": "provision_dispute_settlement",
    "movement_natural_persons": "provision_movement_natural_persons",
    "sd_related": "provision_sd_related",
    "sd_by_concept": "provision_sd_by_concept",
    "labour": "provision_labour",
    "human_rights": "provision_human_rights",
    "gender": "provision_gender",
    "health": "provision_health",
    "environment": "provision_environment",
    "smes": "provision_smes",
    "technical_cooperation": "provision_technical_cooperation",
    "transparency": "provision_transparency",
    "financial_services": "provision_financial_services",
    "telecommunications": "provision_telecommunications",
    "ecommerce": "provision_ecommerce",
    "ecommerce_consumer_protection": "provision_ecommerce_consumer_protection",
    "ecommerce_personal_data": "provision_ecommerce_personal_data",
    "ecommerce_data_flows": "provision_ecommerce_data_flows",
}

EXPECTED_COLS = [
    "aptiad_no",
    "fta_name",
    "member_countries",
    "status",
    "scope",
    "agreement_type",
    "is_upgraded",
    "upgraded_status",
    "year_signature_upgraded",
    "year_enforcement_upgraded",
    "has_trade_goods",
    "year_signature_goods",
    "year_enforcement_goods",
    "wto_notification_goods",
    "wto_notification_link",
    "wto_notification_year_goods",
    "wto_consideration_goods",
    "has_trade_services",
    "year_signature_services",
    "year_enforcement_services",
    "wto_notification_services",
    "wto_notification_year_services",
    "wto_consideration_services",
    "liberalization_services",
    "has_investment",
    "year_signature_investment",
    "year_enforcement_investment",
    "liberalization_investment",
    "bit_unctad",
    *STAGE_PROVISION_TO_ODS.values(),
    "source_link",
    "source_system",
    "snapshot_date",
    "batch_id",
]


def to_bool(val) -> bool | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    v = str(val).strip().lower()
    if v == "yes":
        return True
    if v == "no":
        return False
    return None


def to_year(val) -> int | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    v = str(val).strip()
    if re.fullmatch(r"\d{4}", v):
        return int(v)
    return None


def normalize_label(val, mapping: dict[str, str]) -> str | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    cleaned = " ".join(str(val).split())
    if not cleaned:
        return None
    return mapping.get(cleaned.lower(), cleaned)


def parse_members(members_raw) -> list[str]:
    if members_raw is None or (isinstance(members_raw, float) and pd.isna(members_raw)):
        return []
    parts = [m.strip() for m in str(members_raw).split(";") if m.strip()]
    return list(dict.fromkeys(parts))


def apply_business_rules(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    out = pd.DataFrame()
    out["aptiad_no"] = pd.to_numeric(df["aptiad_no"], errors="coerce").astype("Int64")
    out["fta_name"] = df["title"].astype(str).str.strip().replace({"nan": None, "None": None})
    out["member_countries"] = df["members_raw"].apply(parse_members)
    out["status"] = df["status"].apply(lambda x: normalize_label(x, STATUS_MAP))
    out["scope"] = df["scope"].apply(lambda x: normalize_label(x, SCOPE_MAP))
    out["agreement_type"] = df["agreement_type"].astype(str).str.strip().replace(
        {"nan": None, "None": None}
    )

    out["is_upgraded"] = df["upgraded"].apply(to_bool)
    out["upgraded_status"] = df["upgraded_status"].astype(str).str.strip().replace(
        {"nan": None, "None": None}
    )
    out["year_signature_upgraded"] = df["year_signature_upgraded"].apply(to_year)
    out["year_enforcement_upgraded"] = df["year_enforcement_upgraded"].apply(to_year)

    out["has_trade_goods"] = df["trade_in_goods"].apply(to_bool)
    out["year_signature_goods"] = df["year_signature_goods"].apply(to_year)
    out["year_enforcement_goods"] = df["year_enforcement_goods"].apply(to_year)
    out["wto_notification_goods"] = df["wto_notification_goods"].astype(str).str.strip().replace(
        {"nan": None, "None": None}
    )
    out["wto_notification_link"] = df["wto_notification_link_goods"].astype(str).str.strip().replace(
        {"nan": None, "None": None}
    )
    out["wto_notification_year_goods"] = df["wto_notification_year_goods"].apply(to_year)
    out["wto_consideration_goods"] = df["wto_consideration_goods"].astype(str).str.strip().replace(
        {"nan": None, "None": None}
    )

    out["has_trade_services"] = df["trade_in_services"].apply(to_bool)
    out["year_signature_services"] = df["year_signature_services"].apply(to_year)
    out["year_enforcement_services"] = df["year_enforcement_services"].apply(to_year)
    out["wto_notification_services"] = df["wto_notification_services"].astype(str).str.strip().replace(
        {"nan": None, "None": None}
    )
    out["wto_notification_year_services"] = df["wto_notification_year_services"].apply(to_year)
    out["wto_consideration_services"] = df["wto_consideration_services"].astype(str).str.strip().replace(
        {"nan": None, "None": None}
    )
    out["liberalization_services"] = df["liberalization_services"].astype(str).str.strip().replace(
        {"nan": None, "None": None}
    )

    out["has_investment"] = df["investment"].apply(to_bool)
    out["year_signature_investment"] = df["year_signature_investment"].apply(to_year)
    out["year_enforcement_investment"] = df["year_enforcement_investment"].apply(to_year)
    out["liberalization_investment"] = df["liberalization_investment"].astype(str).str.strip().replace(
        {"nan": None, "None": None}
    )
    out["bit_unctad"] = df["bit_unctad"].astype(str).str.strip().replace({"nan": None, "None": None})

    for stage_col, ods_col in STAGE_PROVISION_TO_ODS.items():
        out[ods_col] = df[stage_col].apply(to_bool)

    out["source_link"] = df["link_website"].astype(str).str.strip().replace(
        {"nan": None, "None": None}
    )
    out["source_system"] = "APTIAD"
    out["snapshot_date"] = df["snapshot_date"]
    out["batch_id"] = df["batch_id"]

    return out[EXPECTED_COLS]


def run(batch_id: uuid.UUID | None = None) -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "fta_stage_to_ods")

    total_rows = 0
    try:
        tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
        input_file = tmp_dir / "fta_stage_extracted.csv"
        if not input_file.exists():
            raise FileNotFoundError(f"Missing file: {input_file}")

        output_file = tmp_dir / "fta_stage_to_ods_transformed.csv"
        if output_file.exists():
            output_file.unlink()

        first_chunk = True
        for chunk in pd.read_csv(input_file, chunksize=DEFAULT_CHUNK_SIZE, low_memory=False):
            chunk = apply_business_rules(chunk)
            chunk.to_csv(
                output_file,
                mode="w" if first_chunk else "a",
                header=first_chunk,
                index=False,
            )
            total_rows += len(chunk)
            first_chunk = False

        logger.info("FTA transform completed: %s rows → %s", total_rows, output_file)

    except Exception as exc:
        logger.exception("fta_stage_to_ods failed")
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=total_rows)

    return total_rows


if __name__ == "__main__":
    run()
