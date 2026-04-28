"""
Unified logging entrypoint. Uses standard logging instead of direct print calls.
Optional: bind context such as round_id=... or step_id=... to aid debugging.
"""
from __future__ import annotations

import logging
from typing import Any, Optional


def get_logger(name: str) -> logging.Logger:
    """Return a logger named ``name``; by default it writes to the root console handler."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(name)s [%(levelname)s] %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    return logger


def bind(logger: logging.Logger, **kwargs: Any) -> logging.LoggerAdapter:
    """Optionally bind context to a logger, such as round_id or step_id, so it appears in logs."""
    return logging.LoggerAdapter(logger, kwargs)
