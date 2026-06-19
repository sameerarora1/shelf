from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is declared but optional at import time
    load_dotenv = None


DEFAULT_USER_AGENT = "ShelfCheckpoint1/0.1 (+https://github.com/infinityaurora6/shelf)"


@dataclass(frozen=True)
class Settings:
    project_root: Path
    data_dir: Path
    evidence_dir: Path
    sqlite_path: Path
    analyzer: str = "deterministic"
    openai_model: str = "gpt-4.1-mini"
    http_timeout_seconds: float = 15.0
    http_max_redirects: int = 5
    http_max_bytes: int = 2_000_000
    raw_html_max_chars: int = 120_000
    user_agent: str = DEFAULT_USER_AGENT

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> Settings:
        root = (project_root or Path.cwd()).resolve()
        if load_dotenv is not None:
            load_dotenv(root / ".env")
        return cls(
            project_root=root,
            data_dir=root / "data",
            evidence_dir=root / "evidence",
            sqlite_path=root / ".shelf" / "shelf.sqlite3",
            analyzer=os.getenv("SHELF_ANALYZER", "deterministic").strip().lower()
            or "deterministic",
            openai_model=os.getenv("SHELF_OPENAI_MODEL", "gpt-4.1-mini").strip()
            or "gpt-4.1-mini",
            http_timeout_seconds=float(os.getenv("SHELF_HTTP_TIMEOUT_SECONDS", "15")),
            http_max_redirects=int(os.getenv("SHELF_HTTP_MAX_REDIRECTS", "5")),
            http_max_bytes=int(os.getenv("SHELF_HTTP_MAX_BYTES", "2000000")),
            raw_html_max_chars=int(os.getenv("SHELF_RAW_HTML_MAX_CHARS", "120000")),
            user_agent=os.getenv("SHELF_USER_AGENT", DEFAULT_USER_AGENT).strip()
            or DEFAULT_USER_AGENT,
        )

    def redacted_config(self) -> dict[str, str | int | float]:
        return {
            "analyzer": self.analyzer,
            "openai_model_configured": bool(os.getenv("OPENAI_API_KEY")),
            "http_timeout_seconds": self.http_timeout_seconds,
            "http_max_redirects": self.http_max_redirects,
            "http_max_bytes": self.http_max_bytes,
            "raw_html_max_chars": self.raw_html_max_chars,
            "user_agent": self.user_agent,
            "sqlite_path": str(self.sqlite_path),
        }


def ensure_project_dirs(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.evidence_dir.mkdir(parents=True, exist_ok=True)
    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

