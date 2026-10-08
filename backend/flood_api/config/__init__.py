"""
Configuration loader for versioned assumptions and parameters.
"""

import yaml
from pathlib import Path
from typing import Dict, Any

CONFIG_DIR = Path(__file__).parent


def load_config(version: str = "v1") -> Dict[str, Any]:
    """Load assumptions config by version."""
    config_file = CONFIG_DIR / f"{version}_assumptions.yaml"
    if not config_file.exists():
        raise FileNotFoundError(f"Config not found: {config_file}")
    with open(config_file) as f:
        return yaml.safe_load(f)


def get_current_config() -> Dict[str, Any]:
    """Get the latest (v1) assumptions."""
    return load_config("v1")
