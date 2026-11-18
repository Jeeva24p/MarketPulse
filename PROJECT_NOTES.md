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
│   DDL upsert)       │     │  .market_ticks  │     │                     │
└─────────────────────┘     └──────────────────┘     └─────────────────────┘
                                                                 │
                                                                 ▼
┌─────────────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│  src/ml/             │────▶│  Gold tables in  │────▶│  fact_anomaly_      │
│  detect_anomalies.  │     │  marketpulse_    │     │  scores (DDL        │
│  (IsolationForest,  │     │  analytics        │     │  upsert)            │
│   MLflow → SQLite,  │     │                  │     │                     │
│   BQ DDL upsert)     │     └──────────────────┘     └─────────────────────┘
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

- **Idempotency:** BigQuery **DDL upserts** (`CREATE OR REPLACE TABLE ... AS SELECT` with
  `ROW_NUMBER()` dedup) keyed on `(ticker, trade_date)`; no duplicate rows.
  **BigQuery Sandbox rejects all DML**, so `MERGE`/`INSERT` are not usable at $0 — this was
  confirmed against the live project (see §4).
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
      idempotent BigQuery staging LOAD `WRITE_TRUNCATE` + DDL upsert into raw.
- [x] `tests/test_ingestion.py` — pytest suite (normalization, retries, dedup, DDL upsert) — **8/8 PASSED**.

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
      risk score normalization (0–100), idempotent DDL upsert into `fact_anomaly_scores`, high-risk webhook trigger (>85).
- [x] `dashboard/app.py` — Streamlit + Plotly candlesticks, risk gauges, ticker filters, anomaly alerts feed.
- [x] `README.md` — comprehensive setup instructions (GCP Sandbox, GitHub Secrets, Streamlit Cloud).
- [x] Finalize `PROJECT_NOTES.md` — marking all build tasks complete.

### Phase 5 — Deployment & Operations — 🚧 IN PROGRESS

- [x] `docs/DEPLOYMENT.md` — deployment runbook + post-deployment verification checklist + rollback notes.
- [x] Local E2E verification run (2026-11-18) against project `marketpulse-demo`:
  - [x] GCP auth: service-account key valid, BigQuery reachable (`scripts/check_gcp_credentials.py`).
  - [x] Datasets/tables present: `marketpulse_raw.market_ticks`,
        `marketpulse_analytics.{fact_daily_metrics, fact_anomaly_scores}`.
  - [x] `dbt run` — 4/4 models built (staging view + intermediate/marts tables).
  - [x] `dbt test` — 9/9 tests pass (incl. new singular grain-uniqueness test).
  - [x] `python -m src.ingestion.fetch_market_data` — 180 rows upserted (6 tickers × 30 days).
  - [x] `python -m src.ml.detect_anomalies` — 180 rows scored, 2 anomalies/ticker, MLflow run stored.
  - [x] Dashboard renders (Streamlit `AppTest`: no exceptions, candlestick + gauge + tables).
- [ ] Push verified changes to GitHub.
- [ ] Configure GitHub Secrets (`GCP_PROJECT_ID`, `GCP_SA_KEY`, `ALERT_WEBHOOK_URL`).
- [ ] Trigger first GitHub Actions run (`workflow_dispatch`) and confirm green.
- [ ] Connect Streamlit Community Cloud app to `dashboard/app.py` (+ `gcp_service_account` secret).

---

## 3. Remaining Tasks

Exact breakdown of files and features still left to build (as of Phase 4 completion):

1. **Phase 2** — ✅ COMPLETE
   - `src/utils/logger.py` — structured JSON logging via `logging.config.dictConfig`.
   - `src/utils/alerts.py` — Slack/Discord webhook alerting with severity levels.
   - `src/ingestion/fetch_market_data.py` — `yfinance` OHLCV fetch, `tenacity` exponential backoff,
     idempotent BigQuery staging LOAD `WRITE_TRUNCATE` + DDL upsert into `marketpulse_raw.market_ticks`.
   - `tests/test_ingestion.py` — pytest suite with mocked `yfinance` + BigQuery client (**8/8 PASSED**).

2. **Phase 3** — ✅ COMPLETE
   - `dbt_project.yml`, `dbt/profiles.yml` — created and validated via `dbt parse`.
   - `dbt/models/staging/sources.yml`, `dbt/models/staging/stg_market_ticks.sql` — source + dedup staging.
   - `dbt/models/intermediate/int_market_features.sql` — 7-day MA, rolling vol, daily returns, volume z-score.
   - `dbt/models/marts/dim_assets.sql`, `dbt/models/marts/fact_daily_metrics.sql`
     - `dbt/models/marts/schema.yml` (data contracts: `unique`, `not_null`, `relationships` tests).

3. **Phase 4** — ✅ COMPLETE
   - `src/ml/detect_anomalies.py` — IsolationForest, MLflow SQLite tracking, risk score 0–100,
     `fact_anomaly_scores` DDL upsert, high-risk webhook trigger (>85).
   - `dashboard/app.py` — Streamlit + Plotly candlesticks, risk gauges, ticker filter, alerts feed.
   - `README.md` — GCP Sandbox setup, GitHub Secrets, Streamlit Cloud deployment.
   - Finalize `PROJECT_NOTES.md`.

4. **Phase 5** — 🚧 IN PROGRESS
   - [x] `docs/DEPLOYMENT.md` — deployment runbook + verification checklist + rollback notes.
   - [x] Execute local deployment verification checklist (service account, BQ tables, dbt, ingest, score, dashboard).
   - [ ] Push to GitHub and configure repository secrets.
   - [ ] First scheduled/manual GitHub Actions run.
   - [ ] Streamlit Cloud deployment.

---

## 4. Known Bugs, Edge Cases & Technical Debt

### Resolved on 2026-11-18 (Phase 5 verification run)

- **`dbt` connection failure (`'NoneType' object has no attribute 'close'`) — ROOT CAUSE FOUND.**
  It was *not* an environment/auth problem. Two profile bugs in `dbt/profiles.yml`:
  1. The service-account path was set via `service_account_file:`, which dbt-bigquery does not
     recognise (`keyfile:` is the supported field). `credentials.keyfile` stayed `None`, producing
     the misleading `'NoneType' object has no attribute 'close'` message.
  2. `database:` was omitted, and dbt-bigquery then injects the **local ADC default project**
     (`data-vault-pipeline`), which silently overrides `project_id`. Both are now set explicitly
     to `env_var('GCP_PROJECT_ID')`.
- **BigQuery Sandbox rejects all DML.** `MERGE` fails with
  `403 ... DML queries are not allowed in the free tier`, so the original MERGE-based idempotency
  design could never run at $0. Ingestion + ML upserts now use
  `CREATE OR REPLACE TABLE ... AS SELECT` (DDL) with `ROW_NUMBER()` dedup and a staging-priority
  rank. Verified working on the free tier.
- **Stray/missing CTE fragments in dbt models.** `stg_market_ticks.sql` had a duplicate
  `{{ source(...) }}` line that corrupted the compiled DDL, and `int_market_features.sql` was
  missing its opening `WITH base AS (...)` block. Both fixed; `dbt run` now passes.
- **Invalid dbt test config in `marts/schema.yml`.** Model-level `not_null` with a `columns:` list
  and a `relationships` test without `column_name` both failed to compile. Replaced with per-column
  `not_null` tests plus a singular grain test
  (`dbt/tests/assert_fact_daily_metrics_grain_unique.sql`). Note: dbt's built-in `unique` test
  does **not** accept a column list — it renders an invalid array literal.
- **`yfinance` API drift.** `history(..., progress=False)` raises
  `TypeError: PriceHistory.history() got an unexpected keyword argument 'progress'` on yfinance 1.8+.
  Removed the argument.
- **`_normalize_history` lost `trade_date`.** Columns were lowercased *before* `reset_index()`, so
  the index name `Date` never matched and `trade_date` was missing. Lowercasing now happens after
  the reset.
- **MLflow URI wrote a file named `mlruns`.** `sqlite:///mlruns` created a SQLite *file* that then
  blocked the artifact directory (`FileNotFoundError: ...\mlruns\0`). Standardised on
  `sqlite:///mlflow.db` with artifacts in `mlruns/`.
- **`client.query(query, params=...)` removed.** `google-cloud-bigquery` 3.x dropped `params`;
  ingestion/ML/dashboard now pass `QueryJobConfig(query_parameters=[ScalarQueryParameter(...)])`.
- **`alerts.py` logged with a string level.** `SEVERITY_TO_LOG_LEVEL` mapped to `"CRITICAL"` etc.,
  so `logger.log()` raised `TypeError: level must be an integer`. Now maps to `logging.*` ints.
- **`run_detection` referenced an undefined `resolved_table`.**
- **Plotly gauge crash.** `go.Indicator(type="gauge", progressBar=...)` fails because `type` is
  read-only; replaced with `mode="gauge+number"` + threshold marker.

### Open

- **Full-table rewrites:** the DDL upsert re-reads and rewrites the whole target table each run.
  Fine at current volume (180 rows / 30-day window); revisit with partitioned overwrite
  (`WRITE_TRUNCATE` on a partition decorator) if the history window grows.
- **`yfinance` rate limits / unauthenticated usage:** may throttle; mitigated by `tenacity` backoff.
- **`ALERT_WEBHOOK_URL` is empty locally**, so alert delivery no-ops by design.
- **`dbt/.user.yml` and `.gitignore` were not tracked correctly** — `.gitignore` ignored itself and
  `.user.yml` was committed. Both corrected (see working tree).
- **Dashboard `use_container_width`** is deprecated in current Streamlit (`width='stretch'` is the
  replacement); still functional, worth migrating.
- **No `packages.yml`** — composite-uniqueness is handled by a singular test rather than
  `dbt_utils.unique_combination_of_columns`, avoiding a package dependency.

---

## 5. Next Session Bootstrap Instructions

1. Read this file (`PROJECT_NOTES.md`) first.
2. Current phase: **Phase 5 — Deployment & Operations (in progress)**. Local E2E verification is
   **complete and green**; what remains is infrastructure wiring:
   - Push the working tree to `origin/master`.
   - Add GitHub Secrets: `GCP_PROJECT_ID`, `GCP_SA_KEY` (full SA JSON), `ALERT_WEBHOOK_URL`.
   - Run the workflow once via `workflow_dispatch` and confirm it is green.
   - Connect Streamlit Community Cloud to `dashboard/app.py` with a `gcp_service_account` secret.
3. Local run recipe (env vars must be set in the same shell session):
   ```powershell
   Get-Content .env | Where-Object { $_ -match '^\s*[^#].*=' } | ForEach-Object { $k,$v = $_ -split '=',2; Set-Item -Path "Env:$($k.Trim())" -Value $v.Trim() }
   python scripts/check_gcp_credentials.py
   python -m src.ingestion.fetch_market_data
   cd dbt; dbt run --profiles-dir .; dbt test --profiles-dir .
   cd ..; python -m src.ml.detect_anomalies
   streamlit run dashboard/app.py
   ```
4. Respect the sequential one-phase-per-turn rule.
5. At the end of every step, update this file (Completed/Remaining checklists, Known Bugs, Bootstrap).

---

*Last updated: Phase 5 (local end-to-end verification passed; dbt/ingestion/ML/dashboard bugs fixed) — 2026-11-18*
