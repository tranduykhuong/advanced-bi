"""NDS → DDS ETL  (SCD Type 1 & Type 2).

Loads data from the Normalized Data Store (NDS) into the Dimensional Data Store
(DDS) star schema in strict FK-dependency order:

  Step 1:  dds.dim_time          — monthly calendar dimension
  Step 2:  dds.dim_currency      — seed VND / USD (idempotent)
  Step 3:  dds.dim_country       — SCD Type 2 (expire + insert new version)
  Step 4:  dds.dim_product       — SCD Type 1 (overwrite + version counter)
  Step 5:  dds.dim_fta           — SCD Type 1 (overwrite + version counter)
  Step 6:  dds.dim_fta_country   — bridge: FTA × member country (delete + re-insert)
  Step 7:  dds.fact_exchange_rate — daily rate fact (upsert)
  Step 8:  dds.fact_trade_transaction — central star fact (upsert + pre-compute VND)

Load modes:
  • Full   — batch_id is None: process all NDS rows (safe re-run).
  • Delta  — batch_id provided: process only rows with that batch_id in NDS.

Exit codes (via run_module shim):
  0  success
  1  unhandled exception
  2  not implemented  (removed — this module is now fully implemented)
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _batch_and(full_sync: bool, alias: str = "") -> str:
    """Return SQL fragment ``<alias.>batch_id = :batch_id AND `` or '' for full."""
    if full_sync:
        return ""
    prefix = f"{alias}." if alias else ""
    return f"{prefix}batch_id = :batch_id AND "


def _params(full_sync: bool, batch_id: uuid.UUID | None) -> dict:
    return {} if full_sync else {"batch_id": str(batch_id)}


# ---------------------------------------------------------------------------
# Step 1 — dds.dim_time
# ---------------------------------------------------------------------------
_SQL_UPSERT_DIM_TIME = text("""
    INSERT INTO dds.dim_time (time_key, year, quarter, month)
    SELECT
        t.year * 100 + t.month   AS time_key,
        t.year,
        t.quarter,
        t.month
    FROM nds.time t
    ON CONFLICT (year, month) DO NOTHING
""")


def _load_dim_time(engine) -> int:
    with engine.begin() as conn:
        r = conn.execute(_SQL_UPSERT_DIM_TIME)
    logger.info("Step 1:  dim_time — inserted %d new rows", r.rowcount)
    return r.rowcount


# ---------------------------------------------------------------------------
# Step 2 — dds.dim_currency  (idempotent seed)
# ---------------------------------------------------------------------------
_CURRENCY_SEED = [
    {"currency_code": "VND", "currency_name": "Vietnamese Dong"},
    {"currency_code": "USD", "currency_name": "United States Dollar"},
]

_SQL_SEED_DIM_CURRENCY = text("""
    INSERT INTO dds.dim_currency (currency_code, currency_name)
    VALUES (:currency_code, :currency_name)
    ON CONFLICT (currency_code) DO NOTHING
""")


def _load_dim_currency(engine) -> int:
    with engine.begin() as conn:
        r = conn.execute(_SQL_SEED_DIM_CURRENCY, _CURRENCY_SEED)
    logger.info("Step 2:  dim_currency — seeded %d rows (VND/USD)", r.rowcount)
    return r.rowcount


# ---------------------------------------------------------------------------
# Step 3 — dds.dim_country  (SCD Type 2)
# Logic:
#   1. Find NDS countries not yet in DDS → INSERT (version=1, is_current=TRUE)
#   2. Find NDS countries whose attrs differ from current DDS row →
#        a. UPDATE old row: is_current=FALSE, valid_to=TODAY
#        b. INSERT new row: version=old+1, is_current=TRUE
#   3. Unchanged rows → no-op
# ---------------------------------------------------------------------------
_SQL_INSERT_NEW_COUNTRIES = text("""
    INSERT INTO dds.dim_country
        (country_code, country_name, continent, region,
         is_current, version, valid_from, valid_to, batch_id)
    SELECT
        n.country_code,
        n.country_name,
        n.continent,
        n.region,
        TRUE,
        1,
        CURRENT_DATE,
        '9999-12-31',
        :batch_id
    FROM nds.country n
    WHERE NOT EXISTS (
        SELECT 1 FROM dds.dim_country d
        WHERE d.country_code = n.country_code
    )
    ON CONFLICT DO NOTHING
""")

_SQL_FIND_CHANGED_COUNTRIES = text("""
    SELECT
        d.country_key,
        d.version,
        n.country_code,
        n.country_name,
        n.continent,
        n.region
    FROM nds.country n
    JOIN dds.dim_country d
        ON d.country_code = n.country_code
       AND d.is_current = TRUE
    WHERE
        COALESCE(n.country_name, '') <> COALESCE(d.country_name, '')
     OR COALESCE(n.continent,    '') <> COALESCE(d.continent,    '')
     OR COALESCE(n.region,       '') <> COALESCE(d.region,       '')
""")

_SQL_EXPIRE_COUNTRY = text("""
    UPDATE dds.dim_country
    SET is_current = FALSE,
        valid_to   = CURRENT_DATE - INTERVAL '1 day'
    WHERE country_key = :country_key
""")

_SQL_INSERT_COUNTRY_VERSION = text("""
    INSERT INTO dds.dim_country
        (country_code, country_name, continent, region,
         is_current, version, valid_from, valid_to, batch_id)
    VALUES
        (:country_code, :country_name, :continent, :region,
         TRUE, :version, CURRENT_DATE, '9999-12-31', :batch_id)
""")


def _load_dim_country(engine, batch_id: uuid.UUID | None) -> int:
    batch_id_str = str(batch_id) if batch_id else str(uuid.uuid4())

    # --- New countries (not yet in DDS) ---
    with engine.begin() as conn:
        r_new = conn.execute(_SQL_INSERT_NEW_COUNTRIES, {"batch_id": batch_id_str})
    logger.info("Step 3:  dim_country — inserted %d new countries", r_new.rowcount)

    # --- Changed countries (SCD2 expire + new version) ---
    with engine.connect() as conn:
        changed = conn.execute(_SQL_FIND_CHANGED_COUNTRIES).fetchall()

    updated = 0
    for row in changed:
        with engine.begin() as conn:
            conn.execute(_SQL_EXPIRE_COUNTRY, {"country_key": row.country_key})
            conn.execute(_SQL_INSERT_COUNTRY_VERSION, {
                "country_code": row.country_code,
                "country_name": row.country_name,
                "continent":    row.continent,
                "region":       row.region,
                "version":      row.version + 1,
                "batch_id":     batch_id_str,
            })
        updated += 1

    logger.info("Step 3:  dim_country — SCD2 expired+versioned %d countries", updated)
    return r_new.rowcount + updated


# ---------------------------------------------------------------------------
# Step 4 — dds.dim_product  (SCD Type 1)
# Overwrite attributes; increment version when anything changed.
# ---------------------------------------------------------------------------
_SQL_UPSERT_DIM_PRODUCT = text("""
    INSERT INTO dds.dim_product
        (hs_code, hs_version, hs_chapter, chapter_name, heading_name,
         product_name, is_current, version, batch_id)
    SELECT
        p.hs_code,
        p.hs_version,
        p.hs_chapter,
        p.category_chapter  AS chapter_name,
        p.category_heading  AS heading_name,
        p.product_name,
        TRUE,
        1,
        :batch_id
    FROM nds.product p
    ON CONFLICT (hs_code, hs_version) DO UPDATE SET
        hs_chapter   = EXCLUDED.hs_chapter,
        chapter_name = EXCLUDED.chapter_name,
        heading_name = EXCLUDED.heading_name,
        product_name = EXCLUDED.product_name,
        version      = CASE
            WHEN dds.dim_product.chapter_name IS DISTINCT FROM EXCLUDED.chapter_name
              OR dds.dim_product.heading_name IS DISTINCT FROM EXCLUDED.heading_name
              OR dds.dim_product.product_name IS DISTINCT FROM EXCLUDED.product_name
            THEN dds.dim_product.version + 1
            ELSE dds.dim_product.version
        END,
        updated_at   = NOW(),
        batch_id     = EXCLUDED.batch_id
""")


def _load_dim_product(engine, batch_id: uuid.UUID | None) -> int:
    batch_id_str = str(batch_id) if batch_id else str(uuid.uuid4())
    with engine.begin() as conn:
        r = conn.execute(_SQL_UPSERT_DIM_PRODUCT, {"batch_id": batch_id_str})
    logger.info("Step 4:  dim_product — upserted %d rows", r.rowcount)
    return r.rowcount


# ---------------------------------------------------------------------------
# Step 5 — dds.dim_fta  (SCD Type 1)
# ---------------------------------------------------------------------------
_SQL_UPSERT_DIM_FTA = text("""
    INSERT INTO dds.dim_fta
        (fta_bk, fta_name, fta_code, agreement_type, scope,
         enforcement_year, status, is_current, version, batch_id)
    SELECT
        f.fta_id                            AS fta_bk,
        f.fta_name,
        f.aptiad_no::TEXT                   AS fta_code,
        f.agreement_type,
        f.scope,
        f.enforcement_year,
        f.status,
        TRUE,
        1,
        :batch_id
    FROM nds.fta f
    ON CONFLICT (fta_bk) DO UPDATE SET
        fta_name         = EXCLUDED.fta_name,
        fta_code         = EXCLUDED.fta_code,
        agreement_type   = EXCLUDED.agreement_type,
        scope            = EXCLUDED.scope,
        enforcement_year = EXCLUDED.enforcement_year,
        status           = EXCLUDED.status,
        version          = CASE
            WHEN dds.dim_fta.fta_name         IS DISTINCT FROM EXCLUDED.fta_name
              OR dds.dim_fta.agreement_type    IS DISTINCT FROM EXCLUDED.agreement_type
              OR dds.dim_fta.scope             IS DISTINCT FROM EXCLUDED.scope
              OR dds.dim_fta.enforcement_year  IS DISTINCT FROM EXCLUDED.enforcement_year
              OR dds.dim_fta.status            IS DISTINCT FROM EXCLUDED.status
            THEN dds.dim_fta.version + 1
            ELSE dds.dim_fta.version
        END,
        updated_at = NOW(),
        batch_id   = EXCLUDED.batch_id
""")


def _load_dim_fta(engine, batch_id: uuid.UUID | None) -> int:
    batch_id_str = str(batch_id) if batch_id else str(uuid.uuid4())
    with engine.begin() as conn:
        r = conn.execute(_SQL_UPSERT_DIM_FTA, {"batch_id": batch_id_str})
    logger.info("Step 5:  dim_fta — upserted %d rows", r.rowcount)
    return r.rowcount


# ---------------------------------------------------------------------------
# Step 6 — dds.dim_fta_country  (bridge: delete + re-insert)
# Maps nds.fta_member → dds.dim_fta × dds.dim_country (using is_current=TRUE)
# ---------------------------------------------------------------------------
_SQL_FETCH_FTA_MEMBERS = text("""
    SELECT
        df.fta_key,
        dc.country_key
    FROM nds.fta_member fm
    JOIN dds.dim_fta     df ON df.fta_bk      = fm.fta_id
    JOIN dds.dim_country dc ON dc.country_code = fm.country_code
                             AND dc.is_current  = TRUE
""")

_SQL_TRUNCATE_FTA_COUNTRY = text("DELETE FROM dds.dim_fta_country")

_SQL_INSERT_FTA_COUNTRY = text("""
    INSERT INTO dds.dim_fta_country (fta_key, country_key)
    VALUES (:fta_key, :country_key)
    ON CONFLICT DO NOTHING
""")


def _load_dim_fta_country(engine) -> int:
    with engine.connect() as conn:
        rows = conn.execute(_SQL_FETCH_FTA_MEMBERS).fetchall()

    if not rows:
        logger.info("Step 6:  dim_fta_country — no members found, skipped")
        return 0

    records = [{"fta_key": r.fta_key, "country_key": r.country_key} for r in rows]

    with engine.begin() as conn:
        conn.execute(_SQL_TRUNCATE_FTA_COUNTRY)
        r = conn.execute(_SQL_INSERT_FTA_COUNTRY, records)

    logger.info("Step 6:  dim_fta_country — inserted %d bridge rows", r.rowcount)
    return r.rowcount


# ---------------------------------------------------------------------------
# Step 7 — dds.fact_exchange_rate
# Grain: rate_date × base_currency × quote_currency
# Resolves time_key from dim_time and currency_key from dim_currency.
# ---------------------------------------------------------------------------
_SQL_UPSERT_FACT_EXCHANGE_RATE = text("""
    INSERT INTO dds.fact_exchange_rate (
        time_key, base_currency_key, quote_currency_key,
        rate_date, rate_raw, exchange_rate, source_system, batch_id
    )
    SELECT
        dt.time_key,
        dc_base.currency_key   AS base_currency_key,
        dc_quote.currency_key  AS quote_currency_key,
        er.rate_date,
        er.rate                AS rate_raw,
        er.vnd_per_usd         AS exchange_rate,
        er.source_system,
        er.batch_id
    FROM nds.exchange_rate er
    JOIN dds.dim_time dt
        ON dt.year  = EXTRACT(YEAR  FROM er.rate_date)::SMALLINT
       AND dt.month = EXTRACT(MONTH FROM er.rate_date)::SMALLINT
    JOIN dds.dim_currency dc_base
        ON dc_base.currency_code = er.base_currency
    JOIN dds.dim_currency dc_quote
        ON dc_quote.currency_code = er.quote_currency
    ON CONFLICT (rate_date, base_currency_key, quote_currency_key) DO UPDATE SET
        time_key           = EXCLUDED.time_key,
        rate_raw           = EXCLUDED.rate_raw,
        exchange_rate      = EXCLUDED.exchange_rate,
        source_system      = EXCLUDED.source_system,
        batch_id           = EXCLUDED.batch_id
""")


def _load_fact_exchange_rate(engine) -> int:
    with engine.begin() as conn:
        r = conn.execute(_SQL_UPSERT_FACT_EXCHANGE_RATE)
    logger.info("Step 7:  fact_exchange_rate — upserted %d rows", r.rowcount)
    return r.rowcount


# ---------------------------------------------------------------------------
# Step 8 — dds.fact_trade_transaction
# Grain: time_key × product_key × partner_key × flow_type × record_source
# Computes value_vnd using the last available exchange rate in the same month.
# fta_keys: array of dim_fta.fta_key gathered from nds.fta_utilization.
# ---------------------------------------------------------------------------
_SQL_UPSERT_FACT_TRADE = text("""
    WITH
    -- Month-end VND/USD rate for each (year, month)
    monthly_fx AS (
        SELECT
            fer.time_key,
            (ARRAY_AGG(fer.exchange_rate ORDER BY fer.rate_date DESC))[1] AS vnd_per_usd
        FROM dds.fact_exchange_rate fer
        JOIN dds.dim_time dt ON dt.time_key = fer.time_key
        WHERE fer.base_currency_key  = (SELECT currency_key FROM dds.dim_currency WHERE currency_code = 'VND')
          AND fer.quote_currency_key = (SELECT currency_key FROM dds.dim_currency WHERE currency_code = 'USD')
        GROUP BY fer.time_key
    ),
    -- FTA keys per trade_id (aggregated into int[])
    fta_agg AS (
        SELECT
            fu.trade_id,
            ARRAY_AGG(df.fta_key ORDER BY df.fta_key) AS fta_keys
        FROM nds.fta_utilization fu
        JOIN dds.dim_fta df ON df.fta_bk = fu.fta_id
        GROUP BY fu.trade_id
    )
    INSERT INTO dds.fact_trade_transaction (
        time_key, product_key, partner_key,
        fta_keys, flow_type, record_source,
        value, quantity, unit, value_vnd,
        source_system, batch_id
    )
    SELECT
        dt.time_key,
        dp.product_key,
        dc.country_key              AS partner_key,
        fa.fta_keys,
        CASE WHEN tt.flow_type = 'Export' THEN TRUE ELSE FALSE END AS flow_type,
        tt.record_source,
        tt.value,
        tt.quantity,
        tt.unit,
        CASE
            WHEN tt.value IS NOT NULL AND fx.vnd_per_usd IS NOT NULL
            THEN ROUND(tt.value * fx.vnd_per_usd, 2)
        END                         AS value_vnd,
        tt.source_system,
        tt.batch_id
    FROM nds.trade_transaction tt
    JOIN nds.time t
        ON t.time_id = tt.time_id
    JOIN dds.dim_time dt
        ON dt.year  = t.year
       AND dt.month = t.month
    JOIN dds.dim_product dp
        ON dp.hs_code    = tt.hs_code
       AND dp.hs_version = tt.hs_version
    JOIN dds.dim_country dc
        ON dc.country_code = tt.partner_code
       AND dc.is_current   = TRUE
    LEFT JOIN fta_agg fa
        ON fa.trade_id = tt.trade_id
    LEFT JOIN monthly_fx fx
        ON fx.time_key = dt.time_key
    ON CONFLICT (time_key, product_key, partner_key, flow_type, record_source)
    DO UPDATE SET
        fta_keys      = EXCLUDED.fta_keys,
        value         = EXCLUDED.value,
        quantity      = EXCLUDED.quantity,
        unit          = EXCLUDED.unit,
        value_vnd     = EXCLUDED.value_vnd,
        source_system = EXCLUDED.source_system,
        batch_id      = EXCLUDED.batch_id,
        updated_at    = NOW()
""")


def _load_fact_trade(engine) -> int:
    with engine.begin() as conn:
        r = conn.execute(_SQL_UPSERT_FACT_TRADE)
    logger.info("Step 8:  fact_trade_transaction — upserted %d rows", r.rowcount)
    return r.rowcount


# ---------------------------------------------------------------------------
# Sanity check
# ---------------------------------------------------------------------------
def _log_sanity_counts(engine) -> None:
    checks = {
        "dds.dim_time":              "SELECT COUNT(*) FROM dds.dim_time",
        "dds.dim_currency":          "SELECT COUNT(*) FROM dds.dim_currency",
        "dds.dim_country (current)": "SELECT COUNT(*) FROM dds.dim_country WHERE is_current = TRUE",
        "dds.dim_product":           "SELECT COUNT(*) FROM dds.dim_product",
        "dds.dim_fta":               "SELECT COUNT(*) FROM dds.dim_fta",
        "dds.dim_fta_country":       "SELECT COUNT(*) FROM dds.dim_fta_country",
        "dds.fact_exchange_rate":    "SELECT COUNT(*) FROM dds.fact_exchange_rate",
        "dds.fact_trade_transaction": "SELECT COUNT(*) FROM dds.fact_trade_transaction",
    }
    with engine.connect() as conn:
        for label, sql in checks.items():
            try:
                n = conn.execute(text(sql)).scalar()
                logger.info("  %-35s %d rows", label, n)
            except Exception as exc:
                logger.warning("  %-35s check failed: %s", label, exc)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def run(batch_id: uuid.UUID | None = None) -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    log_batch_id: uuid.UUID | None = None

    if managed_batch:
        logger.info("NDS→DDS mode: FULL SYNC")
        log_batch_id = register_batch(engine, "nds_to_dds_scd_full")
    else:
        logger.info("NDS→DDS mode: DELTA (batch_id=%s)", batch_id)

    total = 0
    try:
        total += _load_dim_time(engine)
        total += _load_dim_currency(engine)
        total += _load_dim_country(engine, batch_id)
        total += _load_dim_product(engine, batch_id)
        total += _load_dim_fta(engine, batch_id)
        total += _load_dim_fta_country(engine)
        total += _load_fact_exchange_rate(engine)
        total += _load_fact_trade(engine)

        logger.info("NDS→DDS complete. Total rows affected: %d", total)
        _log_sanity_counts(engine)

    except Exception as exc:
        logger.exception("nds_to_dds_scd failed")
        if log_batch_id:
            complete_batch(engine, log_batch_id, status="FAILED", error_message=str(exc))
        raise

    if log_batch_id:
        complete_batch(engine, log_batch_id, rows_loaded=total)

    return total


if __name__ == "__main__":
    sys.exit(0 if run() >= 0 else 1)
