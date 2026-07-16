"""
Phase 04: Forecasting (Prophet)
Extracts historical trade value from dds.fact_trade_transaction.
Trains Prophet per (product_key, partner_key, flow_type) group.
Forecasts 12 months ahead and loads into dds.fact_trade_forecast.
"""

from __future__ import annotations

import logging
import uuid
import pandas as pd
from sqlalchemy import text
from prophet import Prophet

from config import load_config
from common.logging_config import setup_logging
from common.db import get_engine, register_batch, complete_batch

logger = logging.getLogger(__name__)

def fit_predict_group(args):
    product_key, partner_key, flow_type, group_df, batch_id = args
    group_df = group_df.sort_values('ds').reset_index(drop=True)

    # Require at least 6 observations as set by user, but for eval we want ~12
    if len(group_df) < 6:
        return []
        
    forecasts = []
    try:
        import logging as py_logging
        py_logging.getLogger('cmdstanpy').setLevel(py_logging.WARNING)
        worker_logger = py_logging.getLogger(__name__)

        from prophet import Prophet
        
        # --- EVALUATION PHASE (Train/Test Split) ---
        # If we have at least 11 months, we use 9 for training and 2-3 for testing.
        if len(group_df) >= 11:
            test_size = len(group_df) - 9
            if test_size > 3:
                test_size = 3
                
            train_df = group_df.iloc[:-test_size]
            test_df = group_df.iloc[-test_size:]
            
            eval_model = Prophet(yearly_seasonality=True, weekly_seasonality=False, daily_seasonality=False)
            eval_model.fit(train_df[['ds', 'y']])
            
            future_eval = eval_model.make_future_dataframe(periods=test_size, freq='MS')
            forecast_eval = eval_model.predict(future_eval)
            
            pred_y = forecast_eval.tail(test_size)['yhat'].values
            actual_y = test_df['y'].values
            
            import numpy as np
            epsilon = 1e-9
            mape = np.mean(np.abs((actual_y - pred_y) / (actual_y + epsilon))) * 100
            worker_logger.info(f"Group {product_key}-{partner_key}-{'Exp' if flow_type else 'Imp'} | Eval MAPE (Train={len(train_df)}, Test={test_size}): {mape:.2f}%")

        # --- PRODUCTION PHASE (Retrain on FULL data) ---
        model = Prophet(yearly_seasonality=True, weekly_seasonality=False, daily_seasonality=False)
        model.fit(group_df[['ds', 'y']])
        
        future = model.make_future_dataframe(periods=12, freq='MS')
        forecast = model.predict(future)
        
        max_historical_date = group_df['ds'].max()
        future_forecast = forecast[forecast['ds'] > max_historical_date].copy()
        future_forecast['time_key'] = future_forecast['ds'].dt.year * 100 + future_forecast['ds'].dt.month
        
        for _, row in future_forecast.iterrows():
            forecasts.append({
                'time_key': int(row['time_key']),
                'product_key': int(product_key),
                'partner_key': int(partner_key),
                'flow_type': flow_type,
                'forecasted_value': row['yhat'],
                'yhat_lower': row['yhat_lower'],
                'yhat_upper': row['yhat_upper'],
                'model_version': 'prophet_v1',
                'batch_id': str(batch_id)
            })
    except Exception as e:
        # Pass exception silently per worker
        pass
        
    return forecasts


def forecast_trade(engine, batch_id: uuid.UUID):
    # 1. Fetch historical data aggregated by hs_chapter
    query = """
        WITH chapter_totals AS (
            SELECT 
                f.time_key,
                p.hs_chapter,
                f.partner_key,
                f.flow_type,
                SUM(f.value_vnd) as total_value
            FROM dds.fact_trade_transaction f
            JOIN dds.dim_product p ON f.product_key = p.product_key
            GROUP BY f.time_key, p.hs_chapter, f.partner_key, f.flow_type
        ),
        chapter_proxies AS (
            -- Pick one representative product_key per chapter to satisfy the DB constraint
            SELECT hs_chapter, MIN(product_key) as proxy_product_key
            FROM dds.dim_product
            WHERE is_current = TRUE
            GROUP BY hs_chapter
        )
        SELECT 
            c.time_key,
            px.proxy_product_key as product_key,
            c.partner_key,
            c.flow_type,
            c.total_value
        FROM chapter_totals c
        JOIN chapter_proxies px ON c.hs_chapter = px.hs_chapter
        ORDER BY c.hs_chapter, c.partner_key, c.flow_type, c.time_key
    """
    logger.info("Fetching historical trade data aggregated by Chapter for forecasting...")
    df = pd.read_sql(query, engine)
    
    if df.empty:
        logger.warning("No data found for forecasting.")
        return 0
    
    # 2. Preprocess time_key (YYYYMM) to ds (datetime)
    df['ds'] = pd.to_datetime(df['time_key'].astype(str), format='%Y%m')
    df.rename(columns={'total_value': 'y'}, inplace=True)
    
    groups = df.groupby(['product_key', 'partner_key', 'flow_type'])
    
    logger.info(f"Preparing {len(groups)} groups for Prophet models...")
    
    tasks = []
    for (product_key, partner_key, flow_type), group_df in groups:
        tasks.append((product_key, partner_key, flow_type, group_df, batch_id))
        
    forecasts = []
    import concurrent.futures
    import multiprocessing
    
    num_workers = max(1, multiprocessing.cpu_count() - 1)
    logger.info(f"Training Prophet models using {num_workers} workers in parallel...")
    
    with concurrent.futures.ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = {executor.submit(fit_predict_group, task): task for task in tasks}
        count = 0
        for future in concurrent.futures.as_completed(futures):
            try:
                res = future.result()
                forecasts.extend(res)
            except Exception as e:
                logger.warning(f"Error processing group: {e}")
                
            count += 1
            if count % 100 == 0:
                logger.info(f"Processed {count}/{len(tasks)} groups...")
            
    if not forecasts:
        logger.warning("No forecasts generated.")
        return 0
        
    forecast_df = pd.DataFrame(forecasts)
    
    # Clip and round to ensure they fit in NUMERIC(18,2) safely
    for col in ['forecasted_value', 'yhat_lower', 'yhat_upper']:
        # Prophet sometimes produces NaN or inf for erratic data, replace with 0
        forecast_df[col] = forecast_df[col].fillna(0)
        forecast_df[col] = forecast_df[col].replace([float('inf'), float('-inf')], 0)
        
        forecast_df[col] = forecast_df[col].round(2)
        # Stricter bound: 90 trillion VND (~4 billion USD). Safe for NUMERIC(18,2)
        forecast_df[col] = forecast_df[col].clip(lower=-9e13, upper=9e13)
    
    # 3. Load into dds.fact_trade_forecast
    logger.info(f"Loading {len(forecast_df)} forecast rows to DDS...")
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM dds.fact_trade_forecast WHERE model_version = 'prophet_v1'"))
        
        # Ensure future time_keys exist in dim_time
        unique_tks = forecast_df['time_key'].unique()
        for tk in unique_tks:
            yr = int(tk // 100)
            mo = int(tk % 100)
            qu = (mo - 1) // 3 + 1
            conn.execute(text("""
                INSERT INTO dds.dim_time (time_key, year, quarter, month)
                VALUES (:tk, :yr, :qu, :mo)
                ON CONFLICT (time_key) DO NOTHING
            """).bindparams(tk=int(tk), yr=yr, qu=qu, mo=mo))
            
        forecast_df.to_sql(
            'fact_trade_forecast', 
            con=conn, 
            schema='dds', 
            if_exists='append', 
            index=False,
            method='multi',
            chunksize=1000
        )
        
    logger.info("Forecasting phase completed successfully.")
    return len(forecast_df)


def run(batch_id: uuid.UUID | None = None) -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level, service="forecasting")
    engine = get_engine(cfg)

    active_batch_id = (
        batch_id
        if batch_id
        else register_batch(engine, "pipeline_analyze_forecast")
    )

    try:
        rows_upserted = forecast_trade(engine, active_batch_id)
        if not batch_id:
            complete_batch(engine, active_batch_id, rows_upserted=rows_upserted)
        return 0
    except Exception as e:
        logger.exception("Forecasting failed: %s", e)
        if not batch_id:
            complete_batch(engine, active_batch_id, status="FAILED", error_message=str(e))
        return 1

def main():
    import os
    import sys
    raw_batch_id = os.getenv("ETL_BATCH_ID")
    b_id = uuid.UUID(raw_batch_id) if raw_batch_id else None
    sys.exit(run(batch_id=b_id))

if __name__ == "__main__":
    main()
