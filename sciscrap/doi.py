"""DOI parsing helpers."""

from __future__ import annotations

import re
from pathlib import Path

# Crossref's recommended pattern, loosened slightly so it works on free text.
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>,;{}]+", re.IGNORECASE)
_TRAILING = ".)]}"


def normalize_doi(text: str) -> str | None:
    """Return the DOI contained in `text` (a bare DOI, doi: prefix or doi.org URL), or None."""
    if not text:
        return None
    match = DOI_RE.search(text.strip())
    if not match:
        return None
    doi = match.group(0)
    # Strip trailing punctuation picked up from prose, but keep balanced brackets
    # that are part of DOIs such as 10.1016/0006-2952(75)90084-2.
    while doi and doi[-1] in _TRAILING:
        if doi[-1] == ")" and doi.count("(") >= doi.count(")"):
            break
        doi = doi[:-1]
    return doi


def extract_dois(text: str) -> list[str]:
    """All unique DOIs in `text`, in order of first appearance (case-insensitive dedupe)."""
    seen: set[str] = set()
    out: list[str] = []
    for match in DOI_RE.finditer(text):
        doi = normalize_doi(match.group(0))
        if doi and doi.lower() not in seen:
            seen.add(doi.lower())
            out.append(doi)
    return out


def read_doi_file(path: str | Path) -> list[str]:
    """Read DOIs from any text-ish file: one-per-line .txt, .csv, .bib, .ris, JSON, even pasted references."""
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    return extract_dois(text)


def doi_to_filename(doi: str) -> str:
    return safe_filename(doi.replace("/", "_"))


_WIN_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_filename(name: str, max_len: int = 150) -> str:
    """Make `name` valid on Windows (the strictest target) as well as Linux/macOS."""
    name = _WIN_FORBIDDEN.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    name = name[:max_len].rstrip(". ")
    if not name:
        name = "paper"
    if name.split(".")[0].upper() in _WIN_RESERVED:
        name = "_" + name
    return name
