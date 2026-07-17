-- Migration 013: public.late_arrival_audit — permanent late-arrival audit trail
--
-- ods.trade_transaction.is_late_arriving / nds.trade_transaction.is_late_arriving
-- are MUTABLE operational flags: set TRUE by 02_transform/stage_to_ods.py when a
-- business key is genuinely new *and* older than its source_system watermark,
-- then cleared to FALSE by 02_transform/late_arriving_handler.py once verified
-- present in nds.trade_transaction. That lifecycle is correct for its purpose
-- (retry-on-failure bookkeeping) but cannot answer "how often has this source
-- historically reported data late" — the flag trends toward 0 for any period
-- whose late rows have already been resolved.
--
-- This table is the separate, append-only audit trail Kimball/Inmon theory
-- calls for: one row inserted once, in stage_to_ods.py, at the moment a
-- business key is first detected as late-arriving. Rows here are never
-- updated or deleted, independent of the operational flag's lifecycle.
-- Read by 04_mining/risk_trade_balance_prediction.py to compute a historically
-- stable late_arriving_ratio feature.
--
-- All statements are idempotent (IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS public.late_arrival_audit (
    audit_id       BIGSERIAL    PRIMARY KEY,
    batch_id       UUID         NOT NULL REFERENCES public.etl_batch_log(batch_id),
    source_table   VARCHAR(100) NOT NULL,
    year           SMALLINT     NOT NULL,
    month          SMALLINT     NOT NULL,
    hs_code        VARCHAR(8),
    partner_code   VARCHAR(3),
    flow_type      BOOLEAN,
    source_system  VARCHAR(50)  NOT NULL,
    detected_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_late_arrival_audit_period ON public.late_arrival_audit (source_system, year, month);
CREATE INDEX IF NOT EXISTS idx_late_arrival_audit_batch  ON public.late_arrival_audit (batch_id);

COMMENT ON TABLE public.late_arrival_audit IS
    'Append-only, permanent record of every late-arriving business key detected in '
    '02_transform/stage_to_ods.py at first-detection time. Unlike '
    'ods.trade_transaction.is_late_arriving / nds.trade_transaction.is_late_arriving '
    '(mutable operational flags cleared once late_arriving_handler.py verifies '
    'propagation to NDS), rows here are never updated or deleted — they preserve '
    'historical late-arrival events for data-quality analysis '
    '(see 04_mining/risk_trade_balance_prediction.py late_arriving_ratio feature).';
