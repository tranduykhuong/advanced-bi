-- =============================================================================
-- 02_ddl_dds_forecast.sql — Dimensional Data Store (DDS) Forecast Fact Table
-- Schema: dds
--
-- Stores Prophet time-series forecasts for trade transactions.
-- Grain: time × product × partner × flow_type
-- =============================================================================

CREATE TABLE IF NOT EXISTS dds.fact_trade_forecast (
    forecast_key    BIGSERIAL    NOT NULL,

    -- Dimension FKs
    time_key        INTEGER      NOT NULL,   -- FK → dds.dim_time (YYYYMM)
    product_key     BIGINT       NOT NULL,   -- FK → dds.dim_product
    partner_key     BIGINT       NOT NULL,   -- FK → dds.dim_country

    -- Degenerate dimensions
    flow_type       BOOLEAN      NOT NULL,   -- TRUE = Export, FALSE = Import

    -- Prophet forecast measures (USD or VND depending on model logic)
    -- Typically we forecast the pre-computed value_vnd, but let's keep it numeric
    forecasted_value NUMERIC(18,2),
    yhat_lower      NUMERIC(18,2),
    yhat_upper      NUMERIC(18,2),

    -- Lineage / Model info
    model_version   VARCHAR(50),
    batch_id        UUID,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_dds_fact_forecast PRIMARY KEY (forecast_key),
    CONSTRAINT uq_dds_fact_forecast_grain
        UNIQUE (time_key, product_key, partner_key, flow_type, model_version),
    CONSTRAINT fk_dds_forecast_time
        FOREIGN KEY (time_key)    REFERENCES dds.dim_time    (time_key),
    CONSTRAINT fk_dds_forecast_product
        FOREIGN KEY (product_key) REFERENCES dds.dim_product (product_key),
    CONSTRAINT fk_dds_forecast_partner
        FOREIGN KEY (partner_key) REFERENCES dds.dim_country (country_key)
);

CREATE INDEX IF NOT EXISTS ix_dds_fact_forecast_time_key
    ON dds.fact_trade_forecast (time_key);

CREATE INDEX IF NOT EXISTS ix_dds_fact_forecast_partner_key
    ON dds.fact_trade_forecast (partner_key);

CREATE INDEX IF NOT EXISTS ix_dds_fact_forecast_product_key
    ON dds.fact_trade_forecast (product_key);

COMMENT ON TABLE  dds.fact_trade_forecast IS
    'Stores Prophet time-series forecasts for trade transactions. Grain: time × product × partner × flow_type.';
COMMENT ON COLUMN dds.fact_trade_forecast.flow_type  IS 'TRUE = Export, FALSE = Import.';
COMMENT ON COLUMN dds.fact_trade_forecast.model_version IS 'Identifies which run/version of the model generated this forecast.';
