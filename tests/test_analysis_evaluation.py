from shelf.analysis.evaluate import evaluate_analysis_quality
from shelf.models import SavedItem, TraceEvent


def _item(**overrides):
    data = {
        "item_id": "veg",
        "url": "https://example.com/veg",
        "canonical_url": "https://example.com/veg",
        "source_type": "public_webpage",
        "theme_hint": "vegetarian recipes",
        "selected_strategy": "WebPageExtractor",
        "extraction_status": "success",
        "title": "Vegetarian dinner",
        "extracted_text": "A vegetarian dinner with tofu and lentils.",
        "text_available": True,
        "text_character_count": 42,
        "summary": "A vegetarian dinner with tofu and lentils.",
        "topics": ["vegetarian", "tofu"],
        "entities": [],
        "content_type": "recipe",
        "intent_tags": ["cook", "read"],
        "collection": "Vegetarian Recipes",
        "analysis_mode": "deterministic",
        "trace_id": "trace-veg",
    }
    data.update(overrides)
    return SavedItem(**data)


def _traces(item_id: str, trace_id: str, *, fallback: bool = False) -> list[TraceEvent]:
    stages = [
        "triage",
        "strategy_selection",
        "extraction",
        "validation",
        "analysis",
        "organization",
        "indexing",
        "persistence",
    ]
    if fallback:
        stages.insert(4, "fallback")
    return [
        TraceEvent(
            trace_id=trace_id,
            item_id=item_id,
            sequence=index,
            stage=stage,
            action=stage,
            decision="ok",
            reason="test trace",
            tool="test",
            status="ok",
        )
        for index, stage in enumerate(stages, start=1)
    ]


def test_analysis_quality_passes_complete_success_item() -> None:
    item = _item()
    metrics, details = evaluate_analysis_quality([item], _traces("veg", "trace-veg"))

    assert metrics["item_count"] == 1
    assert metrics["structured_output_valid_rate"] == 1.0
    assert metrics["metadata_complete_rate"] == 1.0
    assert metrics["tag_agreement_rate"] == 1.0
    assert metrics["trace_coverage_rate"] == 1.0
    assert metrics["overall_pass_rate"] == 1.0
    assert details[0]["failure_reasons"] == []


def test_analysis_quality_requires_error_evidence_for_fallback_items() -> None:
    item = _item(
        item_id="blocked",
        url="https://example.com/blocked",
        canonical_url="https://example.com/blocked",
        theme_hint="investment education",
        extraction_status="blocked",
        title=None,
        extracted_text=None,
        text_available=False,
        text_character_count=0,
        summary="Metadata-limited record: investment education",
        topics=["investment"],
        content_type="education article",
        intent_tags=["learn-investing", "read", "needs-review"],
        collection="Needs Review",
        error_code=None,
        error_message=None,
        trace_id="trace-blocked",
    )
    metrics, details = evaluate_analysis_quality(
        [item],
        _traces("blocked", "trace-blocked", fallback=True),
    )

    assert metrics["metadata_complete_rate"] == 0.0
    assert metrics["fallback_behavior_valid_rate"] == 0.0
    assert metrics["overall_pass_rate"] == 0.0
    assert "fallback item is missing error evidence" in details[0]["failure_reasons"]


def test_analysis_quality_flags_missing_trace_stage() -> None:
    item = _item()
    metrics, details = evaluate_analysis_quality([item], [])

    assert metrics["trace_coverage_rate"] == 0.0
    assert metrics["overall_pass_rate"] == 0.0
    assert any(
        reason.startswith("missing trace stages:")
        for reason in details[0]["failure_reasons"]
    )
