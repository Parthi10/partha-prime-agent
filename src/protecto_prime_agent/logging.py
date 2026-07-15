from __future__ import annotations

import logging
import sys
from typing import Any

from fastapi import Request


class CorrelationIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = getattr(record, "correlation_id", "-")
        return True


def build_logger() -> logging.Logger:
    logger = logging.getLogger("protecto_prime_agent")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "message": "%(message)s", "correlation_id": "%(correlation_id)s"}',
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        handler.setFormatter(formatter)
        handler.addFilter(CorrelationIdFilter())
        logger.addHandler(handler)

    return logger


def attach_correlation_id(request: Request) -> str:
    correlation_id = request.headers.get("X-Correlation-ID") or request.headers.get("x-correlation-id")
    if not correlation_id:
        correlation_id = "generated"
    return correlation_id


def log_contextual(message: str, **context: Any) -> None:
    logger = build_logger()
    payload = {"message": message, **context}
    logger.info(payload)
