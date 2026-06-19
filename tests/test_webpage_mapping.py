from pathlib import Path

from shelf.config import Settings
from shelf.extractors.webpage import WebPageExtractor

FIXTURES = Path(__file__).parent / "fixtures"


def test_webpage_html_mapping_from_fixture() -> None:
    html = (FIXTURES / "webpage.html").read_text()
    extractor = WebPageExtractor(Settings.from_env(Path(__file__).parents[1]))
    result = extractor.map_html_to_result(
        "https://example.com/veg",
        "https://example.com/veg",
        {"content-type": "text/html; charset=utf-8"},
        html,
    )
    assert result.source_type == "public_webpage"
    assert result.extraction_status == "success"
    assert result.title == "High Protein Vegetarian Dinner Ideas"
    assert result.description
    assert result.text_available is True
    assert "lentils" in (result.extracted_text or "")


def test_webpage_metadata_only_fallback_from_empty_body() -> None:
    html = (
        "<html><head><title>Only Metadata</title>"
        "<meta name='description' content='Short description.'>"
        "</head><body></body></html>"
    )
    extractor = WebPageExtractor(Settings.from_env(Path(__file__).parents[1]))
    result = extractor.map_html_to_result(
        "https://example.com/meta",
        "https://example.com/meta",
        {"content-type": "text/html"},
        html,
    )
    assert result.extraction_status == "metadata_only"
    assert result.title == "Only Metadata"
    assert result.text_available is False
