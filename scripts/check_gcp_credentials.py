"""MarketPulse GCP credentials & BigQuery connectivity smoke check.

Validates:
1. GCP_PROJECT_ID is set.
2. GCP_SA_KEY_PATH points to an existing, valid service-account JSON key.
3. (Optional) BigQuery connectivity via a lightweight API call.

Exit code 0 = all enabled checks passed; 1 = one or more checks failed.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from google.cloud import bigquery

REQUIRED_CHECKS = ("env_project_id", "sa_key_file", "bq_connectivity")


def check_env_project_id() -> tuple[bool, str]:
    value = os.getenv("GCP_PROJECT_ID")
    if not value:
        return False, "GCP_PROJECT_ID environment variable is not set"
    return True, f"GCP_PROJECT_ID={value}"


def check_sa_key_file() -> tuple[bool, str]:
    raw_path = os.getenv("GCP_SA_KEY_PATH")
    if not raw_path:
        return False, "GCP_SA_KEY_PATH environment variable is not set"
    key_path = Path(raw_path)
    if not key_path.exists():
        return False, f"Service account key file not found at {key_path}"
    try:
        payload = json.loads(key_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"Service account key is not valid JSON: {exc}"
    if payload.get("type") != "service_account":
        return False, f"Service account key has unexpected type: {payload.get('type')}"
    return True, f"Service account key OK at {key_path} (project={payload.get('project_id')})"


def check_bq_connectivity() -> tuple[bool, str]:
    project_id = os.getenv("GCP_PROJECT_ID")
    if not project_id:
        return False, "Skipping BQ connectivity check: GCP_PROJECT_ID not set"
    try:
        client = bigquery.Client(project=project_id)
        datasets = list(client.list_datasets())
        return True, f"BigQuery connectivity OK (project={project_id}, datasets={[d.dataset_id for d in datasets]})"
    except Exception as exc:  # noqa: BLE001 - smoke check must report, not crash
        return False, f"BigQuery connectivity check failed: {exc}"


def main() -> int:
    checks = [
        ("GCP project id configured", check_env_project_id()),
        ("Service account key valid", check_sa_key_file()),
        ("BigQuery connectivity", check_bq_connectivity()),
    ]

    failed = False
    for name, (ok, detail) in checks:
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}: {detail}")
        if not ok:
            failed = True

    if failed:
        print("GCP SMOKE CHECK FAILED")
        return 1
    print("GCP SMOKE CHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
