"""Logging configuration — text in dev, structured JSON in production."""

import logging
import sys
from datetime import UTC
from typing import Any


class _JsonFormatter(logging.Formatter):
    """Minimal JSON log formatter for production."""

    def format(self, record: logging.LogRecord) -> str:
        import json
        from datetime import datetime

        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO", fmt: str = "text") -> None:
    """Configure root logger. Call once at startup."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    root.handlers.clear()
    root.addHandler(handler)
