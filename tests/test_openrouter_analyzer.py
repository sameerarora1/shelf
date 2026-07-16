import json
from types import SimpleNamespace

import pytest

from shelf.analysis.categories import DEFAULT_COLLECTIONS
from shelf.analysis.openai_provider import OpenAIAnalyzer, OpenRouterConfigError
from shelf.models import SavedItem
from shelf.organization.organizer import Organizer


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        content = response if isinstance(response, str) else json.dumps(response)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content),
                )
            ]
        )


class FakeClient:
    def __init__(self, responses):
        self.completions = FakeCompletions(responses)
        self.chat = SimpleNamespace(completions=self.completions)


class RateLimitError(Exception):
    status_code = 429

    def __init__(self):
        self.body = {"error": {"message": "Rate limit exceeded: free-models-per-day"}}
        super().__init__("rate limit")


def _item(**overrides):
    data = {
        "item_id": "item1",
        "url": "https://example.com/item1",
        "canonical_url": "https://example.com/item1",
        "source_type": "public_webpage",
        "theme_hint": "",
        "selected_strategy": "WebPageExtractor",
        "extraction_status": "success",
        "title": "Understanding LLM agents",
        "description": "A guide to autonomous AI agents and tool use.",
        "extracted_text": "AI agents use LLMs, tools, memory, and planning to complete tasks.",
        "text_available": True,
        "text_character_count": 67,
        "trace_id": "trace1",
    }
    data.update(overrides)
    return SavedItem(**data)


def _llm_payload(action, category, confidence=0.9, reason="Test classification."):
    return {
        "summary": "Short summary.",
        "topics": ["ai agents"],
        "entities": [],
        "content_type": "article",
        "intent_tags": ["read"],
        "evidence_notes": ["validated by test"],
        "category_decision": {
            "action": action,
            "category": category,
            "confidence": confidence,
            "reason": reason,
        },
    }


def _analyzer(responses):
    return OpenAIAnalyzer(model="test-model", timeout_seconds=12, client=FakeClient(responses))


def _apply_analysis(organizer, analyzer, item):
    analysis = analyzer.analyze(item, organizer.category_context())
    item.collection = analysis.suggested_collection
    decision = organizer.assign(item, analysis)
    item.collection = decision.collection
    return analysis, decision


def test_investment_item_reuses_investment_education() -> None:
    analyzer = _analyzer(
        [
            _llm_payload(
                "use_existing",
                "Investment Education",
                reason="The item explains portfolio diversification and index funds.",
            )
        ]
    )
    item = _item(
        title="Index funds for beginners",
        description="Learn how ETFs, index funds, and portfolio risk work.",
        extracted_text="This investing guide explains index funds, ETFs, risk, and portfolios.",
    )

    result = analyzer.analyze(item, DEFAULT_COLLECTIONS)

    assert result.suggested_collection == "Investment Education"
    assert result.category_action == "use_existing"


def test_vegetarian_recipe_reuses_vegetarian_recipes() -> None:
    analyzer = _analyzer(
        [
            _llm_payload(
                "use_existing",
                "Vegetarian Recipes",
                reason="The item is a vegetarian lentil dinner recipe.",
            )
        ]
    )
    item = _item(
        title="Vegetarian lentil dinner",
        description="A tofu and lentil recipe for weeknight dinner.",
        extracted_text="Cook lentils, tofu, chickpeas, and vegetables for a vegetarian meal.",
    )

    result = analyzer.analyze(item, DEFAULT_COLLECTIONS)

    assert result.suggested_collection == "Vegetarian Recipes"
    assert result.category_action == "use_existing"


def test_ai_agent_item_creates_new_category_when_no_related_category_exists() -> None:
    analyzer = _analyzer(
        [
            _llm_payload(
                "create_new",
                "AI Agents",
                reason="No existing category covers autonomous LLM agents.",
            )
        ]
    )

    result = analyzer.analyze(_item(), DEFAULT_COLLECTIONS)

    assert result.suggested_collection == "AI Agents"
    assert result.category_action == "create_new"


def test_ai_agent_item_reuses_ai_llm_applications_when_available() -> None:
    analyzer = _analyzer(
        [
            _llm_payload(
                "use_existing",
                "AI and LLM Applications",
                reason="The item fits the existing AI application category.",
            )
        ]
    )

    result = analyzer.analyze(_item(), [*DEFAULT_COLLECTIONS, "AI and LLM Applications"])

    assert result.suggested_collection == "AI and LLM Applications"
    assert result.category_action == "use_existing"


def test_near_duplicate_ai_category_reuses_existing_category() -> None:
    analyzer = _analyzer(
        [
            _llm_payload(
                "create_new",
                "AI Agent Systems",
                reason="The model proposed a similar category.",
            )
        ]
    )

    result = analyzer.analyze(_item(), [*DEFAULT_COLLECTIONS, "AI Agents"])

    assert result.suggested_collection == "AI Agents"
    assert result.category_action == "use_existing"


def test_new_category_is_available_to_later_items_in_same_run() -> None:
    organizer = Organizer()
    analyzer = _analyzer(
        [
            _llm_payload("create_new", "AI Agents"),
            _llm_payload("use_existing", "AI Agents"),
        ]
    )

    first_item = _item(item_id="ai1", trace_id="trace-ai1")
    second_item = _item(item_id="ai2", trace_id="trace-ai2")
    _apply_analysis(organizer, analyzer, first_item)
    _apply_analysis(organizer, analyzer, second_item)

    second_prompt = analyzer._client.completions.calls[1]["messages"][1]["content"]
    existing_names = [
        category["name"]
        for category in json.loads(second_prompt)["existing_categories"]
    ]
    assert "AI Agents" in organizer.collection_names()
    assert "AI Agents" in existing_names
    assert first_item.collection == "AI Agents"
    assert second_item.collection == "AI Agents"


def test_insufficient_metadata_results_in_needs_review() -> None:
    analyzer = _analyzer(
        [
            _llm_payload(
                "needs_review",
                "Needs Review",
                confidence=0.34,
                reason="The item has too little information to categorize reliably.",
            )
        ]
    )
    item = _item(
        title=None,
        description=None,
        extracted_text=None,
        text_available=False,
        text_character_count=0,
    )

    result = analyzer.analyze(item, DEFAULT_COLLECTIONS)

    assert result.suggested_collection == "Needs Review"
    assert result.category_action == "needs_review"


def test_malformed_llm_response_falls_back_safely() -> None:
    analyzer = _analyzer(["not valid json"])

    result = analyzer.analyze(_item(), DEFAULT_COLLECTIONS)

    assert result.analysis_mode == "deterministic"
    assert result.suggested_collection == "AI and LLM Applications"
    assert any("deterministic fallback used" in note for note in result.evidence_notes)


def test_api_request_failure_falls_back_safely() -> None:
    analyzer = _analyzer([RuntimeError("network unavailable")])

    result = analyzer.analyze(_item(), DEFAULT_COLLECTIONS)

    assert result.analysis_mode == "deterministic"
    assert any("OpenRouter analyzer failed" in note for note in result.evidence_notes)


def test_rate_limit_is_sanitized_and_stops_later_provider_requests() -> None:
    client = FakeClient([RateLimitError()])
    analyzer = OpenAIAnalyzer(model="test-model", client=client)

    first = analyzer.analyze(_item(), DEFAULT_COLLECTIONS)
    second = analyzer.analyze(_item(item_id="item2"), DEFAULT_COLLECTIONS)

    assert len(client.completions.calls) == 1
    assert any("HTTP 429" in note for note in first.evidence_notes)
    assert any("skipped after a prior rate-limit" in note for note in second.evidence_notes)


def test_missing_openrouter_api_key_produces_clear_configuration_error(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(OpenRouterConfigError, match="OPENROUTER_API_KEY is required"):
        OpenAIAnalyzer()


def test_openrouter_request_uses_mocked_client_timeout_and_no_reasoning_options() -> None:
    analyzer = _analyzer([_llm_payload("create_new", "AI Agents")])

    analyzer.analyze(_item(), DEFAULT_COLLECTIONS)

    call = analyzer._client.completions.calls[0]
    assert call["model"] == "test-model"
    assert call["timeout"] == 12
    assert "extra_body" not in call
    assert call["response_format"] == {"type": "json_object"}
