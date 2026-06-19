from shelf.extractors.base import ExtractorResult
from shelf.orchestrator import validate_extraction_result
from shelf.trace import TraceRecorder


def test_validation_accepts_text_success() -> None:
    result = ExtractorResult(
        canonical_url="https://example.com",
        source_type="public_webpage",
        selected_strategy="WebPageExtractor",
        extraction_status="success",
        extracted_text="usable extracted text",
        text_available=True,
    )
    valid, reason = validate_extraction_result(result)
    assert valid is True
    assert "non-empty" in reason


def test_validation_flags_failed_for_fallback() -> None:
    result = ExtractorResult(
        canonical_url="https://example.com",
        source_type="public_webpage",
        selected_strategy="WebPageExtractor",
        extraction_status="failed",
        error_code="network_error",
    )
    valid, reason = validate_extraction_result(result)
    assert valid is False
    assert "fallback" in reason


def test_trace_sequence_increments_per_trace() -> None:
    recorder = TraceRecorder()
    recorder.record(
        trace_id="t1",
        item_id="i1",
        stage="triage",
        action="a",
        decision="d",
        reason="r",
        tool="tool",
        status="ok",
    )
    recorder.record(
        trace_id="t1",
        item_id="i1",
        stage="strategy_selection",
        action="a",
        decision="d",
        reason="r",
        tool="tool",
        status="ok",
    )
    assert [event.sequence for event in recorder.events] == [1, 2]

