"""MarketPulse ML anomaly detection: IsolationForest scoring + MLflow tracking + BigQuery write-back."""

from __future__ import annotations

import os
from typing import Optional

import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
from google.cloud import bigquery
from google.api_core.exceptions import NotFound
from google.oauth2 import service_account
from sklearn.ensemble import IsolationForest

from src.utils.logger import get_logger
from src.utils.alerts import RISK_SCORE_HIGH, check_risk_spike

logger = get_logger(__name__)

DEFAULT_CONTAMINATION = 0.05
DEFAULT_MAX_RISK_SCORE = 100.0
DEFAULT_MIN_RISK_SCORE = 0.0
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "sqlite:///mlflow.db")
MLFLOW_MODEL_NAME = "isolation_forest"

GOLD_FEATURE_COLUMNS: list[str] = [
    "seven_day_ma_close",
    "seven_day_volatility",
    "daily_return",
    "volume_z_score",
]

ANOMALY_TABLE = "fact_anomaly_scores"
ANOMALY_STAGING_TABLE = "fact_anomaly_scores_staging"

ANOMALY_TABLE_SCHEMA: list[bigquery.SchemaField] = [
    bigquery.SchemaField("ticker", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("trade_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("risk_score", "FLOAT64", mode="REQUIRED"),
    bigquery.SchemaField("is_anomaly", "BOOL"),
    bigquery.SchemaField("anomaly_score", "FLOAT64"),
]


def normalize_risk_scores(raw_anomaly_scores: np.ndarray) -> np.ndarray:
    """Normalize raw IsolationForest anomaly scores into a 0-100 risk score.

    IsolationForest anomaly scores are such that *lower = more abnormal*, so the
    normalized risk score is inverted: worst (lowest) score -> 100, best -> 0.
    """
    scores = np.asarray(raw_anomaly_scores, dtype=np.float64)
    if scores.size == 0:
        return np.array([], dtype=np.float64)
    low = float(np.min(scores))
    high = float(np.max(scores))
    if high - low < 1e-12:
        return np.full_like(scores, DEFAULT_MAX_RISK_SCORE, dtype=np.float64)
    normalized = (high - scores) / (high - low) * 100.0
    return np.clip(normalized, DEFAULT_MIN_RISK_SCORE, DEFAULT_MAX_RISK_SCORE)


def _build_bq_client(project_id: str) -> bigquery.Client:
    """Create a BigQuery client, preferring the configured service-account key.

    Falls back to Application Default Credentials only when no key path is set,
    which keeps GitHub Actions (keyfile present) and local runs aligned.
    """
    key_path = os.getenv("GCP_SA_KEY_PATH")
    if key_path and os.path.exists(key_path):
        credentials = service_account.Credentials.from_service_account_file(
            key_path,
            scopes=["https://www.googleapis.com/auth/bigquery"],
        )
        return bigquery.Client(project=project_id, credentials=credentials)
    return bigquery.Client(project=project_id)


def fetch_gold_features(
    project_id: Optional[str] = None,
    dataset: Optional[str] = None,
    table: Optional[str] = None,
    ticker: Optional[str] = None,
) -> pd.DataFrame:
    """Read engineered gold features from the BigQuery analytics mart."""
    resolved_project = project_id or os.getenv("GCP_PROJECT_ID")
    resolved_dataset = dataset or os.getenv("BIGQUERY_ANALYTICS_DATASET", "marketpulse_analytics")
    resolved_table = table or "fact_daily_metrics"
    full_table_id = f"{resolved_project}.{resolved_dataset}.{resolved_table}"

    query = f"""
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
        FROM `{full_table_id}`
    """
    params: list = []
    if ticker:
        query += " WHERE ticker = @ticker"
        params = [bigquery.ScalarQueryParameter("ticker", "STRING", ticker)]

    client = _build_bq_client(resolved_project)
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    return client.query(query, job_config=job_config).to_dataframe()


def score_ticker(
    ticker: str,
    feature_rows: pd.DataFrame,
    contamination: float = DEFAULT_CONTAMINATION,
) -> pd.DataFrame:
    """Train an IsolationForest per ticker on its engineered features and score all rows."""
    if feature_rows.empty:
        return pd.DataFrame()

    columns = [column for column in GOLD_FEATURE_COLUMNS if column in feature_rows.columns]
    X = feature_rows[columns].to_numpy(dtype=np.float64)

    model = IsolationForest(
        contamination=float(contamination),
        random_state=42,
        n_estimators=100,
    )
    model.fit(X)

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    with mlflow.start_run(run_name=f"isolation_forest_{ticker}"):
        mlflow.log_params(
            {
                "model_type": "isolation_forest",
                "ticker": str(ticker),
                "contamination": str(contamination),
            }
        )
        raw_scores = np.asarray(model.score_samples(X), dtype=np.float64)
        predictions = np.asarray(model.predict(X))
        risk_scores = normalize_risk_scores(raw_scores)

        mlflow.log_metric("mean_risk_score", float(np.mean(risk_scores)) if risk_scores.size else 0.0)
        mlflow.log_metric("max_risk_score", float(np.max(risk_scores)) if risk_scores.size else 0.0)
        mlflow.log_metric("anomaly_rate", float(np.mean(predictions == -1)) if predictions.size else 0.0)
        mlflow.sklearn.log_model(
            model,
            artifact_path="isolation_forest",
            skops_trusted_types=["sklearn.tree._tree.Tree"],
        )

    scored = feature_rows.copy().reset_index(drop=True)
    scored["risk_score"] = risk_scores
    scored["is_anomaly"] = predictions == -1
    scored["anomaly_score"] = raw_scores
    return scored


def _build_anomaly_upsert_sql(project_id: str, dataset_id: str, table_id: str) -> str:
    """Idempotent score upsert as DDL (Sandbox rejects DML such as MERGE)."""
    return f"""
CREATE OR REPLACE TABLE `{project_id}.{dataset_id}.{table_id}`
PARTITION BY trade_date
CLUSTER BY ticker
AS
WITH combined AS (
    SELECT
        ticker,
        trade_date,
        risk_score,
        is_anomaly,
        anomaly_score,
        0 AS source_rank
    FROM `{project_id}.{dataset_id}.{ANOMALY_STAGING_TABLE}`
    UNION ALL
    SELECT
        ticker,
        trade_date,
        risk_score,
        is_anomaly,
        anomaly_score,
        1 AS source_rank
    FROM `{project_id}.{dataset_id}.{table_id}`
),
deduplicated AS (
    SELECT
        ticker,
        trade_date,
        risk_score,
        is_anomaly,
        anomaly_score,
        ROW_NUMBER() OVER (
            PARTITION BY ticker, trade_date
            ORDER BY source_rank ASC
        ) AS row_num
    FROM combined
)
SELECT
    ticker,
    trade_date,
    risk_score,
    is_anomaly,
    anomaly_score
FROM deduplicated
WHERE row_num = 1
"""


def _ensure_anomaly_table(client: bigquery.Client, table_id: str, schema: list[bigquery.SchemaField]) -> None:
    try:
        client.get_table(table_id)
    except NotFound:
        client.create_table(table_id=table_id, schema=schema)


def upsert_anomaly_scores(
    df: pd.DataFrame,
    project_id: Optional[str] = None,
    dataset: Optional[str] = None,
    table: str = ANOMALY_TABLE,
) -> int:
    """Idempotently upsert anomaly scores into the gold fact table via MERGE."""
    resolved_project = project_id or os.getenv("GCP_PROJECT_ID")
    resolved_dataset = dataset or os.getenv("BIGQUERY_ANALYTICS_DATASET", "marketpulse_analytics")
    resolved_table = table or ANOMALY_TABLE
    target_full_table_id = f"{resolved_project}.{resolved_dataset}.{resolved_table}"
    staging_full_table_id = f"{resolved_project}.{resolved_dataset}.{ANOMALY_STAGING_TABLE}"

    client = _build_bq_client(resolved_project)
    _ensure_anomaly_table(client=client, table_id=target_full_table_id, schema=ANOMALY_TABLE_SCHEMA)

    if not df.empty:
        load_job = client.load_table_from_dataframe(
            df,
            staging_full_table_id,
            job_config=bigquery.LoadJobConfig(
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                schema=ANOMALY_TABLE_SCHEMA,
            ),
        )
        load_job.result()

    merge_job = client.query(_build_anomaly_upsert_sql(resolved_project, resolved_dataset, resolved_table))
    merge_job.result()
    return int(df.shape[0])


def run_detection(
    tickers: Optional[list[str]] = None,
    project_id: Optional[str] = None,
    dataset: Optional[str] = None,
    table: str = ANOMALY_TABLE,
    contamination: float = DEFAULT_CONTAMINATION,
) -> pd.DataFrame:
    """Run end-to-end ML detection: read gold features -> score -> alert -> upsert."""
    resolved_project = project_id or os.getenv("GCP_PROJECT_ID")
    resolved_dataset = dataset or os.getenv("BIGQUERY_ANALYTICS_DATASET", "marketpulse_analytics")
    resolved_table = table or ANOMALY_TABLE

    gold_features = fetch_gold_features(
        project_id=resolved_project,
        dataset=resolved_dataset,
        table="fact_daily_metrics",
    )

    scored_frames: list[pd.DataFrame] = []
    for ticker, group in gold_features.groupby("ticker", sort=False):
        logger.info("Running anomaly detection", extra={"ticker": str(ticker)})
        scored = score_ticker(ticker=str(ticker), feature_rows=group, contamination=contamination)
        if scored.empty:
            continue
        scored_frames.append(scored)

    if not scored_frames:
        logger.warning("No gold features available for anomaly detection")
        return pd.DataFrame()

    scores = pd.concat(scored_frames, ignore_index=True)

    critical_alerts = 0
    for _, row in scores.iterrows():
        if row["is_anomaly"] and float(row["risk_score"]) > RISK_SCORE_HIGH:
            critical_alerts += 1
            check_risk_spike(
                risk_score=float(row["risk_score"]),
                ticker=str(row["ticker"]),
                threshold=RISK_SCORE_HIGH,
            )

    rows_written = upsert_anomaly_scores(
        df=scores,
        project_id=resolved_project,
        dataset=resolved_dataset,
        table=resolved_table,
    )

    logger.info(
        "Anomaly detection run complete",
        extra={"critical_alerts": critical_alerts, "scored_rows": int(len(scores)), "rows_written": rows_written},
    )

    return scores


if __name__ == "__main__":
    detection_scores = run_detection(
        tickers=None,
        project_id=os.getenv("GCP_PROJECT_ID"),
        dataset=os.getenv("BIGQUERY_ANALYTICS_DATASET", "marketpulse_analytics"),
        contamination=float(os.getenv("ANOMALY_CONTAMINATION", str(DEFAULT_CONTAMINATION))),
    )
    logger.info("MarketPulse anomaly detection pipeline completed", extra={"scored_rows": int(len(detection_scores))})
