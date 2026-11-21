# src/config.py - Loads and validates config.yaml settings.

from pathlib import Path
from typing import Any
import yaml


def load_config(config_path: str | Path = "config.yaml") -> dict[str, Any]:
    path = Path(config_path)
    if not path.is_absolute() and not path.exists():
        # Fallback to triage directory if called from scripts or tests
        triage_root = Path(__file__).resolve().parent.parent
        alt_path = triage_root / config_path
        if alt_path.exists():
            path = alt_path

    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}
