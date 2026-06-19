from __future__ import annotations

from shelf.extractors.base import ExtractionContext, ExtractorResult


class UnsupportedExtractor:
    selected_strategy = "UnsupportedExtractor"

    def __init__(self, *, reason: str, error_code: str = "unsupported_source") -> None:
        self.reason = reason
        self.error_code = error_code

    def extract(self, context: ExtractionContext) -> ExtractorResult:
        return ExtractorResult(
            canonical_url=context.url,
            source_type="unsupported",
            selected_strategy=self.selected_strategy,
            extraction_status="rejected" if self.error_code.startswith("unsafe") else "unsupported",
            error_code=self.error_code,
            error_message=self.reason,
        )

