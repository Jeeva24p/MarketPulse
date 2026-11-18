"""Pytest unit tests for the MarketPulse ingestion pipeline (mocked yfinance + BigQuery)."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.ingestion import fetch_market_data as fmd


def _history_frame() -> pd.DataFrame:
    """Build a realistic yfinance-shaped OHLCV frame (Date as a column)."""
    return pd.DataFrame(
        {
            "Open": [147.0, 148.0],
            "High": [152.0, 151.0],
            "Low": [146.0, 147.0],
            "Close": [150.0, 149.0],
            "Volume": [118000, 121000],
            "Date": pd.to_datetime(["2026-11-16", "2026-11-17"]),
            "Adj Close": [150.0, 149.0],
        }
    )


def _normalized_frame() -> pd.DataFrame:
    return fmd._normalize_history(ticker="AAPL", history=_history_frame())


class TestNormalization:
    def test_normalize_history_adds_ticker_and_types(self):
        frame = _normalized_frame()
        assert frame["ticker"].iloc[0] == "AAPL"
        assert frame["source"].iloc[0] == "yfinance"
        assert frame["trade_date"].iloc[0].date() == date(2026, 11, 16)
        assert frame["volume"].iloc[0] == 118000

    def test_normalize_history_empty_frame_returns_empty_schema(self):
        frame = fmd._normalize_history(ticker="BTC-USD", history=pd.DataFrame())
        assert frame.empty
        assert "trade_date" in frame.columns
        assert "close_price" in frame.columns


class TestFetch:
    @patch("src.ingestion.fetch_market_data.yf.Ticker")
    def test_fetch_ticker_returns_normalized_history(self, mock_ticker_cls):
        mock_ticker_cls.return_value.history.return_value = _history_frame()

        frame = fmd.fetch_ticker(ticker="AAPL", lookback_days=10)

        mock_ticker_cls.return_value.history.assert_called_once()
        assert mock_ticker_cls.return_value.history.call_args.kwargs["period"] == "10d"
        assert frame["ticker"].tolist() == ["AAPL", "AAPL"]
        assert len(frame) == 2

    @patch("src.ingestion.fetch_market_data.yf.Ticker")
    def test_fetch_ticker_retries_transient_connection_error(self, mock_ticker_cls):
        mock_ticker_cls.return_value.history.side_effect = [ConnectionError("transient"), _history_frame()]

        frame = fmd._fetch_history_with_backoff(ticker="MSFT", period="30d")

        assert frame is not None
        assert mock_ticker_cls.return_value.history.call_count == 2

    @patch("src.ingestion.fetch_market_data.fetch_ticker")
    def test_fetch_market_data_dedups_across_tickers(self, mock_fetch_ticker):
        mock_fetch_ticker.side_effect = [
            fmd._normalize_history(ticker="AAPL", history=_history_frame()),
            fmd._normalize_history(ticker="MSFT", history=_history_frame()),
        ]

        df = fmd.fetch_market_data(tickers=["aapl", "msft"], lookback_days=5)

        assert mock_fetch_ticker.call_count == 2
        assert set(df["ticker"].unique().tolist()) == {"AAPL", "MSFT"}


class TestBigQueryUpsert:
    @patch("src.ingestion.fetch_market_data.bigquery.Client")
    def test_upsert_market_ticks_runs_ddl_upsert(self, mock_client_cls):
        client = MagicMock()
        mock_client_cls.return_value = client

        rows = fmd.upsert_market_ticks(df=_normalized_frame(), project_id="test-project")

        client.get_table.assert_called_once()
        client.load_table_from_dataframe.assert_called_once()
        client.query.assert_called_once()

        upsert_sql = client.query.call_args.args[0]
        assert upsert_sql.lstrip().upper().startswith("CREATE OR REPLACE TABLE")
        assert "market_ticks_staging" in upsert_sql
        assert "ROW_NUMBER()" in upsert_sql
        assert rows == len(_normalized_frame())

    @patch("src.ingestion.fetch_market_data.bigquery.Client")
    def test_upsert_market_ticks_uses_raw_table_id(self, mock_client_cls):
        client = MagicMock()
        mock_client_cls.return_value = client

        fmd.upsert_market_ticks(df=_normalized_frame(), project_id="test-project")

        assert (
            client.get_table.call_args.args[0] == "test-project.marketpulse_raw.market_ticks"
        )

    def test_run_ingestion_skips_upsert_when_no_data(self, monkeypatch):
        monkeypatch.setattr(fmd, "fetch_market_data", lambda *args, **kwargs: pd.DataFrame(columns=fmd.RAW_COLUMNS))

        assert fmd.run_ingestion(tickers=["AAPL"], lookback_days=5, project_id="p") == 0
