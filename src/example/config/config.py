"""
load config from environment variables or .env file, forbidden to store plain text keys in the repository.

Priority: environment variables > .env file in the current working directory (optional)
"""
from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderConfig:
    """Configuration for a single LLM provider (planner or worker)."""
    api_key: str
    base_url: str
    model: str


def _load_dotenv(dotenv_path: Path) -> None:
    """
    Minimal .env parser: support KEY=VALUE, ignore empty lines and # comments.
    Only write to os.environ when the environment variable is not set (to avoid overwriting).
    """
    if not dotenv_path.exists():
        return
    for raw in dotenv_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def load_dotenv(dotenv: str = ".env") -> None:
    """
    Parse the dotenv path from the current working directory and load the .env.
    If dotenv is a relative path, it is relative to Path.cwd(), otherwise it is used directly.
    """
    p = Path(dotenv)
    if not p.is_absolute():
        p = Path.cwd() / p
    _load_dotenv(p.resolve())
