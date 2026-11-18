# MarketPulse — Project Notes

> **Living state file.** This document is updated automatically at the end of **every** build step.
> A brand-new AI agent session should read this file first to seamlessly continue the build.

---

## 1. Project Overview & Architecture

### 1.1 Vision

**MarketPulse** is a **100% zero-cost ($0 / ₹0)** Financial Market Data & Anomaly Detection platform.
It fetches free public market data (via `yfinance`), lands it in Google BigQuery (Free Tier / Sandbox),
transforms it through a Medallion-to-Star-Schema dbt architecture, runs unsupervised ML anomaly
detection (IsolationForest) with local MLflow tracking, and serves an interactive Streamlit dashboard.

### 1.2 Tech Stack

| Layer | Technology | Cost |
|---|---|---|
| Language | Python 3.11 | Free |
| CI/CD | GitHub Actions (cron + PR quality gates) | Free |
| Ingestion | `yfinance`, `pandas`, `tenacity`, `google-cloud-bigquery` | Free |
| Orchestration | GitHub Actions scheduled workflow | Free |
| Warehouse | Google BigQuery **Sandbox** (`marketpulse_raw`, `marketpulse_analytics`) | Free |
| Transformations | `dbt Core` (`dbt-bigquery`) | Free |
| ML | `scikit-learn` (IsolationForest), `MLflow` (SQLite tracking) | Free |
| Serving | `Streamlit` + `Plotly` (BigQuery backend) | Free |
| Alerting | Slack/Discord webhook (`alerts.py`) | Free |

### 1.3 Data Flow Diagram

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

### 1.4 BigQuery Dataset & Table Schemas

**Dataset `marketpulse_raw`**
- Table `market_ticks` — partitioned by `trade_date` (DATE field-based partitioning), clustered by `ticker`.

**Dataset `marketpulse_analytics`**
- `dim_assets` — star dimension (`dim_assets`: ticker + asset_class), clustered by `ticker`.
- `fact_daily_metrics` — daily OHLCV aggregates, partitioned by `DATE`, clustered by `ticker`, with
  computed features (7-day moving average, rolling volatility, daily returns, volume z-score).
- `fact_anomaly_scores` — per-ticker daily ML risk score (0–100) + `is_anomaly` boolean.

### 1.5 Key FAANG Design Decisions

- **Idempotency:** BigQuery `MERGE` upserts keyed on `(ticker, trade_date)`; no duplicate rows.
- **Feature store in dbt:** features computed inside SQL in `int_market_features` to prevent
  training-serving skew.
- **Zero-cost constraints:** BigQuery Sandbox only, free-tier GitHub Actions, local SQLite MLflow,
  `yfinance` public data, Streamlit Community Cloud free tier — **no credit card required**.

### 1.6 Phase Roadmap

- **Phase 1 (done):** Repo scaffolding, config, CI/CD, notes — ✅ Complete.
- **Phase 2 (done):** Utils (logger/alerts), ingestion, pytest — ✅ Complete.
- **Phase 3 (done):** dbt Medallion → Star schema — ✅ Complete.
- **Phase 4 (done):** ML, dashboard, docs — ✅ Complete.
- **Phase 5 (in progress):** Deployment verification & operations — runbook created.

---

## 2. Completed Features & File Manifest

### Phase 1 — Scaffold & CI/CD — ✅ COMPLETE

- [x] Complete repository folder structure (src/, tests/, dbt/, dashboard/, .github/workflows/, …).
- [x] `PROJECT_NOTES.md` initialized with full architecture + Phase 1–4 roadmap.
- [x] `requirements.txt` created.
- [x] `.env.example` created.
- [x] `.gitignore` created.
- [x] `.github/workflows/pipeline.yml` created (pytest → dbt parse → ingest → score, cron + dispatch; dbt steps use `working-directory: dbt`).

### Phase 2 — Utils, Ingestion & Tests — ✅ COMPLETE

- [x] `src/utils/logger.py` — structured JSON logging via `logging.config.dictConfig`.
- [x] `src/utils/alerts.py` — webhook alerting (Slack/Discord) + `check_risk_spike` high-risk trigger.
- [x] `src/ingestion/fetch_market_data.py` — `yfinance` OHLCV fetch, `tenacity` exponential backoff,
      idempotent BigQuery staging LOAD `WRITE_TRUNCATE` + `MERGE` upsert into raw.
- [x] `tests/test_ingestion.py` — pytest suite (normalization, retries, dedup, MERGE upsert) — **8/8 PASSED**.

### Phase 3 — dbt Medallion → Star Schema — ✅ COMPLETE
- [x] `dbt_project.yml` — dbt project config (`marketpulse`, staging view / intermediate table / marts table).
- [x] `dbt/profiles.yml` — BigQuery (`dbt-bigquery`) profiles (`dev`/`prod`, service-account auth, env-var driven).
- [x] `dbt/models/staging/sources.yml` — source `marketpulse_raw.market_ticks`.
- [x] `dbt/models/staging/stg_market_ticks.sql` — dedup via `ROW_NUMBER()`, type casting, standardization.
- [x] `dbt/models/intermediate/int_market_features.sql` — 7-day MA, rolling vol, daily returns, volume z-score.
- [x] `dbt/models/marts/dim_assets.sql` — gold dimension (`dim_assets`).
- [x] `dbt/models/marts/fact_daily_metrics.sql` — gold fact with features (`fact_daily_metrics`).
- [x] `dbt/models/marts/schema.yml` — data contracts: `unique`, `not_null`, `relationships` tests.
- [x] Validated with `dbt parse` (4 models, 6 tests, 1 source) + BigQuery-dialect SQL check via sqlglot.

### Phase 4 — ML, Dashboard, Docs — ✅ COMPLETE

- [x] `src/ml/detect_anomalies.py` — IsolationForest (fit + score), MLflow (SQLite, params/metrics/model logging),
      risk score normalization (0–100), idempotent MERGE into `fact_anomaly_scores`, high-risk webhook trigger (>85).
- [x] `dashboard/app.py` — Streamlit + Plotly candlesticks, risk gauges, ticker filters, anomaly alerts feed.
- [x] `README.md` — comprehensive setup instructions (GCP Sandbox, GitHub Secrets, Streamlit Cloud).
- [x] Finalize `PROJECT_NOTES.md` — marking all build tasks complete.

### Phase 5 — Deployment & Operations — 🚧 IN PROGRESS

- [x] `docs/DEPLOYMENT.md` — deployment runbook + post-deployment verification checklist + rollback notes.
- [ ] Execute deployment verification checklist (GCP service account creation, BQ tables, secrets, first run).

---

## 3. Remaining Tasks

Exact breakdown of files and features still left to build (as of Phase 4 completion):

1. **Phase 2** — ✅ COMPLETE
   - `src/utils/logger.py` — structured JSON logging via `logging.config.dictConfig`.
   - `src/utils/alerts.py` — Slack/Discord webhook alerting with severity levels.
   - `src/ingestion/fetch_market_data.py` — `yfinance` OHLCV fetch, `tenacity` exponential backoff,
     idempotent BigQuery staging LOAD `WRITE_TRUNCATE` + `MERGE` upsert into `marketpulse_raw.market_ticks`.
   - `tests/test_ingestion.py` — pytest suite with mocked `yfinance` + BigQuery client (**8/8 PASSED**).

2. **Phase 3** — ✅ COMPLETE
   - `dbt_project.yml`, `dbt/profiles.yml` — created and validated via `dbt parse`.
   - `dbt/models/staging/sources.yml`, `dbt/models/staging/stg_market_ticks.sql` — source + dedup staging.
   - `dbt/models/intermediate/int_market_features.sql` — 7-day MA, rolling vol, daily returns, volume z-score.
   - `dbt/models/marts/dim_assets.sql`, `dbt/models/marts/fact_daily_metrics.sql`
     - `dbt/models/marts/schema.yml` (data contracts: `unique`, `not_null`, `relationships` tests).

3. **Phase 4** — ✅ COMPLETE
   - `src/ml/detect_anomalies.py` — IsolationForest, MLflow SQLite tracking, risk score 0–100,
     `fact_anomaly_scores` MERGE, high-risk webhook trigger (>85).
   - `dashboard/app.py` — Streamlit + Plotly candlesticks, risk gauges, ticker filter, alerts feed.
   - `README.md` — GCP Sandbox setup, GitHub Secrets, Streamlit Cloud deployment.
   - Finalize `PROJECT_NOTES.md`.

4. **Phase 5** — 🚧 IN PROGRESS
   - `docs/DEPLOYMENT.md` — deployment runbook + verification checklist + rollback notes.
   - Execute deployment verification checklist (service account, BQ tables, secrets, first run).

---

## 4. Known Bugs, Edge Cases & Technical Debt

- **BigQuery Sandbox DML quotas:** Free tier limits on long-running queries / partitions; consider
  batching `MERGE` operations.
- **yfinance rate limits / unauthenticated usage:** may throttle; mitigated by `tenacity` backoff.
- **MLflow default tracking URI:** SQLite file per-run; must be set via `MLFLOW_TRACKING_URI`.
- **DBT schema naming:** staging/ intermediate/ mart schemas under `marketpulse_analytics`.
- **BigQuery `MERGE` for daily partitions:** date-partition overwrite strategy must be idempotent.
- **dbt connection failure (`'NoneType' object has no attribute 'close'`):** caused by missing/invalid
  GCP credentials. Valid SA key found at `D:\MarketPulse\secrets\marketpulse-sa.json` (project
  `marketpulse-demo`) — must set `GCP_PROJECT_ID=marketpulse-demo` and `GCP_SA_KEY_PATH` in the same
  shell session before running dbt commands. `git` binary missing locally causes an unrelated dbt check
  failure (environmental). The failure persisted even with valid env wiring set (incl. `GOOGLE_APPLICATION_CREDENTIALS`),
  indicating an environment-level auth/network constraint rather than local misconfiguration.

---

## 5. Next Session Bootstrap Instructions

1. Read this file (`PROJECT_NOTES.md`) first.
2. Current phase: **Phase 5 — Deployment & Operations (in progress)**. Next: execute deployment verification checklist from `docs/DEPLOYMENT.md`.
3. Respect the sequential one-phase-per-turn rule.
4. At the end of every step, update this file (Completed/Remaining checklists, Known Bugs, Bootstrap).

---

*Last updated: Phase 5 (deployment runbook created) — 2026-11-18*
