from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from shelf.analysis.base import AnalysisResult, AnalyzerBackend
from shelf.analysis.categories import (
    DEFAULT_CATEGORY_DESCRIPTIONS,
    DEFAULT_COLLECTIONS,
    CategoryDescription,
    validate_category_decision,
)
from shelf.analysis.deterministic import DeterministicAnalyzer
from shelf.models import SavedItem

DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"


class OpenRouterConfigError(RuntimeError):
    """Raised when the OpenRouter analyzer is selected but not configured."""


class OpenRouterRequestError(RuntimeError):
    """Raised when the OpenRouter API request cannot be completed."""


class OpenRouterResponseError(RuntimeError):
    """Raised when OpenRouter returns empty, malformed, or invalid output."""


class _OpenRouterResponse(BaseModel):
    summary: str | None = None
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    content_type: str = "unknown"
    intent_tags: list[str] = Field(default_factory=list)
    evidence_notes: list[str] = Field(default_factory=list)

    @field_validator("topics", "entities", "intent_tags", "evidence_notes", mode="before")
    @classmethod
    def _coerce_string_list(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("field must be a list")
        cleaned = [re.sub(r"\s+", " ", str(item)).strip() for item in value]
        return [item for item in cleaned if item]

    @field_validator("content_type")
    @classmethod
    def _strip_content_type(cls, value: str) -> str:
        value = re.sub(r"\s+", " ", value or "").strip()
        return value or "unknown"


class OpenAIAnalyzer(AnalyzerBackend):
    mode = "openrouter"

    def __init__(
        self,
        model: str | None = None,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        api_key: str | None = None,
        client: object | None = None,
        fallback: AnalyzerBackend | None = None,
    ) -> None:
        self.model = (model or os.getenv("OPENROUTER_MODEL") or DEFAULT_OPENROUTER_MODEL).strip()
        self.base_url = (
            base_url or os.getenv("OPENROUTER_BASE_URL") or DEFAULT_OPENROUTER_BASE_URL
        ).strip()
        self.timeout_seconds = float(
            timeout_seconds or os.getenv("OPENROUTER_TIMEOUT_SECONDS") or 30
        )
        self._fallback = fallback or DeterministicAnalyzer()

        resolved_api_key = api_key if api_key is not None else os.getenv("OPENROUTER_API_KEY")
        if client is not None:
            self._client = client
            return
        if not resolved_api_key:
            raise OpenRouterConfigError(
                "OPENROUTER_API_KEY is required when SHELF_ANALYZER=openrouter."
            )
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - depends on optional install
            raise OpenRouterConfigError(
                "The OpenRouter analyzer requires the optional OpenAI SDK. "
                'Install with: pip install -e ".[openai]"'
            ) from exc
        self._client = OpenAI(
            base_url=self.base_url,
            api_key=resolved_api_key,
        )

    @property
    def enabled(self) -> bool:
        return True

    def analyze(
        self,
        item: SavedItem,
        existing_categories: Sequence[str | CategoryDescription] | None = None,
    ) -> AnalysisResult:
        category_context = list(existing_categories or DEFAULT_COLLECTIONS)
        try:
            parsed, decision = self._analyze_with_openrouter(item, category_context)
            return AnalysisResult(
                summary=parsed.summary,
                topics=parsed.topics[:8],
                entities=parsed.entities[:8],
                content_type=parsed.content_type,
                intent_tags=parsed.intent_tags[:8],
                suggested_collection=decision.category,
                category_action=decision.action,
                category_confidence=decision.confidence,
                category_reason=decision.reason,
                analysis_mode=self.mode,
                evidence_notes=[
                    *parsed.evidence_notes[:5],
                    "OpenRouter structured output validated",
                ],
            )
        except (
            OpenRouterRequestError,
            OpenRouterResponseError,
            ValidationError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            result = self._fallback.analyze(item, category_context)
            result.analysis_mode = "deterministic"
            result.evidence_notes.append(
                f"OpenRouter analyzer failed; deterministic fallback used: {type(exc).__name__}"
            )
            return result

    def _analyze_with_openrouter(
        self,
        item: SavedItem,
        existing_categories: Sequence[str | CategoryDescription],
    ) -> tuple[_OpenRouterResponse, Any]:
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=_messages(item, existing_categories),
                temperature=0.1,
                response_format={"type": "json_object"},
                timeout=self.timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            raise OpenRouterRequestError("OpenRouter API request failed.") from exc

        content = _response_content(response)
        payload = _json_payload(content)
        parsed = _OpenRouterResponse.model_validate(payload)
        decision_payload = _category_decision_payload(payload)
        decision = validate_category_decision(decision_payload, existing_categories)
        return parsed, decision


def _messages(
    item: SavedItem,
    existing_categories: Sequence[str | CategoryDescription],
) -> list[dict[str, str]]:
    payload = {
        "item": {
            "url": str(item.url),
            "canonical_url": item.canonical_url,
            "source_type": item.source_type,
            "title": item.title,
            "description": item.description,
            "creator_or_author": item.creator_or_author,
            "published_at": item.published_at,
            "theme_hint": item.theme_hint,
            "extraction_status": item.extraction_status,
            "text_available": item.text_available,
            "text_character_count": item.text_character_count,
            "transcript_or_page_text": (item.extracted_text or "")[:12_000],
        },
        "existing_categories": [_category_payload(category) for category in existing_categories],
    }
    return [
        {
            "role": "system",
            "content": (
                "Analyze only the supplied saved-item content. Do not fabricate facts. "
                "Return JSON only, with no markdown and no private reasoning. Include a "
                "short user-facing classification reason, but never include chain-of-thought. "
                "Existing categories are semantic concepts, not exact keyword matches. "
                "Choose an existing category when it meaningfully covers the primary topic "
                "of the item, even if the wording differs. Create a new category only when "
                "none of the existing categories provides a strong semantic match. Do not "
                "create a new category merely because the item uses different terminology. "
                "Use Needs Review when the available content is insufficient or the topic "
                "cannot be determined confidently. New category names must be concise, "
                "human-readable, consistently capitalized, meaningful topics, not URLs, "
                "single-document titles, or broad names like Miscellaneous. Return this "
                "shape: {\"summary\": string|null, \"topics\": string[], "
                "\"entities\": string[], \"content_type\": string, "
                "\"intent_tags\": string[], \"evidence_notes\": string[], "
                "\"category_decision\": {\"action\": \"use_existing\"|"
                "\"create_new\"|\"needs_review\", \"category\": string, "
                "\"confidence\": number, \"reason\": string}}."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=True, sort_keys=True),
        },
    ]


def _category_payload(category: str | CategoryDescription) -> dict[str, object]:
    if isinstance(category, CategoryDescription):
        return {
            "name": category.name,
            "description": category.description,
            "examples": list(category.examples[:3]),
        }
    return {
        "name": category,
        "description": DEFAULT_CATEGORY_DESCRIPTIONS.get(category),
        "examples": [],
    }


def _category_decision_payload(payload: dict[str, object]) -> object:
    nested = payload.get("category_decision")
    if isinstance(nested, dict):
        return nested
    if {"action", "category", "confidence", "reason"} <= payload.keys():
        return {key: payload[key] for key in ("action", "category", "confidence", "reason")}
    raise OpenRouterResponseError("Model response did not include a category decision.")


def _response_content(response: object) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    try:
        choices = response.choices
        first_choice = choices[0]
        message = first_choice.message
        content = message.content
    except (AttributeError, IndexError, TypeError) as exc:
        raise OpenRouterResponseError(
            "OpenRouter response did not include message content."
        ) from exc

    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "\n".join(_content_part_text(part) for part in content)
    else:
        raise OpenRouterResponseError("OpenRouter response content was not text.")
    text = text.strip()
    if not text:
        raise OpenRouterResponseError("OpenRouter response content was empty.")
    return text


def _content_part_text(part: object) -> str:
    if isinstance(part, dict):
        return str(part.get("text") or part.get("content") or "").strip()
    return str(getattr(part, "text", "") or getattr(part, "content", "") or "").strip()


def _json_payload(content: str) -> dict[str, object]:
    text = _strip_code_fence(content.strip())
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise OpenRouterResponseError("Model response JSON must be an object.")
    return payload


def _strip_code_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
