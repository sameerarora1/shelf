from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Literal

from pydantic import BaseModel, Field, field_validator

CategoryAction = Literal["use_existing", "create_new", "needs_review"]

NEEDS_REVIEW = "Needs Review"
METADATA_ONLY = "Metadata Only"

DEFAULT_COLLECTIONS = [
    "Vegetarian Recipes",
    "Investment Education",
    "Gym and Exercise",
    NEEDS_REVIEW,
    METADATA_ONLY,
]

DEFAULT_CATEGORY_DESCRIPTIONS = {
    "Vegetarian Recipes": "Vegetarian and plant-forward recipes, cooking ideas, and meal planning.",
    "Investment Education": (
        "Educational investing, portfolio construction, funds, markets, and personal "
        "finance learning."
    ),
    "Gym and Exercise": (
        "Fitness, workouts, strength training, exercise technique, and gym programming."
    ),
    NEEDS_REVIEW: "Items with too little or too ambiguous information for reliable categorization.",
    METADATA_ONLY: "Items where only public metadata was available during extraction.",
}

_SMALL_WORDS = {"and", "or", "of", "for", "to", "in", "on", "with", "by"}
_ACRONYMS = {"ai", "llm", "ml", "api", "apis", "ui", "ux", "seo", "sql"}
_GENERIC_CATEGORY_WORDS = {
    "application",
    "applications",
    "education",
    "educational",
    "guide",
    "guides",
    "resource",
    "resources",
    "system",
    "systems",
    "technology",
    "technologies",
    "tool",
    "tools",
    "topic",
    "topics",
}
_BANNED_CATEGORY_KEYS = {
    "misc",
    "miscellaneous",
    "other",
    "uncategorized",
    "general",
    "random",
    "links",
    "content",
    "articles",
    "videos",
}


@dataclass(frozen=True)
class CategoryDescription:
    name: str
    description: str | None = None
    examples: tuple[str, ...] = field(default_factory=tuple)


class CategoryDecision(BaseModel):
    action: CategoryAction
    category: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str

    @field_validator("category", "reason")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        value = re.sub(r"\s+", " ", value or "").strip()
        if not value:
            raise ValueError("field must not be empty")
        return value


def category_names(
    categories: Sequence[str | CategoryDescription | dict[str, object]],
) -> list[str]:
    names: list[str] = []
    for category in categories:
        if isinstance(category, CategoryDescription):
            name = category.name
        elif isinstance(category, dict):
            name = str(category.get("name") or "")
        else:
            name = str(category)
        name = re.sub(r"\s+", " ", name).strip()
        if name and not any(_category_key(existing) == _category_key(name) for existing in names):
            names.append(name)
    return names


def validate_category_decision(
    raw_decision: object,
    existing_categories: Sequence[str | CategoryDescription | dict[str, object]],
) -> CategoryDecision:
    decision = CategoryDecision.model_validate(raw_decision)
    existing_names = category_names(existing_categories)

    if decision.action == "needs_review":
        return decision.model_copy(update={"category": NEEDS_REVIEW})

    if decision.action == "use_existing":
        match = matching_existing_category(decision.category, existing_names)
        if match == NEEDS_REVIEW:
            return decision.model_copy(update={"action": "needs_review", "category": NEEDS_REVIEW})
        if match is None:
            raise ValueError(
                f"category {decision.category!r} is not an existing category"
            )
        return decision.model_copy(update={"category": match})

    proposed = format_category_name(decision.category)
    _validate_new_category_name(proposed)
    match = matching_existing_category(proposed, existing_names)
    if match is not None:
        return decision.model_copy(
            update={
                "action": "use_existing",
                "category": match,
                "reason": (
                    f"Proposed category was too close to existing category "
                    f"{match!r}; reused the existing category."
                ),
            }
        )
    return decision.model_copy(update={"category": proposed})


def matching_existing_category(proposed: str, existing_categories: Sequence[str]) -> str | None:
    proposed_key = _category_key(proposed)
    if not proposed_key:
        return None
    for existing in existing_categories:
        if _category_key(existing) == proposed_key:
            return existing

    proposed_tokens = _semantic_tokens(proposed)
    for existing in existing_categories:
        existing_tokens = _semantic_tokens(existing)
        if not proposed_tokens or not existing_tokens:
            continue
        intersection = proposed_tokens & existing_tokens
        if proposed_tokens == existing_tokens:
            return existing
        if len(intersection) >= 2 and (
            intersection == proposed_tokens or intersection == existing_tokens
        ):
            return existing
        if len(intersection) >= 2:
            jaccard = len(intersection) / len(proposed_tokens | existing_tokens)
            if jaccard >= 0.72:
                return existing

    for existing in existing_categories:
        if SequenceMatcher(None, proposed_key, _category_key(existing)).ratio() >= 0.9:
            return existing
    return None


def format_category_name(name: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", name)
    formatted: list[str] = []
    for index, word in enumerate(words):
        lower = word.lower()
        if lower in _ACRONYMS:
            formatted.append(lower.upper())
        elif lower in _SMALL_WORDS and index != 0:
            formatted.append(lower)
        else:
            formatted.append(lower.capitalize())
    return " ".join(formatted)


def _validate_new_category_name(name: str) -> None:
    if not name:
        raise ValueError("new category name is empty")
    if len(name) > 60:
        raise ValueError("new category name is too long")
    if re.search(r"https?://|www\.|\.com|/|\\", name, flags=re.IGNORECASE):
        raise ValueError("new category name must not be based on a URL")
    words = re.findall(r"[A-Za-z0-9]+", name)
    if not 1 <= len(words) <= 6:
        raise ValueError("new category name must be concise")
    if _category_key(name) in _BANNED_CATEGORY_KEYS:
        raise ValueError("new category name is too broad")


def _category_key(name: str) -> str:
    return " ".join(_normalize_word(word) for word in re.findall(r"[A-Za-z0-9]+", name.lower()))


def _semantic_tokens(name: str) -> set[str]:
    return {
        token
        for token in _category_key(name).split()
        if token not in _SMALL_WORDS and token not in _GENERIC_CATEGORY_WORDS
    }


def _normalize_word(word: str) -> str:
    if len(word) > 3 and word.endswith("ies"):
        return f"{word[:-3]}y"
    if len(word) > 3 and word.endswith("s"):
        return word[:-1]
    return word
