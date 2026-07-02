"""Manual text extraction: PDF (pypdf) or the official HTML mirror."""

from __future__ import annotations

import re
from pathlib import Path


def _normalize(text: str) -> str:
    text = text.replace(" ", " ").replace("‑", "-")
    return re.sub(r"[ \t]+", " ", text)


def extract_pdf_text(path: str | Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return _normalize("\n".join(pages))


def extract_html_text(path: str | Path) -> str:
    from html.parser import HTMLParser

    class _Text(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.chunks: list[str] = []
            self._skip = 0

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style"):
                self._skip += 1

        def handle_endtag(self, tag):
            if tag in ("script", "style") and self._skip:
                self._skip -= 1

        def handle_data(self, data):
            if not self._skip:
                self.chunks.append(data)

    parser = _Text()
    parser.feed(Path(path).read_text(errors="replace"))
    return _normalize("\n".join(parser.chunks))


def extract_manual_text(path: str | Path) -> str:
    """Dispatch on file extension."""
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        return extract_pdf_text(p)
    if p.suffix.lower() in (".htm", ".html"):
        return extract_html_text(p)
    return _normalize(p.read_text(errors="replace"))
