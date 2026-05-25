from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class IngestionCompleteEvent:
    workspace_key: str | None = None
    terraform_repo_url: str | None = None
    terraform_ref: str | None = None
    terraform_subdir: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeterministicCompleteEvent:
    run_id: int
    workspace_key: str | None = None
    terraform_repo_url: str | None = None
    terraform_ref: str | None = None
    terraform_subdir: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
