"""
Configuration loading from environment variables and optional .env files only.
Do not store plaintext keys in the repository.

Priority: environment variables > .env file in the current working directory
"""
from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderConfig:
    """Configuration for a single LLM provider, such as planner or worker."""
    api_key: str
    base_url: str
    model: str


def _load_dotenv(dotenv_path: Path) -> None:
    """
    Minimal .env parser: supports KEY=VALUE and ignores empty lines and # comments.
    Writes to os.environ only when the variable is not already set.
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
    Resolve the dotenv path from the current working directory and load it.
    Relative paths are resolved against Path.cwd(); absolute paths are used as-is.
    """
    p = Path(dotenv)
    if not p.is_absolute():
        p = Path.cwd() / p
    _load_dotenv(p.resolve())
