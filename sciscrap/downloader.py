"""Batch downloading with concurrency, resume, and a CSV manifest."""

from __future__ import annotations

import csv
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from .config import Config
from .doi import doi_to_filename, normalize_doi, safe_filename
from .net import Http
from .search import Paper
from .sources import NotFound, OpenAccessSource, SciHubSource

log = logging.getLogger(__name__)

MANIFEST = "manifest.csv"
FAILED = "failed_dois.txt"


@dataclass
class Result:
    doi: str
    status: str  # downloaded | exists | not_found | failed | invalid
    source: str = ""
    file: str = ""
    url: str = ""
    error: str = ""
    title: str = ""
    citations: int | None = None
    seconds: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def paper_filename(paper: Paper | None, doi: str, style: str) -> str:
    """style: 'doi' -> 10.1038_nature12373.pdf ; 'title' -> Kucsko_2013_Nanometre-scale thermometry...pdf"""
    if style == "title" and paper and paper.title:
        title = re.sub(r"<[^>]+>", "", paper.title)  # Crossref titles can contain <i> tags
        parts = [p for p in (paper.first_author_surname, str(paper.year or ""), title[:90]) if p]
        return safe_filename("_".join(parts)) + ".pdf"
    return doi_to_filename(doi) + ".pdf"


class Downloader:
    def __init__(self, config: Config, out_dir: str | Path, name_style: str = "doi", http: Http | None = None):
        self.config = config
        self.out_dir = Path(out_dir).expanduser().resolve()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.name_style = name_style
        self.http = http or Http(config)
        self.sources = []
        for name in config.sources:
            if name == "oa":
                self.sources.append(OpenAccessSource(config, self.http))
            elif name == "scihub":
                self.sources.append(SciHubSource(config, self.http))
            else:
                raise ValueError(f"unknown source {name!r}; use 'oa' and/or 'scihub'")
        self._manifest_lock = threading.Lock()

    # ------------------------------------------------------------------ single

    def download(self, doi_or_paper: str | Paper, overwrite: bool = False) -> Result:
        start = time.monotonic()
        paper = doi_or_paper if isinstance(doi_or_paper, Paper) else None
        raw = paper.doi if paper else str(doi_or_paper)
        doi = normalize_doi(raw)
        if not doi:
            return Result(doi=raw, status="invalid", error="not a DOI")

        extra = {"title": paper.title if paper else "", "citations": paper.citations if paper else None}
        target = self.out_dir / paper_filename(paper, doi, self.name_style)
        existing = self._existing_file(doi, target)
        if existing and not overwrite:
            return Result(doi=doi, status="exists", file=str(existing), **extra)

        errors, all_not_found = [], True
        for source in self.sources:
            try:
                if isinstance(source, OpenAccessSource):
                    data, url = source.fetch(doi, hint=paper.oa_pdf_url if paper else "")
                else:
                    data, url = source.fetch(doi)
            except NotFound as exc:
                errors.append(f"[{source.name}] {exc}")
                continue
            except Exception as exc:
                all_not_found = False
                errors.append(f"[{source.name}] {exc}")
                continue
            tmp = target.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(target)
            return Result(
                doi=doi, status="downloaded", source=source.name, file=str(target), url=url,
                seconds=round(time.monotonic() - start, 1), **extra,
            )
        return Result(
            doi=doi, status="not_found" if all_not_found else "failed", error=" | ".join(errors)[:1000],
            seconds=round(time.monotonic() - start, 1), **extra,
        )

    def _existing_file(self, doi: str, target: Path) -> Path | None:
        if target.exists() and target.stat().st_size > 0:
            return target
        # Downloaded earlier under the other naming style?
        alt = self.out_dir / (doi_to_filename(doi) + ".pdf")
        if alt.exists() and alt.stat().st_size > 0:
            return alt
        return self._manifest_file(doi)

    def _manifest_file(self, doi: str) -> Path | None:
        path = self.out_dir / MANIFEST
        if not path.exists():
            return None
        with self._manifest_lock, path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if row.get("doi", "").lower() == doi.lower() and row.get("status") == "downloaded":
                    f = Path(row.get("file", ""))
                    if f.exists():
                        return f
        return None

    # ------------------------------------------------------------------- batch

    def download_many(
        self,
        items: Iterable[str | Paper],
        workers: int | None = None,
        overwrite: bool = False,
        on_result: Callable[[Result, int, int], None] | None = None,
    ) -> list[Result]:
        items = list(items)
        total = len(items)
        results: list[Result] = []
        workers = max(1, workers or self.config.workers)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self._safe_download, it, overwrite): it for it in items}
            for fut in as_completed(futures):
                res = fut.result()
                results.append(res)
                self._record(res)
                if on_result:
                    on_result(res, len(results), total)
        self._write_failed(results)
        return results

    def _safe_download(self, item, overwrite) -> Result:
        try:
            return self.download(item, overwrite=overwrite)
        except Exception as exc:  # never let one paper kill a batch of hundreds
            doi = item.doi if isinstance(item, Paper) else str(item)
            log.exception("unexpected error for %s", doi)
            return Result(doi=doi, status="failed", error=f"unexpected: {exc}")

    def _record(self, res: Result) -> None:
        if res.status == "exists":
            return
        path = self.out_dir / MANIFEST
        fields = ["timestamp", *Result.__dataclass_fields__.keys()]
        with self._manifest_lock:
            new = not path.exists()
            with path.open("a", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=fields)
                if new:
                    writer.writeheader()
                writer.writerow({"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), **res.to_dict()})

    def _write_failed(self, results: list[Result]) -> None:
        failed = [r.doi for r in results if r.status in ("failed", "not_found")]
        path = self.out_dir / FAILED
        if failed:
            path.write_text("\n".join(failed) + "\n", encoding="utf-8")
        elif path.exists():
            path.unlink()
