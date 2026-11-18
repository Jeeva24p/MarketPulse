-- Composite grain guard for fact_daily_metrics (ticker + trade_date).
-- dbt's built-in `unique` test does not accept a column list here, so this
-- singular test asserts the grain directly: it must return zero rows.

SELECT
    ticker,
    trade_date,
    COUNT(*) AS row_count
FROM {{ ref('fact_daily_metrics') }}
GROUP BY ticker, trade_date
HAVING COUNT(*) > 1
