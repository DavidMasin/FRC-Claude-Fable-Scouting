"""Provider fallback chain: TBA -> FRC Events -> Nexus.

Providers that aren't configured (no key) are skipped with a note rather
than counted as failures. All errors are aggregated so a total failure tells
you exactly why each provider bailed.
"""

from __future__ import annotations

from .errors import ScheduleError
from .matchkey import parse_match_key
from .model import LineupError, MatchLineup
from . import frc_events, nexus, tba

PROVIDERS = {
    "tba": tba.get_lineup,
    "frc_events": frc_events.get_lineup,
    "nexus": nexus.get_lineup,
}
DEFAULT_ORDER = ("tba", "frc_events", "nexus")


def fetch_lineup(match_key: str, config: dict, session=None,
                 providers: tuple[str, ...] = DEFAULT_ORDER) -> MatchLineup:
    """Resolve the 6-team lineup for a match, trying providers in order."""
    if session is None:
        import requests
        session = requests.Session()

    mk = parse_match_key(match_key)
    errors: list[str] = []
    for name in providers:
        if name not in PROVIDERS:
            raise ValueError(f"unknown schedule provider {name!r}")
        try:
            return PROVIDERS[name](mk, config, session)
        except (ScheduleError, LineupError) as exc:
            errors.append(str(exc))
        except Exception as exc:  # network layer, JSON decode, ...
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    raise ScheduleError(
        f"no provider could resolve {match_key}:\n  " + "\n  ".join(errors)
    )
