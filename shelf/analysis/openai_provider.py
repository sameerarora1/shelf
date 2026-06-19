from __future__ import annotations

import json
import os

from pydantic import BaseModel, Field, ValidationError

from shelf.analysis.base import AnalysisResult, AnalyzerBackend
from shelf.analysis.deterministic import DeterministicAnalyzer
from shelf.models import SavedItem


class _OpenAIResponse(BaseModel):
    summary: str | None
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    content_type: str = "unknown"
    intent_tags: list[str] = Field(default_factory=list)
    suggested_collection: str = "Needs Review"
    evidence_notes: list[str] = Field(default_factory=list)


class OpenAIAnalyzer(AnalyzerBackend):
    mode = "openai"

    def __init__(self, model: str = "gpt-4.1-mini") -> None:
        self.model = model
        self._fallback = DeterministicAnalyzer()
        self._enabled = bool(os.getenv("OPENAI_API_KEY"))

    @property
    def enabled(self) -> bool:
        return self._enabled

    def analyze(self, item: SavedItem) -> AnalysisResult:
        if not self._enabled:
            result = self._fallback.analyze(item)
            result.analysis_mode = "deterministic"
            result.evidence_notes.append("OpenAI analyzer not enabled; used deterministic fallback")
            return result
        try:
            from openai import OpenAI

            client = OpenAI()
            content = "\n".join(
                part
                for part in [
                    f"Title: {item.title or ''}",
                    f"Description: {item.description or ''}",
                    f"Extracted text: {(item.extracted_text or '')[:6000]}",
                ]
                if part
            )
            response = client.responses.create(
                model=self.model,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "Analyze only the supplied content. Do not fabricate facts. "
                            "Return compact JSON with summary, topics, entities, content_type, "
                            "intent_tags, suggested_collection, and evidence_notes."
                        ),
                    },
                    {"role": "user", "content": content},
                ],
            )
            parsed = _OpenAIResponse.model_validate_json(response.output_text)
            return AnalysisResult(
                summary=parsed.summary,
                topics=parsed.topics[:8],
                entities=parsed.entities[:8],
                content_type=parsed.content_type,
                intent_tags=parsed.intent_tags[:8],
                suggested_collection=parsed.suggested_collection,
                analysis_mode=self.mode,
                evidence_notes=parsed.evidence_notes + ["OpenAI schema output validated"],
            )
        except (ValidationError, json.JSONDecodeError, Exception) as exc:  # noqa: BLE001
            result = self._fallback.analyze(item)
            result.analysis_mode = "deterministic"
            result.evidence_notes.append(f"OpenAI analyzer failed validation; fallback used: {exc}")
            return result

