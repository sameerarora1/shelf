from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from shelf.analysis.categories import CategoryAction, CategoryDescription
from shelf.models import SavedItem


@dataclass
class AnalysisResult:
    summary: str | None
    topics: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    content_type: str = "unknown"
    intent_tags: list[str] = field(default_factory=list)
    suggested_collection: str = "Needs Review"
    category_action: CategoryAction = "needs_review"
    category_confidence: float = 0.0
    category_reason: str | None = None
    analysis_mode: str = "deterministic"
    evidence_notes: list[str] = field(default_factory=list)


class AnalyzerBackend:
    mode = "base"

    def analyze(
        self,
        item: SavedItem,
        existing_categories: Sequence[str | CategoryDescription] | None = None,
    ) -> AnalysisResult:
        raise NotImplementedError
