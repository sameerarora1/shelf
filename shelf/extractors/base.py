from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shelf.models import ExtractionStatus, SourceType


@dataclass
class ExtractionContext:
    item_id: str
    url: str
    raw_dir: Path | None = None


@dataclass
class ExtractorResult:
    canonical_url: str
    source_type: SourceType
    selected_strategy: str
    extraction_status: ExtractionStatus
    title: str | None = None
    creator_or_author: str | None = None
    published_at: str | None = None
    duration_seconds: int | None = None
    description: str | None = None
    extracted_text: str | None = None
    text_available: bool = False
    content_hash: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    latency_ms: int = 0
    raw_artifacts: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def text_character_count(self) -> int:
        return len(self.extracted_text or "")


class BaseExtractor:
    selected_strategy = "BaseExtractor"

    def extract(self, context: ExtractionContext) -> ExtractorResult:
        raise NotImplementedError


def content_hash(text: str | None) -> str | None:
    if not text:
        return None
    normalized = re.sub(r"\s+", " ", text).strip().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def sanitize_error(exc: BaseException) -> str:
    message = f"{type(exc).__name__}: {exc}"
    message = re.sub(r"(?i)(api[_-]?key|token|password)=([^&\\s]+)", r"\1=<redacted>", message)
    return message[:600]

