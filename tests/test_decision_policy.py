from shelf.decision_policy import classify_url


def test_classifies_supported_public_sources() -> None:
    assert classify_url("https://www.youtube.com/watch?v=abc").source_type == "youtube"
    assert classify_url("https://youtu.be/abc").selected_strategy == "YouTubeExtractor"
    assert classify_url("https://example.com/article").source_type == "public_webpage"
    assert classify_url("https://www.instagram.com/p/example/").source_type == "instagram_public"
    assert classify_url("https://x.com/example/status/1").source_type == "x_public"
    assert classify_url("https://x.com/example/status/1").selected_strategy == "XPostExtractor"


def test_rejects_unsafe_urls() -> None:
    unsafe = [
        "file:///etc/passwd",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://10.0.0.1",
        "http://169.254.169.254/latest/meta-data",
        "ftp://example.com/file",
    ]
    for url in unsafe:
        decision = classify_url(url)
        assert decision.safe is False
        assert decision.selected_strategy == "UnsupportedExtractor"
        assert decision.error_code is not None
