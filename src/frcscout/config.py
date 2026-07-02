"""config.yaml loading. Secrets may come from the file or the environment;
environment variables win only when the file leaves a value empty."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

# (config path under "apis", env var) pairs for secret fallback.
_ENV_FALLBACKS = [
    (("tba", "auth_key"), "TBA_AUTH_KEY"),
    (("frc_events", "username"), "FRC_EVENTS_USERNAME"),
    (("frc_events", "auth_token"), "FRC_EVENTS_AUTH_TOKEN"),
    (("nexus", "api_key"), "NEXUS_API_KEY"),
    (("anthropic", "api_key"), "ANTHROPIC_API_KEY"),
]


def load_config(path: str | Path = "config.yaml") -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"{p} not found — copy config.example.yaml to config.yaml and fill it in"
        )
    config = yaml.safe_load(p.read_text()) or {}
    apis = config.setdefault("apis", {})
    for (section, key), env_var in _ENV_FALLBACKS:
        target = apis.setdefault(section, {})
        if not target.get(key) and os.environ.get(env_var):
            target[key] = os.environ[env_var]
    return config
