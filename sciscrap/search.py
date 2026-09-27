"""Find papers (and their DOIs) on a subject, ranked by citation count.

Providers, tried in order when provider="auto":
  1. OpenAlex          - best coverage, native sort by citations (free; API key/email optional)
  2. Semantic Scholar  - native sort by citations (free; API key optional, raises rate limit)
  3. Crossref          - relevance search, re-ranked locally by citation count
"""

from __future__ import annotations

import difflib
import logging
import math
import re
from dataclasses import asdict, dataclass, field

from .config import Config
from .doi import normalize_doi
from .net import Http

log = logging.getLogger(__name__)

PROVIDERS = ("openalex", "semanticscholar", "crossref")


@dataclass
class Paper:
    doi: str
    title: str = ""
    year: int | None = None
    citations: int = 0
    venue: str = ""
    authors: list[str] = field(default_factory=list)
    oa_pdf_url: str = ""
    provider: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def first_author_surname(self) -> str:
        name = self.authors[0].strip() if self.authors else ""
        if not name:
            return ""
        # "Family, Given" or "Given Family"
        return name.split(",")[0].strip() if "," in name else name.split()[-1]


class SearchError(RuntimeError):
    pass


class Searcher:
    def __init__(self, config: Config, http: Http | None = None):
        self.config = config
        self.http = http or Http(config)

    # ------------------------------------------------------------------ public

    def search(
        self,
        query: str,
        limit: int = 20,
        *,
        year_from: int | None = None,
        year_to: int | None = None,
        min_citations: int = 0,
        provider: str = "auto",
        articles_only: bool = False,
    ) -> list[Paper]:
        """Top `limit` papers matching `query`, most-cited first, each with a DOI."""
        providers = PROVIDERS if provider == "auto" else (provider,)
        errors = []
        for name in providers:
            fn = getattr(self, f"_search_{name}", None)
            if fn is None:
                raise ValueError(f"unknown provider {name!r}; choose from {', '.join(PROVIDERS)} or auto")
            try:
                papers = fn(query, limit, year_from, year_to, min_citations, articles_only)
            except Exception as exc:  # network error, rate limit, API outage: fall through to next provider
                log.warning("%s search failed: %s", name, exc)
                errors.append(f"{name}: {exc}")
                continue
            papers = _finalize(papers, limit, year_from, year_to, min_citations)
            if papers or provider != "auto":
                return papers
            errors.append(f"{name}: no results")
        raise SearchError("all search providers failed -> " + " | ".join(errors))

    def resolve_title(self, title: str) -> Paper | None:
        """Find the DOI of a paper from its (approximate) title, or a full reference string.

        Candidates are pooled from Crossref, OpenAlex and Semantic Scholar, then the closest title wins
        (citation count breaks near-ties, so the famous paper beats a same-titled erratum or chapter).
        """
        crossref: list[Paper] = []
        candidates: list[Paper] = []
        try:
            params = {"query.bibliographic": title, "rows": 5, "select": _CROSSREF_SELECT}
            if self.config.email:
                params["mailto"] = self.config.email
            items = self.http.get_json("https://api.crossref.org/works", params=params)["message"]["items"]
            crossref = [p for p in (_crossref_to_paper(i) for i in items) if p]
            candidates += crossref
        except Exception as exc:
            log.warning("crossref lookup failed: %s", exc)
        try:
            candidates += self._search_openalex(title, 10, None, None, 0, False)
        except Exception as exc:
            log.warning("openalex lookup failed: %s", exc)
        try:
            data = self.http.get_json(
                "https://api.semanticscholar.org/graph/v1/paper/search/match",
                params={"query": title, "fields": "title,externalIds,citationCount,year,venue,authors,openAccessPdf"},
                headers={"x-api-key": self.config.s2_api_key} if self.config.s2_api_key else {},
            )
            for p in data.get("data") or []:
                doi = normalize_doi((p.get("externalIds") or {}).get("DOI") or "")
                if doi:
                    candidates.append(Paper(
                        doi=doi, title=p.get("title") or "", year=p.get("year"),
                        citations=p.get("citationCount") or 0, venue=p.get("venue") or "",
                        authors=[a.get("name", "") for a in p.get("authors") or []][:20],
                        oa_pdf_url=(p.get("openAccessPdf") or {}).get("url") or "", provider="semanticscholar",
                    ))
        except Exception as exc:
            log.debug("semantic scholar match failed: %s", exc)

        target = _norm_title(title)
        best, best_score, best_sim = None, -1.0, 0.0
        for paper in candidates:
            sim = difflib.SequenceMatcher(None, target, _norm_title(paper.title)).ratio()
            score = sim + 0.02 * math.log10(1 + paper.citations)
            if score > best_score:
                best, best_score, best_sim = paper, score, sim
        if best and best_sim >= 0.6:
            return best
        # A full citation string won't closely match any bare title: trust Crossref's bibliographic ranking.
        return crossref[0] if crossref else best

    # --------------------------------------------------------------- providers

    def _search_openalex(self, query, limit, year_from, year_to, min_citations, articles_only):
        # Match title+abstract only: the default `search` param also hits full text, which lets
        # hugely cited but off-topic papers dominate a citation-sorted list. Commas/pipes are filter syntax.
        filters = ["has_doi:true", "title_and_abstract.search:" + query.replace(",", " ").replace("|", " ")]
        if year_from or year_to:
            filters.append(f"publication_year:{year_from or ''}-{year_to or ''}")
        if min_citations:
            filters.append(f"cited_by_count:>{min_citations - 1}")
        if articles_only:
            filters.append("type:article")
        params = {
            "filter": ",".join(filters),
            "sort": "cited_by_count:desc",
            "per-page": min(200, max(limit, 1)),
            "select": "doi,display_name,publication_year,cited_by_count,primary_location,authorships,best_oa_location",
            "cursor": "*",
        }
        if self.config.openalex_api_key:
            params["api_key"] = self.config.openalex_api_key
        if self.config.email:
            params["mailto"] = self.config.email
        papers: list[Paper] = []
        while len(papers) < limit:
            resp = self.http.get("https://api.openalex.org/works", params=params, polite=False)
            if resp.status_code != 200:
                raise SearchError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            for w in data.get("results", []):
                doi = normalize_doi(w.get("doi") or "")
                if not doi:
                    continue
                source = ((w.get("primary_location") or {}).get("source") or {})
                papers.append(Paper(
                    doi=doi,
                    title=w.get("display_name") or "",
                    year=w.get("publication_year"),
                    citations=w.get("cited_by_count") or 0,
                    venue=source.get("display_name") or "",
                    authors=[(a.get("author") or {}).get("display_name", "") for a in w.get("authorships", [])][:20],
                    oa_pdf_url=(w.get("best_oa_location") or {}).get("pdf_url") or "",
                    provider="openalex",
                ))
            cursor = (data.get("meta") or {}).get("next_cursor")
            if not cursor or not data.get("results"):
                break
            params["cursor"] = cursor
        return papers

    def _search_semanticscholar(self, query, limit, year_from, year_to, min_citations, articles_only):
        params = {
            "query": query,
            "sort": "citationCount:desc",
            "fields": "title,externalIds,citationCount,year,venue,authors,openAccessPdf,publicationTypes",
        }
        if year_from or year_to:
            params["year"] = f"{year_from or ''}-{year_to or ''}"
        if min_citations:
            params["minCitationCount"] = str(min_citations)
        if articles_only:
            params["publicationTypes"] = "JournalArticle"
        headers = {"x-api-key": self.config.s2_api_key} if self.config.s2_api_key else {}
        papers: list[Paper] = []
        while len(papers) < limit:
            data = self.http.get_json(
                "https://api.semanticscholar.org/graph/v1/paper/search/bulk", params=params, headers=headers
            )
            for p in data.get("data") or []:
                doi = normalize_doi((p.get("externalIds") or {}).get("DOI") or "")
                if not doi:
                    continue
                papers.append(Paper(
                    doi=doi,
                    title=p.get("title") or "",
                    year=p.get("year"),
                    citations=p.get("citationCount") or 0,
                    venue=p.get("venue") or "",
                    authors=[a.get("name", "") for a in p.get("authors") or []][:20],
                    oa_pdf_url=(p.get("openAccessPdf") or {}).get("url") or "",
                    provider="semanticscholar",
                ))
            token = data.get("token")
            if not token or not data.get("data"):
                break
            params["token"] = token
        return papers

    def _search_crossref(self, query, limit, year_from, year_to, min_citations, articles_only):
        # Crossref's sort-by-citations ignores relevance, so pull a wide relevance window and re-rank.
        filters = []
        if year_from:
            filters.append(f"from-pub-date:{year_from}")
        if year_to:
            filters.append(f"until-pub-date:{year_to}-12-31")
        if articles_only:
            filters.append("type:journal-article")
        params = {"query": query, "rows": min(1000, max(limit * 5, 100)), "select": _CROSSREF_SELECT}
        if filters:
            params["filter"] = ",".join(filters)
        if self.config.email:
            params["mailto"] = self.config.email
        items = self.http.get_json("https://api.crossref.org/works", params=params)["message"]["items"]
        return [p for p in (_crossref_to_paper(i) for i in items) if p]


def _norm_title(title: str) -> str:
    title = re.sub(r"<[^>]+>", " ", title.lower())
    return " ".join(re.sub(r"[^\w\s]", " ", title).split())


_CROSSREF_SELECT = "DOI,title,is-referenced-by-count,issued,container-title,author,type"


def _crossref_to_paper(item: dict) -> Paper | None:
    doi = normalize_doi(item.get("DOI") or "")
    if not doi:
        return None
    parts = ((item.get("issued") or {}).get("date-parts") or [[None]])[0]
    authors = [
        " ".join(x for x in (a.get("given"), a.get("family")) if x) or a.get("name", "")
        for a in item.get("author") or []
    ]
    return Paper(
        doi=doi,
        title=" ".join(item.get("title") or []),
        year=parts[0] if parts else None,
        citations=item.get("is-referenced-by-count") or 0,
        venue=" ".join(item.get("container-title") or []),
        authors=authors[:20],
        provider="crossref",
    )


def _finalize(papers, limit, year_from, year_to, min_citations) -> list[Paper]:
    seen: set[str] = set()
    out = []
    for p in sorted(papers, key=lambda p: p.citations, reverse=True):
        key = p.doi.lower()
        if key in seen or p.citations < min_citations:
            continue
        if year_from and p.year and p.year < year_from:
            continue
        if year_to and p.year and p.year > year_to:
            continue
        seen.add(key)
        out.append(p)
    return out[:limit]
