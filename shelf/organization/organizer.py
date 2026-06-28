from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from shelf.analysis.base import AnalysisResult
from shelf.analysis.categories import (
    DEFAULT_CATEGORY_DESCRIPTIONS,
    DEFAULT_COLLECTIONS,
    METADATA_ONLY,
    NEEDS_REVIEW,
    CategoryDescription,
    matching_existing_category,
)
from shelf.models import SavedItem

COLLECTIONS = list(DEFAULT_COLLECTIONS)


@dataclass(frozen=True)
class OrganizationDecision:
    collection: str
    reason: str


class Organizer:
    def __init__(self, collections: Sequence[str] | None = None) -> None:
        self._collections: list[str] = []
        self._examples: dict[str, list[str]] = {}
        for collection in collections or COLLECTIONS:
            self._ensure_collection(collection)

    def category_context(self) -> list[CategoryDescription]:
        return [
            CategoryDescription(
                name=collection,
                description=DEFAULT_CATEGORY_DESCRIPTIONS.get(collection),
                examples=tuple(self._examples.get(collection, [])[:3]),
            )
            for collection in self._collections
        ]

    def collection_names(self) -> list[str]:
        return list(self._collections)

    def assign(
        self,
        item: SavedItem,
        analysis: AnalysisResult | None = None,
    ) -> OrganizationDecision:
        if item.extraction_status == "metadata_only":
            return self._remember(
                item,
                OrganizationDecision(
                    collection=METADATA_ONLY,
                    reason=(
                        "Body text was unavailable, so item is separated for "
                        "metadata-only review."
                    ),
                ),
            )
        if item.extraction_status in {"blocked", "failed", "unsupported", "rejected"}:
            return self._remember(
                item,
                OrganizationDecision(
                    collection=NEEDS_REVIEW,
                    reason=(
                        f"Extraction status is {item.extraction_status}; "
                        "manual review is required."
                    ),
                ),
            )

        if analysis is not None:
            analyzer_decision = self._decision_from_analysis(item, analysis)
            if analyzer_decision is not None:
                return analyzer_decision

        if (
            item.collection not in {NEEDS_REVIEW, METADATA_ONLY}
            and item.collection not in COLLECTIONS
        ):
            collection = self._ensure_collection(item.collection)
            return self._remember(
                item,
                OrganizationDecision(
                    collection=collection,
                    reason="Previously assigned dynamic category was preserved.",
                ),
            )

        theme = item.theme_hint.lower()
        topics = {topic.lower() for topic in item.topics}
        intents = {tag.lower() for tag in item.intent_tags}
        content_type = (item.content_type or "").lower()
        if "vegetarian" in theme:
            return self._remember(
                item,
                OrganizationDecision(
                    collection="Vegetarian Recipes",
                    reason="Input theme hint indicates vegetarian cooking content.",
                ),
            )
        if "investment" in theme:
            return self._remember(
                item,
                OrganizationDecision(
                    collection="Investment Education",
                    reason="Input theme hint indicates investing education.",
                ),
            )
        if "gym" in theme or "exercise" in theme or "workout" in theme:
            return self._remember(
                item,
                OrganizationDecision(
                    collection="Gym and Exercise",
                    reason="Input theme hint indicates exercise or gym content.",
                ),
            )
        if "vegetarian" in topics or "cook" in intents or "recipe" in content_type:
            return self._remember(
                item,
                OrganizationDecision(
                    collection="Vegetarian Recipes",
                    reason=(
                        "Topics, intent tags, or content type indicate vegetarian "
                        "cooking content."
                    ),
                ),
            )
        if "investment" in topics or "learn-investing" in intents:
            return self._remember(
                item,
                OrganizationDecision(
                    collection="Investment Education",
                    reason="Topics or intent tags indicate investing education.",
                ),
            )
        if "exercise" in topics or "train" in intents:
            return self._remember(
                item,
                OrganizationDecision(
                    collection="Gym and Exercise",
                    reason="Topics or intent tags indicate exercise or gym content.",
                ),
            )
        return self._remember(
            item,
            OrganizationDecision(
                collection=NEEDS_REVIEW,
                reason="No deterministic collection rule matched with enough confidence.",
            ),
        )

    def _decision_from_analysis(
        self,
        item: SavedItem,
        analysis: AnalysisResult,
    ) -> OrganizationDecision | None:
        if analysis.category_action == "needs_review":
            return self._remember(
                item,
                OrganizationDecision(
                    collection=NEEDS_REVIEW,
                    reason=analysis.category_reason
                    or "Analyzer reported insufficient information for reliable categorization.",
                ),
            )
        suggested = (analysis.suggested_collection or "").strip()
        if not suggested or suggested in {NEEDS_REVIEW, METADATA_ONLY}:
            return None
        collection = self._ensure_collection(suggested)
        return self._remember(
            item,
            OrganizationDecision(
                collection=collection,
                reason=analysis.category_reason or f"Analyzer selected {collection}.",
            ),
        )

    def _ensure_collection(self, collection: str) -> str:
        collection = " ".join((collection or "").split())
        if not collection:
            collection = NEEDS_REVIEW
        match = matching_existing_category(collection, self._collections)
        if match is not None:
            return match
        self._collections.append(collection)
        self._examples.setdefault(collection, [])
        return collection

    def _remember(
        self,
        item: SavedItem,
        decision: OrganizationDecision,
    ) -> OrganizationDecision:
        collection = self._ensure_collection(decision.collection)
        example = item.title or item.summary
        if example and collection not in {NEEDS_REVIEW, METADATA_ONLY}:
            examples = self._examples.setdefault(collection, [])
            clean_example = " ".join(example.split())
            if clean_example not in examples:
                examples.append(clean_example[:120])
        return OrganizationDecision(collection=collection, reason=decision.reason)


def group_collections(items: list[SavedItem]) -> dict[str, list[str]]:
    grouped = {collection: [] for collection in COLLECTIONS}
    for item in items:
        grouped.setdefault(item.collection, []).append(item.item_id)
    return {key: value for key, value in grouped.items() if value}
