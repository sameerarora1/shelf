from __future__ import annotations

import re
from collections import Counter

from shelf.analysis.base import AnalysisResult, AnalyzerBackend
from shelf.models import SavedItem

TOPIC_KEYWORDS = {
    "vegetarian": {
        "vegetarian",
        "vegan",
        "tofu",
        "lentil",
        "chickpea",
        "recipe",
        "dinner",
        "protein",
        "beans",
        "salad",
        "pasta",
    },
    "investment": {
        "invest",
        "investment",
        "investing",
        "stock",
        "stocks",
        "bond",
        "etf",
        "index",
        "fund",
        "portfolio",
        "market",
        "risk",
        "valuation",
    },
    "exercise": {
        "gym",
        "exercise",
        "workout",
        "fitness",
        "strength",
        "muscle",
        "cardio",
        "bodyweight",
        "training",
        "sets",
        "reps",
    },
}

STOPWORDS = {
    "about",
    "after",
    "also",
    "and",
    "are",
    "because",
    "from",
    "have",
    "into",
    "that",
    "the",
    "their",
    "this",
    "with",
    "you",
    "your",
    "for",
    "how",
    "what",
    "when",
    "where",
    "why",
    "video",
    "article",
}


class DeterministicAnalyzer(AnalyzerBackend):
    mode = "deterministic"

    def analyze(self, item: SavedItem) -> AnalysisResult:
        source_text = _source_text(item)
        tokens = _tokens(source_text)
        topics = _topics(tokens, item.theme_hint)
        summary = _summary(item, source_text)
        entities = _entities(source_text)
        content_type = _content_type(item, tokens)
        intent_tags = _intent_tags(item, topics, content_type)
        collection = _suggested_collection(topics, intent_tags, item.extraction_status)
        notes = []
        if item.extracted_text:
            notes.append("summary derived from extracted text")
        elif item.description or item.title:
            notes.append("summary derived from public metadata only")
        else:
            notes.append("no title, description, or body text available")
        if item.theme_hint:
            notes.append(f"theme hint used for deterministic tagging: {item.theme_hint}")
        return AnalysisResult(
            summary=summary,
            topics=topics,
            entities=entities,
            content_type=content_type,
            intent_tags=intent_tags,
            suggested_collection=collection,
            analysis_mode=self.mode,
            evidence_notes=notes,
        )


def _source_text(item: SavedItem) -> str:
    parts = [
        item.title or "",
        item.description or "",
        item.extracted_text or "",
        item.theme_hint or "",
    ]
    return "\n".join(part for part in parts if part)


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", text)]


def _topics(tokens: list[str], theme_hint: str) -> list[str]:
    token_set = set(tokens)
    topics: list[str] = []
    theme = theme_hint.lower()
    theme_topic_pairs = [
        ("vegetarian", "vegetarian"),
        ("investment", "investment"),
        ("gym", "exercise"),
        ("exercise", "exercise"),
        ("workout", "exercise"),
    ]
    for marker, topic in theme_topic_pairs:
        if marker in theme and topic not in topics:
            topics.append(topic)
    theme_topics = set(topics)
    for topic, keywords in TOPIC_KEYWORDS.items():
        if theme_topics and topic not in theme_topics:
            continue
        if token_set & keywords or topic in theme:
            if topic in topics:
                continue
            topics.append(topic)
    counts = Counter(token for token in tokens if token not in STOPWORDS and len(token) > 3)
    for token, _count in counts.most_common(10):
        if len(topics) >= 8:
            break
        if theme_topics and token in TOPIC_KEYWORDS and token not in theme_topics:
            continue
        if token not in topics and not token.isdigit():
            topics.append(token)
    return topics[:8]


def _summary(item: SavedItem, source_text: str) -> str | None:
    if not source_text.strip():
        return None
    basis = item.extracted_text or item.description or item.title or source_text
    sentences = re.split(r"(?<=[.!?])\s+", basis.strip())
    candidate = " ".join(sentence for sentence in sentences[:2] if sentence).strip()
    if not candidate:
        candidate = basis.strip()
    candidate = re.sub(r"\s+", " ", candidate)
    if len(candidate) > 360:
        candidate = candidate[:357].rstrip() + "..."
    if item.extraction_status in {"metadata_only", "blocked", "failed", "unsupported", "rejected"}:
        return f"Metadata-limited record: {candidate}"
    return candidate


def _entities(text: str) -> list[str]:
    candidates = re.findall(r"\b(?:[A-Z][a-zA-Z]+(?:\s+|$)){1,4}", text[:5000])
    cleaned: list[str] = []
    for candidate in candidates:
        entity = re.sub(r"\s+", " ", candidate).strip()
        if len(entity) > 2 and entity.lower() not in STOPWORDS and entity not in cleaned:
            cleaned.append(entity)
    return cleaned[:8]


def _content_type(item: SavedItem, tokens: list[str]) -> str:
    token_set = set(tokens)
    if item.source_type == "youtube":
        return "video"
    if {"recipe", "dinner", "tofu", "lentil"} & token_set:
        return "recipe"
    if {"workout", "exercise", "sets", "reps"} & token_set:
        return "exercise guide"
    if {"investment", "investing", "etf", "portfolio"} & token_set:
        return "education article"
    if item.extraction_status == "metadata_only":
        return "metadata record"
    return "article"


def _intent_tags(item: SavedItem, topics: list[str], content_type: str) -> list[str]:
    tags: list[str] = []
    topic_set = set(topics)
    if "vegetarian" in topic_set or content_type == "recipe":
        tags.append("cook")
    if "investment" in topic_set:
        tags.append("learn-investing")
    if "exercise" in topic_set:
        tags.append("train")
    if item.source_type == "youtube":
        tags.append("watch")
    elif content_type != "metadata record":
        tags.append("read")
    if item.extraction_status == "metadata_only":
        tags.append("metadata-only")
    if item.extraction_status in {"blocked", "failed", "unsupported", "rejected"}:
        tags.append("needs-review")
    return tags[:8]


def _suggested_collection(topics: list[str], intent_tags: list[str], status: str) -> str:
    if status == "metadata_only":
        return "Metadata Only"
    if "vegetarian" in topics or "cook" in intent_tags:
        return "Vegetarian Recipes"
    if "investment" in topics or "learn-investing" in intent_tags:
        return "Investment Education"
    if "exercise" in topics or "train" in intent_tags:
        return "Gym and Exercise"
    return "Needs Review"
