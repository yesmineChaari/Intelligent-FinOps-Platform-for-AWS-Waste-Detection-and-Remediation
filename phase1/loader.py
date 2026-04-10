"""
Rules loader.
Reads rules.yaml and validates it against the Pydantic Rules model.
Fails fast at startup if the file is missing or malformed.
"""

import yaml
from pathlib import Path
from .models import Rules


def load_rules(path: str = "rules.yaml") -> Rules:
    """
    Load and validate rules.yaml.
    Raises FileNotFoundError if the file does not exist.
    Raises ValidationError if any field is missing or has the wrong type.
    Both failures are intentional — the pipeline must not run with bad config.
    """
    rules_path = Path(path)

    if not rules_path.exists():
        raise FileNotFoundError(
            f"rules.yaml not found at {rules_path.resolve()}. "
            "The pipeline cannot start without threshold configuration."
        )

    with open(rules_path) as f:
        raw = yaml.safe_load(f)

    # Pydantic validates every field and type — raises ValidationError with
    # a clear message if anything is wrong before a single DB query runs
    return Rules(**raw)
