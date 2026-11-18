# 🚀 MarketPulse — Deployment & Operations Runbook

This document is the authoritative guide for deploying and verifying the **MarketPulse** platform.

---

## 1. Deployment Overview

| Component | Technology | Deployment Target |
|---|---|---|
| Ingestion + ML scoring + dbt | GitHub Actions (cron `0 2 * * 1`, manual dispatch) | GitHub-hosted runner |
| Dashboard | Streamlit Cloud (free tier) or self-hosted | Streamlit |
| MLflow tracking | Local SQLite (`mlruns/`) | Container / local |
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

1. [ ] `dbt test` passes (staging/fact contracts: unique, not_null, relationships).
2. [ ] `python -m src.ingestion.fetch_market_data` completes with rows upserted.
3. [ ] `python -m src.ml.detect_anomalies` completes; MLflow run appears in SQLite store.
4. [ ] `fact_anomaly_scores` has rows for the tickers in `TICKERS`.
5. [ ] Dashboard renders candlesticks, gauge, and alerts feed.
6. [ ] Critical risk spike alert fires webhook (risk > 85) or is properly skipped.

---

## 5. Rollback & Operations

- Re-run dbt steps to rebuild gold tables: `dbt run --full-refresh`
- Delete/recreate staging + MERGE again (idempotent design supports safe re-runs).
- MLflow runs append-only; SQLite store can be reset via `MLFLOW_TRACKING_URI=sqlite:///<path>`.
- Alerting: if `ALERT_WEBHOOK_URL` is empty, alerts no-op (by design).

---

*MarketPulse Deployment Runbook — Phase 5*
