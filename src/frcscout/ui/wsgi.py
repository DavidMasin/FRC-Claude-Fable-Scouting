"""Production WSGI entrypoint (Railway/gunicorn):

    gunicorn -w 1 --threads 8 -b 0.0.0.0:$PORT frcscout.ui.wsgi:app

Exactly one worker: scouting jobs live in the worker's memory (JobManager
threads), so multiple workers would each see a different job list. Scale
with threads, not workers.

Configuration is environment-first:
    FRCSCOUT_OUT_DIR   where records/uploads live (overrides everything)
    RAILWAY_VOLUME_MOUNT_PATH  set by Railway when a volume is attached —
                       records go to <mount>/out automatically, so any
                       mount path works with zero configuration
    FRCSCOUT_CONFIG    optional config.yaml path
    TBA_AUTH_KEY, FRC_EVENTS_USERNAME/AUTH_TOKEN, NEXUS_API_KEY,
    ANTHROPIC_API_KEY  picked up automatically (no config file needed)
"""

from __future__ import annotations

import os

from .app import create_app


def _out_dir() -> str:
    explicit = os.environ.get("FRCSCOUT_OUT_DIR")
    if explicit:
        return explicit
    volume = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
    if volume:
        return os.path.join(volume, "out")
    return "out"  # ephemeral: works, but resets on redeploy


app = create_app(
    config_path=os.environ.get("FRCSCOUT_CONFIG", "config.yaml"),
    out_dir=_out_dir(),
)
