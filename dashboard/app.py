"""MarketPulse interactive Streamlit dashboard.

Reads gold market data + anomaly scores from BigQuery and renders:
- Interactive Plotly candlestick charts.
- Live risk gauges (0-100 normalized risk scores).
- Ticker filters.
- Anomaly Alerts Feed (critical risk spikes).
"""

from __future__ import annotations

import os
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from google.cloud import bigquery

from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_TICKERS: list[str] = ["AAPL", "MSFT", "GOOGL", "NVDA", "SPY", "BTC-USD"]
DEFAULT_GOLD_TABLE: str = "fact_daily_metrics"
DEFAULT_ANOMALY_TABLE: str = "fact_anomaly_scores"
RISK_SCORE_HIGH: float = float(os.getenv("RISK_SCORE_HIGH", "85"))
CANDLE_REFRESH_SECONDS: int = 300
ALERT_REFRESH_SECONDS: int = 60


def _full_table(dataset: str, table: str) -> str:
    project_id = os.getenv("GCP_PROJECT_ID", "")
    return f"{project_id}.{dataset}.{table}"


@st.cache_resource
def get_bigquery_client():
    return bigquery.Client()


@st.cache_data(ttl=CANDLE_REFRESH_SECONDS)
def load_market_data(tickers: tuple) -> pd.DataFrame:
    """Load gold daily candles + engineered features for the selected tickers."""
    if not tickers:
        return pd.DataFrame()

    client = get_bigquery_client()
    dataset = os.getenv("BIGQUERY_ANALYTICS_DATASET", "marketpulse_analytics")
    full_table = _full_table(dataset, os.getenv("BIGQUERY_GOLD_TABLE", DEFAULT_GOLD_TABLE))
    placeholders = ", ".join([f"@ticker_{idx}" for idx in range(len(tickers))])
    params = {f"ticker_{idx}": ticker for idx, ticker in enumerate(tickers)}
    query = f"""
        SELECT
            ticker,
            trade_date,
            open_price,
            high_price,
            low_price,
            close_price,
            volume,
            daily_return,
            seven_day_ma_close,
            seven_day_volatility,
            volume_z_score
        FROM `{full_table}`
        WHERE ticker IN ({placeholders})
        ORDER BY ticker, trade_date
    """
    return client.query(query, params=params).to_dataframe()


@st.cache_data(ttl=ALERT_REFRESH_SECONDS)
def load_alerts(tickers: tuple) -> pd.DataFrame:
    """Load critical anomaly alerts (risk score > threshold)."""
    if not tickers:
        return pd.DataFrame()

    client = get_bigquery_client()
    dataset = os.getenv("BIGQUERY_ANALYTICS_DATASET", "marketpulse_analytics")
    full_table = _full_table(dataset, os.getenv("BIGQUERY_ANOMALY_TABLE", DEFAULT_ANOMALY_TABLE))
    placeholders = ", ".join([f"@ticker_{idx}" for idx in range(len(tickers))])
    params = {f"ticker_{idx}": ticker for idx, ticker in enumerate(tickers)}
    query = f"""
        SELECT
            ticker,
            trade_date,
            risk_score,
            anomaly_score
        FROM `{full_table}`
        WHERE is_anomaly = TRUE
          AND risk_score > @risk_threshold
          AND ticker IN ({placeholders})
        ORDER BY risk_score DESC
    """
    params["risk_threshold"] = RISK_SCORE_HIGH
    return client.query(query, params=params).to_dataframe()


def render_candlestick_chart(df: pd.DataFrame):
    fig = go.Figure(
        data=[
            go.Candlestick(
                x=[str(day.date()) if hasattr(day, "date") else str(day) for day in df["trade_date"]],
                open=df["open_price"].astype(float),
                high=df["high_price"].astype(float),
                low=df["low_price"].astype(float),
                close=df["close_price"].astype(float),
            )
        ]
    )
    fig.update_layout(
        title=f"{df['ticker'].iloc[0]} - Daily OHLCV Candlestick",
        xaxis_title="Trade Date",
        yaxis_title="Price",
        height=450,
        xaxis_rangeslider_visible=False,
    )
    st.plotly_chart(fig, use_container_width=True)
    return fig


def render_risk_gauge(risk_score: float) -> go.Figure:
    gauge = go.Figure(
        data=[
            go.Indicator(
                type="gauge",
                progressBar={"visible": True, "width": 12},
                gauge={
                    "axis": {"range": [0, 100]},
                    "bar": {"thickness": 0.3},
                },
                value=float(risk_score),
            )
        ]
    )
    gauge.update_layout(title="Risk Score (0-100)", height=220)
    return gauge


def render_metrics_table(df: pd.DataFrame) -> None:
    display = df.copy()
    display["trade_date"] = display["trade_date"].astype(str)
    st.dataframe(display, use_container_width=True)


def main() -> None:
    st.set_page_config(page_title="MarketPulse", page_icon="📈", layout="wide")
    st.title("📈 MarketPulse")
    st.caption("Zero-cost Financial Market Data & Anomaly Detection Platform")

    selected_tickers = st.sidebar.multiselect(
        "Tickers",
        options=DEFAULT_TICKERS,
        default=["AAPL", "NVDA"],
        help="Select ticker universe for monitoring",
    )

    if not selected_tickers:
        st.warning("Select at least one ticker from the sidebar to render dashboards.")
        return

    market_df = load_market_data(tuple(selected_tickers))
    alerts_df = load_alerts(tuple(selected_tickers))

    chart_ticker = st.selectbox("Chart ticker", options=list(selected_tickers))

    ticker_df = market_df[market_df["ticker"] == chart_ticker] if not market_df.empty else pd.DataFrame()

    col1, col2 = st.columns([2, 1])
    with col1:
        st.subheader(f"{chart_ticker} - Candlestick")
        if ticker_df.empty:
            st.info("No market data available for the selected ticker.")
        else:
            render_candlestick_chart(ticker_df)

    with col2:
        st.subheader("Live Risk Gauge")
        latest_scores = (
            alerts_df[alerts_df["ticker"] == chart_ticker]
            if not alerts_df.empty
            else pd.DataFrame()
        )
        if latest_scores.empty:
            st.metric(label="Risk Score", value=0.0)
        else:
            latest = latest_scores.iloc[0]
            risk_score = float(latest["risk_score"])
            st.plotly_chart(render_risk_gauge(risk_score), use_container_width=True)
            st.caption(f"Critical threshold: {RISK_SCORE_HIGH}")

    st.subheader("Anomaly Alerts Feed")
    if alerts_df.empty:
        st.success("✅ No critical anomalies detected in the selected ticker universe.")
    else:
        st.dataframe(alerts_df, use_container_width=True)

    if not ticker_df.empty:
        st.subheader("Market Metrics")
        render_metrics_table(ticker_df)


if __name__ == "__main__":
    main()
