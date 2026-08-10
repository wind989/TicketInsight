"""Bounded, redacted in-process progress events for one analysis run's SSE subscribers."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Literal


ProgressStatus = Literal["started", "completed", "rejected", "failed", "limited"]
MAX_EVENTS_PER_RUN = 32
MAX_TRACKED_RUNS = 128

# The event store refuses caller-supplied prose.  This finite allow-list prevents
# model output, SQL, exception text, evidence, connection strings, and PII from
# entering the SSE channel even if a future caller is implemented incorrectly.
SAFE_EVENT_SUMMARIES: dict[tuple[str, ProgressStatus], str] = {
    ("retrieval_started", "started"): "Approved evidence retrieval started.",
    ("retrieval_completed", "completed"): "Approved evidence retrieval completed.",
    ("retrieval_completed", "failed"): "Evidence retrieval was unavailable; safeguards remain active.",
    ("sql_validation_rejected", "rejected"): "Candidate SQL was blocked before execution.",
    ("sql_repair_started", "started"): "One bounded SQL repair is starting.",
    ("query_completed", "completed"): "Bounded read-only query completed.",
    ("query_completed", "failed"): "Bounded read-only query was unavailable.",
    ("draft_completed", "completed"): "Analysis draft completed from bounded inputs.",
    ("draft_completed", "failed"): "Analysis draft was unavailable; safeguards remain active.",
    ("review_completed", "completed"): "Bounded review completed.",
    ("review_completed", "failed"): "Review was unavailable; bounded fallback completed.",
    ("analysis_completed", "completed"): "Analysis completed with bounded safeguards.",
    ("analysis_completed", "limited"): "Analysis completed with documented limitations.",
    ("failed", "failed"): "Analysis failed safely; final status is available from the report API.",
}


@dataclass(frozen=True)
class ProgressEvent:
    sequence: int
    run_id: str
    stage: str
    status: ProgressStatus
    summary: str
    timestamp: str

    def payload(self) -> dict[str, str]:
        """Expose only the five approved SSE fields; sequence stays internal to the cache."""

        return {
            "run_id": self.run_id,
            "stage": self.stage,
            "status": self.status,
            "summary": self.summary,
            "timestamp": self.timestamp,
        }


class ProgressEventStore:
    """Keep a small process-local event tail; never accept arbitrary event text."""

    def __init__(self) -> None:
        self._events: dict[str, deque[ProgressEvent]] = {}
        self._next_sequence: dict[str, int] = {}
        self._lock = Lock()

    def emit(self, run_id: str, stage: str, status: ProgressStatus, summary: str) -> None:
        if SAFE_EVENT_SUMMARIES.get((stage, status)) != summary:
            raise ValueError("Progress event is not an approved safe status signal")
        with self._lock:
            if run_id not in self._events and len(self._events) >= MAX_TRACKED_RUNS:
                oldest = next(iter(self._events))
                self._events.pop(oldest, None)
                self._next_sequence.pop(oldest, None)
            sequence = self._next_sequence.get(run_id, 0) + 1
            self._next_sequence[run_id] = sequence
            self._events.setdefault(run_id, deque(maxlen=MAX_EVENTS_PER_RUN)).append(
                ProgressEvent(
                    sequence=sequence,
                    run_id=run_id,
                    stage=stage,
                    status=status,
                    summary=summary,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
            )

    def after(self, run_id: str, sequence: int) -> list[ProgressEvent]:
        with self._lock:
            return [event for event in self._events.get(run_id, ()) if event.sequence > sequence]

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._next_sequence.clear()


progress_events = ProgressEventStore()
