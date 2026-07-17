-- =============================================================================
-- 012_fta_utilization_time.sql — Time-aware FTA utilization for the Saiku cube
-- Schema: dds
--
-- WHY
--   FTA_Utilization_Cube was built on dds.fta_utilization_summary, pre-aggregated
--   per fta_key ONLY (no time), so a Saiku dashboard time filter (dim_time) had
--   nothing to bind to and the FTA tile did not react to it.
--
--   Two things are fixed here:
--   1. TIME. Grain is (fta_name, time_key) so the dashboard time filter applies.
--   2. GRAIN BY AGREEMENT. dim_fta is granular: ~2130 fta_key values map to only
--      ~355 fta_name agreements (e.g. RCEP spans 6 fta_key). Users analyse
--      agreements ("RCEP utilization"), so we aggregate by fta_name and count
--      DISTINCT trade_key — which also dedupes a transaction that matches several
--      fta_key of the SAME agreement.
--
--   UtilizationRate is a ratio (agreement_count / total_VN_count). To keep it
--   correct under any time slice, both numerator and denominator must be sliced
--   by the same time filter. We do this single-cube (Mondrian virtual/cross cubes
--   were unreliable on this build) with a "sentinel" denominator row:
--
--     grain = (fta_name, time_key)
--       - agreement rows : fta_trade_count = # distinct transactions eligible for
--                          that agreement in that period.
--       - sentinel rows  : fta_name = 'ALL VN TRADE', fta_trade_count = total #
--                          VN transactions in that period (denominator).
--
--   The cube computes UtilizationRate as a CalculatedMember:
--       [FTA Trade Count] / ([dim_fta].[ALL VN TRADE], [FTA Trade Count]) * 100
--   Both operands share the current dim_time context, so filtering to a period
--   recomputes the rate correctly; summed over all periods it equals the
--   whole-period rate (a trade_key maps to exactly one period).
--
-- Idempotent: CREATE OR REPLACE VIEW (fresh names, no DROP needed).
-- Read-only over dds.
--
-- NOTE: these views read the BASE table dds.dim_fta (filtered to is_current),
-- NOT the convenience view dds.dim_fta_current. Migration 009 runs earlier and
-- does `DROP VIEW IF EXISTS dds.dim_fta_current` (without CASCADE) to retrofit
-- dim_fta; depending on that view would block 009 on every deploy. dim_fta is a
-- plain table 009 only ALTERs (it never drops the fta_key/fta_name/is_current
-- columns these views use), so the base-table dependency is safe.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Agreement-level FTA dimension = distinct agreement names + one sentinel
-- denominator member.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW dds.dim_fta_agreement AS
SELECT DISTINCT fta_name FROM dds.dim_fta WHERE is_current
UNION ALL
SELECT 'ALL VN TRADE';

COMMENT ON VIEW dds.dim_fta_agreement IS
    'Distinct FTA agreement names plus a sentinel member (''ALL VN TRADE'') that '
    'carries the per-period denominator for FTA_Utilization_Cube.UtilizationRate.';

-- ---------------------------------------------------------------------------
-- Time-aware utilization fact: numerator per (agreement, period) + sentinel
-- denominator per period.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW dds.fta_utilization_by_agreement AS
SELECT
    dd.fta_name,
    b.time_key,
    COUNT(DISTINCT b.trade_key)::int AS fta_trade_count
FROM dds.fact_trade_fta_bridge b
JOIN dds.dim_fta dd ON b.fta_key = dd.fta_key AND dd.is_current
GROUP BY dd.fta_name, b.time_key
UNION ALL
SELECT
    'ALL VN TRADE' AS fta_name,
    f.time_key,
    COUNT(*)::int AS fta_trade_count
FROM dds.fact_trade_transaction f
GROUP BY f.time_key;

COMMENT ON VIEW dds.fta_utilization_by_agreement IS
    'FTA utilization at (fta_name, time_key) grain for FTA_Utilization_Cube. '
    'Agreement rows hold the numerator (distinct eligible transactions per '
    'agreement); the ''ALL VN TRADE'' rows hold the per-period denominator (total '
    'VN transactions). Lets the Saiku time filter apply while keeping '
    'UtilizationRate correct under any time slice.';
