import json
from pathlib import Path

from shelf.config import Settings
from shelf.extractors.youtube import YouTubeExtractor, normalize_subtitle_text

FIXTURES = Path(__file__).parent / "fixtures"


def test_youtube_metadata_mapping_from_fixture() -> None:
    info = json.loads((FIXTURES / "youtube_info.json").read_text())
    extractor = YouTubeExtractor(Settings.from_env(Path(__file__).parents[1]))
    result = extractor.map_info_to_result(
        "https://www.youtube.com/watch?v=abc123",
        info,
        transcript_text="Welcome to beginner strength training.",
        subtitle_source="human:en",
    )
    assert result.source_type == "youtube"
    assert result.extraction_status == "success"
    assert result.title == "Beginner Strength Training Basics"
    assert result.creator_or_author == "Example Fitness Channel"
    assert result.published_at == "2024-01-15"
    assert result.duration_seconds == 612
    assert result.text_available is True
    assert result.metadata["subtitle_source"] == "human:en"


def test_subtitle_normalization_removes_timestamps_and_duplicates() -> None:
    subtitle = (FIXTURES / "sample_subtitles.vtt").read_text()
    normalized = normalize_subtitle_text(subtitle)
    assert "00:00" not in normalized
    assert "WEBVTT" not in normalized
    assert normalized.count("safe exercise form") == 1
    assert normalized.startswith("Welcome to beginner strength training.")

