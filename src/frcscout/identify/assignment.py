"""Track ↔ team assignment: a 6-way (3-per-alliance) assignment problem.

The schedule gives the only 6 possible identities. Alliance color halves the
problem; within an alliance, evidence accumulates per (track, team):

- station prior at match start (station order maps to image-x order),
- fuzzy-matched bumper OCR reads (similarity-weighted, so a partial '598'
  counts toward 5987 but a read matching no expected number counts nowhere).

The solver enumerates track→team bijections per alliance (≤3 teams, so brute
force is exact Hungarian) and keeps the incumbent assignment unless a
challenger beats it by `reassign_margin` — a single noisy OCR read can never
flip a high-confidence assignment.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations, permutations

from ..schedule.model import MatchLineup


def _levenshtein(a: str, b: str) -> int:
    if not a or not b:
        return max(len(a), len(b))
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        row = [i]
        for j, cb in enumerate(b, 1):
            row.append(min(prev[j] + 1, row[-1] + 1, prev[j - 1] + (ca != cb)))
        prev = row
    return prev[-1]


def digit_similarity(read: str, team: int) -> float:
    """0..1 similarity between an OCR digit string and a team number."""
    target = str(team)
    if not read:
        return 0.0
    return max(0.0, 1.0 - _levenshtein(read, target) / max(len(read), len(target)))


@dataclass(frozen=True)
class Assignment:
    team: int | None
    confidence: float
    evidence: float  # total accumulated score mass behind this track


# noisy footage spawns hundreds of junk tracks; only the best-evidenced few
# per alliance enter the (combinatorial) solve
_MAX_SOLVE_TRACKS = 8


class TeamAssigner:
    def __init__(self, lineup: MatchLineup, min_conf: float = 0.6,
                 reassign_margin: float = 0.25, min_similarity: float = 0.5) -> None:
        self.lineup = lineup
        self.min_conf = min_conf
        self.reassign_margin = reassign_margin
        self.min_similarity = min_similarity
        # (track_id) -> team -> accumulated score
        self._scores: dict[int, dict[int, float]] = {}
        self._alliance: dict[int, str] = {}
        self._incumbent: dict[str, dict[int, int]] = {"red": {}, "blue": {}}
        self._cache: dict[int, Assignment] | None = None

    # ---- evidence -------------------------------------------------------

    def _bucket(self, track_id: int, alliance: str) -> dict[int, float]:
        self._cache = None
        self._alliance[track_id] = alliance
        return self._scores.setdefault(
            track_id, {team: 0.0 for team in self.lineup.teams(alliance)})

    def seed_station_prior(self, tracks, weight: float = 1.0,
                           stations_left_to_right: dict[str, list[int]] | None = None) -> None:
        """Seed from starting positions: at match start each alliance's robots
        line up by station. Default mapping is image-x order ↔ station order;
        pass stations_left_to_right per alliance to flip/override per camera
        (finalized properly by homography in milestone 7).
        """
        for alliance in ("red", "blue"):
            mine = sorted((tr for tr in tracks if tr.alliance == alliance),
                          key=lambda tr: tr.center[0])
            order = (stations_left_to_right or {}).get(alliance) \
                or self.lineup.teams(alliance)
            for track, team in zip(mine, order):
                self._bucket(track.track_id, alliance)[team] += weight

    def add_ocr(self, track_id: int, alliance: str, digits: str, conf: float) -> None:
        bucket = self._bucket(track_id, alliance)
        for team in bucket:
            sim = digit_similarity(digits, team)
            if sim >= self.min_similarity:
                bucket[team] += conf * sim * sim  # square: near-exact reads dominate

    # ---- solving ----------------------------------------------------------

    def _solve_alliance(self, alliance: str) -> dict[int, int]:
        teams = self.lineup.teams(alliance)
        track_ids = [tid for tid, a in self._alliance.items() if a == alliance]
        if not track_ids:
            return {}
        if len(track_ids) > _MAX_SOLVE_TRACKS:
            # keep the incumbents plus the best-evidenced challengers: the
            # solve is C(n,3)*3! so n must stay small no matter how many
            # junk tracks a noisy detector produced
            keep = set(self._incumbent[alliance]) & set(track_ids)
            by_evidence = sorted(track_ids, reverse=True,
                                 key=lambda tid: sum(self._scores[tid].values()))
            for tid in by_evidence:
                if len(keep) >= _MAX_SOLVE_TRACKS:
                    break
                keep.add(tid)
            track_ids = list(keep)

        def total(mapping: dict[int, int]) -> float:
            return sum(self._scores[tid][team] for tid, team in mapping.items())

        best: dict[int, int] = {}
        best_total = -1.0
        r = min(len(teams), len(track_ids))
        for chosen in combinations(track_ids, r):
            for perm in permutations(teams, r):
                candidate = dict(zip(chosen, perm))
                cand_total = total(candidate)
                if cand_total > best_total:
                    best, best_total = candidate, cand_total

        incumbent = self._incumbent[alliance]
        if incumbent and all(tid in self._scores for tid in incumbent):
            # hysteresis: challenger must beat the incumbent by a real margin
            if best_total < total(incumbent) + self.reassign_margin:
                return incumbent
        self._incumbent[alliance] = best
        return best

    def assignments(self) -> dict[int, Assignment]:
        """Current track→team assignment with confidences. Cached until new
        evidence arrives — callers hit this several times per frame."""
        if self._cache is not None:
            return self._cache
        out: dict[int, Assignment] = {}
        solved: dict[int, int] = {}
        for alliance in ("red", "blue"):
            solved.update(self._solve_alliance(alliance))
        for tid, bucket in self._scores.items():
            team = solved.get(tid)
            evidence = sum(bucket.values())
            if team is None or evidence <= 0:
                out[tid] = Assignment(team=None, confidence=0.0, evidence=evidence)
                continue
            # softmax over this track's team scores, damped by how much
            # evidence exists at all (1 read of '3' shouldn't yield conf 0.9)
            exps = {t: math.exp(s) for t, s in bucket.items()}
            softmax = exps[team] / sum(exps.values())
            damp = 1.0 - math.exp(-evidence)
            out[tid] = Assignment(team=team, confidence=softmax * damp, evidence=evidence)
        self._cache = out
        return out

    def team_labels(self) -> dict[int, str]:
        """track_id -> display label for the debug renderer."""
        labels = {}
        for tid, a in self.assignments().items():
            if a.team is not None:
                mark = "" if a.confidence >= self.min_conf else "?"
                labels[tid] = f"{a.team}{mark}"
        return labels
