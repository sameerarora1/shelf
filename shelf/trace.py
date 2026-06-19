from __future__ import annotations

from collections import defaultdict
from time import perf_counter

from shelf.models import TraceEvent, TraceStage


class TraceRecorder:
    def __init__(self) -> None:
        self._events: list[TraceEvent] = []
        self._sequences: defaultdict[str, int] = defaultdict(int)

    @property
    def events(self) -> list[TraceEvent]:
        return list(self._events)

    def record(
        self,
        *,
        trace_id: str,
        item_id: str,
        stage: TraceStage,
        action: str,
        decision: str,
        reason: str,
        tool: str,
        status: str,
        input_summary: str | None = None,
        output_summary: str | None = None,
        duration_ms: int = 0,
        error_code: str | None = None,
    ) -> TraceEvent:
        self._sequences[trace_id] += 1
        event = TraceEvent(
            trace_id=trace_id,
            item_id=item_id,
            sequence=self._sequences[trace_id],
            stage=stage,
            action=action,
            decision=decision,
            reason=reason,
            tool=tool,
            status=status,
            input_summary=input_summary,
            output_summary=output_summary,
            duration_ms=duration_ms,
            error_code=error_code,
        )
        self._events.append(event)
        return event


class Timer:
    def __enter__(self) -> Timer:
        self._started = perf_counter()
        self.duration_ms = 0
        return self

    def __exit__(self, *_args: object) -> None:
        self.duration_ms = self.elapsed_ms

    @property
    def elapsed_ms(self) -> int:
        return int((perf_counter() - self._started) * 1000)
