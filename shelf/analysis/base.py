from __future__ import annotations

from dataclasses import dataclass, field

from shelf.models import SavedItem


@dataclass
class AnalysisResult:
    summary: str | None
    topics: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    content_type: str = "unknown"
    intent_tags: list[str] = field(default_factory=list)
    suggested_collection: str = "Needs Review"
    analysis_mode: str = "deterministic"
    evidence_notes: list[str] = field(default_factory=list)


class AnalyzerBackend:
    mode = "base"

    def analyze(self, item: SavedItem) -> AnalysisResult:
        raise NotImplementedError

