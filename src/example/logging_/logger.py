"""
Standard logging entry point. Use standard logging, do not directly print.
Optional: bind(round_id=..., step_id=...) etc. context, for debugging.
"""
from __future__ import annotations

import logging
from typing import Any, Optional


def get_logger(name: str) -> logging.Logger:
    """Return the logger named name, default output to root (console)."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(name)s [%(levelname)s] %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    return logger


def bind(logger: logging.Logger, **kwargs: Any) -> logging.LoggerAdapter:
    """Optional: bind context (e.g. round_id, step_id) to the logger, for easier debugging in the logs."""
    return logging.LoggerAdapter(logger, kwargs)
