"""Where PDFs come from.

Each source takes a DOI and returns PDF bytes or raises SourceError.
  * OpenAccessSource - legal open-access copies (Unpaywall, OpenAlex, Semantic Scholar, arXiv, PMC)
  * SciHubSource     - Sci-Hub mirrors (https://www.sci-hub.in first by default)
"""

from __future__ import annotations

import html as html_lib
import logging
import re
import threading
import time
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

from .config import Config
from .net import Http

log = logging.getLogger(__name__)


class SourceError(RuntimeError):
    pass


class NotFound(SourceError):
    """The source definitely does not have this paper (as opposed to a transient failure)."""


class Captcha(SourceError):
    pass


def looks_like_pdf(data: bytes) -> bool:
    # Some servers prepend whitespace or a BOM before the header.
    return b"%PDF-" in data[:1024]


def fetch_pdf(http: Http, url: str, config: Config, referer: str | None = None) -> tuple[bytes | None, str]:
    """GET `url`. Returns (pdf_bytes, "") on success, or (None, html_text) if an HTML page came back."""
    headers = {"Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8"}
    if referer:
        headers["Referer"] = referer
    resp = http.get(url, headers=headers, stream=True, allow_redirects=True)
    try:
        if resp.status_code == 404:
            raise NotFound(f"HTTP 404 for {url}")
        if resp.status_code >= 400:
            raise SourceError(f"HTTP {resp.status_code} for {url}")
        limit = config.max_pdf_mb * 1024 * 1024
        chunks, size = [], 0
        for chunk in resp.iter_content(64 * 1024):
            chunks.append(chunk)
            size += len(chunk)
            if size > limit:
                raise SourceError(f"file larger than {config.max_pdf_mb} MB: {url}")
        data = b"".join(chunks)
    finally:
        resp.close()
    if looks_like_pdf(data):
        return data, ""
    return None, data.decode(resp.encoding or "utf-8", errors="replace")


# --------------------------------------------------------------------------- HTML parsing

_ONCLICK_URL = re.compile(r"""location\.href\s*=\s*['"]([^'"]+)['"]""")
_PDF_URL_IN_TEXT = re.compile(r"""(?:https?:)?//[^\s'"<>]+?\.pdf(?:[?#][^\s'"<>]*)?""", re.IGNORECASE)
_NOT_FOUND_MARKERS = (
    "article not found",
    "no matching proxies found",
    "unfortunately, sci-hub doesn't have",
    "статья не найдена",
    "search proxy to download article",
)
_CAPTCHA_MARKERS = ("captcha", "are you a robot", "cf-challenge", "challenge-platform")


def _absolute(url: str, base: str) -> str:
    url = html_lib.unescape(url.strip()).replace("\\/", "/")
    if url.startswith("//"):
        url = "https:" + url
    url = urljoin(base, url)
    return url.split("#", 1)[0]


def extract_pdf_url(page_html: str, base_url: str) -> str | None:
    """Find the PDF link on a Sci-Hub (or publisher/repository landing) page."""
    soup = BeautifulSoup(page_html, "html.parser")

    # 1. Sci-Hub viewer: <embed id="pdf" src=...> / <iframe id="pdf" src=...> / <object data=...>
    for tag in soup.select("#pdf, embed[type='application/pdf'], iframe#pdf, object[type='application/pdf']"):
        src = tag.get("src") or tag.get("data")
        if src and "about:blank" not in src:
            return _absolute(src, base_url)

    # 2. Standard scholarly metadata used by publishers and repositories (PMC, arXiv, journals).
    meta = soup.find("meta", attrs={"name": "citation_pdf_url"})
    if meta and meta.get("content"):
        return _absolute(meta["content"], base_url)

    # 3. Sci-Hub "save" button: onclick="location.href='https:\/\/.../x.pdf?download=true'"
    for tag in soup.find_all(onclick=True):
        m = _ONCLICK_URL.search(tag["onclick"])
        if m and ".pdf" in m.group(1).lower():
            return _absolute(m.group(1), base_url)

    # 4. Any iframe (some mirrors don't set id="pdf").
    for tag in soup.find_all("iframe", src=True):
        if ".pdf" in tag["src"].lower():
            return _absolute(tag["src"], base_url)

    # 5. Explicit download links.
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().split("?")[0].endswith(".pdf") or "download=true" in href:
            return _absolute(href, base_url)

    # 6. Last resort: a .pdf URL anywhere in the markup (inline scripts etc.).
    m = _PDF_URL_IN_TEXT.search(page_html)
    if m:
        return _absolute(m.group(0), base_url)
    return None


def classify_scihub_page(page_html: str) -> str:
    """'captcha', 'not_found' or 'unknown' for a Sci-Hub page that had no PDF link."""
    low = page_html.lower()
    if any(m in low for m in _CAPTCHA_MARKERS):
        return "captcha"
    if any(m in low for m in _NOT_FOUND_MARKERS):
        return "not_found"
    return "unknown"


# --------------------------------------------------------------------------- sources


class SciHubSource:
    name = "scihub"

    def __init__(self, config: Config, http: Http):
        self.config = config
        self.http = http
        self._lock = threading.Lock()
        self._mirrors = list(config.mirrors)
        self._dead_until: dict[str, float] = {}

    DEAD_COOLDOWN = 600  # seconds to skip a mirror that could not be reached

    def _mirror_order(self) -> list[str]:
        now = time.monotonic()
        with self._lock:
            alive = [m for m in self._mirrors if self._dead_until.get(m, 0) <= now]
            return alive or list(self._mirrors)  # everything dead: try them all again

    def _mark_dead(self, mirror: str) -> None:
        with self._lock:
            self._dead_until[mirror] = time.monotonic() + self.DEAD_COOLDOWN
        log.info("mirror %s unreachable; skipping it for %ds", mirror, self.DEAD_COOLDOWN)

    def _promote(self, mirror: str) -> None:
        with self._lock:
            if self._mirrors and self._mirrors[0] != mirror:
                self._mirrors.remove(mirror)
                self._mirrors.insert(0, mirror)

    def fetch(self, doi: str) -> tuple[bytes, str]:
        errors, not_found = [], 0
        mirrors = self._mirror_order()
        for mirror in mirrors:
            page_url = f"{mirror.rstrip('/')}/{doi}"
            try:
                data, page = fetch_pdf(self.http, page_url, self.config)
                if data:  # some mirrors redirect straight to the PDF
                    self._promote(mirror)
                    return data, page_url
                pdf_url = extract_pdf_url(page, page_url)
                if not pdf_url:
                    kind = classify_scihub_page(page)
                    if kind == "not_found":
                        not_found += 1
                        errors.append(f"{mirror}: not in Sci-Hub database")
                        continue
                    raise Captcha("captcha / bot check") if kind == "captcha" else SourceError("no PDF link on page")
                data, _ = fetch_pdf(self.http, pdf_url, self.config, referer=page_url)
                if not data:
                    raise SourceError(f"PDF link returned HTML: {pdf_url}")
                self._promote(mirror)
                return data, pdf_url
            except NotFound:
                not_found += 1
                errors.append(f"{mirror}: 404")
            except requests.ConnectionError as exc:
                self._mark_dead(mirror)
                errors.append(f"{mirror}: unreachable ({type(exc).__name__})")
            except Exception as exc:  # connection refused, DNS, TLS, captcha: try the next mirror
                errors.append(f"{mirror}: {exc}")
        if mirrors and not_found == len(mirrors):
            raise NotFound("; ".join(errors))
        raise SourceError("; ".join(errors) or "no mirrors configured")


class OpenAccessSource:
    name = "oa"

    def __init__(self, config: Config, http: Http):
        self.config = config
        self.http = http

    def candidate_urls(self, doi: str, hint: str = "") -> list[str]:
        urls: list[str] = [hint] if hint else []
        low = doi.lower()
        if low.startswith("10.48550/arxiv."):
            urls.append(f"https://arxiv.org/pdf/{doi.split('.', 2)[-1]}")

        if self.config.email:
            try:
                data = self.http.get_json(
                    f"https://api.unpaywall.org/v2/{quote(doi)}", params={"email": self.config.email}, polite=False
                )
                for loc in [data.get("best_oa_location")] + (data.get("oa_locations") or []):
                    if loc:
                        urls += [loc.get("url_for_pdf") or "", loc.get("url") or ""]
            except Exception as exc:
                log.debug("unpaywall lookup failed for %s: %s", doi, exc)

        try:
            params = {"select": "best_oa_location,locations"}
            if self.config.openalex_api_key:
                params["api_key"] = self.config.openalex_api_key
            if self.config.email:
                params["mailto"] = self.config.email
            data = self.http.get_json(f"https://api.openalex.org/works/doi:{doi}", params=params, polite=False)
            for loc in [data.get("best_oa_location")] + (data.get("locations") or []):
                if loc and loc.get("is_oa"):
                    urls += [loc.get("pdf_url") or "", loc.get("landing_page_url") or ""]
        except Exception as exc:
            log.debug("openalex lookup failed for %s: %s", doi, exc)

        try:
            headers = {"x-api-key": self.config.s2_api_key} if self.config.s2_api_key else {}
            data = self.http.get_json(
                f"https://api.semanticscholar.org/graph/v1/paper/DOI:{quote(doi)}",
                params={"fields": "openAccessPdf,externalIds"},
                headers=headers,
            )
            urls.append((data.get("openAccessPdf") or {}).get("url") or "")
            arxiv = (data.get("externalIds") or {}).get("ArXiv")
            if arxiv:
                urls.append(f"https://arxiv.org/pdf/{arxiv}")
        except Exception as exc:
            log.debug("semantic scholar lookup failed for %s: %s", doi, exc)

        seen, out = set(), []
        for u in urls:
            # doi.org landing pages just bounce to the paywalled publisher page
            if u and u not in seen and "doi.org/" not in u:
                seen.add(u)
                out.append(u)
        return out

    def fetch(self, doi: str, hint: str = "") -> tuple[bytes, str]:
        errors = []
        candidates = self.candidate_urls(doi, hint)
        if not candidates:
            raise NotFound("no open-access copy known")
        for url in candidates[:8]:
            try:
                data, page = fetch_pdf(self.http, url, self.config)
                if data:
                    return data, url
                # Landing page (e.g. PMC, repository): follow its citation_pdf_url / PDF link once.
                pdf_url = extract_pdf_url(page, url)
                if pdf_url and pdf_url != url:
                    data, _ = fetch_pdf(self.http, pdf_url, self.config, referer=url)
                    if data:
                        return data, pdf_url
                errors.append(f"{url}: not a PDF")
            except Exception as exc:
                errors.append(f"{url}: {exc}")
        raise SourceError("; ".join(errors))
