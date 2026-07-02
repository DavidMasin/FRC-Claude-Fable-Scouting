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


def load_config(path: str | Path = "config.yaml", allow_missing: bool = False) -> dict:
    """Load config.yaml; with allow_missing, a missing file yields an empty
    config that still picks up secrets from the environment (the deployment
    case: PaaS env vars, no file)."""
    p = Path(path)
    if not p.exists():
        if not allow_missing:
            raise FileNotFoundError(
                f"{p} not found — copy config.example.yaml to config.yaml and fill it in"
            )
        config: dict = {}
    else:
        config = yaml.safe_load(p.read_text()) or {}
    apis = config.setdefault("apis", {})
    for (section, key), env_var in _ENV_FALLBACKS:
        target = apis.setdefault(section, {})
        if not target.get(key) and os.environ.get(env_var):
            target[key] = os.environ[env_var]
    return config
