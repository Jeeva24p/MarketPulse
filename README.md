# 📈 MarketPulse

**MarketPulse** is a **100% zero-cost ($0 / ₹0)** Financial Market Data & Anomaly Detection platform built to FAANG-grade engineering standards.

It ingests free public market data, lands it in Google BigQuery (Free Tier / Sandbox), transforms it through a Medallion-to-Star-Schema dbt architecture, runs unsupervised ML anomaly detection (IsolationForest) with local MLflow tracking, and serves an interactive Streamlit dashboard.

---

## 🏗️ Architecture

```
GitHub Actions Cron (Mon 02:00 UTC)
        │
        ▼
┌─────────────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│  src/ingestion/      │────▶│  BigQuery        │────▶│  dbt (staging →   │
│  fetch_market_data. │     │  marketpulse_   │     │  intermediate →    │
│  (yfinance + BQ     │     │  raw             │     │  marts)            │
│   MERGE upsert)      │     │  .market_ticks  │     │                     │
└─────────────────────┘     └──────────────────┘     └─────────────────────┘
                                                                 │
                                                                 ▼
┌─────────────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│  src/ml/             │────▶│  Gold tables in  │────▶│  fact_anomaly_      │
│  detect_anomalies.  │     │  marketpulse_    │     │  scores (BQ MERGE)  │
│  (IsolationForest,  │     │  analytics        │     │                     │
│   MLflow → SQLite,  │     │                  │     │                     │
│   BQ MERGE)          │     └──────────────────┘     └─────────────────────┘
└─────────────────────┘              │
        │                          ▼
        ▼                   ┌─────────────────────┐
   Streamlit + Plotly     │  risk spikes >85    │
   dashboard/app.py      │  → Discord/Slack    │
                        │  webhook alert      │
                        └─────────────────────┘
```

1. **Ingestion** (`src/ingestion/fetch_market_data.py`): `yfinance` OHLCV → normalize → dedup → staging `WRITE_TRUNCATE` → BigQuery **`MERGE`** upsert into `marketpulse_raw.market_ticks`.
2. **Transformation** (dbt): staging (`stg_market_ticks` – `ROW_NUMBER` dedup) → intermediate (`int_market_features` – 7-day MA, rolling vol, returns, volume z-score) → marts (`dim_assets`, `fact_daily_metrics`).
3. **ML Detection** (`src/ml/detect_anomalies.py`): IsolationForest per ticker on gold features → normalized risk score (0–100) → MLflow (SQLite) tracking → MERGE into `marketpulse_analytics.fact_anomaly_scores` → critical risk spike alerts.
4. **Serving** (`dashboard/app.py`): Streamlit + Plotly candlesticks, risk gauges, ticker filters, anomaly alerts feed.

---

## 🧰 Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| CI/CD | GitHub Actions (cron + PR quality gates) |
| Ingestion | `yfinance`, `pandas`, `tenacity`, `google-cloud-bigquery` |
| Orchestration | GitHub Actions scheduled workflow |
| Warehouse | Google BigQuery **Sandbox** (`marketpulse_raw`, `marketpulse_analytics`) |
| Transformations | `dbt Core` (`dbt-bigquery`) |
| ML | `scikit-learn` (IsolationForest), `MLflow` (SQLite tracking) |
| Serving | `Streamlit` + `Plotly` (BigQuery backend) |
| Alerting | Slack/Discord webhook (`src/utils/alerts.py`) |
| Quality | `pytest` |

---

## 💰 Zero-Cost Architecture

The platform runs **strictly within free tiers** and requires **no credit card**:

- **BigQuery**: Free Tier / Sandbox (limited queries, enough for this demo).
- **GitHub Actions**: Free for public repos / generous free minutes for private.
- **yfinance**: Free public API.
- **dbt**: Open source.
- **MLflow**: Local SQLite tracking.
- **Streamlit**: Community Cloud free tier.

---

## 📁 Repository Structure

```
MarketPulse/
├── PROJECT_NOTES.md
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── .github/workflows/pipeline.yml
├── src/
│   ├── utils/            # logger.py (JSON), alerts.py (webhooks)
│   ├── ingestion/        # fetch_market_data.py (yfinance + MERGE)
│   └── ml/               # detect_anomalies.py (IsolationForest + MLflow)
├── tests/                # pytest suite
├── dbt/
│   ├── dbt_project.yml
│   ├── profiles.yml
│   └── models/
│       ├── staging/     # sources.yml, stg_market_ticks.sql
│       ├── intermediate/# int_market_features.sql
│       └── marts/       # dim_assets.sql, fact_daily_metrics.sql, schema.yml
├── dashboard/
│   └── app.py           # Streamlit + Plotly
└── scripts/             # utility scripts (SQL validation)
```

---

## 🗄️ Data Model (BigQuery)

### `marketpulse_raw` — dataset
- **`market_ticks`** — raw OHLCV ticks. Partitioned by `trade_date`, clustered by `ticker`.

### `marketpulse_analytics` — dataset
- **`dim_assets`** — star dimension (ticker, asset_class).
- **`fact_daily_metrics`** — daily fact (ticker + trade_date grain) with engineered features.
- **`fact_anomaly_scores`** — ML risk scores (ticker, trade_date, risk_score, is_anomaly, anomaly_score).

DDL:

```sql
CREATE SCHEMA IF NOT EXISTS `your-gcp-project.marketpulse_raw`;
CREATE SCHEMA IF NOT EXISTS `your-gcp-project.marketpulse_analytics`;

CREATE TABLE IF NOT EXISTS `your-gcp-project.marketpulse_raw.market_ticks` (
    ticker STRING NOT NULL,
    trade_date DATE NOT NULL,
    open_price FLOAT64 NOT NULL,
    high_price FLOAT64 NOT NULL,
    low_price FLOAT64 NOT NULL,
    close_price FLOAT64 NOT NULL,
    volume INT64 NOT NULL,
    source STRING,
) PARTITION BY trade_date
CLUSTER BY ticker;

CREATE TABLE IF NOT EXISTS `your-gcp-project.marketpulse_analytics.fact_daily_metrics` (
    ticker STRING NOT NULL,
    trade_date DATE NOT NULL,
    open_price FLOAT64 NOT NULL,
    high_price FLOAT64 NOT NULL,
    low_price FLOAT64 NOT NULL,
    close_price FLOAT64 NOT NULL,
    volume INT64 NOT NULL,
    daily_return FLOAT64,
    seven_day_ma_close FLOAT64,
    seven_day_volatility FLOAT64,
    volume_z_score FLOAT64,
) PARTITION BY trade_date
CLUSTER BY ticker;

CREATE TABLE IF NOT EXISTS `your-gcp-project.marketpulse_analytics.fact_anomaly_scores` (
    ticker STRING NOT NULL,
    trade_date DATE NOT NULL,
    risk_score FLOAT64 NOT NULL,
    is_anomaly BOOL,
    anomaly_score FLOAT64,
) PARTITION BY trade_date
CLUSTER BY ticker;
```

---

## 🚀 Getting Started

### 1. Prerequisites
- Python 3.11+
- GCP project with **BigQuery Sandbox** enabled
- GitHub repo (for Actions)

### 2. GCP Setup (BigQuery Sandbox)
1. Create GCP project → enable **BigQuery API**.
2. Create datasets `marketpulse_raw` and `marketpulse_analytics`.
3. Create service account with **BigQuery Data Editor + Job User** roles → download JSON key.
4. Set env vars (`GCP_PROJECT_ID`, `GCP_SA_KEY_PATH`, etc.).

### 3. Local Configuration
```bash
cp .env.example .env
# edit .env with your GCP project / webhook / params
```

### 4. Install & Run
```bash
pip install -r requirements.txt
dbt deps
dbt run
dbt test
python -m src.ingestion.fetch_market_data
python -m src.ml.detect_anomalies
streamlit run dashboard/app.py
```

### 5. GitHub Secrets (for Actions)
- `GCP_PROJECT_ID`
- `GCP_SA_KEY` (service account JSON)
- `ALERT_WEBHOOK_URL` (Slack/Discord)

### 6. Deployment
- **Dashboard**: Streamlit Community Cloud (`streamlit run dashboard/app.py`) or self-host.
- **Pipeline**: GitHub Actions cron (`0 2 * * 1`) + manual dispatch.

---

*MarketPulse — built for zero-cost, FAANG-grade financial data engineering.*
