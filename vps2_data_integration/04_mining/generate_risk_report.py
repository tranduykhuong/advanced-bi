"""Render a static PDF report for the two risk mining models.

Both risk_exchange_rate_prediction.py (regressor: signed % change) and
risk_trade_balance_prediction.py (regressor: trade balance level) read
from ODS (no NDS/DDS dependency) and write to mining.* tables that carry
no dimensional keys (no product/country breakdown) — there is nothing to
slice/dice, so an OLAP cube adds ceremony without value here. A plain
chart does the one thing this output needs: show the trend and make the
periods that crossed the alert threshold visually obvious.

Output: a 2-page PDF (one page per model), built in memory and emailed as an
attachment on every mining run — matches the "báo cáo tĩnh (PDF)" functional
requirement (report Section II.c), independent from the interactive Saiku
dashboards which stay scoped to DDS/OLAP. Never written to disk — email is
the only delivery channel, so a run with SMTP unset produces no artifact.
"""

from __future__ import annotations

import io
import smtplib
import sys
import uuid
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless — no display available in the ETL container

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.ticker import FuncFormatter
from sqlalchemy import text

DATE_FORMAT = "%d-%m-%Y"
MONTH_FORMAT = "%m-%Y"  # trade balance x-axis is monthly-grain, no day component

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch

logger = get_logger(__name__)

RISK_COLOR = "#C0392B"  # red — period crossed the alert threshold
NORMAL_COLOR = "#2E75B6"  # blue — period within normal range
THRESHOLD_COLOR = "#7B241C"

REPORT_FILENAME = "risk_report.pdf"


_ENSURE_TABLES_SQL = """
CREATE SCHEMA IF NOT EXISTS mining;

CREATE TABLE IF NOT EXISTS mining.exchange_rate_risk_prediction (
    prediction_id        UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    target_date           DATE           NOT NULL,
    horizon_days          INT            NOT NULL,
    predicted_change_pct  NUMERIC(9,6)   NOT NULL,
    predicted_rate        NUMERIC(18,6)  NOT NULL,
    is_high_risk          BOOLEAN        NOT NULL,
    risk_threshold_up     NUMERIC(9,6)   NOT NULL,
    model_version         VARCHAR(30)    NOT NULL,
    batch_id              UUID           NOT NULL,
    predicted_at          TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_mining_exchange_rate_risk_prediction UNIQUE (target_date, model_version)
);
CREATE TABLE IF NOT EXISTS mining.trade_balance_risk_prediction (
    prediction_id        UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    target_month          DATE           NOT NULL,
    horizon_months         INT            NOT NULL,
    predicted_balance     NUMERIC(20,2)  NOT NULL,
    is_high_risk          BOOLEAN        NOT NULL,
    risk_threshold_down   NUMERIC(20,2)  NOT NULL,
    model_version         VARCHAR(30)    NOT NULL,
    batch_id              UUID           NOT NULL,
    predicted_at          TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_mining_trade_balance_risk_prediction UNIQUE (target_month, model_version)
);
"""


def _ensure_tables(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(_ENSURE_TABLES_SQL))


def _load_exchange_rate_risk(engine) -> pd.DataFrame:
    """Fetch the latest mining run's day-by-day forecast, one row per
    target_date. The table is TRUNCATEd on every run (see
    risk_exchange_rate_prediction.py)."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
                SELECT target_date, horizon_days, predicted_change_pct,
                       predicted_rate, is_high_risk, risk_threshold_up
                FROM mining.exchange_rate_risk_prediction
                ORDER BY target_date
                """)).fetchall()
    df = pd.DataFrame(
        rows,
        columns=[
            "target_date",
            "horizon_days",
            "predicted_change_pct",
            "predicted_rate",
            "is_high_risk",
            "risk_threshold_up",
        ],
    )
    if not df.empty:
        # NUMERIC columns come back as decimal.Decimal — cast before any arithmetic/plotting.
        df["predicted_change_pct"] = df["predicted_change_pct"].astype(float)
        df["predicted_rate"] = df["predicted_rate"].astype(float)
        df["risk_threshold_up"] = df["risk_threshold_up"].astype(float)
    return df


def _load_trade_balance_risk(engine) -> pd.DataFrame:
    """Fetch the latest mining run's month-by-month forecast, one row per
    target_month. The table is TRUNCATEd on every run (see
    risk_trade_balance_prediction.py)."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
                SELECT target_month, horizon_months, predicted_balance,
                       is_high_risk, risk_threshold_down, predicted_at
                FROM mining.trade_balance_risk_prediction
                ORDER BY target_month
                """)).fetchall()
    df = pd.DataFrame(
        rows,
        columns=[
            "target_month",
            "horizon_months",
            "predicted_balance",
            "is_high_risk",
            "risk_threshold_down",
            "predicted_at",
        ],
    )
    if not df.empty:
        # NUMERIC columns come back as decimal.Decimal — cast before plotting.
        df["predicted_balance"] = df["predicted_balance"].astype(float)
        df["risk_threshold_down"] = df["risk_threshold_down"].astype(float)
        df["target_month"] = pd.to_datetime(df["target_month"])
    return df


def _plot_exchange_rate_page(pdf: PdfPages, df: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(11, 6))
    if df.empty:
        ax.text(
            0.5, 0.5, "Chưa có dữ liệu dự báo rủi ro tỷ giá", ha="center", va="center"
        )
        ax.axis("off")
        pdf.savefig(fig)
        plt.close(fig)
        return

    colors = [RISK_COLOR if r else NORMAL_COLOR for r in df["is_high_risk"]]
    ax.plot(
        df["target_date"],
        df["predicted_change_pct"],
        color=NORMAL_COLOR,
        linewidth=1.5,
        zorder=1,
    )
    ax.scatter(
        df["target_date"],
        df["predicted_change_pct"],
        c=colors,
        s=45,
        zorder=2,
        edgecolors="white",
        linewidths=0.6,
    )
    for x, y in zip(df["target_date"], df["predicted_change_pct"]):
        ax.annotate(
            f"{y:.1%}",
            (x, y),
            textcoords="offset points",
            xytext=(0, 6),
            ha="center",
            va="bottom",
            fontsize=6.5,
            rotation=90,
            zorder=3,
        )

    threshold_up = float(df["risk_threshold_up"].iloc[-1])
    first_row = df.iloc[0]
    as_of_date = first_row["target_date"] - pd.Timedelta(
        days=int(first_row["horizon_days"])
    )
    ax.axhline(0, color="#999999", linewidth=0.8, zorder=0)  # "no change" reference
    ax.axhline(threshold_up, color=THRESHOLD_COLOR, linestyle="--", linewidth=1.5)
    ax.annotate(
        f"Ngưỡng an toàn: {threshold_up:.2%}",
        (df["target_date"].iloc[-1], threshold_up),
        textcoords="offset points",
        xytext=(0, 4),
        ha="right",
        va="bottom",
        fontsize=8,
        color=THRESHOLD_COLOR,
        fontweight="bold",
    )

    as_of_date_str = as_of_date.strftime(DATE_FORMAT)
    ax.set_title(
        f"Dự báo % thay đổi tỷ giá USD/VND — {len(df)} ngày tới kể từ {as_of_date_str}",
        fontsize=14,
        fontweight="bold",
    )
    ax.set_xlabel("Ngày dự báo")
    ax.set_ylabel("% thay đổi dự kiến so với tỷ giá hôm nay")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.1%}"))
    ax.xaxis.set_major_formatter(mdates.DateFormatter(DATE_FORMAT))
    ax.margins(y=0.2)
    fig.autofmt_xdate()

    n_risk_days = int(df["is_high_risk"].sum())
    as_of_rate = float(
        df["predicted_rate"].iloc[0] / (1 + df["predicted_change_pct"].iloc[0])
    )
    fig.text(
        0.5,
        0.01,
        f"Dự báo lập ngày {as_of_date_str} (tỷ giá gốc: {as_of_rate:,.2f})  |  "
        f"Ngưỡng an toàn hướng tăng: {threshold_up:.4%}  |  "
        f"Số ngày dự báo rủi ro cao: {n_risk_days}/{len(df)}",
        ha="center",
        fontsize=9,
        color="#555555",
    )

    fig.tight_layout(rect=(0, 0.03, 1, 1))
    pdf.savefig(fig)
    plt.close(fig)


def _plot_trade_balance_page(pdf: PdfPages, df: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(11, 6))
    if df.empty:
        ax.text(
            0.5,
            0.5,
            "Chưa có dữ liệu dự báo rủi ro thâm hụt cán cân thương mại",
            ha="center",
            va="center",
        )
        ax.axis("off")
        pdf.savefig(fig)
        plt.close(fig)
        return

    colors = [RISK_COLOR if r else NORMAL_COLOR for r in df["is_high_risk"]]
    bars = ax.bar(df["target_month"], df["predicted_balance"], color=colors, width=20)
    for bar, value in zip(bars, df["predicted_balance"]):
        ax.annotate(
            f"{value / 1e9:,.1f}",
            (bar.get_x() + bar.get_width() / 2, value),
            textcoords="offset points",
            xytext=(0, 4 if value >= 0 else -4),
            ha="center",
            va="bottom" if value >= 0 else "top",
            fontsize=7.5,
            zorder=3,
        )

    threshold_down = float(df["risk_threshold_down"].iloc[-1])
    # Actual mining run timestamp (DB-recorded), NOT derived from target_month —
    # ODS data always lags behind today (last real month here is 2026-05, but
    # mining can run in July), so "target_month[0] - 1 month" reflects the
    # data's cutoff, not when the model actually ran.
    mining_run_date = pd.Timestamp(df["predicted_at"].iloc[0])
    as_of_date_str = mining_run_date.strftime(DATE_FORMAT)
    ax.axhline(0, color="#999999", linewidth=0.8, zorder=0)  # surplus/deficit boundary
    ax.axhline(threshold_down, color=THRESHOLD_COLOR, linestyle="--", linewidth=1.5)
    ax.annotate(
        f"Ngưỡng rủi ro: {threshold_down / 1e9:,.2f} tỷ USD",
        (df["target_month"].iloc[-1], threshold_down),
        textcoords="offset points",
        xytext=(0, -4),
        ha="right",
        va="top",
        fontsize=8,
        color=THRESHOLD_COLOR,
        fontweight="bold",
    )

    ax.set_title(
        f"Dự báo cán cân thương mại — {len(df)} tháng tới kể từ {as_of_date_str}",
        fontsize=14,
        fontweight="bold",
    )
    ax.set_xlabel("Tháng dự báo")
    ax.set_ylabel("Cán cân thương mại dự kiến (tỷ USD)")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 1e9:,.1f}"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter(MONTH_FORMAT))
    ax.margins(y=0.2)
    fig.autofmt_xdate()

    n_risk_months = int(df["is_high_risk"].sum())
    fig.text(
        0.5,
        0.01,
        f"Dự báo lập từ tháng {as_of_date_str}  |  "
        f"Ngưỡng rủi ro thâm hụt: {threshold_down / 1e9:,.2f} tỷ USD  |  "
        f"Số tháng dự báo rủi ro cao: {n_risk_months}/{len(df)}",
        ha="center",
        fontsize=9,
        color="#555555",
    )

    fig.tight_layout(rect=(0, 0.03, 1, 1))
    pdf.savefig(fig)
    plt.close(fig)


def _send_report_email(cfg, pdf_bytes: bytes) -> None:
    """Email the PDF as an attachment — the only delivery channel; the report
    is never written to disk.

    Opt-in: skipped (not an error) unless SMTP_USER/SMTP_PASSWORD/
    REPORT_EMAIL_TO are all set. Delivery failures are logged and swallowed
    — a broken mailbox should never fail the mining phase.
    """
    if not (cfg.report_email_to and cfg.smtp_user and cfg.smtp_password):
        logger.info(
            "SMTP_USER/SMTP_PASSWORD/REPORT_EMAIL_TO not fully set — skipping email delivery"
        )
        return

    msg = EmailMessage()
    msg["Subject"] = f"[BI DW] Báo cáo rủi ro — {datetime.now().strftime('%Y-%m-%d')}"
    msg["From"] = cfg.smtp_user
    msg["To"] = cfg.report_email_to
    msg.set_content(
        "Báo cáo dự báo rủi ro biến động tỷ giá USD/VND và rủi ro thâm hụt cán cân "
        "thương mại được đính kèm (tự động, từ phase mining của pipeline ETL)."
    )
    msg.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename=REPORT_FILENAME,
    )

    try:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as server:
            server.starttls()
            server.login(cfg.smtp_user, cfg.smtp_password)
            server.send_message(msg)
        logger.info("Emailed risk report to %s", cfg.report_email_to)
    except Exception as exc:
        logger.warning("Failed to email risk report (non-fatal): %s", exc)


def run(batch_id: uuid.UUID | None = None) -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "generate_risk_report")

    try:
        _ensure_tables(engine)
        fx_df = _load_exchange_rate_risk(engine)
        balance_df = _load_trade_balance_risk(engine)

        buffer = io.BytesIO()
        with PdfPages(buffer) as pdf:
            _plot_exchange_rate_page(pdf, fx_df)
            _plot_trade_balance_page(pdf, balance_df)

        logger.info(
            "Generated risk report in memory (%d + %d rows)",
            len(fx_df),
            len(balance_df),
        )

        _send_report_email(cfg, buffer.getvalue())

    except Exception as exc:
        logger.exception("generate_risk_report failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=len(fx_df) + len(balance_df))
    return 0


if __name__ == "__main__":
    sys.exit(run())
