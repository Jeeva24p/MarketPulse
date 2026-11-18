SELECT DISTINCT
    ticker,
    CASE
        WHEN ticker = 'BTC-USD' THEN 'CRYPTO'
        ELSE 'EQUITY'
    END AS asset_class
FROM {{ ref('int_market_features') }}
