from __future__ import annotations

import os


def env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_str(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)
