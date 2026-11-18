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
FROM {{ ref('int_market_features') }}
