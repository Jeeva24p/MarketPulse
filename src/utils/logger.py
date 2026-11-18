"""Structured JSON logging for the MarketPulse platform.

All pipeline logs are emitted as single-line JSON records so they can be ingested
by log aggregators (Cloud Logging, ELK, Loki, etc.) without custom parsing.
"""

from __future__ import annotations

import json
import logging
import logging.config
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_FILE = "logs/pipeline.log"

LOG_DIR = Path(os.getenv("LOG_DIR", "logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = os.getenv("LOG_FILE", str(LOG_DIR / "pipeline.log"))
LOG_LEVEL = os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()

# Context keys forwarded from the log record into the JSON payload.
LOG_RECORD_EXTRA_KEYS = ("ticker", "trade_date", "risk_score", "is_anomaly", "anomaly_score")


class JsonFormatter(logging.Formatter):
    """Emits machine-parseable single-line JSON log records."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_text:
            payload["exc_info"] = record.exc_text
        for key in LOG_RECORD_EXTRA_KEYS:
            value = record.__dict__.get(key)
            if value is not None:
                payload[key] = value
        return json.dumps(payload)


def setup_logging(log_file: Optional[str] = None, level: Optional[str] = None) -> None:
    """(Re)configure the root logger with JSON console + file handlers. Safe to re-run."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {"()": "src.utils.logger.JsonFormatter"},
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "json",
                "level": "INFO",
                "stream": "ext://sys.stderr",
            },
            "file": {
                "class": "logging.FileHandler",
                "formatter": "json",
                "level": "DEBUG",
                "filename": log_file or str(LOG_FILE),
            },
        },
        "root": {
            "handlers": ["console", "file"],
            "level": (level or LOG_LEVEL).upper(),
        },
    }
    logging.config.dictConfig(config)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger using the MarketPulse JSON formatting."""
    return logging.getLogger(name)
