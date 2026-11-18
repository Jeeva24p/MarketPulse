# 🚀 MarketPulse — Deployment & Operations Runbook

This document is the authoritative guide for deploying and verifying the **MarketPulse** platform.

---

## 1. Deployment Overview

| Component | Technology | Deployment Target |
|---|---|---|
| Ingestion + ML scoring + dbt | GitHub Actions (cron `0 2 * * 1`, manual dispatch) | GitHub-hosted runner |
| Dashboard | Streamlit Cloud (free tier) or self-hosted | Streamlit |
| MLflow tracking | Local SQLite (`mlflow.db`, artifacts in `mlruns/`) | Container / local |
| BigQuery | BigQuery Sandbox (free tier) | GCP |

---

## 2. Pre-Deployment Checklist

- [ ] GCP project created (`GCP_PROJECT_ID`)
- [ ] BigQuery API enabled
- [ ] BigQuery datasets created: `marketpulse_raw`, `marketpulse_analytics`
- [ ] BigQuery tables created (see DDL in `README.md`):
  - `marketpulse_raw.market_ticks`
  - `marketpulse_analytics.fact_daily_metrics`
  - `marketpulse_analytics.fact_anomaly_scores`
- [ ] Service account created with:
  - `roles/bigquery.dataEditor`
  - `roles/bigquery.jobUser`
- [ ] Service account JSON key downloaded (`*.sa.json`)
- [ ] `.env` populated (`GCP_PROJECT_ID`, `GCP_SA_KEY_PATH`, `ALERT_WEBHOOK_URL`, `TICKERS`, `LOOKBACK_DAYS`, `MLFLOW_TRACKING_URI`)
- [ ] GitHub Secrets configured:
  - `GCP_PROJECT_ID`
  - `GCP_SA_KEY`
  - `ALERT_WEBHOOK_URL`
- [ ] dbt dependencies resolved (`cd dbt && dbt deps`)
- [ ] Streamlit Cloud app connected to repo (`dashboard/app.py`)

---

## 3. Deployment Steps

### 3.1 Database Layer
```bash
cd dbt
dbt deps
dbt run
dbt test
```

### 3.2 Ingestion
```bash
python -m src.ingestion.fetch_market_data
```

### 3.3 ML Anomaly Scoring
```bash
python -m src.ml.detect_anomalies
```

### 3.4 Dashboard
```bash
streamlit run dashboard/app.py
```

### 3.5 CI/CD (GitHub Actions)
- Manual dispatch via `workflow_dispatch`
- Scheduled: `0 2 * * 1` (Monday 02:00 UTC)

---

## 4. Post-Deployment Verification Checklist

Verified locally on 2026-11-18 against project `marketpulse-demo` (all items below passed).

1. [x] `dbt test` passes (staging/fact contracts: unique, not_null, relationships + grain test).
2. [x] `python -m src.ingestion.fetch_market_data` completes with rows upserted (180 rows / 6 tickers).
3. [x] `python -m src.ml.detect_anomalies` completes; MLflow run appears in the SQLite store.
4. [x] `fact_anomaly_scores` has rows for the tickers in `TICKERS` (180 rows, 2 anomalies/ticker).
5. [x] Dashboard renders candlesticks, gauge, and alerts feed (Streamlit `AppTest`, no exceptions).
6. [x] Critical risk spike alert path fires (risk > 85) or no-ops cleanly when no webhook is set.

> **Sandbox note:** BigQuery's free tier rejects all DML (`MERGE`/`INSERT`/`UPDATE`). Both the
> ingestion and ML write-backs use `CREATE OR REPLACE TABLE ... AS SELECT` with `ROW_NUMBER()`
> dedup, which is DDL and allowed on the free tier.

## 5. Rollback & Operations

- Re-run dbt steps to rebuild gold tables: `dbt run --full-refresh`
- Re-run ingestion to rebuild the raw table: the DDL upsert re-reads the target, unions the fresh
  staging batch, and keeps one row per `(ticker, trade_date)` — safe to repeat.
- MLflow runs append-only; the SQLite store can be reset by deleting `mlflow.db` (artifacts in
  `mlruns/`).
- Alerting: if `ALERT_WEBHOOK_URL` is empty, alerts no-op (by design).

---

*MarketPulse Deployment Runbook — Phase 5*
