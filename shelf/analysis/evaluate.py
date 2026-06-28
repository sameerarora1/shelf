from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from shelf.models import SavedItem, TraceEvent

REQUIRED_TRACE_STAGES = {
    "triage",
    "strategy_selection",
    "extraction",
    "validation",
    "analysis",
    "organization",
    "indexing",
    "persistence",
}
FALLBACK_STATUSES = {"metadata_only", "blocked", "failed", "unsupported", "rejected"}


def evaluate_analysis_quality(
    items: list[SavedItem],
    traces: list[TraceEvent] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    trace_stages = _trace_stages_by_item(traces or [])
    details = [_evaluate_item(item, trace_stages.get(item.item_id, set())) for item in items]
    modes = Counter(item.analysis_mode for item in items)

    metrics = {
        "status": "evaluated" if items else "not_evaluated",
        "item_count": len(items),
        "analysis_modes": dict(sorted(modes.items())),
        "structured_output_valid_count": _count_true(details, "structured_output_valid"),
        "metadata_complete_count": _count_true(details, "metadata_complete"),
        "tag_agreement_count": _count_true(details, "tag_agreement"),
        "fallback_behavior_valid_count": _count_true(details, "fallback_behavior_valid"),
        "trace_coverage_count": _count_true(details, "trace_coverage_valid"),
        "overall_pass_count": _count_true(details, "overall_pass"),
    }
    for key in (
        "structured_output_valid",
        "metadata_complete",
        "tag_agreement",
        "fallback_behavior_valid",
        "trace_coverage",
        "overall_pass",
    ):
        count_key = f"{key}_count"
        metrics[f"{key}_rate"] = _rate(metrics[count_key], len(items))
    return metrics, details


def _evaluate_item(item: SavedItem, observed_stages: set[str]) -> dict[str, Any]:
    expected = _expected_from_theme(item.theme_hint)
    structured, structured_reasons = _structured_output_check(item)
    metadata, metadata_reasons = _metadata_check(item)
    tag_agreement, tag_reasons = _tag_agreement_check(item, expected)
    fallback, fallback_reasons = _fallback_check(item)
    trace_coverage, missing_stages = _trace_coverage_check(item, observed_stages)
    reasons = (
        structured_reasons
        + metadata_reasons
        + tag_reasons
        + fallback_reasons
        + [f"missing trace stages: {', '.join(missing_stages)}" for _ in missing_stages[:1]]
    )
    return {
        "item_id": item.item_id,
        "source_type": item.source_type,
        "extraction_status": item.extraction_status,
        "analysis_mode": item.analysis_mode,
        "expected_topic": expected.get("topic"),
        "expected_collection": expected.get("collection"),
        "actual_collection": item.collection,
        "structured_output_valid": structured,
        "metadata_complete": metadata,
        "tag_agreement": tag_agreement,
        "fallback_behavior_valid": fallback,
        "trace_coverage_valid": trace_coverage,
        "overall_pass": all([structured, metadata, tag_agreement, fallback, trace_coverage]),
        "failure_reasons": reasons,
    }


def _trace_stages_by_item(traces: list[TraceEvent]) -> dict[str, set[str]]:
    stages: defaultdict[str, set[str]] = defaultdict(set)
    for trace in traces:
        stages[trace.item_id].add(trace.stage)
    return dict(stages)


def _structured_output_check(item: SavedItem) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not (item.summary or "").strip():
        reasons.append("summary is missing")
    if not item.topics:
        reasons.append("topics are missing")
    if not (item.content_type or "").strip() or item.content_type == "unknown":
        reasons.append("content_type is missing or unknown")
    if not item.intent_tags:
        reasons.append("intent_tags are missing")
    if not (item.analysis_mode or "").strip():
        reasons.append("analysis_mode is missing")
    return not reasons, reasons


def _metadata_check(item: SavedItem) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    for field_name in ("canonical_url", "source_type", "selected_strategy", "extraction_status"):
        if not getattr(item, field_name):
            reasons.append(f"{field_name} is missing")
    if item.extraction_status == "success":
        if not item.title:
            reasons.append("successful item is missing title")
        if not item.text_available or item.text_character_count <= 0:
            reasons.append("successful item is missing extracted text")
    elif item.extraction_status == "metadata_only":
        if not (item.title or item.description):
            reasons.append("metadata-only item lacks public title or description")
    else:
        if not (item.error_code or item.error_message):
            reasons.append("fallback item is missing error evidence")
    return not reasons, reasons


def _tag_agreement_check(item: SavedItem, expected: dict[str, str]) -> tuple[bool, list[str]]:
    if not expected:
        return True, []
    reasons: list[str] = []
    expected_topic = expected["topic"]
    if expected_topic not in {topic.lower() for topic in item.topics}:
        reasons.append(f"expected topic missing: {expected_topic}")
    if item.extraction_status == "success" and item.collection != expected["collection"]:
        reasons.append(f"expected collection {expected['collection']}, got {item.collection}")
    return not reasons, reasons


def _fallback_check(item: SavedItem) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if item.extraction_status == "metadata_only":
        if item.collection != "Metadata Only":
            reasons.append("metadata-only item is not in Metadata Only collection")
        if "metadata-only" not in item.intent_tags:
            reasons.append("metadata-only item lacks metadata-only intent tag")
    elif item.extraction_status in {"blocked", "failed", "unsupported", "rejected"}:
        if item.collection != "Needs Review":
            reasons.append("fallback item is not in Needs Review collection")
        if "needs-review" not in item.intent_tags:
            reasons.append("fallback item lacks needs-review intent tag")
        if not (item.error_code or item.error_message):
            reasons.append("fallback item lacks error evidence")
    return not reasons, reasons


def _trace_coverage_check(item: SavedItem, observed_stages: set[str]) -> tuple[bool, list[str]]:
    required = set(REQUIRED_TRACE_STAGES)
    if item.extraction_status in FALLBACK_STATUSES:
        required.add("fallback")
    missing = sorted(required - observed_stages)
    return not missing, missing


def _expected_from_theme(theme_hint: str) -> dict[str, str]:
    theme = theme_hint.lower()
    if "vegetarian" in theme or "recipe" in theme:
        return {
            "topic": "vegetarian",
            "collection": "Vegetarian Recipes",
        }
    if "investment" in theme or "investing" in theme:
        return {
            "topic": "investment",
            "collection": "Investment Education",
        }
    if "gym" in theme or "exercise" in theme or "workout" in theme:
        return {
            "topic": "exercise",
            "collection": "Gym and Exercise",
        }
    return {}


def _count_true(details: list[dict[str, Any]], key: str) -> int:
    return sum(1 for row in details if row[key])


def _rate(count: int, total: int) -> float:
    if total == 0:
        return 0.0
    return round(count / total, 4)
