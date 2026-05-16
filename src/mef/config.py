"""Configuration loader for MEF.

Loads two YAML files from the `config/` directory at the repo root:

- `config/postgres.secrets.yaml` — DB credentials for mefdb, shdb, overwatch.
- `config/mef.yaml`              — application settings (cadence, ranker, llm, email, ...).

Credentials live exclusively in the YAML file. No env-var fallback for
passwords — see `~/repos/notes/secrets-conventions.md`. ``MEF_LOG_LEVEL``
and ``MEF_CLAUDE_PATH`` remain as runtime overrides for non-credential
values.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def _repo_root() -> Path:
    """Return the repo root (directory containing `config/`).

    `src/mef/config.py` → repo root is two levels up from `src/mef/`.
    """
    return Path(__file__).resolve().parents[2]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Config file must be a mapping: {path}")
    return data


def load_postgres_config() -> dict[str, dict[str, Any]]:
    """Return the parsed postgres.secrets.yaml as a dict keyed by db-role section."""
    cfg = _load_yaml(_repo_root() / "config" / "postgres.secrets.yaml")
    for required in ("mefdb", "shdb", "overwatch"):
        if required not in cfg:
            raise ConfigError(
                f"config/postgres.secrets.yaml missing required section: {required}"
            )
    return cfg


def load_app_config() -> dict[str, Any]:
    """Return the parsed mef.yaml with env-var overrides applied."""
    cfg = _load_yaml(_repo_root() / "config" / "mef.yaml")
    for required in ("cadence", "ranker", "llm", "email", "logging"):
        if required not in cfg:
            raise ConfigError(f"config/mef.yaml missing required section: {required}")

    if path := os.environ.get("MEF_CLAUDE_PATH"):
        cfg["llm"]["cli_path"] = path
    if level := os.environ.get("MEF_LOG_LEVEL"):
        cfg["logging"]["level"] = level

    return cfg
