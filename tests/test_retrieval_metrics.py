from pathlib import Path

from shelf.models import SavedItem
from shelf.retrieval.evaluate import evaluate_queries
from shelf.retrieval.index import TfidfSearchIndex


def _saved_item(item_id: str, title: str, summary: str, topics: list[str]) -> SavedItem:
    return SavedItem(
        item_id=item_id,
        url=f"https://example.com/{item_id}",
        canonical_url=f"https://example.com/{item_id}",
        source_type="public_webpage",
        theme_hint="",
        selected_strategy="WebPageExtractor",
        extraction_status="success",
        title=title,
        extracted_text=summary,
        text_available=True,
        text_character_count=len(summary),
        summary=summary,
        topics=topics,
        entities=[],
        content_type="article",
        intent_tags=topics,
        collection="Needs Review",
        trace_id=f"trace-{item_id}",
    )


def test_tfidf_search_returns_relevant_item() -> None:
    items = [
        _saved_item("veg", "Vegetarian dinner", "lentils tofu protein recipe", ["vegetarian"]),
        _saved_item("invest", "Index funds", "ETF investing portfolio risk", ["investment"]),
    ]
    results = TfidfSearchIndex(items).search("tofu vegetarian protein", top_k=1)
    assert results[0].item_id == "veg"


def test_precision_and_mrr(tmp_path: Path) -> None:
    items = [
        _saved_item("veg", "Vegetarian dinner", "lentils tofu protein recipe", ["vegetarian"]),
        _saved_item("invest", "Index funds", "ETF investing portfolio risk", ["investment"]),
        _saved_item("gym", "Bodyweight workout", "beginner workout reps sets", ["exercise"]),
    ]
    queries = tmp_path / "queries.csv"
    queries.write_text(
        "query_id,query,relevant_item_ids\n"
        "q1,vegetarian tofu protein,veg\n"
        "q2,index ETF portfolio,invest\n",
        encoding="utf-8",
    )
    metrics, details = evaluate_queries(items, queries)
    assert metrics["status"] == "evaluated"
    assert metrics["evaluated_query_count"] == 2
    assert metrics["mrr"] == 1.0
    assert details[0]["precision_at_3"] == 1 / 3

