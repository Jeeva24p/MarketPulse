"""Validate MarketPulse dbt SQL statements against the BigQuery dialect via sqlglot."""

import re

import sqlglot

MERGE_SQL = """
MERGE `test-project.marketpulse_raw.market_ticks` AS tgt
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
    FROM `test-project.marketpulse_raw.market_ticks_staging`
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

SELECT_SQL = """
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
FROM with_volume_z
"""

for name, sql in (("MERGE", MERGE_SQL.strip()), ("SELECT", SELECT_SQL.strip())):
    parsed = sqlglot.parse_one(sql, read="bigquery")
    print(f"{name} SQL parsed OK -> dialect={parsed.args.get('dialect', 'bigquery')}")

print("DBT SQL VALIDATION PASSED")
