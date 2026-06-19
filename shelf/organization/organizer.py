from __future__ import annotations

from dataclasses import dataclass

from shelf.models import SavedItem

COLLECTIONS = [
    "Vegetarian Recipes",
    "Investment Education",
    "Gym and Exercise",
    "Needs Review",
    "Metadata Only",
]


@dataclass(frozen=True)
class OrganizationDecision:
    collection: str
    reason: str


class Organizer:
    def assign(self, item: SavedItem) -> OrganizationDecision:
        if item.extraction_status == "metadata_only":
            return OrganizationDecision(
                collection="Metadata Only",
                reason="Body text was unavailable, so item is separated for metadata-only review.",
            )
        if item.extraction_status in {"blocked", "failed", "unsupported", "rejected"}:
            return OrganizationDecision(
                collection="Needs Review",
                reason=f"Extraction status is {item.extraction_status}; manual review is required.",
            )
        theme = item.theme_hint.lower()
        topics = {topic.lower() for topic in item.topics}
        intents = {tag.lower() for tag in item.intent_tags}
        content_type = (item.content_type or "").lower()
        if "vegetarian" in theme:
            return OrganizationDecision(
                collection="Vegetarian Recipes",
                reason="Input theme hint indicates vegetarian cooking content.",
            )
        if "investment" in theme:
            return OrganizationDecision(
                collection="Investment Education",
                reason="Input theme hint indicates investing education.",
            )
        if "gym" in theme or "exercise" in theme or "workout" in theme:
            return OrganizationDecision(
                collection="Gym and Exercise",
                reason="Input theme hint indicates exercise or gym content.",
            )
        if "vegetarian" in topics or "cook" in intents or "recipe" in content_type:
            return OrganizationDecision(
                collection="Vegetarian Recipes",
                reason="Topics, intent tags, or content type indicate vegetarian cooking content.",
            )
        if "investment" in topics or "learn-investing" in intents:
            return OrganizationDecision(
                collection="Investment Education",
                reason="Topics or intent tags indicate investing education.",
            )
        if "exercise" in topics or "train" in intents:
            return OrganizationDecision(
                collection="Gym and Exercise",
                reason="Topics or intent tags indicate exercise or gym content.",
            )
        return OrganizationDecision(
            collection="Needs Review",
            reason="No deterministic collection rule matched with enough confidence.",
        )


def group_collections(items: list[SavedItem]) -> dict[str, list[str]]:
    grouped = {collection: [] for collection in COLLECTIONS}
    for item in items:
        grouped.setdefault(item.collection, []).append(item.item_id)
    return {key: value for key, value in grouped.items() if value}
