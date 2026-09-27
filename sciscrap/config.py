"""Runtime configuration. Every value can be overridden by env var or CLI flag."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_MIRRORS = [
    "https://www.sci-hub.in",
    "https://sci-hub.se",
    "https://sci-hub.st",
    "https://sci-hub.ru",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return list(default)
    return [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]


@dataclass
class Config:
    # Sci-Hub mirrors, tried in order; the first one that works is remembered.
    mirrors: list[str] = field(default_factory=lambda: _env_list("SCISCRAP_MIRRORS", DEFAULT_MIRRORS))
    # Download sources, tried in order: "oa" (open access: Unpaywall/OpenAlex/Semantic Scholar/arXiv)
    # and "scihub".
    sources: list[str] = field(default_factory=lambda: _env_list("SCISCRAP_SOURCES", ["oa", "scihub"]))
    # Contact email: required by Unpaywall, and puts OpenAlex/Crossref requests in their faster "polite pool".
    email: str = field(default_factory=lambda: os.environ.get("SCISCRAP_EMAIL", ""))
    openalex_api_key: str = field(default_factory=lambda: os.environ.get("OPENALEX_API_KEY", ""))
    s2_api_key: str = field(default_factory=lambda: os.environ.get("S2_API_KEY", ""))
    # Minimum seconds between two requests to the same host.
    delay: float = field(default_factory=lambda: float(os.environ.get("SCISCRAP_DELAY", "2.0")))
    timeout: float = field(default_factory=lambda: float(os.environ.get("SCISCRAP_TIMEOUT", "60")))
    workers: int = field(default_factory=lambda: int(os.environ.get("SCISCRAP_WORKERS", "3")))
    max_pdf_mb: int = 200
    proxy: str = field(default_factory=lambda: os.environ.get("SCISCRAP_PROXY", ""))
