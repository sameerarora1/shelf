from shelf.analysis.deterministic import DeterministicAnalyzer
from shelf.models import SavedItem
from shelf.organization.organizer import Organizer


def _item(**overrides):
    data = {
        "item_id": "item1",
        "url": "https://example.com",
        "canonical_url": "https://example.com",
        "source_type": "public_webpage",
        "theme_hint": "vegetarian recipes",
        "selected_strategy": "WebPageExtractor",
        "extraction_status": "success",
        "title": "Vegetarian lentil dinner",
        "description": "A recipe with tofu and lentils.",
        "extracted_text": "A vegetarian recipe for dinner with tofu and lentils.",
        "text_available": True,
        "text_character_count": 54,
        "trace_id": "trace1",
    }
    data.update(overrides)
    return SavedItem(**data)


def test_deterministic_analyzer_generates_tags() -> None:
    item = _item()
    result = DeterministicAnalyzer().analyze(item)
    assert "vegetarian" in result.topics
    assert "cook" in result.intent_tags
    assert result.analysis_mode == "deterministic"


def test_organizer_assigns_collection() -> None:
    item = _item(topics=["vegetarian"], intent_tags=["cook"], content_type="recipe")
    decision = Organizer().assign(item)
    assert decision.collection == "Vegetarian Recipes"
    assert "vegetarian" in decision.reason.lower()


def test_organizer_sends_failed_items_to_review() -> None:
    item = _item(extraction_status="failed")
    decision = Organizer().assign(item)
    assert decision.collection == "Needs Review"

