{{ source('marketpulse_raw', 'market_ticks') }}

SELECT
    CAST(ticker AS STRING) AS ticker,
    CAST(trade_date AS DATE) AS trade_date,
    CAST(open_price AS FLOAT64) AS open_price,
    CAST(high_price AS FLOAT64) AS high_price,
    CAST(low_price AS FLOAT64) AS low_price,
    CAST(close_price AS FLOAT64) AS close_price,
    CAST(volume AS INT64) AS volume,
    CAST(source AS STRING) AS source
FROM (
    SELECT
        ticker,
        trade_date,
        open_price,
        high_price,
        low_price,
        close_price,
        volume,
        source,
        ROW_NUMBER() OVER (
            PARTITION BY ticker, trade_date
            ORDER BY source DESC
        ) AS row_num
    FROM {{ source('marketpulse_raw', 'market_ticks') }}
) AS deduplicated
WHERE row_num = 1
