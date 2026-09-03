"""Project-local environment loading for the IM entry point."""

from __future__ import annotations

import os
from pathlib import Path


def load_environment() -> None:
    """Load ``.env`` from the project root without overwriting shell variables."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def require_environment(keys: list[str]) -> None:
    missing = [key for key in keys if not os.getenv(key)]
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            f"Missing required model configuration: {joined}. "
            "Copy .env.example to .env and set the values."
        )
