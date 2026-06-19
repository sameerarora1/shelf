from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

SourceType = Literal[
    "youtube",
    "public_webpage",
    "instagram_public",
    "x_public",
    "unsupported",
]

ExtractionStatus = Literal[
    "success",
    "metadata_only",
    "blocked",
    "unsupported",
    "failed",
    "rejected",
]

TraceStage = Literal[
    "triage",
    "strategy_selection",
    "extraction",
    "validation",
    "fallback",
    "analysis",
    "organization",
    "indexing",
    "persistence",
]


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class SavedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    url: HttpUrl | str
    canonical_url: str
    source_type: SourceType
    theme_hint: str = ""
    selected_strategy: str
    extraction_status: ExtractionStatus
    title: str | None = None
    creator_or_author: str | None = None
    published_at: str | None = None
    duration_seconds: int | None = None
    description: str | None = None
    extracted_text: str | None = None
    text_available: bool = False
    text_character_count: int = 0
    content_hash: str | None = None
    summary: str | None = None
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    content_type: str | None = None
    intent_tags: list[str] = Field(default_factory=list)
    collection: str = "Needs Review"
    analysis_mode: str = "deterministic"
    trace_id: str
    error_code: str | None = None
    error_message: str | None = None
    latency_ms: int = 0
    created_at: str = Field(default_factory=utc_now_iso)


class TraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    item_id: str
    sequence: int
    stage: TraceStage
    action: str
    decision: str
    reason: str
    tool: str
    status: str
    input_summary: str | None = None
    output_summary: str | None = None
    started_at: str = Field(default_factory=utc_now_iso)
    duration_ms: int = 0
    error_code: str | None = None

