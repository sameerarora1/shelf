from __future__ import annotations

import csv
from pathlib import Path
from statistics import mean
from typing import Any

from shelf.models import SavedItem
from shelf.retrieval.index import TfidfSearchIndex


def parse_relevant_ids(value: str) -> set[str]:
    return {part.strip() for part in value.replace(";", "|").split("|") if part.strip()}


def evaluate_queries(
    items: list[SavedItem],
    queries_csv: Path,
    *,
    top_k: int = 3,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not queries_csv.exists():
        return (
            {
                "status": "not_evaluated",
                "reason": f"Query file not found: {queries_csv}",
                "evaluated_query_count": 0,
            },
            [],
        )

    rows: list[dict[str, str]] = []
    with queries_csv.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(row)

    labeled_rows = [
        row
        for row in rows
        if row.get("query") and parse_relevant_ids(row.get("relevant_item_ids", ""))
    ]
    if not labeled_rows:
        return (
            {
                "status": "not_evaluated",
                "reason": "No rows contain both query and relevant_item_ids labels.",
                "evaluated_query_count": 0,
            },
            [],
        )

    index = TfidfSearchIndex(items)
    details: list[dict[str, Any]] = []
    precisions: list[float] = []
    reciprocal_ranks: list[float] = []
    for row in labeled_rows:
        query = row["query"]
        relevant = parse_relevant_ids(row.get("relevant_item_ids", ""))
        results = index.search(query, top_k=top_k)
        returned = [result.item_id for result in results]
        hits = [item_id for item_id in returned[:top_k] if item_id in relevant]
        precision = len(hits) / top_k
        rr = 0.0
        for rank, item_id in enumerate(returned, start=1):
            if item_id in relevant:
                rr = 1.0 / rank
                break
        precisions.append(precision)
        reciprocal_ranks.append(rr)
        details.append(
            {
                "query_id": row.get("query_id") or "",
                "query": query,
                "relevant_item_ids": sorted(relevant),
                "returned_item_ids": returned,
                "precision_at_3": precision,
                "reciprocal_rank": rr,
            }
        )

    metrics = {
        "status": "evaluated",
        "precision_at_3": mean(precisions) if precisions else 0.0,
        "mrr": mean(reciprocal_ranks) if reciprocal_ranks else 0.0,
        "evaluated_query_count": len(labeled_rows),
        "top_k": top_k,
    }
    return metrics, details

