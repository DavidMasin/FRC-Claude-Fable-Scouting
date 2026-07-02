"""VLM disambiguation: the expensive path, used only when zone+overlay
attribution is ambiguous — never per-frame.

The engine calls ``choose_scorer(candidate_track_ids, context)`` and expects
``(track_id | None, confidence)``. Implementations must be conservative:
returning (None, 0) keeps the heuristic's flagged low-confidence pick, which
is always a safe outcome.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path


class AnthropicDisambiguator:
    """Sends short frame crops of the candidate robots to Claude and asks
    which one scored. Responses are cached on disk keyed by the clip hash so
    replays never pay twice."""

    def __init__(self, api_key: str, model: str = "claude-fable-5",
                 cache_dir: str | Path = ".vlm_cache",
                 frame_provider=None) -> None:
        import anthropic

        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # frame_provider(track_id, t) -> BGR crop around that track, or None.
        self.frame_provider = frame_provider

    def _encode(self, image) -> dict:
        import cv2

        ok, buf = cv2.imencode(".jpg", image)
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg",
                       "data": base64.b64encode(buf.tobytes()).decode()},
        }

    def choose_scorer(self, candidates: list[int], context: dict
                      ) -> tuple[int | None, float]:
        if self.frame_provider is None:
            return None, 0.0
        crops = {tid: self.frame_provider(tid, context.get("t")) for tid in candidates}
        crops = {tid: c for tid, c in crops.items() if c is not None}
        if not crops:
            return None, 0.0

        key_material = json.dumps({"ctx": context, "tids": sorted(crops)}, sort_keys=True)
        for tid, crop in sorted(crops.items()):
            key_material += hashlib.sha1(crop.tobytes()).hexdigest()
        cache_key = hashlib.sha1(key_material.encode()).hexdigest()
        cache_file = self.cache_dir / f"{cache_key}.json"
        if cache_file.exists():
            cached = json.loads(cache_file.read_text())
            return cached["track_id"], cached["conf"]

        content: list = [{
            "type": "text",
            "text": (
                "These are crops of FRC robots near the scoring HUB when the "
                f"{context.get('alliance')} alliance score increased by "
                f"{context.get('delta')} during {context.get('phase')}. "
                f"The crops are labeled in order: {sorted(crops)}. "
                "Which robot most likely just scored FUEL (yellow foam balls)? "
                'Reply with JSON only: {"track_id": <id or null>, "confidence": <0..1>}. '
                "Use null if you cannot tell."
            ),
        }]
        for tid in sorted(crops):
            content.append({"type": "text", "text": f"track {tid}:"})
            content.append(self._encode(crops[tid]))

        response = self.client.messages.create(
            model=self.model, max_tokens=100,
            messages=[{"role": "user", "content": content}])
        try:
            data = json.loads(response.content[0].text)
            tid = data.get("track_id")
            conf = float(data.get("confidence", 0.0))
            if tid is not None and int(tid) not in crops:
                tid = None
        except (ValueError, KeyError, IndexError):
            tid, conf = None, 0.0
        cache_file.write_text(json.dumps(
            {"track_id": int(tid) if tid is not None else None, "conf": conf}))
        return (int(tid) if tid is not None else None), conf
