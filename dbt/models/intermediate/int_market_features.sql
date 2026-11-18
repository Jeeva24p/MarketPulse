WITH base AS (
    SELECT
        ticker,
        trade_date,
        open_price,
        high_price,
        low_price,
        close_price,
        volume
    FROM {{ ref('stg_market_ticks') }}
)

, lagged AS (
    SELECT
        ticker,
        trade_date,
        open_price,
        high_price,
        low_price,
        close_price,
        volume,
        LAG(close_price) OVER (
            PARTITION BY ticker
            ORDER BY trade_date
        ) AS prev_close
    FROM {{ ref('stg_market_ticks') }}
)

, with_daily_return AS (
    SELECT
        ticker,
        trade_date,
        open_price,
        high_price,
        low_price,
        close_price,
        volume,
        CASE
            WHEN prev_close IS NULL OR prev_close = 0 THEN NULL
            ELSE close_price / prev_close - 1.0
        END AS daily_return
    FROM lagged
)

, with_rolling AS (
    SELECT
        ticker,
        trade_date,
        open_price,
        high_price,
        low_price,
        close_price,
        volume,
        daily_return,
        AVG(close_price) OVER (
            PARTITION BY ticker
            ORDER BY trade_date
            ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
        ) AS seven_day_ma_close,
        STDDEV_SAMP(daily_return) OVER (
            PARTITION BY ticker
            ORDER BY trade_date
            ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
        ) AS seven_day_volatility
    FROM with_daily_return
)

, with_volume_stats AS (
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
        AVG(volume) OVER (
            PARTITION BY ticker
            ORDER BY trade_date
            ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
        ) AS volume_avg_30d,
        STDDEV_SAMP(volume) OVER (
            PARTITION BY ticker
            ORDER BY trade_date
            ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
        ) AS volume_std_30d
    FROM with_rolling
)

, with_volume_z AS (
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
        CASE
            WHEN volume_avg_30d IS NULL OR volume_std_30d IS NULL OR volume_std_30d = 0 THEN 0.0
            ELSE (volume - volume_avg_30d) / volume_std_30d
        END AS volume_z_score
    FROM with_volume_stats
)

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
