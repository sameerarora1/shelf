from __future__ import annotations

import json
from pathlib import Path

from shelf import orchestrator
from shelf.config import Settings
from shelf.extractors import opencli as opencli_module
from shelf.extractors.base import ExtractionContext, ExtractorResult
from shelf.extractors.instagram import InstagramPostExtractor
from shelf.extractors.opencli import (
    OpenCliDoctorResult,
    OpenCliInstagramRunner,
    OpenCliPostRead,
    parse_instagram_markdown,
)
from shelf.orchestrator import ShelfPipeline

FIXTURE = Path(__file__).parent / "fixtures" / "instagram_post_markdown.txt"
POST_URL = "https://www.instagram.com/p/DWxmSwTDFk2/"


def _fixture_markdown() -> str:
    return FIXTURE.read_text(encoding="utf-8")


class FakeRunner:
    def __init__(
        self,
        doctor_result: OpenCliDoctorResult,
        read_result: OpenCliPostRead | None = None,
    ) -> None:
        self.doctor_result = doctor_result
        self.read_result = read_result
        self.read_urls: list[str] = []

    def doctor(self) -> OpenCliDoctorResult:
        return self.doctor_result

    def read_post(self, url: str) -> OpenCliPostRead:
        self.read_urls.append(url)
        assert self.read_result is not None
        return self.read_result


class FakePublicMetadataExtractor:
    def extract(self, context: ExtractionContext) -> ExtractorResult:
        return ExtractorResult(
            canonical_url=context.url,
            source_type="instagram_public",
            selected_strategy="PublicMetadataExtractor",
            extraction_status="metadata_only",
            title="Public Instagram metadata",
            description="Metadata that remains available without opencli.",
        )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        evidence_dir=tmp_path / "evidence",
        sqlite_path=tmp_path / ".shelf" / "shelf.sqlite3",
    )


def _available_doctor() -> OpenCliDoctorResult:
    return OpenCliDoctorResult(available=True, binary="opencli", session_active=True)


# --------------------------------------------------------------------------- #
# Markdown parser
# --------------------------------------------------------------------------- #


def test_parse_instagram_markdown_recovers_structured_fields() -> None:
    parsed = parse_instagram_markdown(_fixture_markdown(), POST_URL)

    assert parsed.author == "brycenwood.ai"
    assert parsed.media_type == "reel"
    assert parsed.display_date == "April 5"
    assert parsed.relative_time == "14w"
    assert parsed.canonical_url == "https://www.instagram.com/brycenwood.ai/reel/DWxmSwTDFk2/"
    assert parsed.like_count_display == "57.7K"
    assert parsed.comment_count_display == "13.6K"
    assert parsed.caption is not None
    assert parsed.caption.startswith("ChatGPT is recommending my vehicle wrap shop")
    assert "#chatgpt" in parsed.caption
    # Hashtag markdown links are collapsed to plain text (no residual markup).
    assert "](/explore/tags" not in parsed.caption
    assert parsed.has_caption is True


def test_parse_instagram_markdown_partial_when_caption_absent() -> None:
    markdown = (
        "[\n\nsomeone\n\n\n](/someone/)\n\n Edited•3d\n\n"
        "[![c's profile picture](x)](/c/)\n\n"
        "12.3K4.5K\n\n[April 1](/someone/reel/ABC123/)\n"
    )
    parsed = parse_instagram_markdown(markdown, "https://www.instagram.com/p/ABC123/")

    assert parsed.author == "someone"
    assert parsed.caption is None
    assert parsed.like_count_display == "12.3K"
    assert "caption" not in parsed.fields_found
    assert any("caption" in note for note in parsed.notes)


def test_parse_counts_note_when_not_splittable() -> None:
    markdown = "[\n\nx\n\n\n](/x/)\n\n 2d\n\ncaption body\n\n[April 1](/x/reel/ZZZ999/)\n"
    parsed = parse_instagram_markdown(markdown, "https://www.instagram.com/p/ZZZ999/")

    assert parsed.like_count_display is None
    assert parsed.comment_count_display is None
    assert any("counts" in note for note in parsed.notes)


# --------------------------------------------------------------------------- #
# Extractor success / partial
# --------------------------------------------------------------------------- #


def test_instagram_success_maps_parsed_post_to_result(tmp_path: Path) -> None:
    runner = FakeRunner(
        _available_doctor(),
        OpenCliPostRead(
            ok=True,
            url=POST_URL,
            markdown=_fixture_markdown(),
            argv_log=["opencli browser shelf-ig open " + POST_URL + " --window background"],
            returncode=0,
        ),
    )
    extractor = InstagramPostExtractor(_settings(tmp_path), runner=runner)

    result = extractor.extract(
        ExtractionContext(item_id="ig_1", url=POST_URL, raw_dir=tmp_path / "raw")
    )

    assert result.source_type == "instagram_public"
    assert result.selected_strategy == "InstagramPostExtractor"
    assert result.extraction_status == "success"
    assert result.creator_or_author == "brycenwood.ai"
    assert result.canonical_url == "https://www.instagram.com/brycenwood.ai/reel/DWxmSwTDFk2/"
    assert result.text_available is True
    assert result.extracted_text.startswith("ChatGPT is recommending")
    assert result.metadata["like_count_display"] == "57.7K"
    assert result.metadata["comment_count_display"] == "13.6K"
    assert runner.read_urls == [POST_URL]

    evidence = tmp_path / "raw" / "ig_1" / "instagram_opencli_response.json"
    assert evidence.exists()
    payload = json.loads(evidence.read_text())
    # Boolean-only session signal; no logged-in identity is persisted.
    assert payload["logged_in"] is True
    assert "username" not in payload
    assert "user_id" not in payload
    assert "session_active" not in payload
    assert payload["parsed"]["author"] == "brycenwood.ai"


def test_instagram_partial_parse_is_metadata_only(tmp_path: Path) -> None:
    markdown = (
        "[\n\nauthoronly\n\n\n](/authoronly/)\n\n 5d\n\n"
        "[![c's profile picture](x)](/c/)\n\n"
        "9.9K1.1K\n\n[March 2](/authoronly/reel/DEF456/)\n"
    )
    runner = FakeRunner(
        _available_doctor(),
        OpenCliPostRead(ok=True, url=POST_URL, markdown=markdown, returncode=0),
    )
    extractor = InstagramPostExtractor(_settings(tmp_path), runner=runner)

    result = extractor.extract(
        ExtractionContext(item_id="ig_partial", url="https://www.instagram.com/p/DEF456/")
    )

    assert result.extraction_status == "metadata_only"
    assert result.creator_or_author == "authoronly"
    assert result.text_available is False
    assert result.error_code == "opencli_instagram_partial"


# --------------------------------------------------------------------------- #
# Extractor fallbacks
# --------------------------------------------------------------------------- #


def test_instagram_unavailable_uses_public_metadata_fallback(tmp_path: Path) -> None:
    runner = FakeRunner(
        OpenCliDoctorResult(
            available=False,
            error_code="opencli_not_installed",
            error_message="opencli CLI is not resolvable.",
        )
    )
    extractor = InstagramPostExtractor(
        _settings(tmp_path),
        runner=runner,
        metadata_extractor=FakePublicMetadataExtractor(),  # type: ignore[arg-type]
    )

    result = extractor.extract(
        ExtractionContext(item_id="ig_2", url="https://www.instagram.com/p/DEF456/")
    )

    assert result.extraction_status == "metadata_only"
    assert result.title == "Public Instagram metadata"
    assert result.selected_strategy == "InstagramPostExtractor"
    assert result.error_code == "opencli_not_installed"
    assert result.metadata["opencli_error_code"] == "opencli_not_installed"


def test_instagram_empty_parse_uses_public_metadata_fallback(tmp_path: Path) -> None:
    # A page loaded but nothing recoverable -> prefer the richer metadata tier.
    runner = FakeRunner(
        _available_doctor(),
        OpenCliPostRead(
            ok=True,
            url=POST_URL,
            markdown="![](https://cdn.example/x.jpg)\n\nsome unrelated page text\n",
            returncode=0,
        ),
    )
    extractor = InstagramPostExtractor(
        _settings(tmp_path),
        runner=runner,
        metadata_extractor=FakePublicMetadataExtractor(),  # type: ignore[arg-type]
    )

    result = extractor.extract(
        ExtractionContext(item_id="ig_empty", url=POST_URL, raw_dir=tmp_path / "raw")
    )

    assert result.extraction_status == "metadata_only"
    assert result.error_code == "opencli_instagram_empty"
    assert (tmp_path / "raw" / "ig_empty" / "instagram_opencli_error.json").exists()


def test_instagram_read_failure_uses_public_metadata_fallback(tmp_path: Path) -> None:
    runner = FakeRunner(
        _available_doctor(),
        OpenCliPostRead(
            ok=False,
            url=POST_URL,
            error_code="opencli_browser_extract_failed",
            error_message="extract failed",
        ),
    )
    extractor = InstagramPostExtractor(
        _settings(tmp_path),
        runner=runner,
        metadata_extractor=FakePublicMetadataExtractor(),  # type: ignore[arg-type]
    )

    result = extractor.extract(
        ExtractionContext(item_id="ig_3", url=POST_URL, raw_dir=tmp_path / "raw")
    )

    assert result.extraction_status == "metadata_only"
    assert result.error_code == "opencli_browser_extract_failed"
    error_evidence = tmp_path / "raw" / "ig_3" / "instagram_opencli_error.json"
    assert error_evidence.exists()


# --------------------------------------------------------------------------- #
# Subprocess layer (mocked) — no live network / browser
# --------------------------------------------------------------------------- #


class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_runner_doctor_reads_session_without_persisting_identity(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        # whoami returns identity fields; the runner must reduce this to a bool.
        return _FakeCompleted(
            0,
            stdout=json.dumps(
                {"user_id": "999", "username": "the_logged_in_user", "full_name": "Private Name"}
            ),
        )

    monkeypatch.setattr(opencli_module.shutil, "which", lambda _name: "/fake/opencli")
    monkeypatch.setattr(opencli_module.subprocess, "run", fake_run)

    runner = OpenCliInstagramRunner(30.0, session_name="shelf-ig")
    doctor = runner.doctor()

    assert doctor.available is True
    assert doctor.session_active is True
    assert calls == [["/fake/opencli", "instagram", "whoami", "-f", "json"]]
    # The result object structurally cannot carry identity fields.
    serialized = json.dumps(doctor.__dict__, default=str)
    assert "the_logged_in_user" not in serialized
    assert "Private Name" not in serialized


def test_runner_read_post_drives_open_extract_close(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        action = argv[3] if len(argv) > 3 else ""
        if action == "open":
            return _FakeCompleted(0, stdout=json.dumps({"url": POST_URL, "page": "abc"}))
        if action == "extract":
            return _FakeCompleted(0, stdout=json.dumps({"content": _fixture_markdown()}))
        if action == "close":
            return _FakeCompleted(0, stdout="closed")
        return _FakeCompleted(1, stderr="unexpected")

    monkeypatch.setattr(opencli_module.shutil, "which", lambda _name: "/fake/opencli")
    monkeypatch.setattr(opencli_module.subprocess, "run", fake_run)

    runner = OpenCliInstagramRunner(
        30.0, session_name="shelf-ig", window_mode="background"
    )
    read = runner.read_post(POST_URL)

    assert read.ok is True
    assert "ChatGPT is recommending" in read.markdown
    actions = [c[3] for c in calls]
    assert actions == ["open", "extract", "close"]
    # Background window flag is passed on open.
    assert "--window" in calls[0] and "background" in calls[0]


def test_runner_read_post_closes_session_on_extract_failure(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        action = argv[3] if len(argv) > 3 else ""
        if action == "open":
            return _FakeCompleted(0, stdout=json.dumps({"url": POST_URL}))
        if action == "extract":
            return _FakeCompleted(1, stderr="extract boom")
        return _FakeCompleted(0, stdout="closed")

    monkeypatch.setattr(opencli_module.shutil, "which", lambda _name: "/fake/opencli")
    monkeypatch.setattr(opencli_module.subprocess, "run", fake_run)

    runner = OpenCliInstagramRunner(30.0)
    read = runner.read_post(POST_URL)

    assert read.ok is False
    assert read.error_code == "opencli_browser_extract_failed"
    # close is still invoked to release the tab lease.
    assert [c[3] for c in calls][-1] == "close"


def test_runner_doctor_reports_missing_binary(monkeypatch) -> None:
    monkeypatch.setattr(opencli_module.shutil, "which", lambda _name: None)
    runner = OpenCliInstagramRunner(30.0)
    doctor = runner.doctor()
    assert doctor.available is False
    assert doctor.error_code == "opencli_not_installed"


# --------------------------------------------------------------------------- #
# Pipeline / trace coverage
# --------------------------------------------------------------------------- #


def test_pipeline_analyzes_instagram_fallback_record(monkeypatch, tmp_path: Path) -> None:
    class FakeInstagramPostExtractor:
        def extract(self, context: ExtractionContext) -> ExtractorResult:
            return ExtractorResult(
                canonical_url=context.url,
                source_type="instagram_public",
                selected_strategy="InstagramPostExtractor",
                extraction_status="metadata_only",
                title="Fitness post on Instagram",
                description="A public post about bodyweight exercise.",
                error_code="opencli_instagram_session_unavailable",
                error_message="opencli Instagram session is unavailable.",
            )

    monkeypatch.setattr(
        orchestrator,
        "InstagramPostExtractor",
        lambda _settings: FakeInstagramPostExtractor(),
    )
    csv_path = tmp_path / "instagram.csv"
    csv_path.write_text(
        "\n".join(
            [
                "item_id,url,theme_hint,notes",
                "ig_item,https://www.instagram.com/p/XYZ123/,gym exercise,fixture",
            ]
        ),
        encoding="utf-8",
    )

    result = ShelfPipeline(_settings(tmp_path)).run_csv(csv_path)

    item = result.items[0]
    assert item.source_type == "instagram_public"
    assert item.selected_strategy == "InstagramPostExtractor"
    assert item.extraction_status == "metadata_only"
    assert item.summary
    assert item.collection == "Metadata Only"
    assert "fallback" in {event.stage for event in result.traces}
