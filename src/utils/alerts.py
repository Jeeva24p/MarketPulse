"""Slack/Discord webhook alerting for the MarketPulse platform."""

from __future__ import annotations

import logging
import os
from typing import Optional

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "")
RISK_SCORE_HIGH = float(os.getenv("RISK_SCORE_HIGH", "85"))

SEVERITY_TO_LOG_LEVEL = {
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "CRITICAL": logging.CRITICAL,
}


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=4, max=20),
    retry=retry_if_exception_type((requests.RequestException, TimeoutError, ConnectionError)),
)
def _post_webhook(payload: dict, url: str) -> bool:
    """Deliver an alert payload to the configured Slack/Discord webhook."""
    response = requests.post(url, json=payload, timeout=10)
    response.raise_for_status()
    return True


def send_alert(
    severity: str,
    title: str,
    message: str,
    webhook_url: Optional[str] = None,
) -> bool:
    """Send a structured alert. No-ops (returns False) when no webhook is configured."""
    normalized_severity = (severity or "INFO").upper()
    log_level = SEVERITY_TO_LOG_LEVEL.get(normalized_severity, "INFO")
    resolved_url = webhook_url or DEFAULT_WEBHOOK_URL

    if not resolved_url:
        logger.log(
            log_level,
            f"Webhook alert not delivered - no ALERT_WEBHOOK_URL configured",
            extra={"alert": {"severity": normalized_severity, "title": title, "delivered": False}},
        )
        return False

    payload = {"content": f"[{normalized_severity}] {title}: {message}"}
    delivered = False
    try:
        _post_webhook(payload, resolved_url)
        delivered = True
    except Exception as exc:  # noqa: BLE001 - alert delivery must never crash the pipeline
        logger.error("Webhook alert delivery failed", exc_info=exc)

    logger.log(
        log_level,
        f"Webhook alert delivered={delivered}",
        extra={"alert": {"severity": normalized_severity, "title": title, "delivered": delivered}},
    )
    return delivered


def send_critical_alert(title: str, message: str, webhook_url: Optional[str] = None) -> bool:
    """Send a CRITICAL alert with retry/backoff semantics."""
    return send_alert("CRITICAL", title, message, webhook_url=webhook_url)


def check_risk_spike(risk_score: float, ticker: str, threshold: Optional[float] = None) -> bool:
    """Trigger a CRITICAL webhook when the normalized risk score exceeds the threshold."""
    resolved_threshold = RISK_SCORE_HIGH if threshold is None else float(threshold)
    score = float(risk_score)
    if score > resolved_threshold:
        send_critical_alert(
            title=f"High risk spike detected: {ticker}",
            message=f"Risk score {score:.2f} exceeded critical threshold {resolved_threshold:.2f}.",
        )
        return True
    return False
