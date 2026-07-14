"""ODS → NDS ETL.

Loads data from ods.trade_transaction, ods.fta, and ods.exchange_rate into
the normalized NDS tables in strict FK-dependency order:

  1. nds.country          (from trade partners + FTA members)
  2. nds.product          (from trade hs_code)
  3. nds.time             (from trade year/month)
  4. nds.fta              (from ods.fta)
  5. nds.fta_member       (DELETE + INSERT)
  6. nds.trade_transaction (JOIN nds.time for time_id)
  7. nds.fta_utilization  (DELETE + INSERT)
  8. nds.currency         (seed VND + USD; idempotent)
  9. nds.exchange_rate    (from ods.exchange_rate; full or delta)

Load modes:
  • Delta  — batch_id provided (ETL_BATCH_ID / --batch-id): only ODS rows
             with that batch_id are processed.
  • Full   — batch_id is None: all ODS rows are processed (local dev default
             when running ``python run_pipeline.py --phase ods-nds`` alone).

Business rules enforced at this layer (see report section VIII):
  BR01 — value must be > 0.
  BR02 — value must be numeric (non-numeric input is already coerced to NULL
         by stage_to_ods.py; a NULL value here is treated as a BR02 violation).
  BR03 — hs_code must be 2-8 digits.
  BR04 — hs_code/partner_code still NULL after Stage→ODS inference is rejected.
  BR06 — partner_code must be a real ISO-3166-1 alpha-3 code (not just non-null).
  BR08 — FTA utilization only counts when partner AND Vietnam are both members
         of the same FTA (see _sql_insert_fta_util).
Rows violating BR01/02/03/04/06 are excluded from nds.trade_transaction (and
from the nds.country/nds.product master upserts) and logged to
public.reject_records via _log_rejected_trade.
"""

from __future__ import annotations

import ast
import sys
import uuid
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch, log_reject_records
from common.country_resolver import resolve_from_country_name, ALPHA3_TO_META

logger = get_logger(__name__)

# BR03: HS Code must be 2-8 digits.
_HS_CODE_FORMAT_RE = "^[0-9]{2,8}$"


def _invalid_code_condition(alias: str, has_invalid_codes: bool) -> str:
    """SQL boolean fragment: TRUE when <alias>.partner_code is a known-invalid
    (non-ISO-3) code. Returns the literal 'FALSE' when there are none in scope,
    so the :invalid_codes bind parameter is only referenced when needed.
    """
    if not has_invalid_codes:
        return "FALSE"
    prefix = f"{alias}." if alias else ""
    return f"{prefix}partner_code = ANY(CAST(:invalid_codes AS text[]))"


def _batch_and(full_sync: bool, alias: str = "") -> str:
    """SQL fragment: ``batch_id = :batch_id AND `` or empty for full sync."""
    if full_sync:
        return ""
    prefix = f"{alias}." if alias else ""
    return f"{prefix}batch_id = :batch_id AND "


def _sql_params(full_sync: bool, batch_id: uuid.UUID) -> dict:
    return {} if full_sync else {"batch_id": str(batch_id)}


# ---------------------------------------------------------------------------
# BR06 — determine which partner_code values in scope are NOT genuine
# ISO-3166-1 alpha-3 codes (as opposed to merely being non-null).
# ---------------------------------------------------------------------------
def _find_invalid_country_codes(engine, full_sync: bool, params: dict) -> list[str]:
    b = _batch_and(full_sync, alias="o")
    sql = text(f"""
        SELECT DISTINCT o.partner_code
        FROM ods.trade_transaction o
        WHERE {b}o.partner_code IS NOT NULL AND o.partner_code <> ''
    """)
    with engine.connect() as conn:
        codes = [r.partner_code for r in conn.execute(sql, params).fetchall()]

    invalid = sorted({c for c in codes if c.upper() not in ALPHA3_TO_META})
    if invalid:
        logger.warning(
            "BR06: %d partner_code value(s) are not valid ISO-3166-1 alpha-3 "
            "codes and will be rejected: %s",
            len(invalid),
            invalid,
        )
    return invalid


# ---------------------------------------------------------------------------
# SQL builders (delta vs full sync)
# ---------------------------------------------------------------------------
def _sql_upsert_countries_trade(full_sync: bool, has_invalid_codes: bool) -> text:
    b = _batch_and(full_sync)
    invalid_cond = _invalid_code_condition("", has_invalid_codes)
    return text(f"""
        INSERT INTO nds.country (country_code, country_name, continent, region)
        SELECT DISTINCT
            partner_code,
            MODE() WITHIN GROUP (ORDER BY partner_name)      AS country_name,
            MODE() WITHIN GROUP (ORDER BY partner_continent) AS continent,
            MODE() WITHIN GROUP (ORDER BY partner_region)    AS region
        FROM ods.trade_transaction
        WHERE {b}partner_code IS NOT NULL
          AND partner_code <> ''
          AND NOT ({invalid_cond})
        GROUP BY partner_code
        ON CONFLICT (country_code) DO UPDATE SET
            country_name = COALESCE(EXCLUDED.country_name, nds.country.country_name),
            continent    = COALESCE(EXCLUDED.continent,    nds.country.continent),
            region       = COALESCE(EXCLUDED.region,       nds.country.region),
            updated_at   = NOW()
    """)


def _sql_upsert_products(full_sync: bool) -> text:
    b = _batch_and(full_sync)
    return text(f"""
        INSERT INTO nds.product (hs_code, hs_version, chapter_name, heading_name, product_name)
        SELECT DISTINCT ON (hs_code)
            hs_code,
            'HS2017'         AS hs_version,
            chapter_name,
            heading_name,
            product_name
        FROM ods.trade_transaction
        WHERE {b}hs_code IS NOT NULL
          AND hs_code <> ''
          AND hs_code ~ '{_HS_CODE_FORMAT_RE}'
        ORDER BY hs_code, product_name NULLS LAST
        ON CONFLICT (hs_code, hs_version) DO UPDATE SET
            chapter_name = COALESCE(EXCLUDED.chapter_name, nds.product.chapter_name),
            heading_name = COALESCE(EXCLUDED.heading_name, nds.product.heading_name),
            product_name     = COALESCE(EXCLUDED.product_name,     nds.product.product_name),
            updated_at       = NOW()
    """)


def _sql_upsert_time(full_sync: bool) -> text:
    b = _batch_and(full_sync)
    return text(f"""
        INSERT INTO nds.time (year, quarter, month)
        SELECT DISTINCT
            year::SMALLINT,
            quarter::SMALLINT,
            month::SMALLINT
        FROM ods.trade_transaction
        WHERE {b}year  IS NOT NULL
          AND month IS NOT NULL
        ON CONFLICT (year, month) DO NOTHING
    """)


def _sql_upsert_fta(full_sync: bool) -> text:
    b = _batch_and(full_sync, alias="f")
    return text(f"""
        INSERT INTO nds.fta (
            fta_id, aptiad_no, fta_name, status, scope,
            agreement_type, enforcement_year, source_system, batch_id
        )
        SELECT
            fta_id,
            aptiad_no,
            fta_name,
            status,
            scope,
            agreement_type,
            year_enforcement_goods AS enforcement_year,
            source_system,
            batch_id
        FROM ods.fta f
        WHERE {b}TRUE
        ON CONFLICT (fta_id) DO UPDATE SET
            aptiad_no        = EXCLUDED.aptiad_no,
            fta_name         = EXCLUDED.fta_name,
            status           = EXCLUDED.status,
            scope            = EXCLUDED.scope,
            agreement_type   = EXCLUDED.agreement_type,
            enforcement_year = EXCLUDED.enforcement_year,
            source_system    = EXCLUDED.source_system,
            batch_id         = EXCLUDED.batch_id,
            updated_at       = NOW()
    """)


def _sql_upsert_trade(full_sync: bool, has_invalid_codes: bool) -> text:
    b = _batch_and(full_sync, alias="o")
    invalid_cond = _invalid_code_condition("o", has_invalid_codes)
    return text(f"""
        INSERT INTO nds.trade_transaction (
            time_id, hs_code, hs_version, partner_code, flow_type,
            value, quantity, unit, source_system,
            batch_id, is_late_arriving, ods_id
        )
        SELECT
            t.time_id,
            o.hs_code,
            'HS2017',
            o.partner_code,
            CASE WHEN o.flow_type THEN 'Export' ELSE 'Import' END,
            o.value,
            o.quantity,
            o.unit,
            o.source_system,
            o.batch_id,
            COALESCE(o.is_late_arriving, FALSE),
            o.ods_id
        FROM ods.trade_transaction o
        JOIN nds.time t ON t.year = o.year AND t.month = o.month
        WHERE {b}o.partner_code IS NOT NULL          -- BR04/BR06
          AND o.partner_code <> ''                   -- BR04/BR06
          AND NOT ({invalid_cond})                    -- BR06
          AND o.hs_code IS NOT NULL                   -- BR04
          AND o.hs_code <> ''                         -- BR04
          AND o.hs_code ~ '{_HS_CODE_FORMAT_RE}'       -- BR03
          AND o.value IS NOT NULL                     -- BR01/BR02
          AND o.value > 0                              -- BR01
        ON CONFLICT (time_id, hs_code, hs_version, partner_code, flow_type, source_system)
        DO UPDATE SET
            value            = EXCLUDED.value,
            quantity         = EXCLUDED.quantity,
            unit             = EXCLUDED.unit,
            batch_id         = EXCLUDED.batch_id,
            is_late_arriving = EXCLUDED.is_late_arriving,
            ods_id           = EXCLUDED.ods_id,
            updated_at       = NOW()
    """)


def _sql_select_rejected_trade(full_sync: bool, has_invalid_codes: bool) -> text:
    """ods.trade_transaction rows that _sql_upsert_trade's WHERE clause would
    silently exclude. Selected *before* the upsert so they can be logged to
    reject_records for audit. The conditions here MUST mirror the negation of
    _sql_upsert_trade's WHERE clause exactly.

    Covers: BR01 (value > 0), BR02 (value numeric — non-numeric input is
    already coerced to NULL upstream, so a NULL value here is a BR02 case),
    BR03 (hs_code 2-8 digits), BR04 (hs_code/partner_code missing),
    BR06 (partner_code missing or not a valid ISO-3 code).
    """
    b = _batch_and(full_sync, alias="o")
    invalid_cond = _invalid_code_condition("o", has_invalid_codes)
    return text(f"""
        SELECT
            o.ods_id, o.year, o.month, o.hs_code, o.partner_code,
            o.flow_type, o.source_system, o.batch_id, o.value,
            CASE
                WHEN o.hs_code IS NULL OR o.hs_code = ''
                    THEN 'missing_hs_code'
                WHEN o.hs_code !~ '{_HS_CODE_FORMAT_RE}'
                    THEN 'invalid_hs_code_format'
                WHEN o.partner_code IS NULL OR o.partner_code = ''
                    THEN 'missing_partner_code'
                WHEN {invalid_cond}
                    THEN 'invalid_partner_code'
                WHEN o.value IS NULL OR o.value <= 0
                    THEN 'invalid_value'
            END AS reject_reason
        FROM ods.trade_transaction o
        WHERE {b}(
            o.hs_code IS NULL OR o.hs_code = ''
            OR o.hs_code !~ '{_HS_CODE_FORMAT_RE}'
            OR o.partner_code IS NULL OR o.partner_code = ''
            OR {invalid_cond}
            OR o.value IS NULL OR o.value <= 0
        )
    """)


def _log_rejected_trade(
    engine,
    log_batch_id: uuid.UUID,
    full_sync: bool,
    params: dict,
    has_invalid_codes: bool,
) -> int:
    """BR01/BR02/BR03/BR04/BR06: select + log ods.trade_transaction rows that
    violate mandatory business rules — these are excluded from
    nds.trade_transaction by design (see _sql_upsert_trade's WHERE clause).
    """
    with engine.connect() as conn:
        rows = conn.execute(
            _sql_select_rejected_trade(full_sync, has_invalid_codes), params
        ).fetchall()

    if not rows:
        return 0

    by_reason: dict[str, list[dict]] = {}
    for r in rows:
        by_reason.setdefault(r.reject_reason, []).append(
            {
                "ods_id": str(r.ods_id),
                "year": r.year,
                "month": r.month,
                "hs_code": r.hs_code,
                "partner_code": r.partner_code,
                "flow_type": r.flow_type,
                "source_system": r.source_system,
                "value": r.value,
                "batch_id": str(r.batch_id) if r.batch_id else None,
            }
        )

    for reason, reason_rows in by_reason.items():
        log_reject_records(
            engine,
            log_batch_id,
            process_type=2,
            source_table="ods.trade_transaction",
            reject_reason=reason,
            rows=reason_rows,
        )

    logger.warning(
        "Step 6:  %d ods.trade_transaction rows rejected (%s)",
        len(rows),
        ", ".join(f"{k}={len(v)}" for k, v in sorted(by_reason.items())),
    )
    return len(rows)


def _sql_delete_fta_util(full_sync: bool) -> text:
    if full_sync:
        return text("DELETE FROM nds.fta_utilization")
    return text("""
        DELETE FROM nds.fta_utilization fu
        USING nds.trade_transaction tt
        WHERE fu.trade_id = tt.trade_id
          AND tt.batch_id = :batch_id
    """)


def _sql_insert_fta_util(full_sync: bool) -> text:
    b = _batch_and(full_sync, alias="tt")
    return text(f"""
        -- BR08: FTA utilization only counts when the partner AND Vietnam (VNM) are
        -- both members of the same FTA — not just any FTA the partner happens to belong to.
        INSERT INTO nds.fta_utilization (trade_id, fta_id)
        SELECT tt.trade_id, fm.fta_id
        FROM nds.trade_transaction tt
        JOIN nds.fta_member fm ON fm.country_code = tt.partner_code
        JOIN nds.fta_member fm_vn
            ON fm_vn.fta_id = fm.fta_id
           AND fm_vn.country_code = 'VNM'
        WHERE {b}TRUE
        ON CONFLICT DO NOTHING
    """)


# ---------------------------------------------------------------------------
# Step 1b: nds.country — from ods.fta.member_countries (Python resolver)
# ---------------------------------------------------------------------------
def _upsert_countries_from_fta_members(
    engine, batch_id: uuid.UUID | None, *, full_sync: bool
) -> int:
    b = _batch_and(full_sync)
    fetch_sql = text(f"""
        SELECT fta_id, member_countries
        FROM ods.fta
        WHERE {b}member_countries IS NOT NULL
          AND cardinality(member_countries) > 0
    """)
    params = _sql_params(full_sync, batch_id) if batch_id else {}
    with engine.connect() as conn:
        rows = conn.execute(fetch_sql, params).fetchall()

    records: dict[str, dict] = {}
    skipped = 0
    for row in rows:
        raw = row.member_countries
        if isinstance(raw, str):
            try:
                raw = ast.literal_eval(raw)
            except Exception:
                raw = [m.strip() for m in raw.split(";") if m.strip()]
        for member_name in raw or []:
            if not member_name or not str(member_name).strip():
                continue
            iso3, region, continent, _ = resolve_from_country_name(str(member_name))
            if iso3 is None:
                logger.warning("FTA member unresolved: %r — skipping", member_name)
                skipped += 1
                continue
            if iso3 not in records:
                records[iso3] = {
                    "country_code": iso3,
                    "country_name": member_name,
                    "continent": continent,
                    "region": region,
                }

    if not records:
        logger.info("Step 1b: no FTA member countries to upsert (skipped=%d)", skipped)
        return 0

    upsert_sql = text("""
        INSERT INTO nds.country (country_code, country_name, continent, region)
        VALUES (:country_code, :country_name, :continent, :region)
        ON CONFLICT (country_code) DO UPDATE SET
            country_name = COALESCE(EXCLUDED.country_name, nds.country.country_name),
            continent    = COALESCE(EXCLUDED.continent,    nds.country.continent),
            region       = COALESCE(EXCLUDED.region,       nds.country.region),
            updated_at   = NOW()
    """)
    with engine.begin() as conn:
        conn.execute(upsert_sql, list(records.values()))

    logger.info(
        "Step 1b: upserted %d FTA member countries (skipped=%d)", len(records), skipped
    )
    return len(records)


# ---------------------------------------------------------------------------
# Step 5: nds.fta_member — DELETE + re-INSERT resolved members
# ---------------------------------------------------------------------------
def _sync_fta_members(engine, batch_id: uuid.UUID | None, *, full_sync: bool) -> int:
    b = _batch_and(full_sync)
    fetch_sql = text(f"""
        SELECT fta_id, member_countries
        FROM ods.fta
        WHERE {b}member_countries IS NOT NULL
    """)
    params = _sql_params(full_sync, batch_id) if batch_id else {}
    with engine.connect() as conn:
        rows = conn.execute(fetch_sql, params).fetchall()

    if not rows:
        logger.info("Step 5: no FTA members to sync")
        return 0

    fta_ids = [str(row.fta_id) for row in rows]
    if full_sync:
        delete_sql = text("DELETE FROM nds.fta_member")
        with engine.begin() as conn:
            conn.execute(delete_sql)
    else:
        delete_sql = text(
            "DELETE FROM nds.fta_member WHERE fta_id = ANY(CAST(:ids AS uuid[]))"
        )
        with engine.begin() as conn:
            conn.execute(delete_sql, {"ids": fta_ids})

    insert_records: list[dict] = []
    skipped = 0
    for row in rows:
        raw = row.member_countries
        if isinstance(raw, str):
            try:
                raw = ast.literal_eval(raw)
            except Exception:
                raw = [m.strip() for m in raw.split(";") if m.strip()]
        for member_name in raw or []:
            if not member_name or not str(member_name).strip():
                continue
            iso3, _, _, _ = resolve_from_country_name(str(member_name))
            if iso3 is None:
                logger.warning(
                    "fta_member: unresolved country %r for fta_id=%s — skipping",
                    member_name,
                    row.fta_id,
                )
                skipped += 1
                continue
            insert_records.append({"fta_id": str(row.fta_id), "country_code": iso3})

    if insert_records:
        insert_sql = text("""
            INSERT INTO nds.fta_member (fta_id, country_code)
            VALUES (:fta_id, :country_code)
            ON CONFLICT DO NOTHING
        """)
        with engine.begin() as conn:
            conn.execute(insert_sql, insert_records)

    logger.info(
        "Step 5: synced %d fta_member rows (skipped=%d)", len(insert_records), skipped
    )
    return len(insert_records)


# ---------------------------------------------------------------------------
# Steps 8-9: nds.currency seed + nds.exchange_rate upsert
# ---------------------------------------------------------------------------
_CURRENCY_SEED = [
    {"currency_code": "VND", "currency_name": "Vietnamese Dong"},
    {"currency_code": "USD", "currency_name": "United States Dollar"},
]

_SQL_SEED_CURRENCY = text("""
    INSERT INTO nds.currency (currency_code, currency_name)
    VALUES (:currency_code, :currency_name)
    ON CONFLICT (currency_code) DO NOTHING
""")


def _sql_upsert_exchange_rate(full_sync: bool) -> text:
    b = _batch_and(full_sync)
    return text(f"""
        INSERT INTO nds.exchange_rate (
            rate_date, base_currency, quote_currency,
            rate, vnd_per_usd, source_system, batch_id
        )
        SELECT
            rate_date,
            base_currency,
            quote_currency,
            rate,
            vnd_per_usd,
            source_system,
            batch_id
        FROM ods.exchange_rate
        WHERE {b}TRUE
        ON CONFLICT (rate_date, base_currency, quote_currency) DO UPDATE SET
            rate          = EXCLUDED.rate,
            vnd_per_usd   = EXCLUDED.vnd_per_usd,
            source_system = EXCLUDED.source_system,
            batch_id      = EXCLUDED.batch_id,
            updated_at    = NOW()
    """)


def _sync_exchange_rate(engine, batch_id: uuid.UUID | None, *, full_sync: bool) -> int:
    # Seed currency dimension first (idempotent)
    with engine.begin() as conn:
        conn.execute(_SQL_SEED_CURRENCY, _CURRENCY_SEED)

    # Upsert exchange rates from ODS
    params = _sql_params(full_sync, batch_id) if batch_id else {}
    with engine.begin() as conn:
        r = conn.execute(_sql_upsert_exchange_rate(full_sync), params)
    logger.info(
        "Step 8-9: seeded currencies; upserted %d exchange_rate rows", r.rowcount
    )
    return r.rowcount


# ---------------------------------------------------------------------------
# Sanity check after load
# ---------------------------------------------------------------------------
def _log_sanity_counts(engine, batch_id: uuid.UUID | None, *, full_sync: bool) -> None:
    checks: dict[str, str] = {
        "nds.country": "SELECT COUNT(*) FROM nds.country",
        "nds.product": "SELECT COUNT(*) FROM nds.product",
        "nds.time": "SELECT COUNT(*) FROM nds.time",
        "nds.fta": "SELECT COUNT(*) FROM nds.fta",
        "nds.fta_member": "SELECT COUNT(*) FROM nds.fta_member",
        "nds.currency": "SELECT COUNT(*) FROM nds.currency",
        "nds.exchange_rate": "SELECT COUNT(*) FROM nds.exchange_rate",
    }
    if full_sync:
        checks["nds.trade_transaction"] = "SELECT COUNT(*) FROM nds.trade_transaction"
        checks["nds.fta_utilization"] = "SELECT COUNT(*) FROM nds.fta_utilization"
    else:
        checks["nds.trade (batch)"] = (
            "SELECT COUNT(*) FROM nds.trade_transaction WHERE batch_id = :bid"
        )
        checks["nds.fta_util (batch)"] = """
            SELECT COUNT(*) FROM nds.fta_utilization fu
            JOIN nds.trade_transaction tt ON tt.trade_id = fu.trade_id
            WHERE tt.batch_id = :bid
        """

    with engine.connect() as conn:
        for label, sql in checks.items():
            try:
                params = {} if full_sync else {"bid": str(batch_id)}
                n = conn.execute(text(sql), params).scalar()
                logger.info("  %-30s %d rows", label, n)
            except Exception as exc:
                logger.warning("  %-30s check failed: %s", label, exc)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def run(batch_id: uuid.UUID | None = None) -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    full_sync = batch_id is None
    log_batch_id: uuid.UUID | None = None

    if full_sync:
        logger.info("ODS→NDS mode: FULL SYNC (all ODS rows)")
        log_batch_id = register_batch(engine, "ods_to_nds_full")
    else:
        logger.info("ODS→NDS mode: DELTA (batch_id=%s)", batch_id)

    params = _sql_params(full_sync, batch_id) if batch_id else {}
    total = 0
    total_rejected = 0
    log_target = log_batch_id or batch_id

    try:
        # BR06: resolve which in-scope partner_code values are not genuine
        # ISO-3 codes *before* anything else, so the country/product master
        # upserts and the trade fact upsert can all exclude them consistently.
        invalid_codes = _find_invalid_country_codes(engine, full_sync, params)
        has_invalid_codes = bool(invalid_codes)
        params_bk = (
            {**params, "invalid_codes": invalid_codes} if has_invalid_codes else params
        )

        with engine.begin() as conn:
            r = conn.execute(
                _sql_upsert_countries_trade(full_sync, has_invalid_codes), params_bk
            )
            logger.info(
                "Step 1a: upserted %d country rows (trade partners)", r.rowcount
            )
            total += r.rowcount

        total += _upsert_countries_from_fta_members(
            engine, batch_id, full_sync=full_sync
        )

        with engine.begin() as conn:
            r = conn.execute(_sql_upsert_products(full_sync), params)
            logger.info("Step 2:  upserted %d product rows", r.rowcount)
            total += r.rowcount

            r = conn.execute(_sql_upsert_time(full_sync), params)
            logger.info("Step 3:  inserted %d time rows", r.rowcount)
            total += r.rowcount

            r = conn.execute(_sql_upsert_fta(full_sync), params)
            logger.info("Step 4:  upserted %d fta rows", r.rowcount)
            total += r.rowcount

        total += _sync_fta_members(engine, batch_id, full_sync=full_sync)

        total_rejected += _log_rejected_trade(
            engine, log_target, full_sync, params_bk, has_invalid_codes
        )

        with engine.begin() as conn:
            r = conn.execute(_sql_upsert_trade(full_sync, has_invalid_codes), params_bk)
            logger.info("Step 6:  upserted %d trade_transaction rows", r.rowcount)
            total += r.rowcount

            d = conn.execute(_sql_delete_fta_util(full_sync), params)
            logger.info(
                "Step 7:  deleted %d fta_utilization rows (pre-insert)", d.rowcount
            )
            r = conn.execute(_sql_insert_fta_util(full_sync), params)
            logger.info("Step 7:  inserted %d fta_utilization rows", r.rowcount)
            total += r.rowcount

        total += _sync_exchange_rate(engine, batch_id, full_sync=full_sync)

        logger.info("ODS→NDS complete. Total rows affected: %d", total)
        _log_sanity_counts(engine, batch_id, full_sync=full_sync)

    except Exception as exc:
        logger.exception("ods_to_nds failed")
        if log_batch_id:
            complete_batch(
                engine, log_batch_id, status="FAILED", error_message=str(exc)
            )
        raise

    if log_batch_id:
        complete_batch(
            engine,
            log_batch_id,
            rows_loaded=total,
            rows_rejected=total_rejected,
            rows_upserted=total,
        )

    return total


if __name__ == "__main__":
    sys.exit(0 if run() >= 0 else 1)
