"""Background scouting jobs for the web UI."""

from __future__ import annotations

import itertools
import threading
import time
import traceback
from dataclasses import dataclass, field


@dataclass
class Job:
    job_id: int
    source: str
    match_key: str
    status: str = "running"           # running | done | error
    error: str | None = None
    events: list[dict] = field(default_factory=list)
    record: dict | None = None
    n_frames: int = 0
    n_unstable: int = 0
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_dict(self, include_events: bool = True) -> dict:
        d = {
            "job_id": self.job_id,
            "source": self.source,
            "match_key": self.match_key,
            "status": self.status,
            "error": self.error,
            "n_events": len(self.events),
            "n_frames": self.n_frames,
            "n_unstable": self.n_unstable,
            "elapsed_s": round((self.finished_at or time.time()) - self.started_at, 1),
        }
        if include_events:
            d["events"] = self.events
        return d


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[int, Job] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def start(self, source: str, match_key: str, runner) -> Job:
        """runner(job) does the work; exceptions land in job.error."""
        with self._lock:
            job = Job(job_id=next(self._ids), source=source, match_key=match_key)
            self._jobs[job.job_id] = job

        def _target() -> None:
            try:
                runner(job)
                job.status = "done"
            except Exception as exc:
                job.status = "error"
                job.error = f"{type(exc).__name__}: {exc}"
                traceback.print_exc()
            finally:
                job.finished_at = time.time()

        threading.Thread(target=_target, daemon=True).start()
        return job

    def get(self, job_id: int) -> Job | None:
        return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.job_id, reverse=True)
