"""MarketPulse market data ingestion.

Fetches daily OHLCV history via ``yfinance`` for the configured ticker universe,
normalizes/st deduplicates the data, and lands it into the BigQuery raw layer via
an idempotent ``MERGE`` upsert pattern (staging snapshot -> raw upsert).
"""

from __future__ import annotations

import logging
import os
from typing import Iterable, Optional

import pandas as pd
import yfinance as yf
from tenacity import before_sleep_log, retry, retry_if_exception_type, stop_after_attempt, wait_exponential
from google.cloud import bigquery
from google.api_core.exceptions import NotFound

from src.utils.logger import get_logger
from src.utils.alerts import send_critical_alert

logger = get_logger(__name__)

DEFAULT_TICKERS: list[str] = ["AAPL", "MSFT", "GOOGL", "NVDA", "SPY", "BTC-USD"]
DEFAULT_LOOKBACK_DAYS = 30
DEFAULT_SOURCE = "yfinance"

FETCH_RETRY_ATTEMPTS = 5
FETCH_RETRY_WAIT_MIN_SECONDS = 1.0
FETCH_RETRY_WAIT_MAX_SECONDS = 30.0

STAGING_TABLE_NAME = "market_ticks_staging"

RAW_COLUMNS: list[str] = [
    "ticker",
    "trade_date",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
    "source",
]

RAW_TABLE_SCHEMA: list[bigquery.SchemaField] = [
    bigquery.SchemaField("ticker", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("trade_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("open_price", "FLOAT64", mode="REQUIRED"),
    bigquery.SchemaField("high_price", "FLOAT64", mode="REQUIRED"),
    bigquery.SchemaField("low_price", "FLOAT64", mode="REQUIRED"),
    bigquery.SchemaField("close_price", "FLOAT64", mode="REQUIRED"),
    bigquery.SchemaField("volume", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("source", "STRING"),
]


class MarketDataError(RuntimeError):
    """Raised when market data ingestion cannot complete."""


@retry(
    stop=stop_after_attempt(FETCH_RETRY_ATTEMPTS),
    wait=wait_exponential(
        multiplier=1.0,
        min=FETCH_RETRY_WAIT_MIN_SECONDS,
        max=FETCH_RETRY_WAIT_MAX_SECONDS,
    ),
    before_sleep=before_sleep_log(logger, log_level=logging.INFO),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
)
def _fetch_history_with_backoff(ticker: str, period: str) -> pd.DataFrame:
    """Fetch daily OHLCV bars via yfinance with exponential backoff retries."""
    return yf.Ticker(ticker).history(period=period, interval="1d", progress=False)


def _normalize_history(ticker: str, history: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Normalize raw yfinance frame into the canonical MarketPulse tick schema."""
    if history is None or history.empty:
        return pd.DataFrame(columns=RAW_COLUMNS)

    frame = history.copy()
    frame.columns = [str(column).lower() for column in frame.columns]
    if "date" not in frame.columns:
        frame = frame.reset_index()
    frame = frame.rename(
        columns={
            "date": "trade_date",
            "open": "open_price",
            "high": "high_price",
            "low": "low_price",
            "close": "close_price",
            "volume": "volume",
        }
    )
    frame["ticker"] = ticker
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.normalize()
    frame["open_price"] = pd.to_numeric(frame["open_price"], errors="coerce")
    frame["high_price"] = pd.to_numeric(frame["high_price"], errors="coerce")
    frame["low_price"] = pd.to_numeric(frame["low_price"], errors="coerce")
    frame["close_price"] = pd.to_numeric(frame["close_price"], errors="coerce")
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce").fillna(0).astype("int64")
    frame["source"] = DEFAULT_SOURCE

    return frame.loc[:, RAW_COLUMNS].reset_index(drop=True)


def fetch_ticker(ticker: str, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> pd.DataFrame:
    """Fetch and normalize daily OHLCV history for a single ticker."""
    period = f"{max(int(lookback_days), 5)}d"
    history = _fetch_history_with_backoff(ticker=ticker, period=period)
    frame = _normalize_history(ticker=ticker, history=history)
    if frame.empty:
        logger.warning("No market data available", extra={"ticker": ticker})
    return frame


def fetch_market_data(
    tickers: Optional[Iterable[str]] = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> pd.DataFrame:
    """Fetch the ticker universe and return a deduplicated OHLCV dataframe."""
    ticker_universe = [str(ticker).upper() for ticker in tickers] if tickers else list(DEFAULT_TICKERS)
    frames: list[pd.DataFrame] = []
    for ticker in ticker_universe:
        logger.info("Fetching market data", extra={"ticker": ticker})
        frame = fetch_ticker(ticker=ticker, lookback_days=lookback_days)
        if frame.empty:
            continue
        frames.append(frame)

    if not frames:
        return pd.DataFrame(columns=RAW_COLUMNS)

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["ticker", "trade_date"], keep="last")
    return combined.reset_index(drop=True)


def _build_merge_sql(project_id: str, dataset_id: str, table_id: str) -> str:
    """Idempotent MERGE upsert: staging snapshot -> raw market ticks."""
    return f"""
MERGE `{project_id}.{dataset_id}.{table_id}` AS tgt
USING (
    SELECT
        ticker,
        trade_date,
        open_price,
        high_price,
        low_price,
        close_price,
        volume,
        source
    FROM `{project_id}.{dataset_id}.{STAGING_TABLE_NAME}`
) AS src
ON tgt.ticker = src.ticker
   AND tgt.trade_date = src.trade_date
WHEN MATCHED THEN UPDATE SET
    open_price = src.open_price,
    high_price = src.high_price,
    low_price = src.low_price,
    close_price = src.close_price,
    volume = src.volume,
    source = src.source
WHEN NOT MATCHED THEN INSERT (
    ticker,
    trade_date,
    open_price,
    high_price,
    low_price,
    close_price,
    volume,
    source
) VALUES (
    src.ticker,
    src.trade_date,
    src.open_price,
    src.high_price,
    src.low_price,
    src.close_price,
    src.volume,
    src.source
)
"""


def _ensure_raw_table(client: bigquery.Client, table_id: str, schema: list[bigquery.SchemaField]) -> None:
    """Create the raw table if it does not exist yet (idempotent DDL)."""
    try:
        client.get_table(table_id)
    except NotFound:
        client.create_table(table_id=table_id, schema=schema)


def upsert_market_ticks(df: pd.DataFrame, project_id: Optional[str] = None) -> int:
    """Upsert normalized market ticks into BigQuery raw via MERGE (idempotent)."""
    resolved_project = project_id or os.getenv("GCP_PROJECT_ID")
    if not resolved_project:
        raise MarketDataError("GCP_PROJECT_ID must be configured for BigQuery operations")

    dataset_id = os.getenv("BIGQUERY_RAW_DATASET", "marketpulse_raw")
    table_id = os.getenv("BIGQUERY_RAW_TABLE", "market_ticks")
    target_full_table_id = f"{resolved_project}.{dataset_id}.{table_id}"
    staging_full_table_id = f"{resolved_project}.{dataset_id}.{STAGING_TABLE_NAME}"

    client = bigquery.Client(project=resolved_project)
    _ensure_raw_table(client=client, table_id=target_full_table_id, schema=RAW_TABLE_SCHEMA)

    if not df.empty:
        load_job = client.load_table_from_dataframe(
            df,
            staging_full_table_id,
            job_config=bigquery.LoadJobConfig(
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            ),
        )
        load_job.result()  # wait for load to complete

    merge_job = client.query(_build_merge_sql(resolved_project, dataset_id, table_id))
    merge_job.result()
    return int(merge_job.output_rows or 0)


def run_ingestion(
    tickers: Optional[Iterable[str]] = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    project_id: Optional[str] = None,
) -> int:
    """End-to-end ingestion: fetch -> normalize -> deduplicate -> BigQuery MERGE upsert."""
    df = fetch_market_data(tickers=tickers, lookback_days=lookback_days)
    if df.empty:
        logger.info("No market rows fetched - skipping BigQuery upsert")
        return 0
    rows_upserted = upsert_market_ticks(df=df, project_id=project_id)
    logger.info("Ingestion upsert complete", extra={"rows_upserted": rows_upserted})
    return rows_upserted


if __name__ == "__main__":
    import os

    ticker_universe = [
        ticker.strip().upper()
        for ticker in os.getenv("TICKERS", "AAPL,MSFT,GOOGL,NVDA,SPY,BTC-USD").split(",")
        if ticker.strip()
    ]
    ingested_rows = run_ingestion(
        tickers=ticker_universe,
        lookback_days=int(os.getenv("LOOKBACK_DAYS", str(DEFAULT_LOOKBACK_DAYS))),
    )
    logger.info("MarketPulse ingestion pipeline completed", extra={"rows_upserted": ingested_rows})
