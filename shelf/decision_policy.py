from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlparse

from shelf.models import SourceType

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "music.youtube.com",
}
INSTAGRAM_HOSTS = {"instagram.com", "www.instagram.com"}
X_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}


@dataclass(frozen=True)
class UrlDecision:
    url: str
    canonical_url: str
    source_type: SourceType
    selected_strategy: str
    safe: bool
    decision: str
    reason: str
    error_code: str | None = None


def _hostname_is_blocked(hostname: str) -> tuple[bool, str | None]:
    host = hostname.strip().lower().rstrip(".")
    if host in {"localhost", "0", "0.0.0.0"} or host.endswith(".localhost"):
        return True, "localhost hostname"

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False, None

    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    ):
        return True, f"blocked IP address range: {ip}"
    return False, None


def _registered_host(hostname: str) -> str:
    host = hostname.lower().rstrip(".")
    parts = host.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def classify_url(url: str) -> UrlDecision:
    raw_url = url.strip()
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"}:
        return UrlDecision(
            url=raw_url,
            canonical_url=raw_url,
            source_type="unsupported",
            selected_strategy="UnsupportedExtractor",
            safe=False,
            decision="reject",
            reason=f"Non-HTTP URL scheme is not allowed: {parsed.scheme or 'missing'}",
            error_code="unsafe_scheme",
        )
    if not parsed.hostname:
        return UrlDecision(
            url=raw_url,
            canonical_url=raw_url,
            source_type="unsupported",
            selected_strategy="UnsupportedExtractor",
            safe=False,
            decision="reject",
            reason="URL is missing a hostname",
            error_code="missing_hostname",
        )

    blocked, reason = _hostname_is_blocked(parsed.hostname)
    if blocked:
        return UrlDecision(
            url=raw_url,
            canonical_url=raw_url,
            source_type="unsupported",
            selected_strategy="UnsupportedExtractor",
            safe=False,
            decision="reject",
            reason=f"Unsafe URL target rejected: {reason}",
            error_code="unsafe_host",
        )

    host = parsed.hostname.lower().rstrip(".")
    registered = _registered_host(host)
    if host in YOUTUBE_HOSTS or registered == "youtube.com":
        source_type: SourceType = "youtube"
        strategy = "YouTubeExtractor"
    elif host in INSTAGRAM_HOSTS or registered == "instagram.com":
        source_type = "instagram_public"
        strategy = "PublicMetadataExtractor"
    elif host in X_HOSTS or registered in {"x.com", "twitter.com"}:
        source_type = "x_public"
        strategy = "XPostExtractor"
    else:
        source_type = "public_webpage"
        strategy = "WebPageExtractor"

    return UrlDecision(
        url=raw_url,
        canonical_url=raw_url,
        source_type=source_type,
        selected_strategy=strategy,
        safe=True,
        decision="accept",
        reason=f"Routed {host} to {strategy}",
    )
