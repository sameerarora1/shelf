from __future__ import annotations

from dataclasses import dataclass

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from shelf.models import SavedItem


@dataclass(frozen=True)
class SearchResult:
    item_id: str
    score: float
    title: str | None
    collection: str
    extraction_status: str
    summary: str | None


class TfidfSearchIndex:
    def __init__(self, items: list[SavedItem]) -> None:
        self.items = items
        self._corpus = [_document_text(item) for item in items]
        self._vectorizer: TfidfVectorizer | None = None
        self._matrix = None
        if any(text.strip() for text in self._corpus):
            self._vectorizer = TfidfVectorizer(stop_words="english", max_features=5000)
            self._matrix = self._vectorizer.fit_transform(self._corpus)

    def search(self, query: str, top_k: int = 3) -> list[SearchResult]:
        if not self.items or self._vectorizer is None or self._matrix is None:
            return []
        query_vector = self._vectorizer.transform([query])
        scores = cosine_similarity(query_vector, self._matrix).ravel()
        ranked = sorted(enumerate(scores), key=lambda pair: pair[1], reverse=True)[:top_k]
        return [
            SearchResult(
                item_id=self.items[index].item_id,
                score=float(score),
                title=self.items[index].title,
                collection=self.items[index].collection,
                extraction_status=self.items[index].extraction_status,
                summary=self.items[index].summary,
            )
            for index, score in ranked
            if score > 0
        ]


def _document_text(item: SavedItem) -> str:
    text_cap = (item.extracted_text or "")[:20_000]
    return "\n".join(
        [
            item.title or "",
            item.summary or "",
            " ".join(item.topics),
            " ".join(item.entities),
            " ".join(item.intent_tags),
            text_cap,
        ]
    )

