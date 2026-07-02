"""Download the official game manual (PDF, with HTML mirror fallback)."""

from __future__ import annotations

from pathlib import Path

import requests

from .seed import MANUAL_HTML_URL, MANUAL_PDF_URL

_TIMEOUT = 60


def fetch_manual(dest_dir: str | Path = "data") -> Path:
    """Download the manual; returns the local path. Tries PDF, then HTML.

    Raises requests.RequestException if neither source is reachable (e.g.
    behind a restrictive network policy) — the caller should fall back to a
    locally supplied file or the seed rubric.
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for url, name in ((MANUAL_PDF_URL, "2026GameManual.pdf"),
                      (MANUAL_HTML_URL, "2026GameManual.htm")):
        try:
            resp = requests.get(url, timeout=_TIMEOUT)
            resp.raise_for_status()
            path = dest / name
            path.write_bytes(resp.content)
            return path
        except requests.RequestException as exc:  # try next source
            errors.append(f"{url}: {exc}")
    raise requests.RequestException(
        "could not fetch the game manual from any source:\n" + "\n".join(errors)
    )
